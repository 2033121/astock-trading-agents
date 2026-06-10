"""保守风控分析师 Agent — 从保守角度评估交易方案的风险。

在风控辩论中代表保守派立场：优先保护本金安全，
强调潜在风险因素和极端情景分析，主张审慎决策。
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


def create_conservative_debator(llm: Any) -> Callable:
    """创建保守风控分析师节点。

    Parameters
    ----------
    llm : BaseChatModel
        LangChain 聊天模型实例。

    Returns
    -------
    Callable
        接受 ``AgentState`` 并返回更新后状态的节点函数。
    """

    def conservative_debator_node(state: dict[str, Any]) -> dict[str, Any]:
        """保守风控分析师节点：从保守角度评估交易风险。"""
        reports = _build_full_context(state)
        company = state.get("company_of_interest", "目标股票")
        risk_debate = state.get("risk_debate_state") or {}

        # 获取其他分析师的最新论点
        aggressive_args = risk_debate.get("aggressive_history", [])
        neutral_args = risk_debate.get("neutral_history", [])
        other_arguments: list[str] = []
        if aggressive_args:
            other_arguments.append(f"激进派: {aggressive_args[-1]}")
        if neutral_args:
            other_arguments.append(f"中性派: {neutral_args[-1]}")
        other_text = "\n".join(other_arguments) if other_arguments else "（其他分析师尚未发言）"

        # 风控辩论历史
        risk_history = risk_debate.get("history", [])
        history_text = "\n".join(risk_history[-6:]) if risk_history else "（首轮发言）"

        prompt = (
            f"你是一个保守派风险分析师，正在评估 **{company}** 的交易方案风险。\n\n"
            f"### 完整分析上下文\n{reports}\n\n"
            f"### 风控辩论历史\n{history_text}\n\n"
            f"### 其他风控分析师的论点\n{other_text}\n\n"
            "你代表保守派立场：\n"
            "- 认为本金安全是第一要务\n"
            "- 强调潜在的下行风险和极端情景\n"
            "- 主张充分的止损保护和安全边际\n"
            "- 警惕过度乐观和市场情绪泡沫\n\n"
            "请从保守角度给出你的风险评估（用中文），要求：\n"
            "1. 识别主要风险因素和最坏情景\n"
            "2. 评估止损设置是否充分\n"
            "3. 回应其他分析师的激进观点\n"
            "4. 给出保守的风险调整建议"
        )

        response = llm.invoke([("human", prompt)])
        response_text = response.content

        # 更新风控辩论状态
        new_history = list(risk_history) + [f"[保守派]: {response_text}"]
        new_conservative_history = list(risk_debate.get("conservative_history", [])) + [response_text]
        new_count = risk_debate.get("count", 0) + 1

        new_risk_state = {
            **risk_debate,
            "history": new_history,
            "conservative_history": new_conservative_history,
            "current_conservative_response": response_text,
            "latest_speaker": "conservative",
            "count": new_count,
        }

        return {"risk_debate_state": new_risk_state}

    return conservative_debator_node
