"""Tushare 独有数据工具 — 资金流向、财务指标、业绩预告、融资融券等。

这些工具通过 route_to_vendor 路由，提供 Tushare 独有的结构化数据能力。
"""

from typing import Annotated

from langchain_core.tools import tool

from astock_trader.dataflows.interface import route_to_vendor


@tool
def get_moneyflow(
    symbol: Annotated[str, "A股股票代码，如 000001 或 600519"],
    start_date: Annotated[str, "开始日期 yyyy-mm-dd"] = "",
    end_date: Annotated[str, "结束日期 yyyy-mm-dd"] = "",
) -> str:
    """获取个股资金流向数据，包括大单/中单/小单/超大单的买入卖出分析，用于判别资金动向。"""
    return route_to_vendor("get_moneyflow", symbol, start_date=start_date, end_date=end_date)


@tool
def get_daily_basic(
    symbol: Annotated[str, "A股股票代码，如 000001 或 600519"],
    start_date: Annotated[str, "开始日期 yyyy-mm-dd"] = "",
    end_date: Annotated[str, "结束日期 yyyy-mm-dd"] = "",
) -> str:
    """获取每日基本面指标，包括PE/PB/市值/换手率/股息率/量比等，适合估值分析和选股。"""
    return route_to_vendor("get_daily_basic", symbol, start_date=start_date, end_date=end_date)


@tool
def get_fina_indicator(
    symbol: Annotated[str, "A股股票代码，如 000001 或 600519"],
    start_date: Annotated[str, "报告期开始 yyyy-mm-dd"] = "",
    end_date: Annotated[str, "报告期结束 yyyy-mm-dd"] = "",
) -> str:
    """获取详细财务指标数据，包括ROE/ROA/毛利率/净利率/资产周转率/偿债能力等200+指标。"""
    return route_to_vendor("get_fina_indicator", symbol, start_date=start_date, end_date=end_date)


@tool
def get_forecast(
    symbol: Annotated[str, "A股股票代码，如 000001 或 600519"],
    start_date: Annotated[str, "公告开始日期 yyyy-mm-dd"] = "",
    end_date: Annotated[str, "公告结束日期 yyyy-mm-dd"] = "",
) -> str:
    """获取业绩预告数据，包括预增/预减/扭亏/首亏等类型，了解公司业绩预期变化。"""
    return route_to_vendor("get_forecast", symbol, start_date=start_date, end_date=end_date)


@tool
def get_holdertrade(
    symbol: Annotated[str, "A股股票代码，如 000001 或 600519"],
    start_date: Annotated[str, "公告开始日期 yyyy-mm-dd"] = "",
    end_date: Annotated[str, "公告结束日期 yyyy-mm-dd"] = "",
) -> str:
    """获取股东增减持数据，了解重要股东的股份变动情况，判断内部人信心。"""
    return route_to_vendor("get_holdertrade", symbol, start_date=start_date, end_date=end_date)


@tool
def get_margin_detail(
    symbol: Annotated[str, "A股股票代码，如 000001 或 600519"],
    start_date: Annotated[str, "开始日期 yyyy-mm-dd"] = "",
    end_date: Annotated[str, "结束日期 yyyy-mm-dd"] = "",
) -> str:
    """获取融资融券交易明细，了解杠杆资金动向。"""
    return route_to_vendor("get_margin_detail", symbol, start_date=start_date, end_date=end_date)


@tool
def get_dividend(
    symbol: Annotated[str, "A股股票代码，如 000001 或 600519"],
    start_date: Annotated[str, "公告开始日期 yyyy-mm-dd"] = "",
    end_date: Annotated[str, "公告结束日期 yyyy-mm-dd"] = "",
) -> str:
    """获取分红送股历史数据，了解公司分红政策和股东回报。"""
    return route_to_vendor("get_dividend", symbol, start_date=start_date, end_date=end_date)
