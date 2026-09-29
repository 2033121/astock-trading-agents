"""Data vendor routing system — routes tool calls to configured data providers.

The routing table ``VENDOR_METHODS`` maps each logical method name to one or
more vendor implementations.  ``route_to_vendor`` resolves the correct
implementation based on the global config (``config.get_config()``), with
automatic fallback through the vendor priority list.

换源的两个触发条件
------------------
1. 数据源**抛异常** —— 按 :mod:`astock_trader.dataflows.errors` 里的类型给出
   合适的日志级别：缺 key 是预期内的（debug），限流和故障才是 warning。
2. 数据源**返回 ``"[ERROR] ..."`` 软失败串** —— 这也是失败。此前这类返回值被
   当成正常结果直接返回给调用方，导致「第一个数据源报错就整条 fallback 链作废」：
   例如妙想配额用尽时，链上的 Tushare / 东方财富 / akshare 根本不会被尝试。
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

from .config import get_config
from .errors import (
    NoMarketDataError,
    VendorError,
    VendorNotConfiguredError,
    VendorRateLimitError,
    is_failure_payload,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Vendor routing table
# ---------------------------------------------------------------------------
# Each key is a logical tool name.  The value is an ordered dict of
# ``vendor_label -> "module_function_name"``.  The *first* vendor whose
# module can be imported is used; remaining vendors serve as fallbacks.

VENDOR_METHODS: dict[str, dict[str, str]] = {
    # --- Core price / technical data (akshare) ---
    "get_stock_data": {"akshare": "get_stock_data"},
    "get_indicators": {"akshare": "get_indicators"},
    # --- Financial data (Tushare → MX → akshare fallback) ---
    "get_fundamentals": {"tushare": "get_fundamentals", "mx": "get_fundamentals", "akshare": "get_fundamentals"},
    "get_balance_sheet": {"tushare": "get_balance_sheet", "mx": "get_balance_sheet", "akshare": "get_balance_sheet"},
    "get_cashflow": {"tushare": "get_cashflow", "mx": "get_cashflow", "akshare": "get_cashflow"},
    "get_income_statement": {"tushare": "get_income", "mx": "get_income_statement", "akshare": "get_income_statement"},
    # --- News (MX → Tushare → eastmoney → akshare fallback) ---
    "get_news": {"mx": "get_news", "tushare": "get_news", "eastmoney": "get_news", "akshare": "get_news"},
    "get_global_news": {"mx": "get_global_news", "eastmoney": "get_global_news"},
    "get_insider_transactions": {"akshare": "get_insider_transactions"},
    # --- MX-exclusive data ---
    "get_stock_valuation": {"mx": "get_stock_valuation"},
    "get_shareholder_info": {"mx": "get_shareholder_info"},
    # --- Tushare-exclusive data (structured / quantitative) ---
    "get_daily_basic": {"tushare": "get_daily_basic"},
    "get_fina_indicator": {"tushare": "get_fina_indicator"},
    "get_moneyflow": {"tushare": "get_moneyflow"},
    "get_top10_holders": {"tushare": "get_top10_holders"},
    "get_top10_floatholders": {"tushare": "get_top10_floatholders"},
    "get_holdertrade": {"tushare": "get_holdertrade"},
    "get_forecast": {"tushare": "get_forecast"},
    "get_express": {"tushare": "get_express"},
    "get_dividend": {"tushare": "get_dividend"},
    "get_margin_detail": {"tushare": "get_margin_detail"},
    # --- Industry chain / peers (MX → akshare fallback) ---
    "get_industry_chain": {"mx": "get_industry_chain", "akshare": "get_industry_chain"},
    "get_industry_peers": {"mx": "get_industry_peers", "akshare": "get_industry_peers"},
}

# Mapping from vendor label to the module that contains its implementation.
_VENDOR_MODULES: dict[str, str] = {
    "akshare": "astock_trader.dataflows.akshare_data",
    "eastmoney": "astock_trader.dataflows.eastmoney_news",
    "mx": "astock_trader.dataflows.mx_data",
    "tushare": "astock_trader.dataflows.tushare_data",
}

# Cache of already-imported modules.
_module_cache: dict[str, Any] = {}


def _import_vendor_module(vendor: str) -> Any | None:
    """Import and cache a vendor module; return None on failure."""
    if vendor in _module_cache:
        return _module_cache[vendor]
    module_path = _VENDOR_MODULES.get(vendor)
    if module_path is None:
        logger.warning("Unknown vendor '%s' — no module mapping.", vendor)
        return None
    try:
        mod = importlib.import_module(module_path)
        _module_cache[vendor] = mod
        return mod
    except ImportError as exc:
        logger.warning("Cannot import vendor module '%s': %s", module_path, exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def route_to_vendor(method: str, *args: Any, **kwargs: Any) -> Any:
    """Route a data-tool call to the configured vendor implementation.

    Resolution order:
    1. If the global config contains ``{"data_vendor": "<vendor>"}`` **and**
       that vendor supports *method*, use it.
    2. Otherwise iterate through the vendor list for *method* in declaration
       order (first = primary) and use the first one that loads.
    3. If no vendor works, return an error string.

    一个数据源只有在**既没抛异常、也没返回 ``[ERROR]`` 串**时才算成功；否则
    继续尝试链上的下一个。全部失败时返回最后一个原因，方便定位。

    Args:
        method: Logical tool name (must be a key in ``VENDOR_METHODS``).
        *args: Positional arguments forwarded to the implementation.
        **kwargs: Keyword arguments forwarded to the implementation.

    Returns:
        The return value of the underlying implementation (typically a str).
    """
    if method not in VENDOR_METHODS:
        return f"[ERROR] Unknown data method '{method}'. Available: {list(VENDOR_METHODS.keys())}"

    vendors = VENDOR_METHODS[method]
    config = get_config()
    preferred_vendor = config.get("data_vendor")

    # Build ordered vendor list: preferred first, then the rest in declaration order.
    ordered: list[str] = []
    if preferred_vendor and preferred_vendor in vendors:
        ordered.append(preferred_vendor)
    for v in vendors:
        if v not in ordered:
            ordered.append(v)

    last_error: str | None = None
    for vendor in ordered:
        func_name = vendors[vendor]
        mod = _import_vendor_module(vendor)
        if mod is None:
            last_error = f"vendor module for '{vendor}' could not be imported"
            continue

        func = getattr(mod, func_name, None)
        if func is None:
            last_error = f"'{vendor}' module has no function '{func_name}'"
            continue

        try:
            payload = func(*args, **kwargs)
        except VendorNotConfiguredError as exc:
            # 缺 key／缺依赖属于预期内的「这个源用不了」，不该刷 warning。
            last_error = f"{vendor} is not configured: {exc}"
            logger.debug("Vendor %s.%s not configured: %s", vendor, func_name, exc)
            continue
        except VendorRateLimitError as exc:
            last_error = f"{vendor} is rate limited: {exc}"
            logger.warning("Vendor %s.%s is rate limited: %s", vendor, func_name, exc)
            continue
        except NoMarketDataError as exc:
            last_error = f"{vendor} has no usable data: {exc}"
            logger.info("Vendor %s.%s returned no usable data: %s", vendor, func_name, exc)
            continue
        except VendorError as exc:
            last_error = f"{vendor} is unavailable: {exc}"
            logger.warning("Vendor %s.%s unavailable: %s", vendor, func_name, exc)
            continue
        except Exception as exc:
            last_error = f"{vendor}.{func_name} raised: {exc}"
            logger.warning("Vendor %s.%s failed: %s", vendor, func_name, exc)
            continue

        if is_failure_payload(payload):
            last_error = f"{vendor}.{func_name}: {str(payload).strip()[:300]}"
            logger.warning(
                "Vendor %s.%s returned an error payload; falling back to the next vendor.",
                vendor,
                func_name,
            )
            continue

        return payload

    if len(ordered) == 1:
        return f"[ERROR] Data vendor '{ordered[0]}' unavailable for '{method}': {last_error}"
    return f"[ERROR] All vendors failed for '{method}': {last_error}"


def list_available_methods() -> dict[str, list[str]]:
    """Return a mapping of method -> list of vendors that are currently importable."""
    result: dict[str, list[str]] = {}
    for method, vendors in VENDOR_METHODS.items():
        available = []
        for vendor in vendors:
            mod = _import_vendor_module(vendor)
            if mod is not None and hasattr(mod, vendors[vendor]):
                available.append(vendor)
        result[method] = available
    return result
