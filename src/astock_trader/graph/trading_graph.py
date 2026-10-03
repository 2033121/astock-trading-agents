"""Main orchestrator — ``TradingAgentsGraph`` wires everything together.

This module is the single entry point that the CLI (and any external
caller) uses to run the multi-agent trading-decision pipeline.

Typical usage::

    from astock_trader.graph.trading_graph import TradingAgentsGraph

    graph = TradingAgentsGraph(
        selected_analysts=["market", "news", "fundamentals"],
        config={...},
    )
    final_state, rating = graph.propagate("000001", "2025-06-10")
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from astock_trader.agents.utils.memory import TradingMemoryLog
from astock_trader.agents.utils.rating import extract_action
from astock_trader.dataflows.config import set_config as set_dataflows_config
from astock_trader.default_config import DEFAULT_CONFIG
from astock_trader.graph.checkpointer import (
    get_checkpointer,
    thread_id,
)
from astock_trader.graph.conditional_logic import ConditionalLogic
from astock_trader.graph.propagation import Propagator
from astock_trader.graph.reflection import Reflector
from astock_trader.graph.setup import GraphSetup
from astock_trader.graph.signal_processing import SignalProcessor
from astock_trader.llm_clients.resilience import ResilientInvoker
from astock_trader.paths import project_dir, project_path
from astock_trader.point_in_time import normalize_date

# Backtest feedback consumer (optional import, graceful fallback)
try:
    from astock_trader.agents.utils.backtest_consumer import BacktestFeedbackConsumer
except ImportError:
    BacktestFeedbackConsumer = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

# 反思闭环的持有窗口（交易日）。结算要求已出现 _HOLDING_DAYS + 1 根收盘 K 线，
# 即决策日收盘建仓、持有 _HOLDING_DAYS 个交易日后平仓。
_HOLDING_DAYS = 5

# ────────────────────────────────────────────────────────────────
#  Model-name → base_url auto-detection map
#  When tiers use different models/providers, each gets its own endpoint.
# ────────────────────────────────────────────────────────────────
_MODEL_PREFIX_MAP: dict[str, str] = {
    "deepseek": "https://api.deepseek.com/v1",
    "mimo": "https://api.xiaomimimo.com/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "glm": "https://open.bigmodel.cn/api/paas/v4",
}


class TradingAgentsGraph:
    """High-level orchestrator for the multi-agent trading pipeline.

    Parameters
    ----------
    selected_analysts : list[str]
        Which analyst modules to include.  Valid values:
        ``"market"``, ``"social"``, ``"news"``, ``"fundamentals"``.
    debug : bool
        When ``True``, enables verbose LangGraph logging.
    config : dict | None
        Configuration dictionary.  Falls back to ``DEFAULT_CONFIG``.
    callbacks : list[Callable] | None
        Optional list of callback functions invoked at key stages.
        Each callback receives ``(event_name: str, data: dict)``.
    """

    def __init__(
        self,
        selected_analysts: list[str] | None = None,
        debug: bool = False,
        config: dict[str, Any] | None = None,
        callbacks: list[Callable] | None = None,
    ) -> None:
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.selected_analysts = selected_analysts or ["market", "social", "news", "fundamentals"]
        self.debug = debug
        self.callbacks = callbacks or []

        # ── 把配置推给数据层 ──────────────────────────────────
        # ``dataflows`` 是独立于本模块的全局单例，靠 ``set_config`` 注入。
        # 此前**没有任何地方调用它**，于是 ``get_config()`` 永远返回空 dict：
        # ``data_vendor`` 首选源配置形同虚设，凭证也只能靠环境变量碰运气
        # （user_config.json 里的 tushare token 完全走不到数据源）。
        set_dataflows_config(self.config)

        # ── Create LLM clients (4-tier) ──────────────────────
        self.deep_thinking_llm, self.heavy_thinking_llm, self.standard_thinking_llm, self.quick_thinking_llm = (
            self._create_llms()
        )

        # ── Sub-components ────────────────────────────────────
        self.invoker = ResilientInvoker(
            max_retries=self.config.get("llm_max_retries", 3),
            base_delay=self.config.get("llm_retry_base_delay", 4),
            max_delay=self.config.get("llm_retry_max_delay", 60),
            cb_threshold=self.config.get("circuit_breaker_threshold", 5),
            cb_cooldown=self.config.get("circuit_breaker_cooldown", 30),
        )

        # ── Optional semantic response cache (Token strategy 3) ──
        # Off by default; per-process only; covers researcher/manager/trader
        # node calls routed through GraphSetup._safe_invoke.
        self.semantic_cache = None
        self.progress_recorder = None
        if self.config.get("enable_semantic_cache", False):
            from astock_trader.llm_clients.semantic_cache import SemanticCache

            self.semantic_cache = SemanticCache(
                ttl_minutes=self.config.get("semantic_cache_ttl_minutes", 60),
                max_entries=self.config.get("semantic_cache_max_entries", 256),
                similarity_threshold=self.config.get("semantic_cache_similarity_threshold", 0.92),
            )

        # ── Activate Headroom compression (Library mode) ─────
        # Windows 上 ONNX Runtime 不兼容 Kompress int8-wo 模型，自动降级关闭。
        from astock_trader.llm_clients.resilience import configure_headroom

        _headroom_enabled = self.config.get("enable_headroom_compression", False)
        if _headroom_enabled:
            import sys as _sys

            if _sys.platform == "win32":
                _logger = logging.getLogger("astock_trader.headroom")
                _logger.warning(
                    "Headroom compression is not supported on Windows "
                    "(ONNX Runtime MatMulNBits 仅支持 4-bit，Kompress 需要 8-bit)。"
                    "已自动禁用。如需使用请在 macOS/Linux 上运行。"
                )
                _headroom_enabled = False
        configure_headroom(
            enable=_headroom_enabled,
            min_tokens=self.config.get("headroom_min_tokens", 500),
        )

        self.logic = ConditionalLogic(
            max_debate_rounds=self.config.get("max_debate_rounds", 1),
            max_risk_discuss_rounds=self.config.get("max_risk_discuss_rounds", 1),
        )

        # ── Backtest feedback consumer (optional) ────────────
        self.backtest_consumer = None
        if self.config.get("enable_backtest_feedback", True) and BacktestFeedbackConsumer:
            try:
                self.backtest_consumer = BacktestFeedbackConsumer(
                    feedback_path=self.config.get("backtest_feedback_path", ""),
                    min_verified=self.config.get("backtest_feedback_min_verified", 10),
                    expiry_days=self.config.get("backtest_feedback_expiry_days", 90),
                    decay_warn_days=self.config.get("backtest_feedback_decay_warn_days", 0),
                    decay_ignore_days=self.config.get("backtest_feedback_decay_ignore_days", 0),
                )
                info = self.backtest_consumer.quality_info
                logger.info(
                    "BacktestFeedbackConsumer initialised: gate=%s, verified=%s, decay=%s, age=%dd",
                    info.get("gate_passed"),
                    info.get("total_verified"),
                    info.get("decay_state", "n/a"),
                    info.get("age_days", 0),
                )
            except Exception as exc:
                logger.warning("BacktestFeedbackConsumer init failed: %s", exc)
                self.backtest_consumer = None

        self.graph_setup = GraphSetup(
            deep_thinking_llm=self.deep_thinking_llm,
            heavy_thinking_llm=self.heavy_thinking_llm,
            standard_thinking_llm=self.standard_thinking_llm,
            quick_thinking_llm=self.quick_thinking_llm,
            conditional_logic=self.logic,
            language=self.config.get("output_language", "Chinese"),
            report_output_dir=self.config.get("report_output_dir", ""),
            invoker=self.invoker,
            context_slimming=self.config.get("enable_context_slimming", True),
            backtest_consumer=self.backtest_consumer,
            semantic_cache=self.semantic_cache,
        )
        self.propagator = Propagator(
            max_recur_limit=self.config.get("max_recur_limit", 100),
        )
        self.reflector = Reflector(quick_thinking_llm=self.quick_thinking_llm)
        self.signal_processor = SignalProcessor(
            quick_thinking_llm=self.quick_thinking_llm,
        )
        self.memory_log = TradingMemoryLog(
            memory_dir=self.config.get("project_dir") or project_dir(),
        )

        # ── Vector memory (optional) ─────────────────────────
        self.market_memory = None
        if self.config.get("enable_vector_memory", True):
            try:
                from astock_trader.memory.market_memory import MarketMemory

                mem_dir = self.config.get("vector_memory_dir") or os.path.join(
                    self.config.get("project_dir") or project_dir(),
                    "vector_memory",
                )
                self.market_memory = MarketMemory(
                    backend=self.config.get("vector_memory_backend", "auto"),
                    persist_dir=mem_dir,
                )
                self.market_memory.load()
                logger.info(
                    "MarketMemory initialised: %d records indexed.",
                    self.market_memory.record_count,
                )
            except Exception as exc:
                logger.warning("MarketMemory init failed: %s", exc)
                self.market_memory = None

        # ── Build and compile graph ───────────────────────────
        self._emit("graph_build_start", {})
        self.compiled_graph = self.graph_setup.setup_graph(
            selected_analysts=self.selected_analysts,
        )
        self._emit("graph_build_complete", {})

    # ════════════════════════════════════════════════════════════
    #  Public API
    # ════════════════════════════════════════════════════════════

    def propagate(
        self,
        company_name: str,
        trade_date: str,
    ) -> tuple[dict[str, Any], str]:
        """Run the full analysis pipeline for a stock on a given date.

        This is the main entry point.  It:
        1. Resolves pending memory entries (optional).
        2. Optionally sets up an SQLite checkpointer.
        3. Invokes the compiled LangGraph.
        4. Logs the state to disk.
        5. Stores the decision in the memory log.
        6. Extracts the trading signal (rating).

        Parameters
        ----------
        company_name : str
            Stock ticker (e.g. ``"000001"``) or company name.
        trade_date : str
            Trade date in ``YYYY-MM-DD`` format.

        Returns
        -------
        tuple[dict, str]
            ``(final_state, rating)`` where *final_state* is the complete
            ``AgentState`` after graph execution and *rating* is the
            extracted Chinese rating string.
        """
        self._emit(
            "propagate_start",
            {
                "company": company_name,
                "date": trade_date,
            },
        )

        # Resolve pending memory entries
        self._resolve_pending_memory(company_name)

        # Run the graph
        final_state, rating = self._run_graph(company_name, trade_date)

        self._emit(
            "propagate_complete",
            {
                "company": company_name,
                "date": trade_date,
                "rating": rating,
            },
        )

        return final_state, rating

    # ════════════════════════════════════════════════════════════
    #  Internal: graph execution
    # ════════════════════════════════════════════════════════════

    def _run_graph(
        self,
        company_name: str,
        trade_date: str,
    ) -> tuple[dict[str, Any], str]:
        """Execute the LangGraph and handle post-processing."""
        import time

        # ── Past context from memory ──────────────────────────
        # trade_date 同时作为时间点：历史日期分析只能看到「当时已经落地」的教训，
        # 否则会学到未来才发生的结局（前视偏差）。
        past_context = self.memory_log.get_past_context(company_name, as_of=trade_date)

        # Enrich with vector memory search (if available)
        if self.market_memory and self.market_memory.record_count > 0:
            try:
                query = f"{company_name} 分析 投资"
                records = self.market_memory.search(query, top_k=3, as_of=trade_date)
                memory_context = self.market_memory.format_for_prompt(records)
                if memory_context:
                    past_context = f"{past_context}\n\n{memory_context}" if past_context else memory_context
                    logger.info(
                        "Vector memory: injected %d historical records into context.",
                        len(records),
                    )
            except Exception as exc:
                logger.debug("Vector memory search failed: %s", exc)

        # ── Initial state ─────────────────────────────────────
        initial_state = self.propagator.create_initial_state(
            company_name=company_name,
            trade_date=trade_date,
            past_context=past_context,
        )

        # ── Checkpointer (optional) ──────────────────────────
        checkpoint_enabled = self.config.get("checkpoint_enabled", False)
        checkpointer = None
        thread_config: dict[str, Any] = {}

        if checkpoint_enabled:
            try:
                checkpointer = get_checkpointer(company_name)
                tid = thread_id(company_name, trade_date)
                thread_config = {"configurable": {"thread_id": tid}}
                logger.info("Checkpointer enabled: thread=%s", tid)
            except Exception as exc:
                logger.warning("Failed to set up checkpointer: %s", exc)

        # ── Per-agent progress recorder (sidebar panel feed) ──
        recorder = None
        if self.config.get("enable_progress_recorder", True):
            try:
                from astock_trader.graph.progress_recorder import (
                    NodeProgressRecorder,
                    default_progress_path,
                    with_callback_config,
                )

                progress_file = self.config.get("progress_file") or default_progress_path(
                    self.config.get("results_dir", self.config.get("project_dir", "")),
                    company_name,
                    trade_date,
                )
                recorder = NodeProgressRecorder(progress_file)
                self.progress_recorder = recorder
                logger.info("Progress recorder -> %s", progress_file)
            except Exception as exc:
                logger.warning("Progress recorder init failed: %s", exc)

        # ── Invoke ────────────────────────────────────────────
        graph_args = self.propagator.get_graph_args()

        self._emit(
            "graph_invoke_start",
            {
                "company": company_name,
                "date": trade_date,
                "recursion_limit": graph_args.get("recursion_limit"),
            },
        )

        t0 = time.time()
        try:
            if checkpointer is not None:
                with checkpointer:
                    final_state = self.compiled_graph.invoke(
                        initial_state,
                        config=with_callback_config(thread_config, recorder),
                        **graph_args,
                    )
            else:
                final_state = self.compiled_graph.invoke(
                    initial_state,
                    config=with_callback_config({}, recorder),
                    **graph_args,
                )
        except Exception as exc:
            logger.error("Graph invocation failed: %s", exc)
            self._emit("graph_invoke_error", {"error": str(exc)})
            if self.progress_recorder is not None:
                with contextlib.suppress(Exception):
                    self.progress_recorder.mark_error(str(exc))
            raise
        elapsed = time.time() - t0

        self._emit(
            "graph_invoke_complete",
            {
                "company": company_name,
                "date": trade_date,
                "elapsed": round(elapsed, 1),
            },
        )

        # ── Patch report with actual elapsed time ─────────────
        report_path = final_state.get("report_path", "")
        if report_path and os.path.isfile(report_path):
            try:
                self._patch_report_elapsed(report_path, elapsed)
            except Exception as exc:
                logger.warning("Failed to patch report elapsed time: %s", exc)

        # ── Log state to disk ─────────────────────────────────
        # Inject elapsed seconds into state for the JSON log
        final_state["_elapsed_seconds"] = round(elapsed, 1)
        self._log_state_to_disk(final_state, company_name, trade_date)

        # ── Extract signal ────────────────────────────────────
        decision_text = final_state.get("final_trade_decision", "")
        rating = self.signal_processor.process_signal(decision_text)

        if self.progress_recorder is not None:
            with contextlib.suppress(Exception):
                self.progress_recorder.mark_complete(rating, round(time.time() - t0, 1))

        # ── Store decision in memory ─────────────────────────
        self._store_decision(company_name, trade_date, final_state, rating)

        # ── Rotate old memory entries to prevent unbounded growth ──
        try:
            if self.config.get("enable_memory_rotation", True):
                self.memory_log._apply_rotation(
                    max_same=self.config.get("memory_rotation_max_same", 10),
                    max_cross=self.config.get("memory_rotation_max_cross", 10),
                )
        except Exception as exc:
            logger.debug("Memory rotation failed (non-critical): %s", exc)

        # ── Index in vector memory ───────────────────────────
        self._index_in_memory(company_name, trade_date, final_state, rating)

        return final_state, rating

    # ════════════════════════════════════════════════════════════
    #  Internal: LLM creation
    # ════════════════════════════════════════════════════════════

    def _create_llms(self) -> tuple[Any, Any, Any, Any]:
        """Create deep / heavy / standard / quick LLM instances (4-tier).

        Each tier can use a different model and provider.  When ``backend_url``
        is not set, the base URL is auto-resolved **per model** so that e.g.
        ``mimo-v2.5-pro`` routes to the MiMo API while ``deepseek-v4-flash``
        routes to DeepSeek.

        Returns
        -------
        tuple[deep_llm, heavy_llm, standard_llm, quick_llm]
        """
        from astock_trader.llm_clients.factory import (
            _PROVIDER_BASE_URLS,
            create_llm_client,
        )

        provider = self.config.get("llm_provider", "deepseek")
        deep_model = self.config.get("deep_think_llm", "deepseek-chat")
        heavy_model = self.config.get(
            "heavy_think_llm",
            self.config.get("deep_think_llm", "deepseek-chat"),
        )
        standard_model = self.config.get(
            "standard_think_llm",
            self.config.get("deep_think_llm", "deepseek-chat"),
        )
        quick_model = self.config.get("quick_think_llm", "deepseek-chat")
        explicit_url = self.config.get("backend_url")

        # API key resolution: 配置文件 → 环境变量（多 provider 兼容）。
        # 配置文件（user_config.json）在仓库之外，省得每次开终端都重设环境变量；
        # 环境变量仍然优先于「没有任何配置文件」的情形由下面的 provider 专用变量接管。
        api_key = (
            str(self.config.get("api_key") or "").strip()
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("DASHSCOPE_API_KEY")
            or os.environ.get("MIMO_API_KEY")
            or os.environ.get("LLM_API_KEY")
        )

        def _resolve(model: str) -> tuple[str, str | None]:
            """Return (provider, base_url) for a model name.

            If the user set an explicit ``backend_url``, use it for all tiers.
            Otherwise, auto-detect from the model name.
            """
            if explicit_url:
                return provider, explicit_url
            low = model.lower()
            for prefix, url in _MODEL_PREFIX_MAP.items():
                if low.startswith(prefix):
                    return prefix, url
            # Fallback to the global provider
            return provider, _PROVIDER_BASE_URLS.get(provider)

        deep_prov, deep_url = _resolve(deep_model)
        heavy_prov, heavy_url = _resolve(heavy_model)
        std_prov, std_url = _resolve(standard_model)
        quick_prov, quick_url = _resolve(quick_model)

        def _resolve_api_key(prov: str) -> str:
            """Return the API key appropriate for *prov*.

            Each provider has its own environment variable (e.g. MIMO_API_KEY
            for the ``mimo`` provider).  Falls back to the generic resolution
            chain so single-provider setups keep working unchanged.
            """
            _PROVIDER_KEY_ENV: dict[str, str] = {  # noqa: N806
                "deepseek": "DEEPSEEK_API_KEY",
                "mimo": "MIMO_API_KEY",
                "qwen": "DASHSCOPE_API_KEY",
                "dashscope": "DASHSCOPE_API_KEY",
                "glm": "GLM_API_KEY",
                "zhipu": "GLM_API_KEY",
                "openai": "OPENAI_API_KEY",
                "siliconflow": "SILICONFLOW_API_KEY",
                "openrouter": "OPENROUTER_API_KEY",
                "together": "TOGETHER_API_KEY",
                "groq": "GROQ_API_KEY",
            }
            env_var = _PROVIDER_KEY_ENV.get(prov.lower())
            if env_var:
                key = os.environ.get(env_var)
                if key:
                    return key
            # Fallback to the general resolution chain
            return api_key or ""

        deep_client = create_llm_client(
            provider=deep_prov,
            model=deep_model,
            base_url=deep_url,
            api_key=_resolve_api_key(deep_prov),
            temperature=0.3,
        )
        heavy_client = create_llm_client(
            provider=heavy_prov,
            model=heavy_model,
            base_url=heavy_url,
            api_key=_resolve_api_key(heavy_prov),
            temperature=0.3,
        )
        standard_client = create_llm_client(
            provider=std_prov,
            model=standard_model,
            base_url=std_url,
            api_key=_resolve_api_key(std_prov),
            temperature=0.3,
        )
        quick_client = create_llm_client(
            provider=quick_prov,
            model=quick_model,
            base_url=quick_url,
            api_key=_resolve_api_key(quick_prov),
            temperature=0.3,
        )

        deep_llm = deep_client.get_llm()
        heavy_llm = heavy_client.get_llm()
        standard_llm = standard_client.get_llm()
        quick_llm = quick_client.get_llm()

        logger.info(
            "LLMs created (4-tier): deep=%s@%s, heavy=%s@%s, standard=%s@%s, quick=%s@%s",
            deep_model,
            deep_prov,
            heavy_model,
            heavy_prov,
            standard_model,
            std_prov,
            quick_model,
            quick_prov,
        )
        return deep_llm, heavy_llm, standard_llm, quick_llm

    # ════════════════════════════════════════════════════════════
    #  Internal: logging & memory
    # ════════════════════════════════════════════════════════════

    def _log_state_to_disk(
        self,
        state: dict[str, Any],
        company_name: str,
        trade_date: str,
    ) -> None:
        """Persist the final state as a JSON log file."""
        results_dir = self.config.get(
            "results_dir",
            project_path("logs"),
        )
        Path(results_dir).mkdir(parents=True, exist_ok=True)

        filename = f"{company_name}_{trade_date}_{datetime.now():%Y%m%d_%H%M%S}.json"
        filepath = os.path.join(results_dir, filename)

        # Serialise state — convert messages to dicts, skip non-serialisable
        serialisable = self._make_serialisable(state)

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(serialisable, f, ensure_ascii=False, indent=2)
            logger.info("State logged to %s", filepath)
        except Exception as exc:
            logger.warning("Failed to log state: %s", exc)

    def _store_decision(
        self,
        company_name: str,
        trade_date: str,
        state: dict[str, Any],
        rating: str,
    ) -> None:
        """Store the decision in the trading memory log."""
        decision_record = {
            "rating": rating,
            "action": self._extract_action(state),
            "final_trade_decision": state.get("final_trade_decision", "")[:500],
            "reasoning": state.get("investment_plan", "")[:300],
        }

        try:
            self.memory_log.store_decision(
                ticker=company_name,
                trade_date=trade_date,
                final_decision=decision_record,
            )
        except Exception as exc:
            logger.warning("Failed to store decision in memory: %s", exc)

    def _index_in_memory(
        self,
        company_name: str,
        trade_date: str,
        state: dict[str, Any],
        rating: str,
    ) -> None:
        """Index the analysis result in vector memory for future retrieval."""
        if self.market_memory is None:
            return

        try:
            parts = []
            for field in [
                "market_report",
                "sentiment_report",
                "news_report",
                "fundamentals_report",
            ]:
                value = state.get(field, "")
                if value:
                    parts.append(value)

            decision = state.get("final_trade_decision", "")
            if decision:
                parts.append(decision)

            if parts:
                content = "\n\n".join(parts)
                self.market_memory.index_analysis(
                    ticker=company_name,
                    date=trade_date,
                    content=content,
                    rating=rating,
                )
                self.market_memory.save()
        except Exception as exc:
            logger.debug("Failed to index in vector memory: %s", exc)

    def _resolve_pending_memory(self, company_name: str) -> None:
        """结算持有窗口已经走完的 pending 记忆条目。

        「窗口走完」按**交易日**判定：从决策日起必须已经存在
        ``_HOLDING_DAYS + 1`` 根已收盘 K 线。用自然日判定是不够的 —— 春节、
        国庆长假里 5 个自然日可能只含 1~2 个交易日，那时结算会把「1 日收益」
        当成「5 日收益」写进记忆，等于给未来的反思喂错标签。

        对每个到期条目：

        1. 拉取从决策日起的 ``_HOLDING_DAYS + 1`` 根日线，算出真实收益；
        2. 同日用沪深300 算超额收益；
        3. 用 :class:`Reflector` 生成 LLM 反思；
        4. 批量写回记忆日志（pending → resolved），并记录**平仓日**作为
           ``resolved_date`` —— 它是时间点门控的比较键。

        单条条目出错只记日志并跳过，不阻塞整批。
        """
        from datetime import date, datetime

        try:
            pending = self.memory_log.get_pending_entries()
            if not pending:
                return

            # 廉价预筛：自然日上至少过去 _HOLDING_DAYS 天的条目才值得去拉行情。
            # 真正的资格由 _forward_return 用真实 K 线确认。
            today = datetime.now().date()
            eligible: list[dict[str, Any]] = []
            for entry in pending:
                entry_date = normalize_date(entry.get("date"))
                if entry_date is None:
                    continue
                if (today - date.fromisoformat(entry_date)).days >= _HOLDING_DAYS:
                    eligible.append(entry)

            if not eligible:
                logger.debug(
                    "No pending entries past the calendar pre-filter (%d pending).",
                    len(pending),
                )
                return

            logger.info(
                "Checking %d pending memory entries for a settled %d-trading-day window.",
                len(eligible),
                _HOLDING_DAYS,
            )

            updates: list[dict[str, Any]] = []
            for entry in eligible:
                ticker = entry["ticker"]
                trade_date = entry["date"]
                decision_text = ""
                decision = entry.get("decision", {})
                if isinstance(decision, dict):
                    decision_text = decision.get("final_trade_decision", "") or decision.get("reasoning", "")

                try:
                    outcome = self._forward_return(ticker=ticker, trade_date=trade_date, days=_HOLDING_DAYS)
                    if outcome is None:
                        # 窗口没走完（或行情缺失）：保持 pending，下次再试。
                        logger.debug(
                            "Holding window not settled yet for %s@%s; leaving pending.",
                            ticker,
                            trade_date,
                        )
                        continue
                    raw_ret, exit_date = outcome

                    benchmark = self._forward_return(ticker=None, trade_date=trade_date, days=_HOLDING_DAYS, index=True)
                    bench_ret = benchmark[0] if benchmark else None
                    # 基准缺失时不假装超额为 0：记为未知，让反思看到的是「不知道」。
                    alpha: float | None = (raw_ret - bench_ret) if bench_ret is not None else None

                    reflection_text = self.reflector.reflect_on_final_decision(
                        final_decision=decision_text or f"评级: {entry.get('rating', '?')}",
                        raw_return=raw_ret,
                        alpha_return=alpha if alpha is not None else 0.0,
                    )

                    if alpha is None:
                        outcome_text = f"{_HOLDING_DAYS}日收益 {raw_ret:+.1%}, 超额未获取（基准数据缺失）"
                    else:
                        outcome_text = f"{_HOLDING_DAYS}日收益 {raw_ret:+.1%}, 超额 {alpha:+.1%}"

                    updates.append(
                        {
                            "ticker": ticker,
                            "trade_date": trade_date,
                            # 平仓日 = 结局落地日，历史日期分析据此判断该教训是否已知。
                            "resolved_date": exit_date,
                            "reflection": {
                                "outcome": outcome_text,
                                "raw_return": round(raw_ret, 4),
                                "alpha_return": round(alpha, 4) if alpha is not None else None,
                                "holding_days": _HOLDING_DAYS,
                                "hold_end": exit_date,
                                "lesson": reflection_text,
                                "resolved_date": exit_date,
                            },
                        }
                    )
                    logger.info(
                        "Resolved %s@%s: raw=%.1f%%, alpha=%s, exit=%s",
                        ticker,
                        trade_date,
                        raw_ret * 100,
                        f"{alpha * 100:.1f}%" if alpha is not None else "n/a",
                        exit_date,
                    )
                except Exception as exc:
                    logger.warning("Failed to resolve entry %s@%s: %s", ticker, trade_date, exc)
                    continue

            if updates:
                count = self.memory_log.batch_update_with_outcomes(updates)
                logger.info("Reflection complete: %d/%d entries resolved.", count, len(updates))

        except Exception as exc:
            logger.warning("Memory resolution failed: %s", exc)

    def _forward_return(
        self,
        *,
        ticker: str | None,
        trade_date: str,
        days: int,
        index: bool = False,
    ) -> tuple[float, str] | None:
        """计算从 *trade_date* 起持有 *days* 个**交易日**的收益率。

        Parameters
        ----------
        ticker : str | None
            股票代码；``index=True`` 时忽略。
        trade_date : str
            决策日（``YYYY-MM-DD``）。建仓价取该日（或其后第一个交易日）的收盘。
        days : int
            持有交易日数。
        index : bool
            ``True`` 时拉沪深300（000300）作为基准。

        Returns
        -------
        tuple[float, str] | None
            ``(收益率, 平仓日)``；当已收盘 K 线不足 ``days + 1`` 根时返回
            ``None`` —— 窗口还没走完，不能拿短窗口收益冒充 N 日收益。

        Notes
        -----
        只使用**严格早于今天**的 K 线：当日盘中（或收盘后但数据未落定）的那根
        仍可能变化，用它结算等于把浮动价格写成 T+N 结果。代价是结算最多延后
        一天，换的是「写进记忆的数字都是已收盘价」。
        """
        from datetime import datetime, timedelta

        try:
            import akshare as ak
        except ImportError:
            logger.debug("akshare not available for return fetching.")
            return None

        try:
            start = datetime.strptime(trade_date, "%Y-%m-%d")
        except (TypeError, ValueError):
            logger.debug("Invalid trade_date %r; cannot compute forward return.", trade_date)
            return None

        # 交易日可能稀疏（长假最长可达十余个自然日），窗口留足冗余。
        end = start + timedelta(days=days * 2 + 30)
        start_str = start.strftime("%Y%m%d")
        end_str = end.strftime("%Y%m%d")

        try:
            if index:
                df = ak.index_zh_a_hist(symbol="000300", period="daily", start_date=start_str, end_date=end_str)
            else:
                df = ak.stock_zh_a_hist(
                    symbol=ticker,
                    period="daily",
                    start_date=start_str,
                    end_date=end_str,
                    adjust="qfq",
                )
        except Exception as exc:
            logger.debug("Failed to fetch bars for %s: %s", ticker or "000300", exc)
            return None

        frame = self._settled_bars(df, trade_date, days)
        if frame is None:
            return None

        entry_price = float(frame.iloc[0]["收盘"])
        exit_price = float(frame.iloc[days]["收盘"])
        exit_date = str(frame.iloc[days]["日期"])
        if entry_price <= 0:
            return None
        return (exit_price - entry_price) / entry_price, exit_date

    @staticmethod
    def _settled_bars(df: Any, trade_date: str, days: int) -> Any | None:
        """把原始行情裁剪成「从决策日起、已收盘、连续」的交易日序列。

        返回 ``None`` 表示数据不可用，或已收盘交易日不足 ``days + 1`` 根 ——
        持有窗口还没走完。
        """
        from datetime import datetime

        if df is None or getattr(df, "empty", True):
            return None
        if "日期" not in df.columns or "收盘" not in df.columns:
            return None

        frame = df.copy()
        frame["日期"] = frame["日期"].astype(str).str.slice(0, 10)
        frame = frame[frame["日期"] >= trade_date]
        # 当天的 K 线可能还没落定（盘中/收盘价未定），一律不用。
        today_str = datetime.now().strftime("%Y-%m-%d")
        frame = frame[frame["日期"] < today_str]
        frame = frame.sort_values("日期").reset_index(drop=True)

        if len(frame) < days + 1:
            return None
        return frame

    # ════════════════════════════════════════════════════════════
    #  Internal: helpers
    # ════════════════════════════════════════════════════════════

    @staticmethod
    def _patch_report_elapsed(filepath: str, elapsed: float) -> None:
        """Patch the HTML report file with the actual elapsed time.

        要回填**两处**：JSON 里的 ``elapsed`` 字段（渲染用），以及摘要正文里
        写死的那个数字。此前只补了前者，于是正文永远显示「分析耗时：0.0秒」。
        """
        from astock_trader.graph.report_generator import ELAPSED_PLACEHOLDER

        with open(filepath, encoding="utf-8") as f:
            html = f.read()
        # Replace the placeholder elapsed value (0) in the embedded JSON
        html = html.replace(
            '"elapsed": 0',
            f'"elapsed": {round(elapsed, 1)}',
            1,
        )
        # 摘要正文里的占位符（可能出现两次：抬头 + 流程回溯）
        html = html.replace(ELAPSED_PLACEHOLDER, f"{elapsed:.1f}")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)
        logger.debug("Patched report elapsed: %.1fs in %s", elapsed, filepath)

    @staticmethod
    def _extract_action(state: dict[str, Any]) -> str:
        """Try to extract the trade action from the trader's plan.

        走 :func:`astock_trader.agents.utils.rating.extract_action`：按文中出现
        顺序扫描并**剔除否定语境的提及**。旧实现是「按刻度表顺序找第一个子串」，
        于是交易员写的「这不是"买入信号"，而是布局框架」会被读成「买入」——
        方向正好读反，还会一路写进记忆日志和 history 摘要。
        """
        return extract_action(state.get("trader_investment_plan")) or "unknown"

    @staticmethod
    def _make_serialisable(obj: Any) -> Any:
        """Recursively convert an object tree into a JSON-serialisable form."""
        if isinstance(obj, dict):
            return {k: TradingAgentsGraph._make_serialisable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [TradingAgentsGraph._make_serialisable(item) for item in obj]
        # LangChain messages
        if hasattr(obj, "content") and hasattr(obj, "type"):
            return {
                "type": getattr(obj, "type", "unknown"),
                "content": getattr(obj, "content", ""),
                "name": getattr(obj, "name", None),
            }
        # Fallback
        try:
            json.dumps(obj)
            return obj
        except (TypeError, ValueError):
            return str(obj)

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        """Fire all registered callbacks with the given event."""
        for cb in self.callbacks:
            try:
                cb(event, data)
            except Exception as exc:
                logger.debug("Callback error on '%s': %s", event, exc)
