"""基本面数据工具 — 财务报表、基本面指标。"""

from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool

from astock_trader.dataflows import route_to_vendor


@tool
def get_fundamentals(
    symbol: Annotated[str, "A股股票代码，如 000001、600519"],
) -> str:
    """获取股票基本面信息。

    返回公司基本信息，包括总市值、流通市值、市盈率、市净率、行业分类等。
    """
    return route_to_vendor("get_fundamentals", symbol=symbol)


@tool
def get_balance_sheet(
    symbol: Annotated[str, "A股股票代码，如 000001、600519"],
) -> str:
    """获取公司资产负债表数据。

    返回最近报告期的资产负债表，包含总资产、总负债、股东权益、流动资产等关键指标。
    """
    return route_to_vendor("get_balance_sheet", symbol=symbol)


@tool
def get_cashflow(
    symbol: Annotated[str, "A股股票代码，如 000001、600519"],
) -> str:
    """获取公司现金流量表数据。

    返回经营活动、投资活动、筹资活动的现金流入流出情况。
    """
    return route_to_vendor("get_cashflow", symbol=symbol)


@tool
def get_income_statement(
    symbol: Annotated[str, "A股股票代码，如 000001、600519"],
) -> str:
    """获取公司利润表数据。

    返回营业收入、营业成本、净利润、毛利率等盈利能力指标。
    """
    return route_to_vendor("get_income_statement", symbol=symbol)
