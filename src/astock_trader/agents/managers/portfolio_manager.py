"""组合经理 Agent — 最终投决制定者。

综合风控辩论结果、研究员投资方案、交易员计划和历史记忆，
使用结构化输出（PortfolioDecision schema）做出最终交易决策。
支持 deep_think_llm 以获得更高质量的推理输出。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from astock_trader.agents.schemas import PortfolioDecision, render_pm_decision
from astock_trader.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)


def _build_full_context(state: dict[str, Any]) -> str:
    """构建组合经理决策所需的完整上下文。"""
    sections: list[str] = []

    # 研究员投资方案
    if state.get("investment_plan"):
        sections.append(f"## 研究员投资方案\n{state['investment_plan']}")

    # 交易员交易计划
    if state.get("trader_investment_plan"):
        sections.append(f"## 交易员交易计划\n{state['trader_investment_plan']}")

    # 风控辩论
    risk_debate = state.get("risk_debate_state") or {}
    if risk_debate.get("aggressive_history"):
        agg = risk_debate["aggressive_history"]
        sections.append("## 激进派风控意见\n" + "\n".join(f"- {h}" for h in agg))
    if risk_debate.get("conservative_history"):
        con = risk_debate["conservative_history"]
        sections.append("## 保守派风控意见\n" + "\n".join(f"- {h}" for h in con))
    if risk_debate.get("neutral_history"):
        neu = risk_debate["neutral_history"]
        sections.append("## 中性派风控意见\n" + "\n".join(f"- {h}" for h in neu))

    # 历史记忆
    if state.get("past_context"):
        sections.append(f"## 历史交易记录\n{state['past_context']}")

    return "\n\n".join(sections) if sections else "暂无决策上下文。"


def create_portfolio_manager(llm: Any, deep_think_llm: Any = None) -> Callable:
    """创建组合经理节点。

    Parameters
    ----------
    llm : BaseChatModel
        默认 LLM 实例。
    deep_think_llm : BaseChatModel | None
        用于深度推理的 LLM 实例。若为 None 则使用默认 llm。

    Returns
    -------
    Callable
        接受 ``AgentState`` 并返回更新后状态的节点函数。
    """
    active_llm = deep_think_llm or llm

    # 尝试绑定结构化输出
    structured_llm = bind_structured(active_llm, PortfolioDecision, "portfolio_manager")

    def portfolio_manager_node(state: dict[str, Any]) -> dict[str, Any]:
        """组合经理节点：综合所有信息做出最终交易决策。"""
        company = state.get("company_of_interest", "目标股票")
        context = _build_full_context(state)

        prompt_text = (
            f"你是投资组合经理，需要综合分析以下信息，对 **{company}** 做出最终交易决策。\n\n"
            f"{context}\n\n"
            "请综合考虑研究员的投资方案、交易员的交易计划、各方风控意见和历史交易记录，"
            "给出你的最终决策：\n"
            "1. 最终评级（买入/增持/持有/减持/卖出）\n"
            "2. 执行摘要（一句话概括决策要点）\n"
            "3. 投资逻辑（核心推理过程）\n"
            "4. 目标价（如适用）\n"
            "5. 持有周期（如适用）\n\n"
            "请用中文输出，决策应明确、果断。"
        )

        prompt_messages = [("human", prompt_text)]

        result = invoke_structured_or_freetext(
            structured_llm=structured_llm,
            plain_llm=active_llm,
            prompt=prompt_messages,
            render=render_pm_decision,
            agent_name="portfolio_manager",
        )

        return {"final_trade_decision": result}

    return portfolio_manager_node
