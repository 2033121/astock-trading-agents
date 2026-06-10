"""舆情分析师 Agent — 分析市场情绪、投资者讨论热点。

使用 ReAct 模式：将工具绑定到 LLM，通过多轮工具调用获取新闻和舆情数据后生成情绪分析报告。
"""

from __future__ import annotations

from typing import Any, Callable

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from astock_trader.agents.utils.news_data_tools import get_news


def create_social_media_analyst(llm: Any) -> Callable:
    """创建舆情分析师节点。

    Parameters
    ----------
    llm : BaseChatModel
        LangChain 聊天模型实例。

    Returns
    -------
    Callable
        接受 ``AgentState`` 并返回更新后状态的节点函数。
    """
    tools = [get_news]  # 复用新闻工具获取舆情数据

    prompt = ChatPromptTemplate.from_messages([
        ("system", (
            "你是一个A股市场舆情分析师。你的职责是分析市场情绪、投资者讨论热点，"
            "评估市场对该股票的整体情绪倾向。\n\n"
            "分析要点：\n"
            "1. 市场情绪倾向（乐观/悲观/中性）\n"
            "2. 投资者关注的热点话题\n"
            "3. 潜在的情绪反转信号\n"
            "4. 舆论一致性与分歧度\n\n"
            "请基于信息分析市场情绪，用中文回答。"
        )),
        MessagesPlaceholder(variable_name="messages"),
    ])

    bound_llm = llm.bind_tools(tools)
    chain = prompt | bound_llm

    def social_media_analyst_node(state: dict[str, Any]) -> dict[str, Any]:
        """舆情分析师节点：通过 ReAct 模式调用工具获取数据并生成情绪分析报告。"""
        result = chain.invoke({
            "messages": state["messages"],
        })

        if not result.tool_calls:
            return {
                "messages": [result],
                "sentiment_report": result.content,
            }

        return {"messages": [result]}

    return social_media_analyst_node
