"""新闻与舆情数据工具 — 个股新闻、全球财经新闻、大宗交易。

时间点注入
----------
大宗交易工具的 ``trade_date`` 参数用 :class:`~langgraph.prebuilt.InjectedState`
标注：模型看不到它，由 LangGraph 从图状态注入本次运行的日期，再由数据层决定
放行哪些成交记录。大宗交易逐日公布，历史运行下把分析日之后的成交喂进去就是
前视偏差；日期由运行侧保证，不靠 prompt 提醒模型自己填。
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from astock_trader.dataflows import route_to_vendor
from astock_trader.point_in_time import run_as_of


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
    trade_date: Annotated[str, InjectedState("trade_date")] = "",
) -> str:
    """获取大宗交易数据（作为内部人活动与筹码交换的代理指标）。

    返回该股票近期的大宗交易记录，包括成交价、折溢率、成交量、买卖方营业部。
    历史运行下只返回分析日**之前已发生**的成交记录。
    """
    return route_to_vendor(
        "get_insider_transactions",
        symbol=symbol,
        curr_date=run_as_of(trade_date),
    )
