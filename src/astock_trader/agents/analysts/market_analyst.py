"""市场分析师 Agent — 分析股票技术指标、价格走势、成交量等数据。

使用 ReAct 模式：将工具绑定到 LLM，通过多轮工具调用获取数据后生成技术分析报告。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from astock_trader.agents.utils.core_stock_tools import get_indicators, get_stock_data


def create_market_analyst(llm: Any) -> Callable:
    """创建市场分析师节点。

    Parameters
    ----------
    llm : BaseChatModel
        LangChain 聊天模型实例。

    Returns
    -------
    Callable
        接受 ``AgentState`` 并返回更新后状态的节点函数。
    """
    tools = [get_stock_data, get_indicators]

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                (
                    "你是一个A股市场技术分析师。你的职责是分析股票的技术指标、价格走势、"
                    "成交量等数据，从技术面角度给出专业的市场分析。\n\n"
                    "分析要点：\n"
                    "1. 价格趋势（上升/下降/震荡）\n"
                    "2. 关键支撑位和阻力位\n"
                    "3. 成交量变化特征\n"
                    "4. 移动平均线系统信号\n\n"
                    "请基于数据做出客观分析，用中文回答。"
                ),
            ),
            MessagesPlaceholder(variable_name="messages"),
        ]
    )

    bound_llm = llm.bind_tools(tools)
    chain = prompt | bound_llm

    def market_analyst_node(state: dict[str, Any]) -> dict[str, Any]:
        """市场分析师节点：通过 ReAct 模式调用工具获取数据并生成分析报告。"""
        result = chain.invoke(
            {
                "messages": state["messages"],
            }
        )

        # 如果没有工具调用，说明 LLM 已完成分析，输出最终报告
        if not result.tool_calls:
            return {
                "messages": [result],
                "market_report": result.content,
            }

        # 有工具调用，返回中间消息让 ToolNode 执行
        return {"messages": [result]}

    return market_analyst_node
