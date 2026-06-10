"""News and insider-transaction data from EastMoney / akshare.

Every public function returns a **formatted string** (Markdown-flavoured)
for direct consumption by LLM agents.  All akshare calls are wrapped in
try/except — on failure a descriptive error string is returned.
"""

from __future__ import annotations

import traceback
from datetime import timedelta
from typing import Annotated

import pandas as pd

try:
    import akshare as ak
except ImportError:  # pragma: no cover
    ak = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_akshare() -> str | None:
    if ak is None:
        return "[ERROR] akshare is not installed. Run: pip install akshare"
    return None


def _safe_call(func, *args, **kwargs):
    """Call *func* and return ``(result, None)`` or ``(None, error_string)``."""
    err = _ensure_akshare()
    if err:
        return None, err
    try:
        result = func(*args, **kwargs)
        return result, None
    except Exception as exc:
        tb = traceback.format_exc(limit=3)
        return None, f"[ERROR] {func.__name__} failed: {exc}\n{tb}"


def _fmt_number(val, decimals: int = 2) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "N/A"
    if isinstance(val, int):
        return f"{val:,}"
    try:
        return f"{float(val):,.{decimals}f}"
    except (ValueError, TypeError):
        return str(val)


def _df_to_markdown(df: pd.DataFrame, max_rows: int = 30) -> str:
    if df is None or df.empty:
        return "No data available."
    truncated = len(df) > max_rows
    table = df.head(max_rows).to_markdown(index=False)
    if truncated:
        table += f"\n\n... ({len(df) - max_rows} more rows omitted)"
    return table


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_news(
    symbol: Annotated[str, "A-share stock symbol, e.g. '000001'"],
    start_date: Annotated[str, "Start date 'YYYY-MM-DD' or 'YYYYMMDD' (used for filtering)"],
    end_date: Annotated[str, "End date 'YYYY-MM-DD' or 'YYYYMMDD' (used for filtering)"],
) -> str:
    """Get stock-specific news articles from EastMoney.

    Uses ``ak.stock_news_em(symbol)``.  Returns a formatted list of
    articles with title, source, date, and content summary.
    """
    df, err = _safe_call(ak.stock_news_em, symbol=symbol)
    if err:
        return f"get_news({symbol}): {err}"

    if df is None or df.empty:
        return f"get_news({symbol}): No news found."

    # Normalise column names — akshare returns Chinese headers
    col_map = {
        "新闻标题": "title",
        "新闻内容": "content",
        "发布时间": "datetime",
        "文章来源": "source",
        "新闻链接": "url",
    }
    df = df.rename(columns=col_map)

    # Parse dates and filter
    if "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
        try:
            start_dt = pd.Timestamp(start_date)
            end_dt = pd.Timestamp(end_date) + timedelta(days=1)  # inclusive end
            df = df[(df["datetime"] >= start_dt) & (df["datetime"] < end_dt)]
        except Exception:
            pass  # If date parsing fails, return all

    if df.empty:
        return f"get_news({symbol}): No news in range {start_date} ~ {end_date}."

    # Build output
    lines: list[str] = [f"## News — {symbol} ({start_date} ~ {end_date})\n"]
    for idx, row in df.head(20).iterrows():
        title = str(row.get("title", "N/A"))
        source = str(row.get("source", "N/A"))
        dt = str(row.get("datetime", "N/A"))
        content = str(row.get("content", ""))
        # Truncate long content
        if len(content) > 200:
            content = content[:200] + "..."

        lines.append(f"### {title}")
        lines.append(f"- **Source**: {source}")
        lines.append(f"- **Date**: {dt}")
        if content and content != "nan":
            lines.append(f"- **Summary**: {content}")
        lines.append("")

    if len(df) > 20:
        lines.append(f"... ({len(df) - 20} more articles omitted)")

    return "\n".join(lines)


