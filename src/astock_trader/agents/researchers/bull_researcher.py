"""看多研究员 Agent — 从看多角度论证投资理由。

基于四位分析师的报告，与看空研究员进行多轮辩论，阐述看多论点。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _build_reports_context(state: dict[str, Any]) -> str:
    """从 state 中构建四位分析师报告上下文。"""
    sections: list[str] = []
    if state.get("market_report"):
        sections.append(f"## 技术面分析报告\n{state['market_report']}")
    if state.get("news_report"):
        sections.append(f"## 新闻舆情分析报告\n{state['news_report']}")
    if state.get("sentiment_report"):
        sections.append(f"## 市场情绪分析报告\n{state['sentiment_report']}")
    if state.get("fundamentals_report"):
        sections.append(f"## 基本面分析报告\n{state['fundamentals_report']}")
    return "\n\n".join(sections) if sections else "暂无分析师报告。"


def create_bull_researcher(llm: Any) -> Callable:
    """创建看多研究员节点。

    Parameters
    ----------
    llm : BaseChatModel
        LangChain 聊天模型实例。

    Returns
    -------
    Callable
        接受 ``AgentState`` 并返回更新后状态的节点函数。
    """

    def bull_researcher_node(state: dict[str, Any]) -> dict[str, Any]:
        """看多研究员节点：基于分析报告从看多角度进行论证。"""
        reports = _build_reports_context(state)
        company = state.get("company_of_interest", "目标股票")
        debate = state.get("investment_debate_state") or {}

        debate_history = debate.get("history", [])
        bear_latest = debate.get("bear_history", [])

        # 构建辩论历史摘要
        history_text = "\n".join(debate_history[-6:]) if debate_history else "（首轮发言，暂无辩论历史）"
        bear_text = bear_latest[-1] if bear_latest else "（空头尚未发言）"

        prompt = (
            f"你是一个看多研究员，正在对 **{company}** 进行看多论证。\n\n"
            f"### 分析师报告\n{reports}\n\n"
            f"### 辩论历史\n{history_text}\n\n"
            f"### 对方（空头）最新论点\n{bear_text}\n\n"
            "请基于以上信息，从看多角度给出你的论点。要求：\n"
            "1. 明确阐述看多的核心逻辑\n"
            "2. 针对空头的论点进行反驳\n"
            "3. 给出具体的投资价值和预期收益\n"
            "4. 用中文回答，条理清晰"
        )

        response = llm.invoke([("human", prompt)])
        response_text = response.content

        # 更新辩论状态
        new_history = list(debate_history) + [f"[多头]: {response_text}"]
        new_bull_history = list(debate.get("bull_history", [])) + [response_text]
        new_count = debate.get("count", 0) + 1

        new_debate_state = {
            **debate,
            "history": new_history,
            "bull_history": new_bull_history,
            "current_response": response_text,
            "count": new_count,
        }

        return {"investment_debate_state": new_debate_state}

    return bull_researcher_node
