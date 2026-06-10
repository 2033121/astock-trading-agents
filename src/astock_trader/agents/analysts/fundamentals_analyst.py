"""基本面分析师 Agent — 分析公司财务报表、盈利能力和估值水平。

使用 ReAct 模式：将工具绑定到 LLM，通过多轮工具调用获取财务数据后生成基本面分析报告。
"""

from __future__ import annotations

from typing import Any, Callable

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from astock_trader.agents.utils.fundamental_data_tools import (
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement,
)


def create_fundamentals_analyst(llm: Any) -> Callable:
    """创建基本面分析师节点。

    Parameters
    ----------
    llm : BaseChatModel
        LangChain 聊天模型实例。

    Returns
    -------
    Callable
        接受 ``AgentState`` 并返回更新后状态的节点函数。
    """
    tools = [get_fundamentals, get_balance_sheet, get_cashflow, get_income_statement]

    prompt = ChatPromptTemplate.from_messages([
        ("system", (
            "你是一个A股基本面分析师。你的职责是分析公司财务报表、盈利能力和估值水平，"
            "评估公司的内在价值和投资吸引力。\n\n"
            "分析要点：\n"
            "1. 盈利能力（营收增长、净利润、毛利率、ROE）\n"
            "2. 资产负债状况（资产负债率、流动性）\n"
            "3. 现金流质量（经营性现金流、自由现金流）\n"
            "4. 估值水平（PE、PB 与行业比较）\n\n"
            "请基于财务数据进行专业分析，用中文回答。"
        )),
        MessagesPlaceholder(variable_name="messages"),
    ])

    bound_llm = llm.bind_tools(tools)
    chain = prompt | bound_llm

    def fundamentals_analyst_node(state: dict[str, Any]) -> dict[str, Any]:
        """基本面分析师节点：通过 ReAct 模式调用工具获取财务数据并生成分析报告。"""
        result = chain.invoke({
            "messages": state["messages"],
        })

        if not result.tool_calls:
            return {
                "messages": [result],
                "fundamentals_report": result.content,
            }

        return {"messages": [result]}

    return fundamentals_analyst_node
