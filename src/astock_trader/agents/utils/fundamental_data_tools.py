"""基本面数据工具 — 财务报表、基本面指标。

时间点注入
----------
这四个工具的 ``trade_date`` 参数用 :class:`~langgraph.prebuilt.InjectedState`
标注：模型看不到它，由 LangGraph 在执行时从图状态里取出本次运行的日期。
工具据此算出 ``curr_date`` 交给数据层门控 —— 历史运行下只放行分析日之前
**已经披露**的报告期，实时运行不门控（见 :func:`astock_trader.point_in_time.run_as_of`）。

日期必须由运行侧注入而不是让模型自己填：模型漏填一次，历史运行就退回
「最新财报快照」的前视偏差。
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from astock_trader.dataflows import route_to_vendor
from astock_trader.point_in_time import run_as_of


@tool
def get_fundamentals(
    symbol: Annotated[str, "A股股票代码，如 000001、600519"],
    trade_date: Annotated[str, InjectedState("trade_date")] = "",
) -> str:
    """获取股票基本面信息。

    返回公司基本信息，包括行业分类、市盈率、市净率、ROE，以及已披露报告期的
    财务摘要（历史运行下只含分析日之前已披露的报告期）。
    """
    return route_to_vendor("get_fundamentals", symbol=symbol, curr_date=run_as_of(trade_date))


@tool
def get_balance_sheet(
    symbol: Annotated[str, "A股股票代码，如 000001、600519"],
    trade_date: Annotated[str, InjectedState("trade_date")] = "",
) -> str:
    """获取公司资产负债表数据。

    返回分析日之前已披露的最近报告期的资产负债表，包含总资产、总负债、
    股东权益、流动资产等关键指标。
    """
    return route_to_vendor("get_balance_sheet", symbol=symbol, curr_date=run_as_of(trade_date))


@tool
def get_cashflow(
    symbol: Annotated[str, "A股股票代码，如 000001、600519"],
    trade_date: Annotated[str, InjectedState("trade_date")] = "",
) -> str:
    """获取公司现金流量表数据。

    返回分析日之前已披露的最近报告期的经营、投资、筹资活动现金流入流出情况。
    """
    return route_to_vendor("get_cashflow", symbol=symbol, curr_date=run_as_of(trade_date))


@tool
def get_income_statement(
    symbol: Annotated[str, "A股股票代码，如 000001、600519"],
    trade_date: Annotated[str, InjectedState("trade_date")] = "",
) -> str:
    """获取公司利润表数据。

    返回分析日之前已披露的最近报告期的营业收入、营业成本、净利润、毛利率等
    盈利能力指标。
    """
    return route_to_vendor("get_income_statement", symbol=symbol, curr_date=run_as_of(trade_date))
