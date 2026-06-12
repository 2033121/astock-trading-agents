"""新闻与宏观分析师 Agent — 分析相关新闻、宏观经济环境、行业景气度和市场动态。

使用 ReAct 模式：将工具绑定到 LLM，通过多轮工具调用获取新闻和交易数据后生成新闻与宏观分析报告。
包含宏观经济周期判断、货币/财政政策分析、行业景气度评估等维度。
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
from astock_trader.agents.utils.macro_tools import get_macro_assessment


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
    tools = [get_news, get_global_news, get_insider_transactions, get_macro_assessment]

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                (
                    "你是一个A股新闻分析师。你的职责是分析与目标股票相关的新闻报道和市场动态，"
                    "评估外部因素对股价的影响。\n\n"
                    "分析要点：\n"
                    "1. 近期重要新闻事件及其对个股的影响\n"
                    "2. 行业与政策动态\n"
                    "3. 全球市场联动效应（海外市场、大宗商品、汇率）\n"
                    "4. 大宗交易信号与资金流向\n\n"
                    "关于宏观环境：\n"
                    "- 请**首先调用 get_macro_assessment 工具**获取最新的月度宏观评估报告\n"
                    "- 该报告包含市场指数、北向资金、行业板块表现、市场情绪等数据\n"
                    "- 在分析中引用宏观评估的关键结论作为背景\n"
                    "- **不要重复分析宏观面**，直接使用宏观评估报告中的结论\n"
                    "- 仅当个股所在行业与宏观评估中的行业趋势有特别关联时，才做补充分析\n\n"
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
