"""Core A-share stock data functions powered by akshare.

Every public function returns a **formatted string** (Markdown-flavoured)
so it can be consumed directly by LLM agents as tool output.  All akshare
calls are wrapped in try/except — on failure a descriptive error string is
returned instead of raising.
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import Sequence
from datetime import timedelta
from typing import Annotated

import pandas as pd

from astock_trader.point_in_time import report_is_known

from .errors import NoMarketDataError
from .symbols import to_prefixed_code

try:
    import akshare as ak
except ImportError:  # pragma: no cover
    ak = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# 历史运行下不下发的「当期快照」字段：市值随行情每日变化、股本随资本动作变化，
# 取到的都是**运行当天**的值，无法证明分析日当时可知。
_SNAPSHOT_INFO_KEYS = ("总市值", "流通市值", "总股本", "流通股")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_akshare() -> str | None:
    """Return an error string if akshare is not installed, else None."""
    if ak is None:
        return "[ERROR] akshare is not installed. Run: pip install akshare"
    return None


def _safe_call(func, *args, **kwargs):
    """Call *func* and return ``(df, None)`` or ``(None, error_string)``."""
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
    """Format a number for display, handling NaN / None."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "N/A"
    if isinstance(val, (int,)):
        return f"{val:,}"
    try:
        return f"{float(val):,.{decimals}f}"
    except (ValueError, TypeError):
        return str(val)


def _df_to_markdown(df: pd.DataFrame, max_rows: int = 60) -> str:
    """Convert a DataFrame to a compact Markdown table, truncating if needed."""
    if df is None or df.empty:
        return "No data available."
    truncated = len(df) > max_rows
    table = df.head(max_rows).to_markdown(index=False)
    if truncated:
        table += f"\n\n... ({len(df) - max_rows} more rows omitted)"
    return table


# ---------------------------------------------------------------------------
# Daily OHLCV — 多源抓取与归一化
# ---------------------------------------------------------------------------
# 东方财富 ``push2his.eastmoney.com`` 在部分网络环境下被对端直接断连
# （``RemoteDisconnected``，与是否走代理无关）；同一台机器上新浪与腾讯两条路
# 可用。日线行情是所有技术面分析的底座，只有一个源等于没有源，所以这里做成
# 显式的三级 fallback，并把**实际出数的源**写进返回值，便于审计与排查。
#
# 三个源的列名、日期类型、成交单位都不一样，统一归一化成：
#   date(YYYY-MM-DD) / open / high / low / close / volume(手) / turnover(元)
#
# 单位换算的依据：2026-09-30 贵州茅台同日数据
#   新浪 stock_zh_a_daily: volume=3,833,098（股） amount=4,797,246,636（元）
#   腾讯 stock_zh_a_hist_tx: amount=38,331   → 实为成交量（手），恰为新浪的 1/100
# 因此新浪需 ÷100 折成「手」，腾讯的 amount 列直接当作「手」。
_OHLCV_SOURCES: tuple[str, ...] = ("eastmoney", "sina", "tencent")

_SOURCE_LABELS = {
    "eastmoney": "东方财富 stock_zh_a_hist",
    "sina": "新浪 stock_zh_a_daily",
    "tencent": "腾讯 stock_zh_a_hist_tx",
}

_OHLCV_COLUMNS = ["date", "open", "high", "low", "close", "volume", "turnover"]


def _to_ak_date(value: str) -> str | None:
    """把 ``2026-09-30`` / ``20260930`` 统一成 akshare 要的 ``YYYYMMDD``。"""
    try:
        return pd.Timestamp(str(value).strip()).strftime("%Y%m%d")
    except Exception:
        return None