def get_global_news(
    curr_date: Annotated[str, "Reference date 'YYYY-MM-DD' or 'YYYYMMDD'"],
    look_back_days: Annotated[int, "Number of days to look back"] = 7,
    limit: Annotated[int, "Maximum number of articles to return"] = 5,
) -> str:
    """Get market-wide / global financial news.

    Tries ``ak.stock_info_global_em()`` first (EastMoney global news),
    falls back to ``ak.stock_info_global_cls()`` (CLS / CaiLianShe).
    Returns top *limit* articles.
    """
    # Attempt 1: EastMoney global news
    df, err = _safe_call(ak.stock_info_global_em)
    if err or df is None or df.empty:
        # Attempt 2: CLS news
        df, err2 = _safe_call(ak.stock_info_global_cls)
        if err2 or df is None or df.empty:
            errors = []
            if err:
                errors.append(f"stock_info_global_em: {err}")
            if err2:
                errors.append(f"stock_info_global_cls: {err2}")
            return "get_global_news: " + "; ".join(errors)

    # Normalise columns
    col_map = {
        "标题": "title",
        "内容": "content",
        "发布时间": "datetime",
        "发布日期": "datetime",
        "来源": "source",
        "作者": "author",
    }
    df = df.rename(columns=col_map)

    # Parse dates and filter
    if "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
        try:
            end_dt = pd.Timestamp(curr_date) + timedelta(days=1)
            start_dt = end_dt - timedelta(days=look_back_days)
            mask = df["datetime"].between(start_dt, end_dt)
            filtered = df[mask]
            if not filtered.empty:
                df = filtered
        except Exception:
            pass

    lines: list[str] = [f"## Global Market News (as of {curr_date})\n"]
    for _, row in df.head(limit).iterrows():
        title = str(row.get("title", "N/A"))
        source = str(row.get("source", "N/A"))
        dt = str(row.get("datetime", "N/A"))
        content = str(row.get("content", ""))
        if len(content) > 300:
            content = content[:300] + "..."

        lines.append(f"### {title}")
        lines.append(f"- **Source**: {source}")
        lines.append(f"- **Date**: {dt}")
        if content and content != "nan":
            lines.append(f"- **Summary**: {content}")
        lines.append("")

    return "\n".join(lines)


def get_insider_transactions(
    symbol: Annotated[str, "A-share stock symbol, e.g. '000001'"],
) -> str:
    """Get recent block trades (大宗交易) as a proxy for insider activity.

    Uses ``ak.stock_dzjy_mingxi(symbol)`` for detailed block-trade records.
    Returns a formatted Markdown table.
    """
    df, err = _safe_call(ak.stock_dzjy_mingxi, symbol=symbol)
    if err:
        # Fallback: try the stock_dzjy_detail function
        df, err2 = _safe_call(ak.stock_dzjy_detail, symbol=symbol)
        if err2:
            return f"get_insider_transactions({symbol}): {err}; fallback: {err2}"

    if df is None or df.empty:
        return f"get_insider_transactions({symbol}): No block trade (大宗交易) data found."

    # Normalise common column names
    col_map = {
        "交易日期": "date",
        "成交价": "price",
        "成交金额": "amount",
        "成交量": "volume",
        "买方营业部": "buyer",
        "卖方营业部": "seller",
        "溢价率": "premium_rate",
        "折价率": "discount_rate",
        "收盘价": "close_price",
    }
    df = df.rename(columns=col_map)

    # Keep useful columns
    preferred = ["date", "price", "close_price", "premium_rate", "discount_rate", "volume", "amount", "buyer", "seller"]
    keep = [c for c in preferred if c in df.columns]
    if keep:
        df = df[keep]

    # Format numeric columns
    for c in ["price", "close_price", "volume", "amount"]:
        if c in df.columns:
            df[c] = df[c].apply(lambda x: _fmt_number(x, 2))
    for c in ["premium_rate", "discount_rate"]:
        if c in df.columns:
            df[c] = df[c].apply(lambda x: f"{float(x):.2f}%" if pd.notna(x) else "N/A")

    header = f"## Block Trades (大宗交易) — {symbol}\n\n"
    return header + _df_to_markdown(df, max_rows=30)
