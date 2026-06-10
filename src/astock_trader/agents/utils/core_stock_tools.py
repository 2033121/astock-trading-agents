"""核心股票数据工具 — 日线行情与基本技术指标。"""

from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool

from astock_trader.dataflows import route_to_vendor


@tool
def get_stock_data(
    symbol: Annotated[str, "A股股票代码，如 000001、600519"],
    start_date: Annotated[str, "开始日期，格式 yyyy-mm-dd"],
    end_date: Annotated[str, "结束日期，格式 yyyy-mm-dd"],
) -> str:
    """获取A股股票日线行情数据（前复权）。

    返回包含日期、开盘价、收盘价、最高价、最低价、成交量、涨跌幅等字段的 JSON 数据。
    """
    return route_to_vendor("get_stock_data", symbol=symbol, start_date=start_date, end_date=end_date)


@tool
def get_indicators(
    symbol: Annotated[str, "A股股票代码，如 000001、600519"],
    start_date: Annotated[str, "开始日期，格式 yyyy-mm-dd"],
    end_date: Annotated[str, "结束日期，格式 yyyy-mm-dd"],
) -> str:
    """获取股票技术指标数据（含均线 MA5/MA10/MA20 等）。

    返回包含价格走势和移动平均线的 JSON 数据。
    """
    return route_to_vendor("get_indicators", symbol=symbol, start_date=start_date, end_date=end_date)
