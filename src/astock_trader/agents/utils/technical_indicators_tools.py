"""技术指标数据工具 — 均线系统与量能趋势的组合视图。"""

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
    """获取区间内的均线系统与成交量趋势，用于快速判断趋势结构。

    一次返回 MA5/MA10/MA20/MA60 四条均线、成交量与其 5 日均量，以及
    均线排列（多头/空头）、价格与 MA20 的相对位置、量能放缩的解读。

    与 ``get_indicators`` 的分工：那个一次算一个指标（MACD/RSI/BOLL 等），
    这个给整条均线带。需要 MACD/RSI/BOLL 时请用 ``get_indicators``。

    区间外的历史数据仅用于均线预热，不会出现在结果中。
    """
    return route_to_vendor(
        "get_technical_indicators",
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
    )
