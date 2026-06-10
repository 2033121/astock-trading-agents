"""研究经理 Agent — 综合多空辩论结果，生成结构化投资方案。

使用结构化输出（ResearchPlan schema），对多空辩论进行裁决并给出综合投资建议。
支持 deep_think_llm 以获得更高质量的推理输出。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from astock_trader.agents.schemas import ResearchPlan, render_research_plan
from astock_trader.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)


def _build_debate_context(state: dict[str, Any]) -> str:
    """构建多空辩论上下文。"""
    debate = state.get("investment_debate_state") or {}

    bull_history = debate.get("bull_history", [])
    bear_history = debate.get("bear_history", [])
    full_history = debate.get("history", [])  # noqa: F841  # reserved for future use

    sections: list[str] = []

    if bull_history:
        bull_text = "\n\n".join(f"**第{i + 1}轮**: {h}" for i, h in enumerate(bull_history))
        sections.append(f"## 多头论点\n{bull_text}")

    if bear_history:
        bear_text = "\n\n".join(f"**第{i + 1}轮**: {h}" for i, h in enumerate(bear_history))
        sections.append(f"## 空头论点\n{bear_text}")

    # 添加分析师报告摘要
    for key, label in [
        ("market_report", "技术面分析"),
        ("news_report", "新闻舆情"),
        ("sentiment_report", "市场情绪"),
        ("fundamentals_report", "基本面分析"),
    ]:
        if state.get(key):
            sections.append(f"## {label}报告\n{state[key]}")

    return "\n\n".join(sections) if sections else "暂无辩论记录。"


def create_research_manager(llm: Any, deep_think_llm: Any = None) -> Callable:
    """创建研究经理节点。

    Parameters
    ----------
    llm : BaseChatModel
        默认 LLM 实例。
    deep_think_llm : BaseChatModel | None
        用于深度推理的 LLM 实例（如 reasoning 模型）。若为 None 则使用默认 llm。

    Returns
    -------
    Callable
        接受 ``AgentState`` 并返回更新后状态的节点函数。
    """
    active_llm = deep_think_llm or llm

    # 尝试绑定结构化输出
    structured_llm = bind_structured(active_llm, ResearchPlan, "research_manager")

    def research_manager_node(state: dict[str, Any]) -> dict[str, Any]:
        """研究经理节点：综合辩论结果生成结构化投资方案。"""
        company = state.get("company_of_interest", "目标股票")
        debate_context = _build_debate_context(state)

        prompt_text = (
            f"你是研究经理，需要综合分析以下多空辩论结果，对 **{company}** 做出最终投资评级。\n\n"
            f"{debate_context}\n\n"
            "请综合以上信息，给出：\n"
            "1. 投资评级（买入/增持/持有/减持/卖出）\n"
            "2. 推荐理由（简明扼要）\n"
            "3. 策略建议（具体可执行的操作建议）\n\n"
            "请用中文输出。"
        )

        prompt_messages = [("human", prompt_text)]

        result = invoke_structured_or_freetext(
            structured_llm=structured_llm,
            plain_llm=active_llm,
            prompt=prompt_messages,
            render=render_research_plan,
            agent_name="research_manager",
        )

        return {"investment_plan": result}

    return research_manager_node
