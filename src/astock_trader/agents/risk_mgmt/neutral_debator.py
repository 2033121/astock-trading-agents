"""中性风控分析师 Agent — 从中性/平衡角度评估交易方案的风险。

在风控辩论中代表中性派立场：追求风险与收益的平衡，
既不盲目乐观也不过度悲观，给出客观中立的综合风险评估。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _build_full_context(state: dict[str, Any]) -> str:
    """构建风控辩论的完整上下文。"""
    sections: list[str] = []

    # 分析师报告
    for key, label in [
        ("market_report", "技术面分析"),
        ("news_report", "新闻舆情"),
        ("sentiment_report", "市场情绪"),
        ("fundamentals_report", "基本面分析"),
    ]:
        if state.get(key):
            sections.append(f"## {label}报告\n{state[key]}")

    # 研究员方案
    if state.get("investment_plan"):
        sections.append(f"## 研究员投资方案\n{state['investment_plan']}")

    # 交易员计划
    if state.get("trader_investment_plan"):
        sections.append(f"## 交易员交易计划\n{state['trader_investment_plan']}")

    # 多空辩论结果
    debate = state.get("investment_debate_state") or {}
    if debate.get("bull_history"):
        sections.append("## 多头论点\n" + "\n".join(f"- {h}" for h in debate["bull_history"]))
    if debate.get("bear_history"):
        sections.append("## 空头论点\n" + "\n".join(f"- {h}" for h in debate["bear_history"]))

    return "\n\n".join(sections) if sections else "暂无上下文。"


def create_neutral_debator(llm: Any) -> Callable:
    """创建中性风控分析师节点。

    Parameters
    ----------
    llm : BaseChatModel
        LangChain 聊天模型实例。

    Returns
    -------
    Callable
        接受 ``AgentState`` 并返回更新后状态的节点函数。
    """

    def neutral_debator_node(state: dict[str, Any]) -> dict[str, Any]:
        """中性风控分析师节点：从平衡角度评估交易风险。"""
        reports = _build_full_context(state)
        company = state.get("company_of_interest", "目标股票")
        risk_debate = state.get("risk_debate_state") or {}

        # 获取其他分析师的最新论点
        aggressive_args = risk_debate.get("aggressive_history", [])
        conservative_args = risk_debate.get("conservative_history", [])
        other_arguments: list[str] = []
        if aggressive_args:
            other_arguments.append(f"激进派: {aggressive_args[-1]}")
        if conservative_args:
            other_arguments.append(f"保守派: {conservative_args[-1]}")
        other_text = "\n".join(other_arguments) if other_arguments else "（其他分析师尚未发言）"

        # 风控辩论历史
        risk_history = risk_debate.get("history", [])
        history_text = "\n".join(risk_history[-6:]) if risk_history else "（首轮发言）"

        prompt = (
            f"你是一个中性派风险分析师，正在评估 **{company}** 的交易方案风险。\n\n"
            f"### 完整分析上下文\n{reports}\n\n"
            f"### 风控辩论历史\n{history_text}\n\n"
            f"### 其他风控分析师的论点\n{other_text}\n\n"
            "你代表中性派立场：\n"
            "- 追求风险与收益的合理平衡\n"
            "- 客观分析，既不盲目乐观也不过度悲观\n"
            "- 综合激进派和保守派的合理观点\n"
            "- 给出中立、可量化的风险评估\n\n"
            "请从中性角度给出你的风险评估（用中文），要求：\n"
            "1. 给出风险收益的综合评估\n"
            "2. 分析核心风险因素及其概率\n"
            "3. 调和激进派与保守派的分歧\n"
            "4. 给出平衡的风险管理建议"
        )

        response = llm.invoke([("human", prompt)])
        response_text = response.content

        # 更新风控辩论状态
        new_history = list(risk_history) + [f"[中性派]: {response_text}"]
        new_neutral_history = list(risk_debate.get("neutral_history", [])) + [response_text]
        new_count = risk_debate.get("count", 0) + 1

        new_risk_state = {
            **risk_debate,
            "history": new_history,
            "neutral_history": new_neutral_history,
            "current_neutral_response": response_text,
            "latest_speaker": "neutral",
            "count": new_count,
        }

        return {"risk_debate_state": new_risk_state}

    return neutral_debator_node
