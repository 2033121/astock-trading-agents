"""核心股票数据工具 — 日线行情与单项技术指标。"""

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

    返回包含日期、开盘价、收盘价、最高价、最低价、成交量、成交额等字段的 JSON 数据。
    """
    return route_to_vendor("get_stock_data", symbol=symbol, start_date=start_date, end_date=end_date)


@tool
def get_indicators(
    symbol: Annotated[str, "A股股票代码，如 000001、600519"],
    indicator: Annotated[
        str,
        "指标名，取值之一：close_50_sma、close_200_sma、close_10_ema、macd、rsi、boll",
    ],
    curr_date: Annotated[str, "分析基准日（只看该日及之前的数据），格式 yyyy-mm-dd"],
    look_back_days: Annotated[int, "回看天数，默认 60"] = 60,
) -> str:
    """获取**单个**技术指标的取值与最新信号。

    可用指标：
      - close_50_sma  : 50 日均线
      - close_200_sma : 200 日均线
      - close_10_ema  : 10 日指数均线
      - macd          : MACD 线、信号线、柱状图及金叉/死叉
      - rsi           : 14 日相对强弱指标及超买/超卖区间
      - boll          : 布林带（20 日，2 倍标准差）及价格所处位置

    需要一次看整条均线带（MA5/10/20/60 + 量能）时改用 ``get_technical_indicators``。

    参数名必须与上表一致 —— 该工具只接受 ``indicator`` 与 ``curr_date``，
    没有 ``start_date`` / ``end_date``。
    """
    return route_to_vendor(
        "get_indicators",
        symbol=symbol,
        indicator=indicator,
        curr_date=curr_date,
        look_back_days=look_back_days,
    )
