"""新闻分析师 Agent — 分析相关新闻、市场动态和大宗交易信息。

使用 ReAct 模式：将工具绑定到 LLM，通过多轮工具调用获取新闻和交易数据后生成新闻分析报告。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from astock_trader.agents.utils.news_data_tools import (
    get_global_news,
    get_insider_transactions,
    get_news,
)


def create_news_analyst(llm: Any) -> Callable:
    """创建新闻分析师节点。

    Parameters
    ----------
    llm : BaseChatModel
        LangChain 聊天模型实例。

    Returns
    -------
    Callable
        接受 ``AgentState`` 并返回更新后状态的节点函数。
    """
    tools = [get_news, get_global_news, get_insider_transactions]

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                (
                    "你是一个A股新闻分析师。你的职责是分析与目标股票相关的新闻报道、市场动态"
                    "和大宗交易信息，评估新闻对股价的潜在影响。\n\n"
                    "分析要点：\n"
                    "1. 近期重要新闻事件及其影响\n"
                    "2. 行业与政策动态\n"
                    "3. 全球市场联动效应\n"
                    "4. 大宗交易信号与资金流向\n\n"
                    "请基于新闻事实做出分析，用中文回答。"
                ),
            ),
            MessagesPlaceholder(variable_name="messages"),
        ]
    )

    bound_llm = llm.bind_tools(tools)
    chain = prompt | bound_llm

    def news_analyst_node(state: dict[str, Any]) -> dict[str, Any]:
        """新闻分析师节点：通过 ReAct 模式调用工具获取新闻数据并生成分析报告。"""
        result = chain.invoke(
            {
                "messages": state["messages"],
            }
        )

        if not result.tool_calls:
            return {
                "messages": [result],
                "news_report": result.content,
            }

        return {"messages": [result]}

    return news_analyst_node
