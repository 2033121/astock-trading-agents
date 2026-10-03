"""实时行情源（腾讯为主、新浪兜底）—— 免 Key、低延迟，供监控层轮询使用。

与 ``akshare_data`` 的区别是**用途**：这里的接口是给"盯着看"用的，取的是
**此刻**的盘口快照，而不是给历史回测用的日线。因此本模块有一条硬约束：

    只要调用方给了 ``curr_date``，且它不是**运行当天**，一律抛
    :class:`VendorError` 拒绝出数。

实时行情天生是"现在"，它无法证明分析日当时可知的内容；把它喂进 ``--date``
历史回测就是前视偏差。这条门控与 ``docs/前视偏差防护.md`` 的检查清单一致。

数据源说明（两家都返回 GBK 编码的纯文本，无需注册）：

* 腾讯 ``qt.gtimg.cn`` —— 字段最全，含涨跌幅、换手率、涨停/跌停价、市值，作主源
* 新浪 ``hq.sinajs.cn`` —— 需带 ``Referer``，字段较少，作兜底

两个模块级函数都返回**格式化字符串**（Markdown 表格），与其它数据源一致，
可直接作为 Agent 工具输出或监控层的解析输入。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

import requests

from .errors import NoMarketDataError, VendorError, VendorNotConfiguredError
from .symbols import to_prefixed_code as _to_prefixed_code

logger = logging.getLogger(__name__)

__all__ = ["get_realtime_quote", "get_realtime_quotes_batch", "to_prefixed_code", "parse_realtime_quote"]

_TIMEOUT = 8
# 腾讯行情字段分隔符与整条记录的包裹格式：v_sh600519="1~贵州茅台~600519~...";
_TX_LINE = re.compile(r'v_([a-z]{2}\d{6})="([^"]*)"')
_SINA_LINE = re.compile(r'hq_str_([a-z]{2}\d{6})="([^"]*)"')

# 腾讯行情字段下标（0 基），仅取常用的几个；顺序见 qt.gtimg.cn 公开格式
_TX_NAME = 1
_TX_PRICE = 3
_TX_PREV_CLOSE = 4
_TX_OPEN = 5
_TX_TIME = 30
_TX_CHANGE = 31
_TX_CHANGE_PCT = 32
_TX_HIGH = 33
_TX_LOW = 34
_TX_VOLUME = 36  # 手
_TX_AMOUNT = 37  # 万元
_TX_TURNOVER = 38
_TX_PE = 39
_TX_AMPLITUDE = 43
_TX_MARKET_CAP = 45  # 总市值（亿元）
_TX_PB = 46
_TX_LIMIT_UP = 47
_TX_LIMIT_DOWN = 48
_TX_VOLUME_RATIO = 49  # 量比
_TX_AVG_PRICE = 51

# 新浪行情字段下标
_SINA_NAME = 0
_SINA_OPEN = 1
_SINA_PREV_CLOSE = 2
_SINA_PRICE = 3
_SINA_HIGH = 4
_SINA_LOW = 5
_SINA_VOLUME = 8  # 股
_SINA_AMOUNT = 9  # 元
_SINA_DATE = 30
_SINA_TIME = 31


def to_prefixed_code(symbol: str) -> str:
    """把 6 位 A 股代码转成带交易所前缀的行情代码。

    ``600519 -> sh600519``、``000001 -> sz000001``、``430047 -> bj430047``。
    已带前缀的原样返回（统一小写）。实现集中在 :mod:`astock_trader.dataflows.symbols`。
    """
    return _to_prefixed_code(symbol)


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _guard_historical(curr_date: str | None) -> None:
    """实时源不得服务历史日期 —— 这是前视偏差的第一道门。"""
    if curr_date is None:
        return
    if str(curr_date).strip()[:10] != _today_str():
        raise VendorError(
            f"实时行情源不能服务历史日期 {curr_date}（仅支持运行当天 {_today_str()}）；"
            "历史分析请使用 akshare 日线数据。"
        )


def _parse_symbols(symbols: str | list[str]) -> list[str]:
    if isinstance(symbols, str):
        parts = [p for p in re.split(r"[,\s]+", symbols) if p]
    else:
        parts = [str(p) for p in symbols]
    if not parts:
        raise NoMarketDataError(str(symbols), detail="未提供任何标的代码")
    return [to_prefixed_code(p) for p in parts]


def _get(url: str, headers: dict[str, str] | None = None) -> str:
    try:
        resp = requests.get(url, headers=headers or {}, timeout=_TIMEOUT)
    except requests.RequestException as exc:
        raise VendorError(f"实时行情请求失败: {exc}") from exc
    if resp.status_code == 429:
        from .errors import VendorRateLimitError

        raise VendorRateLimitError("实时行情源限流 (HTTP 429)")
    if resp.status_code != 200:
        raise VendorError(f"实时行情源返回 HTTP {resp.status_code}")
    try:
        return resp.content.decode("gbk", errors="replace")
    except Exception as exc:  # pragma: no cover - decode 兜底
        raise VendorError(f"实时行情响应解码失败: {exc}") from exc


def _float(text: str) -> float | None:
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return value


def _at(fields: list[str], index: int) -> str:
    """按下标取字段；越界返回空串（指数/基金等品种字段比个股少）。"""
    return fields[index] if index < len(fields) else ""


def parse_realtime_quote(symbol: str, raw: str) -> dict | None:
    """把腾讯行情的一行记录解析成结构化 dict；字段缺失返回 ``None``。"""
    fields = raw.split("~")
    if len(fields) <= _TX_LIMIT_DOWN:
        return None
    price = _float(fields[_TX_PRICE])
    prev_close = _float(fields[_TX_PREV_CLOSE])
    if price is None or price <= 0:
        return None
    return {
        "symbol": symbol,
        "code": fields[2] if len(fields) > 2 else symbol[2:],
        "name": fields[_TX_NAME],
        "price": price,
        "prev_close": prev_close,
        "open": _float(fields[_TX_OPEN]),
        "high": _float(fields[_TX_HIGH]),
        "low": _float(fields[_TX_LOW]),
        "change": _float(fields[_TX_CHANGE]),
        "change_pct": _float(fields[_TX_CHANGE_PCT]),
        "volume_lots": _float(fields[_TX_VOLUME]),
        "amount_wan": _float(fields[_TX_AMOUNT]),
        "turnover_pct": _float(fields[_TX_TURNOVER]),
        "volume_ratio": _float(_at(fields, _TX_VOLUME_RATIO)),
        "amplitude_pct": _float(_at(fields, _TX_AMPLITUDE)),
        "avg_price": _float(_at(fields, _TX_AVG_PRICE)),
        "pe": _float(fields[_TX_PE]),
        "pb": _float(_at(fields, _TX_PB)),
        "market_cap_yi": _float(_at(fields, _TX_MARKET_CAP)),
        "limit_up": _float(fields[_TX_LIMIT_UP]),
        "limit_down": _float(fields[_TX_LIMIT_DOWN]),
        "time": fields[_TX_TIME] if len(fields) > _TX_TIME else "",
        "source": "tencent",
    }


def get_realtime_quotes_batch(symbols: str | list[str], curr_date: str | None = None) -> list[dict]:
    """批量取实时行情，返回结构化 dict 列表（已经不是所有标的都有数据）。

    监控层直接用这个函数；面向 Agent 工具的是 :func:`get_realtime_quote`。
    """
    _guard_historical(curr_date)
    codes = _parse_symbols(symbols)

    url = "https://qt.gtimg.cn/q=" + ",".join(codes)
    text = _get(url, headers={"Referer": "https://gu.qq.com/"})

    quotes: list[dict] = []
    for match in _TX_LINE.finditer(text):
        quote = parse_realtime_quote(match.group(1), match.group(2))
        if quote is not None:
            quotes.append(quote)

    if quotes:
        return quotes

    # 腾讯无数据 → 新浪兜底
    logger.info("腾讯行情无有效返回，回退新浪源")
    return _sina_batch(codes)


def _sina_batch(codes: list[str]) -> list[dict]:
    url = "https://hq.sinajs.cn/list=" + ",".join(codes)
    text = _get(url, headers={"Referer": "https://finance.sina.com.cn/"})

    quotes: list[dict] = []
    for match in _SINA_LINE.finditer(text):
        symbol, raw = match.group(1), match.group(2)
        fields = raw.split(",")
        if len(fields) <= _SINA_TIME:
            continue
        price = _float(fields[_SINA_PRICE])
        prev_close = _float(fields[_SINA_PREV_CLOSE])
        if price is None or price <= 0:
            continue
        change = None
        change_pct = None
        if prev_close:
            change = round(price - prev_close, 2)
            change_pct = round((price - prev_close) / prev_close * 100, 2)
        quotes.append(
            {
                "symbol": symbol,
                "code": symbol[2:],
                "name": fields[_SINA_NAME],
                "price": price,
                "prev_close": prev_close,
                "open": _float(fields[_SINA_OPEN]),
                "high": _float(fields[_SINA_HIGH]),
                "low": _float(fields[_SINA_LOW]),
                "change": change,
                "change_pct": change_pct,
                "volume_lots": (_float(fields[_SINA_VOLUME]) or 0) / 100 or None,
                "amount_wan": (_float(fields[_SINA_AMOUNT]) or 0) / 10000 or None,
                "turnover_pct": None,
                "volume_ratio": None,  # 新浪源不提供量比
                "amplitude_pct": None,
                "avg_price": None,
                "pe": None,
                "pb": None,
                "market_cap_yi": None,
                "limit_up": None,
                "limit_down": None,
                "time": f"{fields[_SINA_DATE]} {fields[_SINA_TIME]}",
                "source": "sina",
            }
        )
    if not quotes:
        raise NoMarketDataError(",".join(codes), detail="腾讯与新浪行情源均未返回有效快照")
    return quotes


def _fmt(value: float | None, decimals: int = 2, suffix: str = "") -> str:
    if value is None:
        return "N/A"
    return f"{value:,.{decimals}f}{suffix}"


def get_realtime_quote(symbols: str | list[str], curr_date: str | None = None) -> str:
    """取实时行情快照，返回 Markdown 表格字符串。

    Args:
        symbols: 标的代码，支持逗号/空格分隔的字符串或列表，如 ``"600519,000001"``。
        curr_date: 分析日。**只有等于运行当天才允许出数**，历史日期会被拒绝，
            防止实时快照泄漏进历史回测。

    Raises:
        VendorError: 请求了历史日期，或行情源不可用。
        VendorNotConfiguredError: 缺少 ``requests``（理论上不会，它是核心依赖）。
        NoMarketDataError: 所有行情源都没有返回有效快照。
    """
    try:
        import requests as _requests  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise VendorNotConfiguredError("实时行情源需要 requests 依赖") from exc

    quotes = get_realtime_quotes_batch(symbols, curr_date=curr_date)

    header = f"## 实时行情快照（{_today_str()}，来源：{quotes[0]['source']}）\n"
    lines = [
        "| 代码 | 名称 | 现价 | 涨跌幅 | 今开 | 最高 | 最低 | 成交额(万) | 换手率 | 量比 | 涨停 | 跌停 |",
        "|------|------|------|--------|------|------|------|-----------|--------|------|------|------|",
    ]
    for q in quotes:
        lines.append(
            "| {code} | {name} | {price} | {pct} | {open} | {high} | {low} | {amount} "
            "| {turnover} | {vr} | {lu} | {ld} |".format(
                code=q["code"],
                name=q["name"],
                price=_fmt(q["price"]),
                pct=_fmt(q["change_pct"], 2, "%"),
                open=_fmt(q["open"]),
                high=_fmt(q["high"]),
                low=_fmt(q["low"]),
                amount=_fmt(q["amount_wan"], 0),
                turnover=_fmt(q["turnover_pct"], 2, "%"),
                vr=_fmt(q.get("volume_ratio")),
                lu=_fmt(q["limit_up"]),
                ld=_fmt(q["limit_down"]),
            )
        )
    stamp = quotes[0].get("time", "")
    footer = f"\n更新时间：{stamp}\n" if stamp else ""
    return header + "\n".join(lines) + footer
