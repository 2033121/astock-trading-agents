"""新闻与舆情数据工具 — 个股新闻、全球财经新闻、大宗交易。"""

from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool

from astock_trader.dataflows import route_to_vendor


@tool
def get_news(
    symbol: Annotated[str, "A股股票代码，如 000001、600519"],
) -> str:
    """获取个股相关新闻。

    返回该股票最近的新闻报道，包括标题、内容和发布时间，用于分析市场情绪和事件驱动因素。
    """
    return route_to_vendor("get_news", symbol=symbol)


@tool
def get_global_news() -> str:
    """获取全球财经新闻摘要。

    返回最新的全球财经市场新闻，用于分析宏观环境和外盘影响。
    """
    return route_to_vendor("get_global_news")


@tool
def get_insider_transactions(
    symbol: Annotated[str, "A股股票代码，如 000001、600519"],
) -> str:
    """获取大宗交易 / 内部交易数据。

    返回该股票近期的大宗交易记录，包括交易价格、成交量、买卖方营业部等信息。
    """
    return route_to_vendor("get_insider_transactions", symbol=symbol)
