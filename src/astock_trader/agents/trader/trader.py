"""交易员 Agent — 基于研究员方案制定具体交易计划。

使用结构化输出（TraderProposal schema），将研究员的投资建议转化为
可执行的交易提案（入场价、止损价、仓位等）。
支持 functools.partial 绑定股票名称参数。
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from astock_trader.agents.schemas import TraderProposal, render_trader_proposal
from astock_trader.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)


def create_trader(llm: Any) -> Callable:
    """创建交易员节点工厂。

    返回一个可被 ``functools.partial`` 绑定 ``company_name`` 参数的函数。

    Parameters
    ----------
    llm : BaseChatModel
        LangChain 聊天模型实例。

    Returns
    -------
    Callable
        返回 ``_trader_node`` 函数，需通过 ``functools.partial`` 绑定
        ``company_name`` 参数后作为 LangGraph 节点使用。

    Examples
    --------
    >>> trader_factory = create_trader(llm)
    >>> trader_node = functools.partial(trader_factory, company_name="贵州茅台")
    """
    # 尝试绑定结构化输出
    structured_llm = bind_structured(llm, TraderProposal, "trader")

    def trader_node(state: dict[str, Any], *, company_name: str = "") -> dict[str, Any]:
        """交易员节点：基于研究员方案制定具体交易计划。

        Parameters
        ----------
        state : dict
            AgentState 状态字典。
        company_name : str
            目标公司名称（通过 functools.partial 绑定）。
        """
        company = company_name or state.get("company_of_interest", "目标股票")
        investment_plan = state.get("investment_plan", "暂无投资方案")

        prompt_text = (
            f"你是专业交易员，需要基于研究员的投资方案，为 **{company}** 制定具体的交易执行计划。\n\n"
            f"### 研究员投资方案\n{investment_plan}\n\n"
            "请制定交易计划，包括：\n"
            "1. 交易动作（买入/持有/卖出）\n"
            "2. 交易理由（简明扼要说明执行逻辑）\n"
            "3. 建议入场价（如适用）\n"
            "4. 止损价（如适用）\n"
            "5. 仓位建议（如适用，给出具体比例或金额）\n\n"
            "请用中文输出，计划应具体、可执行。"
        )

        prompt_messages = [("human", prompt_text)]

        result = invoke_structured_or_freetext(
            structured_llm=structured_llm,
            plain_llm=llm,
            prompt=prompt_messages,
            render=render_trader_proposal,
            agent_name="trader",
        )

        return {"trader_investment_plan": result}

    return trader_node


def create_trader_for_company(llm: Any, company_name: str) -> Callable:
    """创建绑定特定公司名称的交易员节点（便捷工厂函数）。

    Parameters
    ----------
    llm : BaseChatModel
        LangChain 聊天模型实例。
    company_name : str
        目标公司名称。

    Returns
    -------
    Callable
        已绑定 ``company_name`` 的交易员节点函数。
    """
    return functools.partial(create_trader(llm), company_name=company_name)
