"""组合经理 Agent — 最终投决制定者。

综合风控辩论结果、研究员投资方案、交易员计划和历史记忆，
使用结构化输出（PortfolioDecision schema）做出最终交易决策。
支持 deep_think_llm 以获得更高质量的推理输出。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from astock_trader.agents.schemas import PortfolioDecision, render_pm_decision
from astock_trader.agents.utils.prompt_prefix import SYSTEM_PREFIX
from astock_trader.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)


def _rating_direction(text: str) -> str:
    """把一段决策文本粗分类为 看多/看空/中性 方向。"""
    from astock_trader.agents.utils.rating import parse_rating

    low = text[:400]  # 风控/意见类是中文，无需 lower() 匹配中文关键字
    if any(k in low for k in ("买入", "增持", "看多", "盈利", "突破")):
        return "看多"
    if any(k in low for k in ("卖出", "减持", "看空", "止损", "下行", "回撤")):
        return "看空"
    rating = parse_rating(text)
    if rating in ("买入", "增持"):
        return "看多"
    if rating in ("减持", "卖出"):
        return "看空"
    return "中性"


def _extract_numbers(text: str, max_items: int = 3) -> list[str]:
    """从决策文本提取带目标/止损/仓位/收益的含数值行片段。"""
    import re

    seen: list[str] = []
    for line in text.splitlines():
        if re.search(r"(目标价|收益|止损|止盈|仓位)[^\n]*\d", line):
            frag = line.strip()
            if frag and frag not in seen:
                seen.append(frag.strip())
        if len(seen) >= max_items:
            break
    return seen


def _build_decision_matrix(state: dict[str, Any]) -> str:
    """构建结构化决策矩阵（0 Token，Token 方案策略 2A PM 侧）。

    在完整上下文之前给出各信息源的方向与关键数值摘要，帮助基金经理
    快速对齐分歧点，同时保留完整文本供深度推理引用。
    """
    sources: list[tuple[str, str, list[str]]] = []
    plan = state.get("investment_plan", "")
    if plan:
        sources.append(("研究员投资方案", _rating_direction(plan), _extract_numbers(plan)))
    trader_plan = state.get("trader_investment_plan", "")
    if trader_plan:
        sources.append(("交易员交易计划", _rating_direction(trader_plan), _extract_numbers(trader_plan)))

    risk_debate = state.get("risk_debate_state") or {}
    for label, key in (
        ("激进派风控", "aggressive_history"),
        ("保守派风控", "conservative_history"),
        ("中性派风控", "neutral_history"),
    ):
        hist = risk_debate.get(key) or []
        if hist:
            latest = str(hist[-1])
            sources.append((label, _rating_direction(latest), _extract_numbers(latest, 2)))

    past = state.get("past_context", "")
    if past:
        sources.append(("历史记忆", "—", _extract_numbers(past, 2)))

    if not sources:
        return ""

    lines = ["## 决策矩阵（各信息源方向速览）"]
    directions = [d for _, d, _ in sources if d != "—"]
    if directions:
        longs = directions.count("看多")
        shorts = directions.count("看空")
        neutrals = directions.count("中性")
        lines.append(f"- 方向分布：看多 {longs} / 中性 {neutrals} / 看空 {shorts}（共 {len(directions)} 源）")
    for name, direction, notes in sources:
        num_str = "；".join(notes) if notes else "—"
        lines.append(f"- {name}：{direction}｜关键数值：{num_str}")
    return "\n".join(lines) + "\n"


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
        matrix = _build_decision_matrix(state)

        prompt_text = (
            f"你是投资组合经理，需要综合分析以下信息，对 **{company}** 做出最终交易决策。\n\n"
            f"{matrix}\n"
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

        prompt_messages = [("system", SYSTEM_PREFIX), ("human", prompt_text)]

        result = invoke_structured_or_freetext(
            structured_llm=structured_llm,
            plain_llm=active_llm,
            prompt=prompt_messages,
            render=render_pm_decision,
            agent_name="portfolio_manager",
        )

        return {"final_trade_decision": result}

    return portfolio_manager_node
