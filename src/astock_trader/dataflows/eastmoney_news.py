"""News and insider-transaction data from EastMoney / akshare.

Every public function returns a **formatted string** (Markdown-flavoured)
for direct consumption by LLM agents.  All akshare calls are wrapped in
try/except — on failure a descriptive error string is returned.
"""

from __future__ import annotations

import traceback
from datetime import datetime
from typing import Annotated

import pandas as pd

from astock_trader.point_in_time import in_window, window_reaches_present

from .symbols import to_bare_code

# 大宗交易默认回看窗口（自然日）。东财「每日明细」接口没有按个股查询的形式，
# 只能按区间拉全市场再筛，窗口开太大等于白拉几千行。
_BLOCK_TRADE_LOOKBACK_DAYS = 90

try:
    import akshare as ak
except ImportError:  # pragma: no cover
    ak = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _as_datetime(value) -> datetime | None:
    """把 pandas 时间戳转成 ``datetime``；``NaT`` / 空值返回 ``None``。

    ``None`` 表示「这条新闻没有可用的发布时间」，交给
    :func:`~astock_trader.point_in_time.in_window` 按窗口是否抵达当下决定去留。
    """
    if value is None or pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value
    try:
        return pd.Timestamp(value).to_pydatetime()
    except (TypeError, ValueError):
        return None


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
    #
    # 历史窗口里的新闻必须严格落在 [start_date, end_date] 内：晚于分析日的稿件
    # 属于未来信息。没有发布时间的条目在回测中同样要丢 —— 无法证明它不是未来。
    # （此前解析失败时直接 `pass` 保留全部，等于让回测读到未来稿件。）
    if "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
        df = df[df["datetime"].apply(lambda ts: in_window(_as_datetime(ts), start_date, end_date))]
    elif not window_reaches_present(start_date, end_date):
        df = df.iloc[0:0]

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
    #
    # 窗口是 [curr_date - look_back_days + 1, curr_date]。这里**无条件**套用过滤
    # 结果：此前只有在筛出非空结果时才采用，一旦窗口内没有稿件就退回未过滤的
    # 全量数据，历史窗口反而拿到了最新（未来）的新闻。
    if "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
        try:
            window_start = (pd.Timestamp(curr_date) - pd.Timedelta(days=look_back_days - 1)).strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            return f"get_global_news: Invalid curr_date '{curr_date}'."
        df = df[df["datetime"].apply(lambda ts: in_window(_as_datetime(ts), window_start, curr_date))]
    elif not window_reaches_present(curr_date, curr_date):
        df = df.iloc[0:0]

    if df.empty:
        return f"get_global_news: No news in window {curr_date} (look_back={look_back_days}d)."

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
    curr_date: Annotated[str | None, "Reference date 'YYYY-MM-DD'; None = live run"] = None,
) -> str:
    """Get recent block trades (大宗交易) as a proxy for insider activity.

    走东方财富「大宗交易-每日明细」（``ak.stock_dzjy_mrmx``）。该接口**没有按个股
    查询的形式** —— 只能按区间取全市场再按代码过滤，所以这里先拉窗口再筛。

    历史运行（``curr_date`` 非空）下只保留**分析日及之前**已发生的成交：大宗交易
    是逐日公布的，分析日之后的成交当时不可知，放进来就是前视偏差。

    .. note::
       此前这里调用的是 ``ak.stock_dzjy_mingxi`` / ``ak.stock_dzjy_detail`` ——
       **这两个函数在 akshare 里根本不存在**，所以这个工具从写下起就没成功过，
       情绪分析师长期拿不到大宗数据，只在报告里写一句「数据源异常」。
    """
    try:
        end_dt = pd.Timestamp(str(curr_date).strip()) if curr_date else pd.Timestamp.today().normalize()
    except (TypeError, ValueError):
        return f"get_insider_transactions({symbol}): invalid curr_date {curr_date!r}"

    start_dt = end_dt - pd.Timedelta(days=_BLOCK_TRADE_LOOKBACK_DAYS)
    start_str, end_str = start_dt.strftime("%Y%m%d"), end_dt.strftime("%Y%m%d")

    df, err = _safe_call(ak.stock_dzjy_mrmx, symbol="A股", start_date=start_str, end_date=end_str)
    if err:
        return f"get_insider_transactions({symbol}): {err}"
    if df is None or df.empty:
        return f"get_insider_transactions({symbol}): 全市场在 {start_str}~{end_str} 区间内无大宗交易记录。"

    df = df.rename(
        columns={
            "交易日期": "date",
            "成交价": "price",
            "成交额": "amount",
            "成交量": "volume",
            "折溢率": "premium_rate",
            "收盘价": "close_price",
            "买方营业部": "buyer",
            "卖方营业部": "seller",
        }
    )

    # 全市场 → 本标的。接口返回的代码是 6 位字符串，但补零更稳。
    code_col = "证券代码"
    if code_col in df.columns:
        df = df[df[code_col].astype(str).str.zfill(6) == to_bare_code(symbol)]

    if df.empty:
        return (
            f"get_insider_transactions({symbol}): 该标的在 {start_str}~{end_str} 区间内无大宗交易记录"
            f"（全市场同期有成交，只是这只票没有）。"
        )

    # 时点门控：分析日之后的成交当时不可知
    if curr_date is not None and "date" in df.columns:
        dates = pd.to_datetime(df["date"], errors="coerce")
        df = df[dates <= end_dt]

    if df.empty:
        return f"get_insider_transactions({symbol}): 该标的在 {start_str}~{end_str} 区间内无大宗交易记录。"

    keep = [
        c
        for c in ("date", "price", "close_price", "premium_rate", "volume", "amount", "buyer", "seller")
        if c in df.columns
    ]
    df = df[keep].copy()
    if "date" in df.columns:
        df = df.sort_values("date", ascending=False)

    for c in ("price", "close_price", "volume", "amount"):
        if c in df.columns:
            df[c] = df[c].apply(lambda x: _fmt_number(x, 2))
    if "premium_rate" in df.columns:
        df["premium_rate"] = df["premium_rate"].apply(lambda x: f"{float(x):.2f}%" if pd.notna(x) else "N/A")

    header = (
        f"## Block Trades (大宗交易) — {symbol}\n\n"
        f"> 区间 {start_str}~{end_str} · 成交量单位「万股」· 成交额单位「万元」· 折溢率为负表示折价成交\n\n"
    )
    return header + _df_to_markdown(df, max_rows=30)
