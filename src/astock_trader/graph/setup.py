"""Graph construction — builds and compiles the LangGraph ``StateGraph``.

The :class:`GraphSetup` assembles every node (analysts, researchers, trader,
risk analysts, managers) and wires them together with conditional edges
to form the full trading-decision pipeline.

Pipeline topology
-----------------
::

    START
     -> Market Analyst  <-> tools_market  -> Msg Clear Market
     -> Social Analyst   <-> tools_social  -> Msg Clear Social
     -> News Analyst     <-> tools_news    -> Msg Clear News
     -> Fundamentals     <-> tools_fund.   -> Msg Clear Fund.
     -> Bull Researcher  <-> Bear Researcher   (debate loop)
     -> Research Manager
     -> Trader
     -> Aggressive Analyst -> Conservative -> Neutral  (risk loop)
     -> Portfolio Manager
     -> Report Generator
     -> END

Selected analysts are inserted in the fixed order shown above; skipped
analysts are simply omitted from the graph.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage, RemoveMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from astock_trader.agents.utils.agent_states import AgentState
from astock_trader.agents.utils.agent_utils import get_language_instruction
from astock_trader.graph.conditional_logic import ConditionalLogic
from astock_trader.llm_clients.resilience import ResilientInvoker

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────
#  Constants
# ────────────────────────────────────────────────────────────────

# Canonical ordering of analysts in the pipeline
ANALYST_ORDER = ["market", "social", "news", "fundamentals"]

# Analyst display names (used as graph node labels)
ANALYST_NAMES: dict[str, str] = {
    "market": "Market Analyst",
    "social": "Social Analyst",
    "news": "News Analyst",
    "fundamentals": "Fundamentals Analyst",
}

# Analyst tool node labels
ANALYST_TOOL_NAMES: dict[str, str] = {
    "market": "tools_market",
    "social": "tools_social",
    "news": "tools_news",
    "fundamentals": "tools_fundamentals",
}

# Analyst message-clear node labels
ANALYST_CLEAR_NAMES: dict[str, str] = {
    "market": "Msg Clear Market",
    "social": "Msg Clear Social",
    "news": "Msg Clear News",
    "fundamentals": "Msg Clear Fundamentals",
}

# Mapping analyst key -> state report field
ANALYST_REPORT_FIELDS: dict[str, str] = {
    "market": "market_report",
    "social": "sentiment_report",
    "news": "news_report",
    "fundamentals": "fundamentals_report",
}

# ────────────────────────────────────────────────────────────────
#  System prompts
# ────────────────────────────────────────────────────────────────

_MARKET_SYSTEM = (
    "你是一位专业的A股市场/技术分析师。使用工具获取股票行情数据和技术指标，"
    "基于价格走势、均线系统、成交量等技术要素撰写详细的市场分析报告。"
    "报告应包含趋势判断、关键支撑/阻力位、技术信号汇总。"
)

_SOCIAL_SYSTEM = (
    "你是一位专业的A股市场情绪分析师。使用工具获取大宗交易、内部人交易等数据，"
    "分析市场参与者的情绪和行为信号，撰写市场情绪报告。"
    "关注资金流向、机构动向、散户情绪等维度。"
)

_NEWS_SYSTEM = (
    "你是一位专业的A股新闻舆情分析师。使用工具获取个股新闻和全球财经新闻，"
    "分析新闻事件对股价的潜在影响，撰写新闻舆情分析报告。"
    "首先调用 get_macro_assessment 获取月度宏观评估作为背景，"
    "关注公司公告、行业动态、政策变化、大宗交易等关键事件。"
    "不要重复分析宏观面，直接引用宏观评估报告结论。"
)

_FUNDAMENTALS_SYSTEM = (
    "你是一位专业的A股基本面分析师。使用工具获取公司财务报表数据"
    "（资产负债表、利润表、现金流量表）和基本面指标，"
    "评估公司的盈利能力、偿债能力、成长性、估值水平和产业链地位，撰写基本面分析报告。"
    "必须包含产业链分析：上下游关系、竞争格局、议价能力、行业壁垒，"
    "以及可比公司估值对比。如果公司涉及多个业务板块，必须分别分析各板块的产业链和竞争格局。"
)


def _get_analyst_system(key: str, language: str = "Chinese") -> str:
    """Return the system prompt for an analyst, with language instruction."""
    prompts = {
        "market": _MARKET_SYSTEM,
        "social": _SOCIAL_SYSTEM,
        "news": _NEWS_SYSTEM,
        "fundamentals": _FUNDAMENTALS_SYSTEM,
    }
    base = prompts.get(key, _MARKET_SYSTEM)
    return base + "\n\n" + get_language_instruction(language)


# ────────────────────────────────────────────────────────────────
#  Default tool sets per analyst
# ────────────────────────────────────────────────────────────────


def _get_default_tools(analyst_key: str) -> list[Any]:
    """Return the default LangChain tool list for an analyst type."""
    if analyst_key == "market":
        from astock_trader.agents.utils.core_stock_tools import (
            get_indicators,
            get_stock_data,
        )
        from astock_trader.agents.utils.technical_indicators_tools import (
            get_technical_indicators,
        )
        from astock_trader.agents.utils.tushare_data_tools import (
            get_daily_basic,
            get_moneyflow,
        )

        return [get_stock_data, get_indicators, get_technical_indicators, get_daily_basic, get_moneyflow]

    if analyst_key == "social":
        from astock_trader.agents.utils.news_data_tools import (
            get_global_news,
            get_insider_transactions,
            get_news,
        )
        from astock_trader.agents.utils.tushare_data_tools import (
            get_holdertrade,
            get_margin_detail,
        )

        return [get_insider_transactions, get_news, get_global_news, get_holdertrade, get_margin_detail]

    if analyst_key == "news":
        from astock_trader.agents.utils.news_data_tools import (
            get_global_news,
            get_news,
        )

        return [get_news, get_global_news]

    if analyst_key == "fundamentals":
        from astock_trader.agents.utils.core_stock_tools import get_stock_data
        from astock_trader.agents.utils.fundamental_data_tools import (
            get_balance_sheet,
            get_cashflow,
            get_fundamentals,
            get_income_statement,
        )
        from astock_trader.agents.utils.mx_data_tools import (
            get_shareholder_info,
            get_stock_valuation,
        )
        from astock_trader.agents.utils.tushare_data_tools import (
            get_dividend,
            get_fina_indicator,
            get_forecast,
        )

        return [
            get_fundamentals,
            get_balance_sheet,
            get_cashflow,
            get_income_statement,
            get_stock_data,
            get_stock_valuation,
            get_shareholder_info,
            get_fina_indicator,
            get_forecast,
            get_dividend,
        ]

    logger.warning("Unknown analyst key '%s'; returning empty tool list.", analyst_key)
    return []


# ────────────────────────────────────────────────────────────────
#  Node factory helpers
# ────────────────────────────────────────────────────────────────


def _create_llm_agent(
    llm: Any,
    tools: list[Any],
    analyst_key: str = "",
    language: str = "Chinese",
    backtest_consumer: Any | None = None,
) -> Callable:
    """Create a ReAct-style agent node function.

    The returned callable receives the full ``AgentState``, invokes the
    LLM with tool bindings, and returns the AI response message.  The
    conditional routing function then decides whether to enter the
    tool-execution loop or advance to the next stage.

    When ``messages`` is empty (first invocation), a system prompt and
    task description are injected automatically.
    """
    llm_with_tools = llm.bind_tools(tools) if tools else llm

    def _node(state: AgentState) -> dict[str, Any]:
        messages = list(state.get("messages", []))

        # Seed initial messages for the first analyst invocation
        if not messages and analyst_key:
            company = state.get("company_of_interest", "")
            trade_date = state.get("trade_date", "")
            past_context = state.get("past_context", "")

            system_text = _get_analyst_system(analyst_key, language)
            human_text = f"请分析股票 {company}，日期 {trade_date}。\n\n"
            if past_context:
                human_text += f"## 历史决策参考\n{past_context}\n\n"
            # Backtest feedback injection (conditional)
            if backtest_consumer is not None:
                try:
                    fb = backtest_consumer.get_analyst_feedback()
                    if fb:
                        human_text += f"## 回测校准\n{fb}\n\n"
                except Exception:
                    pass
            human_text += "请使用工具获取数据，然后撰写详细的分析报告。"

            messages = [
                SystemMessage(content=system_text),
                ("human", human_text),
            ]

        response: AIMessage = llm_with_tools.invoke(messages)
        return {"messages": [response]}

    return _node


def _create_msg_clear_node(
    analyst_key: str,
    report_field: str,
) -> Callable:
    """Create a message-clear node that extracts the report and wipes messages.

    Returns a callable that:
    1. Reads the last AI message as the analyst's report.
    2. Removes all accumulated messages via ``RemoveMessage``.
    3. Stores the report in the appropriate state field.
    """

    def _clear(state: AgentState) -> dict[str, Any]:
        messages = state.get("messages", [])
        report = ""

        # Walk backwards to find the last AI message with content
        for msg in reversed(messages):
            if hasattr(msg, "content") and msg.content and not hasattr(msg, "tool_calls"):
                report = msg.content
                break
            elif isinstance(msg, AIMessage) and msg.content:
                # AI message with content (may or may not have tool_calls)
                if not msg.tool_calls:
                    report = msg.content
                    break

        if not report and messages:
            # Fallback: use the content of the very last message
            last = messages[-1]
            report = getattr(last, "content", "") or ""

        # Remove all messages from state
        removals = [RemoveMessage(id=m.id) for m in messages if hasattr(m, "id")]

        logger.debug(
            "Msg Clear [%s]: extracted %d chars, removing %d messages",
            analyst_key,
            len(report),
            len(removals),
        )

        return {
            "messages": removals,
            report_field: report,
        }

    return _clear


# ════════════════════════════════════════════════════════════════
#  GraphSetup
# ════════════════════════════════════════════════════════════════


class GraphSetup:
    """Build and compile the LangGraph trading-decision pipeline.

    Parameters
    ----------
    deep_thinking_llm : BaseChatModel
        LLM for deep reasoning (Portfolio Manager final decision).
    heavy_thinking_llm : BaseChatModel
        LLM for heavy analysis (Bull/Bear debate).
    standard_thinking_llm : BaseChatModel
        LLM for standard processing (Trader, Research Manager, Risk Analysts).
    quick_thinking_llm : BaseChatModel
        LLM for quick tasks (Analysts, SignalProcessor, Report Generator).
    tool_nodes : dict[str, list[BaseTool]] | None
        Override tool lists per analyst key.  Missing keys fall back to
        the default tool sets.
    conditional_logic : ConditionalLogic
        Routing logic instance.
    language : str
        Output language for agent prompts (default ``"Chinese"``).
    """

    def __init__(
        self,
        deep_thinking_llm: Any,
        quick_thinking_llm: Any,
        heavy_thinking_llm: Any | None = None,
        standard_thinking_llm: Any | None = None,
        tool_nodes: dict[str, list[Any]] | None = None,
        conditional_logic: ConditionalLogic | None = None,
        language: str = "Chinese",
        report_output_dir: str = "",
        invoker: ResilientInvoker | None = None,
        context_slimming: bool = True,
        backtest_consumer: Any | None = None,
    ) -> None:
        self.deep_llm = deep_thinking_llm
        # Backward compat: heavy falls back to deep, standard falls back to deep
        self.heavy_llm = heavy_thinking_llm or deep_thinking_llm
        self.standard_llm = standard_thinking_llm or deep_thinking_llm
        self.quick_llm = quick_thinking_llm
        self.tool_overrides = tool_nodes or {}
        self.logic = conditional_logic or ConditionalLogic()
        self.language = language
        self.report_output_dir = report_output_dir
        self.invoker = invoker or ResilientInvoker()
        self.context_slimming = context_slimming
        self.backtest_consumer = backtest_consumer

    # ────────────────────────────────────────────────────────────
    #  Public entry point
    # ────────────────────────────────────────────────────────────

    def setup_graph(
        self,
        selected_analysts: list[str] | None = None,
    ) -> Any:
        """Build the full ``StateGraph`` and return the compiled workflow.

        Parameters
        ----------
        selected_analysts : list[str] | None
            Analyst keys to include.  Defaults to all four.

        Returns
        -------
        langgraph.graph.CompiledGraph
            The compiled LangGraph workflow, ready for ``.invoke()``.
        """
        if selected_analysts is None:
            selected_analysts = list(ANALYST_ORDER)

        # Filter to valid keys while preserving canonical order
        active = [k for k in ANALYST_ORDER if k in selected_analysts]
        if not active:
            raise ValueError(f"No valid analysts selected. Choose from: {ANALYST_ORDER}")

        # ── Resolve tools ──────────────────────────────────────
        tools: dict[str, list[Any]] = {}
        for key in active:
            tools[key] = self.tool_overrides.get(key) or _get_default_tools(key)

        # ── Create node functions ──────────────────────────────
        analyst_nodes: dict[str, Callable] = {}
        for key in active:
            analyst_nodes[key] = _create_llm_agent(
                self.quick_llm,
                tools[key],
                analyst_key=key,
                language=self.language,
                backtest_consumer=self.backtest_consumer,
            )

        clear_nodes: dict[str, Callable] = {}
        for key in active:
            clear_nodes[key] = _create_msg_clear_node(key, ANALYST_REPORT_FIELDS[key])

        tool_nodes: dict[str, ToolNode] = {}
        for key in active:
            tool_nodes[key] = ToolNode(tools[key])

        debate_nodes = self._create_debate_nodes()
        trader_node = self._create_trader_node()
        risk_nodes = self._create_risk_nodes()
        report_node = self._create_report_generator_node()

        # ── Build StateGraph ──────────────────────────────────
        builder = StateGraph(AgentState)

        # -- Analyst nodes --
        for key in active:
            builder.add_node(ANALYST_NAMES[key], analyst_nodes[key])
            builder.add_node(ANALYST_TOOL_NAMES[key], tool_nodes[key])
            builder.add_node(ANALYST_CLEAR_NAMES[key], clear_nodes[key])

        # -- Debate / manager nodes --
        builder.add_node("Bull Researcher", debate_nodes["bull"])
        builder.add_node("Bear Researcher", debate_nodes["bear"])
        builder.add_node("Research Manager", debate_nodes["research_manager"])
        builder.add_node("Trader", trader_node)
        builder.add_node("Aggressive Analyst", risk_nodes["aggressive"])
        builder.add_node("Conservative Analyst", risk_nodes["conservative"])
        builder.add_node("Neutral Analyst", risk_nodes["neutral"])
        builder.add_node("Portfolio Manager", risk_nodes["portfolio_manager"])
        builder.add_node("Report Generator", report_node)

        # ── Wire edges ────────────────────────────────────────
        first_key = active[0]

        # START -> first analyst
        builder.add_edge(START, ANALYST_NAMES[first_key])

        # Chain analysts
        for i, key in enumerate(active):
            # Analyst -> conditional (tools or msg clear)
            builder.add_conditional_edges(
                ANALYST_NAMES[key],
                self._get_analyst_router(key),
                [ANALYST_TOOL_NAMES[key], ANALYST_CLEAR_NAMES[key]],
            )
            # ToolNode -> back to Analyst
            builder.add_edge(ANALYST_TOOL_NAMES[key], ANALYST_NAMES[key])

            # Msg Clear -> next analyst or first debate node
            if i < len(active) - 1:
                next_key = active[i + 1]
                builder.add_edge(
                    ANALYST_CLEAR_NAMES[key],
                    ANALYST_NAMES[next_key],
                )
            else:
                # Last analyst -> Bull Researcher
                builder.add_edge(
                    ANALYST_CLEAR_NAMES[key],
                    "Bull Researcher",
                )

        # Bull <-> Bear debate loop
        builder.add_conditional_edges(
            "Bull Researcher",
            self.logic.should_continue_debate,
            ["Bear Researcher", "Bull Researcher", "Research Manager"],
        )
        builder.add_conditional_edges(
            "Bear Researcher",
            self.logic.should_continue_debate,
            ["Bull Researcher", "Bear Researcher", "Research Manager"],
        )

        # Research Manager -> Trader
        builder.add_edge("Research Manager", "Trader")

        # Trader -> first risk analyst
        builder.add_edge("Trader", "Aggressive Analyst")

        # Risk debate loop (Aggressive -> Conservative -> Neutral -> ...)
        for risk_name in [
            "Aggressive Analyst",
            "Conservative Analyst",
            "Neutral Analyst",
        ]:
            builder.add_conditional_edges(
                risk_name,
                self.logic.should_continue_risk_analysis,
                [
                    "Aggressive Analyst",
                    "Conservative Analyst",
                    "Neutral Analyst",
                    "Portfolio Manager",
                ],
            )

        # Portfolio Manager -> Report Generator -> END
        builder.add_edge("Portfolio Manager", "Report Generator")
        builder.add_edge("Report Generator", END)

        # ── Compile ───────────────────────────────────────────
        compiled = builder.compile()
        logger.info("Graph compiled with analysts: %s", ", ".join(active))
        return compiled

    # ────────────────────────────────────────────────────────────
    #  Internal helpers
    # ────────────────────────────────────────────────────────────

    def _safe_invoke(self, llm: Any, messages: list, agent_name: str) -> str:
        """Invoke LLM with retry + circuit breaker protection.

        Returns the response content string.  Falls back to raw invoke
        if the invoker raises CircuitBreakerOpen (logged as error).
        """
        from astock_trader.llm_clients.resilience import CircuitBreakerOpen

        try:
            return self.invoker.invoke(llm, messages, agent_name)
        except CircuitBreakerOpen as exc:
            logger.error(
                "[%s] Circuit breaker open (%.1fs remaining). "
                "Falling back to raw invoke.",
                agent_name,
                exc.remaining_cooldown,
            )
            response = llm.invoke(messages)
            return response.content if hasattr(response, "content") else str(response)

    def _gather_reports_for(self, state: AgentState, target_node: str) -> str:
        """Gather analyst reports, optionally slimmed for the target node.

        When ``context_slimming`` is enabled, delegates to
        :func:`context_slimmer.slim_gathered_reports` for node-aware trimming.
        Otherwise falls back to the original ``_gather_reports``.
        """
        if self.context_slimming:
            from astock_trader.graph.context_slimmer import slim_gathered_reports
            return slim_gathered_reports(state, target_node, enable=True)
        return self._gather_reports(state)

    def _get_analyst_router(self, key: str) -> Callable:
        """Return the conditional routing function for a specific analyst."""
        dispatch = {
            "market": self.logic.should_continue_market,
            "social": self.logic.should_continue_social,
            "news": self.logic.should_continue_news,
            "fundamentals": self.logic.should_continue_fundamentals,
        }
        return dispatch[key]

    # ── Debate nodes ──────────────────────────────────────────

    def _create_debate_nodes(self) -> dict[str, Callable]:
        """Create Bull Researcher, Bear Researcher, and Research Manager nodes.

        Model allocation:
        - Bull/Bear Researcher → heavy_llm (complex argumentation)
        - Research Manager → standard_llm (synthesis & judgment)
        """
        heavy_llm = self.heavy_llm
        standard_llm = self.standard_llm
        lang = self.language

        # ── Bull Researcher ───────────────────────────────────

        def bull_researcher(state: AgentState) -> dict[str, Any]:
            debate_state = state.get("investment_debate_state") or {}
            company = state.get("company_of_interest", "")
            trade_date = state.get("trade_date", "")
            past_context = state.get("past_context", "")

            bear_history = debate_state.get("bear_history", [])
            bear_last = "\n\n".join(bear_history[-3:]) if bear_history else "（首轮发言，等待空头回应）"

            reports = self._gather_reports_for(state, "bull")

            system_msg = (
                "你是一位看多研究员（Bull Researcher）。你的任务是基于所有可用信息，"
                "为做多该股票构建最有力的论据。\n\n"
                "规则:\n"
                "1. 以「看多」开头你的回复\n"
                "2. 用数据和逻辑论证，不要空泛\n"
                "3. 如果空头已提出反驳，你必须正面回应\n"
                "4. 突出被低估的利好因素\n\n" + get_language_instruction(lang)
            )

            human_msg = (
                f"分析标的: {company}  |  日期: {trade_date}\n\n"
                f"## 分析报告\n{reports}\n\n"
                f"## 空头最新论点\n{bear_last}\n\n"
            )
            if past_context:
                human_msg += f"## 历史决策参考\n{past_context}\n\n"
            bt_fb = self._bt_feedback("bull")
            if bt_fb:
                human_msg += f"## 回测校准\n{bt_fb}\n\n"
            human_msg += "请给出你的看多论据:"

            response_msgs = [
                    SystemMessage(content=system_msg),
                    ("human", human_msg),
                ]
            content = self._safe_invoke(heavy_llm, response_msgs, "Bull Researcher")

            return {
                "investment_debate_state": {
                    "bull_history": [content],
                    "current_response": content,
                    "history": [f"看多: {content}"],
                    "count": debate_state.get("count", 0) + 1,
                },
            }

        # ── Bear Researcher ───────────────────────────────────

        def bear_researcher(state: AgentState) -> dict[str, Any]:
            debate_state = state.get("investment_debate_state") or {}
            company = state.get("company_of_interest", "")
            trade_date = state.get("trade_date", "")
            past_context = state.get("past_context", "")

            bull_history = debate_state.get("bull_history", [])
            bull_last = "\n\n".join(bull_history[-3:]) if bull_history else "（无多头论点）"

            reports = self._gather_reports_for(state, "bear")

            system_msg = (
                "你是一位看空研究员（Bear Researcher）。你的任务是基于所有可用信息，"
                "为做空/不投资该股票构建最有力的论据。\n\n"
                "规则:\n"
                "1. 以「看空」开头你的回复\n"
                "2. 挑战多头的每一个论点\n"
                "3. 用数据和逻辑论证\n"
                "4. 突出被忽视的风险因素\n\n" + get_language_instruction(lang)
            )

            human_msg = (
                f"分析标的: {company}  |  日期: {trade_date}\n\n"
                f"## 分析报告\n{reports}\n\n"
                f"## 多头最新论点\n{bull_last}\n\n"
            )
            if past_context:
                human_msg += f"## 历史决策参考\n{past_context}\n\n"
            bt_fb = self._bt_feedback("bear")
            if bt_fb:
                human_msg += f"## 回测校准\n{bt_fb}\n\n"
            human_msg += "请给出你的看空论据:"

            response_msgs = [
                    SystemMessage(content=system_msg),
                    ("human", human_msg),
                ]
            content = self._safe_invoke(heavy_llm, response_msgs, "Bear Researcher")

            return {
                "investment_debate_state": {
                    "bear_history": [content],
                    "current_response": content,
                    "history": [f"看空: {content}"],
                    "count": debate_state.get("count", 0) + 1,
                },
            }

        # ── Research Manager (judge) ──────────────────────────

        def research_manager(state: AgentState) -> dict[str, Any]:
            debate_state = state.get("investment_debate_state") or {}
            company = state.get("company_of_interest", "")
            trade_date = state.get("trade_date", "")
            past_context = state.get("past_context", "")

            bull_hist = "\n\n---\n\n".join(debate_state.get("bull_history", []))
            bear_hist = "\n\n---\n\n".join(debate_state.get("bear_history", []))

            reports = self._gather_reports_for(state, "research_manager")

            system_msg = (
                "你是研究员主管（Research Manager / 辩论裁判）。\n"
                "你需要客观地评估多头和空头的论据质量，综合分析报告，"
                "制定最终的投资方案。\n\n"
                "输出格式:\n"
                "1. 辩论总结（多头 vs 空头各 1-2 句话）\n"
                "2. 你的判断（哪方更有说服力、为什么）\n"
                "3. 投资方案（明确的评级和操作建议）\n\n" + get_language_instruction(lang)
            )

            human_msg = (
                f"分析标的: {company}  |  日期: {trade_date}\n\n"
                f"## 分析报告\n{reports}\n\n"
                f"## 多头论据\n{bull_hist}\n\n"
                f"## 空头论据\n{bear_hist}\n\n"
            )
            if past_context:
                human_msg += f"## 历史决策参考\n{past_context}\n\n"
            bt_fb = self._bt_feedback("research_manager")
            if bt_fb:
                human_msg += f"## 回测校准\n{bt_fb}\n\n"
            human_msg += "请给出你的综合投资方案:"

            plan = self._safe_invoke(standard_llm, [
                    SystemMessage(content=system_msg),
                    ("human", human_msg),
                ], "Research Manager")

            return {
                "investment_plan": plan,
                "investment_debate_state": {
                    "judge_decision": plan,
                },
            }

        return {
            "bull": bull_researcher,
            "bear": bear_researcher,
            "research_manager": research_manager,
        }

    # ── Trader node ───────────────────────────────────────────

    def _create_trader_node(self) -> Callable:
        """Create the Trader node that converts the investment plan into a trade.

        Model allocation: standard_llm (balanced execution planning).
        """
        standard_llm = self.standard_llm
        lang = self.language

        def trader(state: AgentState) -> dict[str, Any]:
            company = state.get("company_of_interest", "")
            trade_date = state.get("trade_date", "")
            investment_plan = state.get("investment_plan", "")
            reports = self._gather_reports_for(state, "trader")

            system_msg = (
                "你是一名专业交易员。基于研究员的投资方案和分析报告，"
                "制定具体可执行的交易计划。\n\n"
                "输出必须包含:\n"
                "1. 交易方向（买入/持有/卖出）\n"
                "2. 建议仓位比例\n"
                "3. 入场价格区间\n"
                "4. 止损价位\n"
                "5. 止盈目标\n"
                "6. 交易时间框架\n\n" + get_language_instruction(lang)
            )

            human_msg = (
                f"标的: {company}  |  日期: {trade_date}\n\n"
                f"## 研究员投资方案\n{investment_plan}\n\n"
                f"## 分析报告摘要\n{reports}\n\n"
                "请制定具体交易计划:"
            )

            trader_plan = self._safe_invoke(standard_llm, [
                    SystemMessage(content=system_msg),
                    ("human", human_msg),
                ], "Trader")

            return {"trader_investment_plan": trader_plan}

        return trader

    # ── Risk debate nodes ─────────────────────────────────────

    def _create_risk_nodes(self) -> dict[str, Callable]:
        """Create the three risk analysts and the Portfolio Manager.

        Model allocation:
        - Aggressive/Conservative/Neutral Analysts → standard_llm (risk debate)
        - Portfolio Manager → deep_llm (final decision)
        """
        deep_llm = self.deep_llm
        standard_llm = self.standard_llm
        lang = self.language

        # ── Aggressive Analyst ────────────────────────────────

        def aggressive_analyst(state: AgentState) -> dict[str, Any]:
            risk_state = state.get("risk_debate_state") or {}
            company = state.get("company_of_interest", "")
            trade_date = state.get("trade_date", "")
            plan = state.get("trader_investment_plan", "")
            reports = self._gather_reports_for(state, "risk")

            other_views = []
            cons = risk_state.get("current_conservative_response", "")
            neut = risk_state.get("current_neutral_response", "")
            if cons:
                other_views.append(f"保守派观点: {cons}")
            if neut:
                other_views.append(f"中性派观点: {neut}")
            other_text = "\n".join(other_views) if other_views else "（首轮发言）"

            system_msg = (
                "你是一位激进派风控分析师。你倾向高风险高回报策略。\n"
                "你的任务是从积极的角度评估交易计划，指出其他分析师过度保守的地方，"
                "强调被低估的机会。\n\n"
                "规则: 以「激进派:」开头你的回复\n\n" + get_language_instruction(lang)
            )

            human_msg = (
                f"标的: {company}  |  日期: {trade_date}\n\n"
                f"## 交易计划\n{plan}\n\n"
                f"## 分析报告\n{reports}\n\n"
                f"## 其他分析师观点\n{other_text}\n\n"
            )
            bt_fb = self._bt_feedback("risk")
            if bt_fb:
                human_msg += f"## 回测校准\n{bt_fb}\n\n"
            human_msg += "请给出你的激进派风控评估:"

            content = self._safe_invoke(standard_llm, [
                    SystemMessage(content=system_msg),
                    ("human", human_msg),
                ], "Aggressive Analyst")

            return {
                "risk_debate_state": {
                    "aggressive_history": [content],
                    "current_aggressive_response": content,
                    "latest_speaker": "激进派",
                    "history": [f"激进派: {content}"],
                    "count": risk_state.get("count", 0) + 1,
                },
            }

        # ── Conservative Analyst ──────────────────────────────

        def conservative_analyst(state: AgentState) -> dict[str, Any]:
            risk_state = state.get("risk_debate_state") or {}
            company = state.get("company_of_interest", "")
            trade_date = state.get("trade_date", "")
            plan = state.get("trader_investment_plan", "")
            reports = self._gather_reports_for(state, "risk")

            other_views = []
            agg = risk_state.get("current_aggressive_response", "")
            neut = risk_state.get("current_neutral_response", "")
            if agg:
                other_views.append(f"激进派观点: {agg}")
            if neut:
                other_views.append(f"中性派观点: {neut}")
            other_text = "\n".join(other_views) if other_views else "（无其他观点）"

            system_msg = (
                "你是一位保守派风控分析师。你优先考虑资本保全和风险控制。\n"
                "你的任务是从审慎的角度评估交易计划，指出潜在风险、"
                "下行场景和被忽视的不利因素。\n\n"
                "规则: 以「保守派:」开头你的回复\n\n" + get_language_instruction(lang)
            )

            human_msg = (
                f"标的: {company}  |  日期: {trade_date}\n\n"
                f"## 交易计划\n{plan}\n\n"
                f"## 分析报告\n{reports}\n\n"
                f"## 其他分析师观点\n{other_text}\n\n"
            )
            bt_fb = self._bt_feedback("risk")
            if bt_fb:
                human_msg += f"## 回测校准\n{bt_fb}\n\n"
            human_msg += "请给出你的保守派风控评估:"

            content = self._safe_invoke(standard_llm, [
                    SystemMessage(content=system_msg),
                    ("human", human_msg),
                ], "Conservative Analyst")

            return {
                "risk_debate_state": {
                    "conservative_history": [content],
                    "current_conservative_response": content,
                    "latest_speaker": "保守派",
                    "history": [f"保守派: {content}"],
                    "count": risk_state.get("count", 0) + 1,
                },
            }

        # ── Neutral Analyst ───────────────────────────────────

        def neutral_analyst(state: AgentState) -> dict[str, Any]:
            risk_state = state.get("risk_debate_state") or {}
            company = state.get("company_of_interest", "")
            trade_date = state.get("trade_date", "")
            plan = state.get("trader_investment_plan", "")
            reports = self._gather_reports_for(state, "risk")

            other_views = []
            agg = risk_state.get("current_aggressive_response", "")
            cons = risk_state.get("current_conservative_response", "")
            if agg:
                other_views.append(f"激进派观点: {agg}")
            if cons:
                other_views.append(f"保守派观点: {cons}")
            other_text = "\n".join(other_views) if other_views else "（无其他观点）"

            system_msg = (
                "你是一位中性派风控分析师。你在激进和保守之间寻求平衡。\n"
                "你的任务是客观评估交易计划的风险收益比，综合两方观点，"
                "给出均衡的风险评估。\n\n"
                "规则: 以「中性派:」开头你的回复\n\n" + get_language_instruction(lang)
            )

            human_msg = (
                f"标的: {company}  |  日期: {trade_date}\n\n"
                f"## 交易计划\n{plan}\n\n"
                f"## 分析报告\n{reports}\n\n"
                f"## 其他分析师观点\n{other_text}\n\n"
            )
            bt_fb = self._bt_feedback("risk")
            if bt_fb:
                human_msg += f"## 回测校准\n{bt_fb}\n\n"
            human_msg += "请给出你的中性派风控评估:"

            content = self._safe_invoke(standard_llm, [
                    SystemMessage(content=system_msg),
                    ("human", human_msg),
                ], "Neutral Analyst")

            return {
                "risk_debate_state": {
                    "neutral_history": [content],
                    "current_neutral_response": content,
                    "latest_speaker": "中性派",
                    "history": [f"中性派: {content}"],
                    "count": risk_state.get("count", 0) + 1,
                },
            }

        # ── Portfolio Manager (final judge) ───────────────────

        def portfolio_manager(state: AgentState) -> dict[str, Any]:
            risk_state = state.get("risk_debate_state") or {}
            company = state.get("company_of_interest", "")
            trade_date = state.get("trade_date", "")
            past_context = state.get("past_context", "")
            plan = state.get("trader_investment_plan", "")
            investment_plan = state.get("investment_plan", "")
            reports = self._gather_reports_for(state, "portfolio_manager")

            agg_hist = "\n\n---\n\n".join(risk_state.get("aggressive_history", []))
            cons_hist = "\n\n---\n\n".join(risk_state.get("conservative_history", []))
            neut_hist = "\n\n---\n\n".join(risk_state.get("neutral_history", []))

            system_msg = (
                "你是基金经理（Portfolio Manager），最终决策者。\n\n"
                "你需要综合以下信息做出最终交易决策:\n"
                "1. 研究员的投资方案\n"
                "2. 交易员的交易计划\n"
                "3. 三方风控分析师的评估\n"
                "4. 各维度分析报告\n\n"
                "输出格式:\n"
                "1. 最终评级（买入/增持/持有/减持/卖出）\n"
                "2. 执行摘要（1-2 句话）\n"
                "3. 投资逻辑（核心理由）\n"
                "4. 风险提示\n"
                "5. 操作建议\n\n"
                "**评级**: [你的评级]\n\n" + get_language_instruction(lang)
            )

            human_msg = (
                f"标的: {company}  |  日期: {trade_date}\n\n"
                f"## 研究员投资方案\n{investment_plan}\n\n"
                f"## 交易员计划\n{plan}\n\n"
                f"## 分析报告\n{reports}\n\n"
                f"## 激进派风控评估\n{agg_hist}\n\n"
                f"## 保守派风控评估\n{cons_hist}\n\n"
                f"## 中性派风控评估\n{neut_hist}\n\n"
            )
            if past_context:
                human_msg += f"## 历史交易记录\n{past_context}\n\n"
            bt_fb = self._bt_feedback("portfolio_manager")
            if bt_fb:
                human_msg += f"## 回测校准\n{bt_fb}\n\n"
            human_msg += "请给出你的最终交易决策:"

            decision = self._safe_invoke(deep_llm, [
                    SystemMessage(content=system_msg),
                    ("human", human_msg),
                ], "Portfolio Manager")

            return {
                "final_trade_decision": decision,
                "risk_debate_state": {
                    "judge_decision": decision,
                },
            }

        return {
            "aggressive": aggressive_analyst,
            "conservative": conservative_analyst,
            "neutral": neutral_analyst,
            "portfolio_manager": portfolio_manager,
        }

    # ── Report Generator node ───────────────────────────────

    def _create_report_generator_node(self) -> Callable:
        """Create the Report Generator node that produces an HTML report."""
        output_dir = self.report_output_dir

        def report_generator(state: AgentState) -> dict[str, Any]:
            from astock_trader.graph.report_generator import generate_report
            from astock_trader.graph.signal_processing import SignalProcessor

            if not output_dir:
                logger.info("Report output dir not configured, skipping HTML report.")
                return {"report_path": ""}

            # Extract rating from final decision
            decision = state.get("final_trade_decision", "")
            sp = SignalProcessor(quick_thinking_llm=self.quick_llm)
            rating = sp.process_signal(decision)

            try:
                filepath = generate_report(
                    state=state,
                    output_dir=output_dir,
                    rating=rating,
                    elapsed_seconds=0,  # Will be set by the caller
                )
                logger.info("HTML report generated: %s", filepath)
                return {"report_path": filepath}
            except Exception as exc:
                logger.error("Failed to generate HTML report: %s", exc)
                return {"report_path": ""}

        return report_generator

    # ── Utility ───────────────────────────────────────────────

    def _bt_feedback(self, role: str) -> str:
        """Get backtest feedback text for a specific role (safe wrapper).

        Returns empty string when consumer is not available or gate not passed.
        """
        bc = self.backtest_consumer
        if bc is None:
            return ""
        try:
            dispatch = {
                "analyst": bc.get_analyst_feedback,
                "bull": lambda: bc.get_debater_feedback("bull"),
                "bear": lambda: bc.get_debater_feedback("bear"),
                "research_manager": bc.get_manager_feedback,
                "risk": bc.get_risk_feedback,
                "portfolio_manager": bc.get_pm_feedback,
            }
            fn = dispatch.get(role)
            return fn() if fn else ""
        except Exception as exc:
            logger.debug("Backtest feedback retrieval failed for '%s': %s", role, exc)
            return ""

    @staticmethod
    def _gather_reports(state: AgentState) -> str:
        """Collect all non-empty analyst reports into a single text block."""
        parts: list[str] = []
        for field, label in [
            ("market_report", "市场/技术面分析"),
            ("sentiment_report", "市场情绪分析"),
            ("news_report", "新闻舆情分析"),
            ("fundamentals_report", "基本面分析"),
        ]:
            value = state.get(field, "")
            if value:
                parts.append(f"### {label}\n{value}")
        return "\n\n".join(parts) if parts else "（暂无分析报告）"
