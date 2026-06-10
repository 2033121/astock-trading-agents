"""技术指标数据工具 — 提供更丰富的技术分析指标。"""

from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool

from astock_trader.dataflows import route_to_vendor


@tool
def get_technical_indicators(
    symbol: Annotated[str, "A股股票代码，如 000001、600519"],
    start_date: Annotated[str, "开始日期，格式 yyyy-mm-dd"],
    end_date: Annotated[str, "结束日期，格式 yyyy-mm-dd"],
) -> str:
    """获取股票技术分析指标。

    包含均线系统（MA5/10/20）、成交量趋势等关键技术指标，用于辅助判断趋势和买卖信号。
    """
    return route_to_vendor("get_indicators", symbol=symbol, start_date=start_date, end_date=end_date)