def _finalise(df: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame | None:
    """重命名 → 取公共列 → 统一日期为 ``YYYY-MM-DD`` 字符串 → 按日期升序。"""
    if df is None or df.empty:
        return None
    df = df.rename(columns=mapping).copy()
    if "date" not in df.columns or "close" not in df.columns:
        return None
    for col in _OHLCV_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    df = df[_OHLCV_COLUMNS]
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df = df.dropna(subset=["date", "close"])
    for col in ("open", "high", "low", "close", "volume", "turnover"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.sort_values("date").reset_index(drop=True) if not df.empty else None


def _normalise_em(df: pd.DataFrame) -> pd.DataFrame | None:
    """东方财富 ``stock_zh_a_hist``：中文列名，成交量单位「手」，成交额单位「元」。"""
    return _finalise(
        df,
        {
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
            "成交额": "turnover",
        },
    )


def _normalise_sina(df: pd.DataFrame) -> pd.DataFrame | None:
    """新浪 ``stock_zh_a_daily``：英文列名，volume 单位「股」，amount 单位「元」。"""
    if df is None or df.empty:
        return None
    df = df.copy()
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce") / 100.0  # 股 → 手
    if "amount" in df.columns:
        df["turnover"] = df["amount"]
    return _finalise(df, {})


def _normalise_tx(df: pd.DataFrame) -> pd.DataFrame | None:
    """腾讯 ``stock_zh_a_hist_tx``。

    **这个接口的返回结构在 akshare 1.19 前后不一样，必须分别处理**：

    * ``1.18.x``：只有 6 列 ``date/open/close/high/low/amount``，其中 ``amount``
      其实是**成交量（手）**，完全没有成交额 —— 按列名当成交额用会拿到差 100 倍
      的数字，而且量纲全错。
    * ``>= 1.19``：新增了 ``volume``（股）与 ``amount``（元），列名才是字面意思。

    判据用列名而不是版本号：有没有 ``volume`` 列就足以区分两种结构。
    """
    if df is None or df.empty:
        return None
    df = df.copy()
    # 先记下**原始**列名：下面会补出 volume 列，之后再判断就分不清结构了。
    is_new_schema = "volume" in df.columns
    if is_new_schema:
        # 新结构：volume 单位股，折成「手」与其它源对齐
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce") / 100.0
        if "amount" in df.columns:
            df["turnover"] = pd.to_numeric(df["amount"], errors="coerce")
    else:
        # 旧结构：第 6 列名叫 amount，实为成交量（手）；没有成交额可给
        df["volume"] = pd.to_numeric(df["amount"], errors="coerce")
    return _finalise(df, {})


_NORMALISERS = {
    "eastmoney": _normalise_em,
    "sina": _normalise_sina,
    "tencent": _normalise_tx,
}


def _fetch_raw(source: str, symbol: str, start_str: str, end_str: str, adjust: str):
    """按 source 调用对应的 akshare 接口。"""
    if source == "eastmoney":
        return ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start_str, end_date=end_str, adjust=adjust)
    prefixed = to_prefixed_code(symbol)
    if source == "sina":
        return ak.stock_zh_a_daily(symbol=prefixed, start_date=start_str, end_date=end_str, adjust=adjust)
    if source == "tencent":
        return ak.stock_zh_a_hist_tx(symbol=prefixed, start_date=start_str, end_date=end_str, adjust=adjust)
    raise NoMarketDataError(f"unknown OHLCV source '{source}'")


def _fetch_ohlcv(
    symbol: str,
    start_date: str,
    end_date: str,
    adjust: str = "qfq",
    sources: Sequence[str] = _OHLCV_SOURCES,
) -> tuple[pd.DataFrame | None, str, str | None]:
    """按优先级抓日线，返回 ``(df, source_label, error)``。

    归一化列见 ``_OHLCV_COLUMNS``。任一源出数即返回；全部失败时 ``df`` 为
    ``None``，``error`` 里带上每个源各自的失败原因（而不是只留最后一个），
    因为「东财被断连」和「新浪返回空」是完全不同的故障。
    """
    err = _ensure_akshare()
    if err:
        return None, "", err

    start_str = _to_ak_date(start_date)
    end_str = _to_ak_date(end_date)
    if start_str is None or end_str is None:
        return None, "", f"invalid date range {start_date!r} ~ {end_date!r}"
    if start_str > end_str:
        return None, "", f"start_date {start_date} is later than end_date {end_date}"

    attempts: list[str] = []
    for source in sources:
        try:
            raw = _fetch_raw(source, symbol, start_str, end_str, adjust)
            df = _NORMALISERS[source](raw)
        except Exception as exc:
            attempts.append(f"{source}: {type(exc).__name__}: {str(exc)[:160]}")
            logger.debug("OHLCV source %s failed for %s: %s", source, symbol, exc)
            continue

        if df is None or df.empty:
            attempts.append(f"{source}: no rows returned")
            continue

        logger.debug("OHLCV for %s served by %s (%d rows)", symbol, source, len(df))
        return df, _SOURCE_LABELS[source], None

    return None, "", "all OHLCV sources failed — " + "; ".join(attempts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_stock_data(
    symbol: Annotated[str, "A-share stock symbol, e.g. '000001' or '600519'"],
    start_date: Annotated[str, "Start date in 'YYYY-MM-DD' or 'YYYYMMDD' format"],
    end_date: Annotated[str, "End date in 'YYYY-MM-DD' or 'YYYYMMDD' format"],
) -> str:
    """Get daily OHLCV price data for an A-share stock.

    Returns a formatted Markdown table with columns:
    date, open, high, low, close, volume, turnover.

    前复权。依次尝试东方财富 → 新浪 → 腾讯三个源，表头会写明**实际出数的源**：
    任一家被网络环境阻断时不会整条链路失效。
    """
    df, source, err = _fetch_ohlcv(symbol, start_date, end_date)
    if err:
        return f"get_stock_data({symbol}): {err}"

    assert df is not None  # 无 error 时必有数据
    display = df.copy()
    for c in ("open", "high", "low", "close"):
        display[c] = display[c].apply(lambda x: _fmt_number(x, 2))
    display["volume"] = display["volume"].apply(lambda x: _fmt_number(x, 0))
    display["turnover"] = display["turnover"].apply(lambda x: _fmt_number(x, 0))

    header = (
        f"## Daily OHLCV — {symbol} ({start_date} ~ {end_date}, qfq)\n\n"
        f"> source: {source} · volume 单位「手」· turnover 单位「元」\n\n"
    )
    return header + _df_to_markdown(display)


def get_indicators(
    symbol: Annotated[str, "A-share stock symbol"],
    indicator: Annotated[
        str,
        "Indicator name: close_50_sma, close_200_sma, close_10_ema, macd, rsi, boll",
    ],
    curr_date: Annotated[str, "Reference date 'YYYY-MM-DD' or 'YYYYMMDD'"],
    look_back_days: Annotated[int, "Number of calendar days to look back"] = 60,
) -> str:
    """Calculate a technical indicator and return the latest values as text.

    Supported indicators:
      - close_50_sma  : 50-day simple moving average
      - close_200_sma : 200-day simple moving average
      - close_10_ema  : 10-day exponential moving average
      - macd          : MACD line, signal line, histogram
      - rsi           : 14-day RSI
      - boll          : Bollinger Bands (20-day, 2 std)
    """
    # 先校验指标名再取数：拼错的名字不该浪费一次网络往返。
    if indicator not in ("close_50_sma", "close_200_sma", "close_10_ema", "macd", "rsi", "boll"):
        return (
            f"get_indicators({symbol}, {indicator}): Unknown indicator. "
            f"Supported: close_50_sma, close_200_sma, close_10_ema, macd, rsi, boll"
        )

    # Determine required history length
    sma_periods = {"close_50_sma": 50, "close_200_sma": 200}
    if indicator in sma_periods:
        needed_bars = sma_periods[indicator] + 20
    elif indicator == "macd":
        needed_bars = 60
    elif indicator == "rsi":
        needed_bars = 30
    elif indicator == "boll":
        needed_bars = 40
    else:
        needed_bars = 30

    # Compute date range
    try:
        end_dt = pd.Timestamp(curr_date)
    except Exception:
        return f"get_indicators: Invalid curr_date '{curr_date}'."
    start_dt = end_dt - timedelta(days=max(look_back_days, needed_bars * 2))
    start_str = start_dt.strftime("%Y%m%d")
    end_str = end_dt.strftime("%Y%m%d")

    # 与 get_stock_data 走同一条多源 fallback：东财被断连时自动转新浪/腾讯。
    df, _source, err = _fetch_ohlcv(symbol, start_str, end_str)
    if err:
        return f"get_indicators({symbol}, {indicator}): {err}"

    if df is None or df.empty or len(df) < 5:
        return f"get_indicators({symbol}, {indicator}): Insufficient data."

    if "close" not in df.columns:
        return f"get_indicators({symbol}, {indicator}): 'close' column not found."
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"]).reset_index(drop=True)

    # Filter to dates <= curr_date —— 只用分析基准日及之前的 K 线，不用未来数据。
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df[df["date"] <= end_dt].reset_index(drop=True)

    close = df["close"]
    result_lines: list[str] = [f"## Indicator: {indicator} — {symbol} (as of {curr_date})\n"]

    try:
        if indicator == "close_50_sma":
            sma = close.rolling(50).mean()
            latest = sma.iloc[-1] if len(sma) >= 50 else None
            prev = sma.iloc[-2] if len(sma) >= 51 else None
            result_lines.append(f"- 50-day SMA: {_fmt_number(latest, 2)}")
            result_lines.append(f"- Previous:   {_fmt_number(prev, 2)}")
            if latest and prev:
                direction = "up" if latest > prev else "down"
                result_lines.append(f"- Trend: {direction}")

        elif indicator == "close_200_sma":
            sma = close.rolling(200).mean()
            latest = sma.iloc[-1] if len(sma) >= 200 else None
            prev = sma.iloc[-2] if len(sma) >= 201 else None
            result_lines.append(f"- 200-day SMA: {_fmt_number(latest, 2)}")
            result_lines.append(f"- Previous:    {_fmt_number(prev, 2)}")
            if latest and prev:
                direction = "up" if latest > prev else "down"
                result_lines.append(f"- Trend: {direction}")

        elif indicator == "close_10_ema":
            ema = close.ewm(span=10, adjust=False).mean()
            latest = ema.iloc[-1]
            prev = ema.iloc[-2] if len(ema) >= 2 else None
            result_lines.append(f"- 10-day EMA: {_fmt_number(latest, 2)}")
            result_lines.append(f"- Previous:   {_fmt_number(prev, 2)}")

        elif indicator == "macd":
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            macd_line = ema12 - ema26
            signal_line = macd_line.ewm(span=9, adjust=False).mean()
            histogram = macd_line - signal_line
            result_lines.append(f"- MACD Line:   {_fmt_number(macd_line.iloc[-1], 4)}")
            result_lines.append(f"- Signal Line: {_fmt_number(signal_line.iloc[-1], 4)}")
            result_lines.append(f"- Histogram:   {_fmt_number(histogram.iloc[-1], 4)}")
            if histogram.iloc[-1] > 0 and histogram.iloc[-2] <= 0:
                result_lines.append("- Signal: Bullish crossover")
            elif histogram.iloc[-1] < 0 and histogram.iloc[-2] >= 0:
                result_lines.append("- Signal: Bearish crossover")

        elif indicator == "rsi":
            delta = close.diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)
            avg_gain = gain.rolling(14).mean()
            avg_loss = loss.rolling(14).mean()
            rs = avg_gain / avg_loss.replace(0, float("nan"))
            rsi = 100 - (100 / (1 + rs))
            latest = rsi.iloc[-1]
            result_lines.append(f"- RSI (14): {_fmt_number(latest, 2)}")
            if pd.notna(latest):
                if latest > 70:
                    result_lines.append("- Zone: **Overbought** (>70)")
                elif latest < 30:
                    result_lines.append("- Zone: **Oversold** (<30)")
                else:
                    result_lines.append("- Zone: Neutral")

        elif indicator == "boll":
            sma20 = close.rolling(20).mean()
            std20 = close.rolling(20).std()
            upper = sma20 + 2 * std20
            lower = sma20 - 2 * std20
            result_lines.append(f"- Upper Band:  {_fmt_number(upper.iloc[-1], 2)}")
            result_lines.append(f"- Middle Band: {_fmt_number(sma20.iloc[-1], 2)}")
            result_lines.append(f"- Lower Band:  {_fmt_number(lower.iloc[-1], 2)}")
            result_lines.append(f"- Current Close: {_fmt_number(close.iloc[-1], 2)}")
            if pd.notna(upper.iloc[-1]) and pd.notna(lower.iloc[-1]):
                if close.iloc[-1] > upper.iloc[-1]:
                    result_lines.append("- Position: **Above upper band** (potential overbought)")
                elif close.iloc[-1] < lower.iloc[-1]:
                    result_lines.append("- Position: **Below lower band** (potential oversold)")
                else:
                    pct = (close.iloc[-1] - lower.iloc[-1]) / (upper.iloc[-1] - lower.iloc[-1]) * 100
                    result_lines.append(f"- Position: {pct:.1f}% within bands")

        else:
            return (
                f"get_indicators({symbol}, {indicator}): Unknown indicator. "
                f"Supported: close_50_sma, close_200_sma, close_10_ema, macd, rsi, boll"
            )

    except Exception as exc:
        return f"get_indicators({symbol}, {indicator}): Calculation error — {exc}"

    return "\n".join(result_lines)


# 均线预热所需的额外自然日：MA60 需要 60 个交易日，留足 120 天缓冲，
# 覆盖春节等连续休市，避免长假期把预热窗口吃掉导致整条均线是 NaN。
_MA_WARMUP_DAYS = 120
_MA_PERIODS = (5, 10, 20, 60)


def get_technical_indicators(
    symbol: Annotated[str, "A-share stock symbol"],
    start_date: Annotated[str, "Start date in 'YYYY-MM-DD' or 'YYYYMMDD' format"],
    end_date: Annotated[str, "End date in 'YYYY-MM-DD' or 'YYYYMMDD' format"],
) -> str:
    """均线系统（MA5/MA10/MA20/MA60）+ 成交量趋势，按区间返回日序表与信号解读。

    与 ``get_indicators`` 的分工：那个一次算**一个**指标（MACD/RSI/BOLL 等），
    这个一次给出**整条均线带**加量能对比，用于快速判断趋势结构与量价配合。

    区间外的历史数据只用作均线预热，不会出现在输出里；表头写明实际出数的源。
    """
    try:
        start_ts = pd.Timestamp(str(start_date).strip())
        end_ts = pd.Timestamp(str(end_date).strip())
    except Exception:
        return f"get_technical_indicators({symbol}): invalid date range {start_date!r} ~ {end_date!r}"
    if start_ts > end_ts:
        return f"get_technical_indicators({symbol}): start_date {start_date} is later than end_date {end_date}"

    warm_start = (start_ts - timedelta(days=_MA_WARMUP_DAYS)).strftime("%Y%m%d")
    df, source, err = _fetch_ohlcv(symbol, warm_start, end_ts.strftime("%Y%m%d"))
    if err:
        return f"get_technical_indicators({symbol}): {err}"
    if df is None or len(df) < 6:
        bars = 0 if df is None else len(df)
        return f"get_technical_indicators({symbol}): insufficient history ({bars} bars)."

    for period in _MA_PERIODS:
        df[f"ma{period}"] = df["close"].rolling(period).mean()
    df["vol_ma5"] = df["volume"].rolling(5).mean()

    df["_dt"] = pd.to_datetime(df["date"])
    view = df[df["_dt"] >= start_ts].copy()
    if view.empty:
        return f"get_technical_indicators({symbol}): no trading days in {start_date} ~ {end_date}."

    latest = view.iloc[-1]
    lines: list[str] = [
        f"## 技术指标 — {symbol} ({start_date} ~ {end_date})\n",
        f"> source: {source} · volume 单位「手」· 均线基于前复权收盘价\n",
    ]

    # 信号解读：均线排列 + 价格与 MA20 的关系 + 量能对比
    ma5, ma10, ma20, ma60 = (latest[f"ma{p}"] for p in _MA_PERIODS)
    close = latest["close"]
    signals: list[str] = []
    if pd.notna(ma5) and pd.notna(ma10) and pd.notna(ma20):
        if ma5 > ma10 > ma20:
            signals.append("均线多头排列（MA5 > MA10 > MA20）")
        elif ma5 < ma10 < ma20:
            signals.append("均线空头排列（MA5 < MA10 < MA20）")
        else:
            signals.append("均线交织，趋势不明")
    if pd.notna(ma20):
        side = "上方" if close >= ma20 else "下方"
        signals.append(f"收盘价 {_fmt_number(close, 2)} 位于 MA20（{_fmt_number(ma20, 2)}）{side}")
    if pd.notna(ma60):
        signals.append(f"MA60（{_fmt_number(ma60, 2)}）为中期多空分界")
    if pd.notna(latest["vol_ma5"]) and latest["vol_ma5"]:
        ratio = latest["volume"] / latest["vol_ma5"]
        tag = "放量" if ratio >= 1.5 else ("缩量" if ratio <= 0.7 else "量能持平")
        signals.append(f"最新成交量约为 5 日均量的 {ratio:.2f} 倍（{tag}）")
    lines.append("### 信号解读\n")
    lines.extend(f"- {s}" for s in signals)

    lines.append(f"\n### 最近 {min(len(view), 40)} 个交易日\n")
    display = view.tail(40)[["date", "close", *[f"ma{p}" for p in _MA_PERIODS], "volume", "vol_ma5"]].copy()
    display.columns = ["date", "close", "ma5", "ma10", "ma20", "ma60", "volume", "vol_ma5"]
    for col in ("close", "ma5", "ma10", "ma20", "ma60"):
        display[col] = display[col].apply(lambda x: _fmt_number(x, 2))
    for col in ("volume", "vol_ma5"):
        display[col] = display[col].apply(lambda x: _fmt_number(x, 0))
    lines.append(_df_to_markdown(display, max_rows=40))

    return "\n".join(lines)


def get_fundamentals(
    symbol: Annotated[str, "A-share stock symbol"],
    curr_date: Annotated[str | None, "Reference date 'YYYY-MM-DD'; None = live run"] = None,
) -> str:
    """Get company fundamental information: name, sector, market cap, PE, PB, ROE, etc.

    Combines ``ak.stock_individual_info_em`` (basic info) and
    ``ak.stock_financial_abstract_ths`` (financial summary from THS).

    历史运行（``curr_date`` 非空）下按公告日／法定披露截止日过滤财报行，并隐去
    市值、股本这类「运行当天」的快照字段 —— 报告期结束不等于可知，一季报 3-31
    结束但最晚 4-30 才披露。
    """
    historical = curr_date is not None
    lines: list[str] = [f"## Fundamentals — {symbol}\n"]

    # --- Basic info from EastMoney ---
    info_df, err = _safe_call(ak.stock_individual_info_em, symbol=symbol)
    if err:
        lines.append(f"[WARN] Basic info unavailable: {err}")
    elif info_df is not None and not info_df.empty:
        body: list[str] = []
        withheld: list[str] = []
        for _, row in info_df.iterrows():
            try:
                key = str(row.iloc[0])
                val = str(row.iloc[1])
            except (IndexError, KeyError):
                continue
            if historical and any(k in key for k in _SNAPSHOT_INFO_KEYS):
                withheld.append(key)
                continue
            body.append(f"- **{key}**: {val}")
        if body:
            lines.append("### Company Info (EastMoney)\n")
            lines.extend(body)
        if withheld:
            lines.append(
                f"\n> Point-in-time: as-of {curr_date} snapshot fields withheld "
                f"({', '.join(withheld)}) — they reflect the run date, not the "
                "analysis date. Use get_stock_data / get_indicators for as-of prices."
            )

    # --- Financial abstract from THS ---
    fin_df, err2 = _safe_call(ak.stock_financial_abstract_ths, symbol=symbol)
    if err2:
        lines.append(f"\n[WARN] Financial abstract unavailable: {err2}")
    elif fin_df is not None and not fin_df.empty:
        visible, dropped = _gate_reports(fin_df, curr_date)
        if visible.empty:
            lines.append(
                f"\n### Financial Summary (THS)\n\n"
                f"No reporting period was public as of {curr_date}; "
                "the latest snapshot is withheld."
            )
        else:
            lines.append("\n### Financial Summary (THS)\n")
            if dropped:
                lines.append(
                    f"*(showing the latest periods public as of {curr_date}; {dropped} later period(s) withheld)*\n"
                )
            # Show the latest 2 reporting periods
            show_df = visible.head(2).copy()
            lines.append(_df_to_markdown(show_df, max_rows=4))

    if len(lines) <= 1:
        return f"get_fundamentals({symbol}): No fundamental data found."

    return "\n".join(lines)


def get_balance_sheet(
    symbol: Annotated[str, "A-share stock symbol"],
    freq: Annotated[str, "'quarterly' or 'annual'"] = "quarterly",
    curr_date: Annotated[str | None, "Reference date 'YYYY-MM-DD'; None = live run"] = None,
) -> str:
    """Get the latest balance sheet data.

    Uses ``ak.stock_balance_sheet_by_report_em``.  In a historical run only
    report periods already public as of *curr_date* are considered.
    """
    df, err = _safe_call(ak.stock_balance_sheet_by_report_em, symbol=symbol)
    if err:
        return f"get_balance_sheet({symbol}): {err}"

    if df is None or df.empty:
        return f"get_balance_sheet({symbol}): No balance sheet data returned."

    df, dropped = _gate_reports(df, curr_date)
    if df.empty:
        return f"get_balance_sheet({symbol}): No report was public as of {curr_date}; the latest snapshot is withheld."

    # If quarterly, keep the latest 1 report; if annual, filter by year-end
    if freq == "annual" and len(df) > 1:
        # Annual reports usually end with "12-31" in the date column
        date_col = None
        for c in df.columns:
            if "日期" in str(c) or "date" in str(c).lower() or "报告" in str(c):
                date_col = c
                break
        if date_col:
            annual = df[df[date_col].astype(str).str.contains("12-31", na=False)]
            if not annual.empty:
                df = annual

    # Take the latest report
    latest = df.head(1)
    header = f"## Balance Sheet — {symbol} (Latest {freq})\n\n"
    if dropped:
        header += f"*(as of {curr_date}: {dropped} later report(s) withheld)*\n\n"

    # Transpose for readability: one column per report
    records = []
    for col in latest.columns:
        val = latest.iloc[0][col]
        records.append({"Item": str(col), "Value": _fmt_number(val) if _is_numeric(val) else str(val)})
    result_df = pd.DataFrame(records)

    return header + _df_to_markdown(result_df, max_rows=80)


def get_cashflow(
    symbol: Annotated[str, "A-share stock symbol"],
    freq: Annotated[str, "'quarterly' or 'annual'"] = "quarterly",
    curr_date: Annotated[str | None, "Reference date 'YYYY-MM-DD'; None = live run"] = None,
) -> str:
    """Get the latest cash flow statement.

    Uses ``ak.stock_cash_flow_sheet_by_report_em``.  In a historical run only
    report periods already public as of *curr_date* are considered.
    """
    df, err = _safe_call(ak.stock_cash_flow_sheet_by_report_em, symbol=symbol)
    if err:
        return f"get_cashflow({symbol}): {err}"

    if df is None or df.empty:
        return f"get_cashflow({symbol}): No cash flow data returned."

    df, dropped = _gate_reports(df, curr_date)
    if df.empty:
        return f"get_cashflow({symbol}): No report was public as of {curr_date}; the latest snapshot is withheld."

    if freq == "annual" and len(df) > 1:
        date_col = _find_date_column(df)
        if date_col:
            annual = df[df[date_col].astype(str).str.contains("12-31", na=False)]
            if not annual.empty:
                df = annual

    latest = df.head(1)
    header = f"## Cash Flow Statement — {symbol} (Latest {freq})\n\n"
    if dropped:
        header += f"*(as of {curr_date}: {dropped} later report(s) withheld)*\n\n"

    records = []
    for col in latest.columns:
        val = latest.iloc[0][col]
        records.append({"Item": str(col), "Value": _fmt_number(val) if _is_numeric(val) else str(val)})
    result_df = pd.DataFrame(records)

    return header + _df_to_markdown(result_df, max_rows=80)


def get_income_statement(
    symbol: Annotated[str, "A-share stock symbol"],
    freq: Annotated[str, "'quarterly' or 'annual'"] = "quarterly",
    curr_date: Annotated[str | None, "Reference date 'YYYY-MM-DD'; None = live run"] = None,
) -> str:
    """Get the latest income (profit) statement.

    Uses ``ak.stock_profit_sheet_by_report_em``.  In a historical run only
    report periods already public as of *curr_date* are considered.
    """
    df, err = _safe_call(ak.stock_profit_sheet_by_report_em, symbol=symbol)
    if err:
        return f"get_income_statement({symbol}): {err}"

    if df is None or df.empty:
        return f"get_income_statement({symbol}): No income statement data returned."

    df, dropped = _gate_reports(df, curr_date)
    if df.empty:
        return (
            f"get_income_statement({symbol}): No report was public as of {curr_date}; the latest snapshot is withheld."
        )

    if freq == "annual" and len(df) > 1:
        date_col = _find_date_column(df)
        if date_col:
            annual = df[df[date_col].astype(str).str.contains("12-31", na=False)]
            if not annual.empty:
                df = annual

    latest = df.head(1)
    header = f"## Income Statement — {symbol} (Latest {freq})\n\n"
    if dropped:
        header += f"*(as of {curr_date}: {dropped} later report(s) withheld)*\n\n"

    records = []
    for col in latest.columns:
        val = latest.iloc[0][col]
        records.append({"Item": str(col), "Value": _fmt_number(val) if _is_numeric(val) else str(val)})
    result_df = pd.DataFrame(records)

    return header + _df_to_markdown(result_df, max_rows=80)


# ---------------------------------------------------------------------------
# Internal utilities
# ---------------------------------------------------------------------------


def _is_numeric(val) -> bool:
    """Check whether a value can be treated as numeric for formatting."""
    if val is None:
        return False
    if isinstance(val, (int, float)):
        return True
    try:
        float(val)
        return True
    except (ValueError, TypeError):
        return False


def _find_date_column(df: pd.DataFrame) -> str | None:
    """Heuristically find a date-like column in a DataFrame."""
    for c in df.columns:
        cs = str(c)
        if any(kw in cs for kw in ("日期", "date", "Date", "报告", "REPORT_DATE")):
            return c
    return None


# 报告期列 / 公告日期列的关键词，按优先级排列。财报帧的列名各家不一致：
# 同花顺摘要给「报告期」，东财报表给 ``REPORT_DATE``，Tushare 给 ``end_date``。
_REPORT_PERIOD_HINTS = ("报告期", "report_date", "报告日", "end_date")
_ANNOUNCEMENT_HINTS = ("公告日期", "notice_date", "实际公告日", "f_ann_date", "ann_date", "update_date")


def _find_report_period_column(df: pd.DataFrame) -> str | None:
    """找到「报告期」列（期末日）。"""
    return _find_column_by_hints(df, _REPORT_PERIOD_HINTS)


def _find_announcement_column(df: pd.DataFrame) -> str | None:
    """找到「公告日期」列（该报告实际公开的日期），没有则返回 ``None``。"""
    return _find_column_by_hints(df, _ANNOUNCEMENT_HINTS)


def _find_column_by_hints(df: pd.DataFrame, hints: tuple[str, ...]) -> str | None:
    for hint in hints:
        for c in df.columns:
            if hint in str(c).lower():
                return c
    return None


def _gate_reports(df: pd.DataFrame, curr_date: str | None) -> tuple[pd.DataFrame, int]:
    """Drop report rows that were not yet public on *curr_date*.

    「报告期结束」不等于「可知」：一季报 3-31 结束、最晚 4-30 才披露。有公告日期
    列就按公告日期判，否则退回法定披露截止日（见 :mod:`astock_trader.point_in_time`）。

    Returns
    -------
    tuple[pandas.DataFrame, int]
        ``(放行后的帧, 被剔除的行数)``。``curr_date`` 为 ``None``（实时运行）时
        原样返回。**认不出报告期列时整帧剔除** —— 无法证明任何一行在分析日之前
        可知，宁可不给。
    """
    if curr_date is None or df is None or df.empty:
        return df, 0

    period_col = _find_report_period_column(df)
    if period_col is None:
        return df.iloc[0:0], len(df)

    ann_col = _find_announcement_column(df)
    mask = pd.Series(
        [
            report_is_known(
                row[period_col],
                curr_date,
                ann_date=row[ann_col] if ann_col is not None else None,
            )
            for _, row in df.iterrows()
        ],
        index=df.index,
        dtype=bool,
    )
    return df[mask], int((~mask).sum())


def get_industry_peers(
    symbol: str,
) -> str:
    """获取同行业及同概念可比公司列表。

    先查询个股所属行业板块和相关概念板块，再获取各板块的成分股列表，
    用于多产业公司的可比公司交叉对比分析。
    """
    import akshare as ak

    sections = []

    # 1. 获取个股基本信息，确定所属行业
    try:
        info_df = ak.stock_individual_info_em(symbol=symbol)
        industry = None
        for _, row in info_df.iterrows():
            if "行业" in str(row.iloc[0]):
                industry = str(row.iloc[1])
                break
        if not industry:
            return f"[ERROR] 无法确定 {symbol} 所属行业"
    except Exception as exc:
        return f"[ERROR] 获取 {symbol} 行业信息失败: {exc}"

    # 2. 获取主行业板块的成分股
    cols_to_keep = ["代码", "名称", "最新价", "涨跌幅", "总市值", "流通市值", "市盈率-动态", "市净率"]
    try:
        cons_df = ak.stock_board_industry_cons_em(symbol=industry)
        if cons_df is not None and not cons_df.empty:
            available_cols = [c for c in cols_to_keep if c in cons_df.columns]
            result_df = cons_df[available_cols].head(10)
            sections.append(f"## 行业板块：{industry}（共{len(cons_df)}家，前10家）\n\n" + _df_to_markdown(result_df))
    except Exception:
        sections.append(f"## 行业板块：{industry}\n\n数据获取失败")

    # 3. 查找公司所属的概念板块（取活跃度最高的前20个概念板块逐一匹配）
    concept_hits = []
    try:
        all_concepts = ak.stock_board_concept_name_em()
        if all_concepts is not None and not all_concepts.empty:
            # 按成交额排序，取前20个活跃概念
            sort_col = None
            for c in all_concepts.columns:
                if "成交额" in str(c) or "成交" in str(c):
                    sort_col = c
                    break
            if sort_col:
                all_concepts = all_concepts.sort_values(sort_col, ascending=False)
            top_concepts = all_concepts.head(20)

            name_col = None
            for c in top_concepts.columns:
                if "板块名称" in str(c) or "名称" in str(c):
                    name_col = c
                    break
            if not name_col:
                name_col = top_concepts.columns[1]

            for _, row in top_concepts.iterrows():
                concept_name = str(row[name_col])
                try:
                    cons = ak.stock_board_concept_cons_em(symbol=concept_name)
                    if cons is not None and not cons.empty:
                        # 检查目标股票是否在此概念板块中
                        code_col = None
                        for c in cons.columns:
                            if "代码" in str(c):
                                code_col = c
                                break
                        if code_col:
                            match = cons[cons[code_col].astype(str).str.contains(symbol)]
                            if not match.empty:
                                available_cols = [c for c in cols_to_keep if c in cons.columns]
                                top_5 = cons[available_cols].head(8)
                                concept_hits.append(
                                    f"## 概念板块：{concept_name}（前8家）\n\n" + _df_to_markdown(top_5)
                                )
                                if len(concept_hits) >= 3:
                                    break  # 最多取3个概念板块
                except Exception:
                    continue
    except Exception:
        pass

    if concept_hits:
        sections.extend(concept_hits)

    # 4. 组合输出
    header = f"# {symbol} 可比公司（行业+概念板块交叉对比）\n\n"
    if concept_hits:
        header += f"> 该公司横跨 **{industry}** 行业 + {len(concept_hits)} 个概念板块\n\n"
    summary = ""
    if not concept_hits:
        summary = f"\n\n> 未在活跃概念板块中找到 {symbol}，仅展示行业板块 '{industry}' 的成分股。"

    return header + "\n\n---\n\n".join(sections) + summary


def get_industry_chain(
    symbol: str,
) -> str:
    """通过 akshare 获取公司行业分类信息（产业链数据降级方案）。

    akshare 不提供直接的产业链上下游数据，此函数返回行业分类作为替代。
    如需完整产业链信息，请使用妙想 API。
    """
    import akshare as ak

    try:
        info_df = ak.stock_individual_info_em(symbol=symbol)
        lines = [f"# {symbol} 行业分类信息（akshare）\n"]
        for _, row in info_df.iterrows():
            key = str(row.iloc[0])
            val = str(row.iloc[1])
            lines.append(f"- **{key}**: {val}")
        lines.append(
            "\n> 注：akshare 不提供产业链上下游关系数据。如需供应商/客户/竞争格局等产业链详情，请使用妙想 API。"
        )
        return "\n".join(lines)
    except Exception as exc:
        return f"[ERROR] 获取 {symbol} 行业信息失败: {exc}"
