"""Core A-share stock data functions powered by akshare.

Every public function returns a **formatted string** (Markdown-flavoured)
so it can be consumed directly by LLM agents as tool output.  All akshare
calls are wrapped in try/except — on failure a descriptive error string is
returned instead of raising.
"""

from __future__ import annotations

import traceback
from datetime import datetime, timedelta
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
# Public API
# ---------------------------------------------------------------------------

def get_stock_data(
    symbol: Annotated[str, "A-share stock symbol, e.g. '000001' or '600519'"],
    start_date: Annotated[str, "Start date in 'YYYYMMDD' format"],
    end_date: Annotated[str, "End date in 'YYYYMMDD' format"],
) -> str:
    """Get daily OHLCV price data for an A-share stock.

    Returns a formatted Markdown table with columns:
    date, open, high, low, close, volume, turnover.
    """
    df, err = _safe_call(
        ak.stock_zh_a_hist,
        symbol=symbol,
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust="qfq",
    )
    if err:
        return f"get_stock_data({symbol}): {err}"

    if df is None or df.empty:
        return f"get_stock_data({symbol}): No data returned for {start_date}~{end_date}."

    # Standardise column names (akshare returns Chinese headers)
    col_map = {
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "turnover",
        "振幅": "amplitude",
        "涨跌幅": "pct_change",
        "涨跌额": "change",
        "换手率": "turnover_rate",
    }
    df = df.rename(columns=col_map)

    keep_cols = [c for c in ["date", "open", "high", "low", "close", "volume", "turnover"] if c in df.columns]
    df = df[keep_cols].copy()

    # Format numeric columns
    for c in ["open", "high", "low", "close"]:
        if c in df.columns:
            df[c] = df[c].apply(lambda x: _fmt_number(x, 2))
    if "volume" in df.columns:
        df["volume"] = df["volume"].apply(lambda x: _fmt_number(x, 0))
    if "turnover" in df.columns:
        df["turnover"] = df["turnover"].apply(lambda x: _fmt_number(x, 0))

    header = f"## Daily OHLCV — {symbol} ({start_date} ~ {end_date})\n\n"
    return header + _df_to_markdown(df)


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

    df, err = _safe_call(
        ak.stock_zh_a_hist,
        symbol=symbol,
        period="daily",
        start_date=start_str,
        end_date=end_str,
        adjust="qfq",
    )
    if err:
        return f"get_indicators({symbol}, {indicator}): {err}"

    if df is None or df.empty or len(df) < 5:
        return f"get_indicators({symbol}, {indicator}): Insufficient data."

    col_map = {"日期": "date", "收盘": "close"}
    df = df.rename(columns=col_map)
    if "close" not in df.columns:
        return f"get_indicators({symbol}, {indicator}): 'close' column not found."
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"]).reset_index(drop=True)

    # Filter to dates <= curr_date
    if "date" in df.columns:
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


def get_fundamentals(
    symbol: Annotated[str, "A-share stock symbol"],
    curr_date: Annotated[str | None, "Reference date (optional, unused for latest snapshot)"] = None,
) -> str:
    """Get company fundamental information: name, sector, market cap, PE, PB, ROE, etc.

    Combines ``ak.stock_individual_info_em`` (basic info) and
    ``ak.stock_financial_abstract_ths`` (financial summary from THS).
    """
    lines: list[str] = [f"## Fundamentals — {symbol}\n"]

    # --- Basic info from EastMoney ---
    info_df, err = _safe_call(ak.stock_individual_info_em, symbol=symbol)
    if err:
        lines.append(f"[WARN] Basic info unavailable: {err}")
    elif info_df is not None and not info_df.empty:
        lines.append("### Company Info (EastMoney)\n")
        for _, row in info_df.iterrows():
            try:
                key = str(row.iloc[0])
                val = str(row.iloc[1])
                lines.append(f"- **{key}**: {val}")
            except (IndexError, KeyError):
                continue

    # --- Financial abstract from THS ---
    fin_df, err2 = _safe_call(ak.stock_financial_abstract_ths, symbol=symbol)
    if err2:
        lines.append(f"\n[WARN] Financial abstract unavailable: {err2}")
    elif fin_df is not None and not fin_df.empty:
        lines.append("\n### Financial Summary (THS)\n")
        # Show the latest 2 reporting periods
        show_df = fin_df.head(2).copy()
        lines.append(_df_to_markdown(show_df, max_rows=4))

    if len(lines) <= 1:
        return f"get_fundamentals({symbol}): No fundamental data found."

    return "\n".join(lines)


def get_balance_sheet(
    symbol: Annotated[str, "A-share stock symbol"],
    freq: Annotated[str, "'quarterly' or 'annual'"] = "quarterly",
    curr_date: Annotated[str | None, "Reference date (optional)"] = None,
) -> str:
    """Get the latest balance sheet data.

    Uses ``ak.stock_balance_sheet_by_report_em``.
    """
    df, err = _safe_call(ak.stock_balance_sheet_by_report_em, symbol=symbol)
    if err:
        return f"get_balance_sheet({symbol}): {err}"

    if df is None or df.empty:
        return f"get_balance_sheet({symbol}): No balance sheet data returned."

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
    curr_date: Annotated[str | None, "Reference date (optional)"] = None,
) -> str:
    """Get the latest cash flow statement.

    Uses ``ak.stock_cash_flow_sheet_by_report_em``.
    """
    df, err = _safe_call(ak.stock_cash_flow_sheet_by_report_em, symbol=symbol)
    if err:
        return f"get_cashflow({symbol}): {err}"

    if df is None or df.empty:
        return f"get_cashflow({symbol}): No cash flow data returned."

    if freq == "annual" and len(df) > 1:
        date_col = _find_date_column(df)
        if date_col:
            annual = df[df[date_col].astype(str).str.contains("12-31", na=False)]
            if not annual.empty:
                df = annual

    latest = df.head(1)
    header = f"## Cash Flow Statement — {symbol} (Latest {freq})\n\n"

    records = []
    for col in latest.columns:
        val = latest.iloc[0][col]
        records.append({"Item": str(col), "Value": _fmt_number(val) if _is_numeric(val) else str(val)})
    result_df = pd.DataFrame(records)

    return header + _df_to_markdown(result_df, max_rows=80)


def get_income_statement(
    symbol: Annotated[str, "A-share stock symbol"],
    freq: Annotated[str, "'quarterly' or 'annual'"] = "quarterly",
    curr_date: Annotated[str | None, "Reference date (optional)"] = None,
) -> str:
    """Get the latest income (profit) statement.

    Uses ``ak.stock_profit_sheet_by_report_em``.
    """
    df, err = _safe_call(ak.stock_profit_sheet_by_report_em, symbol=symbol)
    if err:
        return f"get_income_statement({symbol}): {err}"

    if df is None or df.empty:
        return f"get_income_statement({symbol}): No income statement data returned."

    if freq == "annual" and len(df) > 1:
        date_col = _find_date_column(df)
        if date_col:
            annual = df[df[date_col].astype(str).str.contains("12-31", na=False)]
            if not annual.empty:
                df = annual

    latest = df.head(1)
    header = f"## Income Statement — {symbol} (Latest {freq})\n\n"

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
