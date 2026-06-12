"""基本面分析师 Agent — 分析公司财务报表、盈利能力、估值水平和产业链地位。

使用 ReAct 模式：将工具绑定到 LLM，通过多轮工具调用获取财务数据后生成基本面分析报告。
包含产业链上下游分析、竞争格局评估、可比公司估值对比等维度。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from astock_trader.agents.utils.fundamental_data_tools import (
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_income_statement,
)
from astock_trader.agents.utils.industry_chain_tools import (
    get_industry_chain,
    get_industry_peers,
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
    tools = [
        get_fundamentals,
        get_balance_sheet,
        get_cashflow,
        get_income_statement,
        get_industry_chain,
        get_industry_peers,
    ]

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                (
                    "你是一个A股基本面分析师。你的职责是分析公司财务报表、盈利能力、估值水平"
                    "和产业链地位，评估公司的内在价值和投资吸引力。\n\n"
                    "分析要点：\n"
                    "1. 盈利能力（营收增长、净利润、毛利率、ROE）\n"
                    "2. 资产负债状况（资产负债率、流动性）\n"
                    "3. 现金流质量（经营性现金流、自由现金流）\n"
                    "4. 估值水平（PE、PB 与行业及可比公司比较）\n"
                    "5. 产业链分析（必须包含）：\n"
                    "   - 公司在产业链中的位置（上游/中游/下游）及业务构成\n"
                    "   - 上游原材料供应商及议价能力（供应集中度、替代性）\n"
                    "   - 下游客户结构及议价能力（客户集中度、转换成本）\n"
                    "   - 同行业竞争格局（主要竞争对手、市占率、差异化程度）\n"
                    "   - 行业壁垒与护城河（技术、品牌、规模、牌照等）\n"
                    "6. 多业务板块分析（重要）：\n"
                    "   - 如果公司涉及多个业务板块（从营收构成中识别），"
                    "必须**分别分析**各板块的产业链和竞争格局\n"
                    "   - 各板块分别列出：上下游关系、主要竞争对手、市占率\n"
                    "   - 评估各板块对整体营收/利润的贡献和增长前景\n"
                    "   - 最终给出综合判断：哪个板块是核心驱动力、哪个是拖累项\n"
                    "7. 估值对比：列出 3-5 家可比公司，对比 PE/PB/市值/增速，"
                    "判断当前估值在行业中的相对位置\n\n"
                    "请基于财务数据和行业认知进行专业分析，用中文回答。"
                    "你可以通过 get_industry_chain 工具查询产业链上下游信息，"
                    "通过 get_industry_peers 工具获取同行业及概念板块可比公司数据"
                    "（该工具会自动匹配行业+概念板块的交叉对比）。"
                    "请务必调用这两个工具获取实际数据，而非仅依赖自身知识。"
                ),
            ),
            MessagesPlaceholder(variable_name="messages"),
        ]
    )

    bound_llm = llm.bind_tools(tools)
    chain = prompt | bound_llm

    def fundamentals_analyst_node(state: dict[str, Any]) -> dict[str, Any]:
        """基本面分析师节点：通过 ReAct 模式调用工具获取财务数据并生成分析报告。"""
        result = chain.invoke(
            {
                "messages": state["messages"],
            }
        )

        if not result.tool_calls:
            return {
                "messages": [result],
                "fundamentals_report": result.content,
            }

        return {"messages": [result]}

    return fundamentals_analyst_node
