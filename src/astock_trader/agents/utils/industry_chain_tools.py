"""产业链数据工具 — 行业分类、可比公司、产业链上下游。

提供两个工具：
- get_industry_chain: 查询公司产业链信息（上下游供应商、客户、竞争格局）
- get_industry_peers: 获取同行业可比公司列表及估值对比
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool

from astock_trader.dataflows import route_to_vendor


@tool
def get_industry_chain(
    symbol: Annotated[str, "A股股票代码，如 000001、600519"],
) -> str:
    """查询公司产业链信息。

    返回公司在产业链中的位置、上游供应商、下游客户、主要竞争对手和市场份额等信息。
    优先使用妙想 API 查询，不可用时返回行业分类信息作为替代。
    """
    return route_to_vendor("get_industry_chain", symbol=symbol)


@tool
def get_industry_peers(
    symbol: Annotated[str, "A股股票代码，如 000001、600519"],
) -> str:
    """获取同行业可比公司列表及估值对比。

    返回公司所属行业板块的成分股列表（前15家），包含股价、市值、PE、PB 等关键指标，
    用于可比公司估值分析。数据来源于东方财富行业板块。
    """
    return route_to_vendor("get_industry_peers", symbol=symbol)
