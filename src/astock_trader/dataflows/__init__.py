"""astock_trader.dataflows — A-share data layer.

Replaces TradingAgents' yfinance + Alpha Vantage with A-share data sources
(akshare + EastMoney + Tushare + MX).  All public functions return formatted
strings suitable for direct consumption by LLM agents.

Quick start::

    from astock_trader.dataflows import (
        get_stock_data,
        get_indicators,
        get_fundamentals,
        get_news,
        route_to_vendor,
    )

    # Direct call
    table = get_stock_data("600519", "20250101", "20250401")

    # Or via the vendor router (respects global config)
    table = route_to_vendor("get_stock_data", "600519", "20250101", "20250401")
"""

# --- Config ---------------------------------------------------------------
# --- Core stock data (akshare) -------------------------------------------
from .akshare_data import (
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_income_statement,
    get_indicators,
    get_stock_data,
)
from .config import get_config, set_config

# --- News data (EastMoney / akshare) -------------------------------------
from .eastmoney_news import (
    get_global_news,
    get_insider_transactions,
    get_news,
)

# --- Vendor routing -------------------------------------------------------
from .interface import list_available_methods, route_to_vendor

__all__ = [
    # config
    "get_config",
    "set_config",
    # stock data
    "get_stock_data",
    "get_indicators",
    "get_fundamentals",
    "get_balance_sheet",
    "get_cashflow",
    "get_income_statement",
    # news
    "get_news",
    "get_global_news",
    "get_insider_transactions",
    # routing
    "route_to_vendor",
    "list_available_methods",
]
