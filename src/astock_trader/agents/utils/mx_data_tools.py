"""妙想 (MX) 独有数据工具 — 估值查询和股东信息。

这些工具仅在妙想 API 可用时使用，通过 route_to_vendor 路由。
"""

from typing import Annotated

from langchain_core.tools import tool

from astock_trader.dataflows.interface import route_to_vendor


@tool
def get_stock_valuation(
    symbol: Annotated[str, "A股股票代码，如 000001 或 600519"],
    curr_date: Annotated[str, "当前日期（可选）"] = None,
) -> str:
    """查询股票估值数据，包括 PE/PB/PS/股息率及历史分位。基于东方财富权威数据源。"""
    return route_to_vendor("get_stock_valuation", symbol, curr_date=curr_date)


@tool
def get_shareholder_info(
    symbol: Annotated[str, "A股股票代码，如 000001 或 600519"],
    curr_date: Annotated[str, "当前日期（可选）"] = None,
) -> str:
    """查询公司十大股东、持股变动和机构持仓信息。基于东方财富权威数据源。"""
    return route_to_vendor("get_shareholder_info", symbol, curr_date=curr_date)
