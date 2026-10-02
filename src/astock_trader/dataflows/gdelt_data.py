"""GDELT 全球新闻源 —— 免费、免 Key，补上"全球事件面"的空白。

本模块对接 GDELT 2.0 DOC API（``api.gdeltproject.org/api/v2/doc/doc``），
与仓库里其它新闻源的区别是**覆盖范围是全球事件图**，而不是中文财经媒体：
地缘冲突、灾害、政策、供应链这类会外溢到 A 股的宏观事件，在这里比在个股
新闻里更早出现。

时点门控
--------
GDELT 的每条文章都带 ``seendate``。本模块把查询区间**上界钉死在分析日当天
23:59:59**（``enddatetime``），因此历史运行下不会看到分析日之后的报道，
满足 ``docs/前视偏差防护.md`` 的要求。

覆盖窗口（重要且诚实）
----------------------
GDELT DOC API 只索引**最近三个月**。查询更早的日期区间会返回空集，此时抛
:class:`NoMarketDataError` 让路由换源，而不是伪装成"当天没有新闻"。
更早的历史需要 GDELT 的 raw/full 归档文件（每条 15 分钟一个包），不在本模块范围。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Annotated

import requests

from .errors import NoMarketDataError, VendorError, VendorRateLimitError

logger = logging.getLogger(__name__)

__all__ = ["get_global_news"]

_API = "https://api.gdeltproject.org/api/v2/doc/doc"
_TIMEOUT = 20

# GDELT 官方限流：同一个 IP 每 5 秒最多一次请求（429 响应里明确写了）。
# 反爬不是靠"出错了再退避"，而是**根本不要发那么快**，所以这里做客户端节流；
# 否则多个 Agent 并发调新闻会把自己打成 429，然后整条新闻链一起换源。
_MIN_INTERVAL_S = 5.0
_last_call_at = 0.0
_call_lock = threading.Lock()

# 默认查询：中文语境下的市场/宏观/政策面。GDELT 语法里空格是 AND，OR 取并集。
_DEFAULT_QUERY = "(A股 OR 中国股市 OR 中国经济 OR 宏观经济 OR 央行)"

# DOC API 的索引深度（天）。超出这个窗口的查询必然为空。
_COVERAGE_DAYS = 92


def _gdelt_datetime(date_str: str, *, end_of_day: bool = False) -> str:
    """``2026-09-30`` → ``20260930000000`` / ``20260930235959``。"""
    digits = date_str.replace("-", "").strip()
    if len(digits) != 8 or not digits.isdigit():
        raise VendorError(f"GDELT 需要 yyyy-mm-dd 或 yyyymmdd 形式的日期，收到 {date_str!r}")
    return f"{digits}{'235959' if end_of_day else '000000'}"


def _shift_days(date_str: str, days: int) -> str:
    from datetime import datetime, timedelta

    base = datetime.strptime(date_str.replace("-", ""), "%Y%m%d")
    return (base - timedelta(days=days)).strftime("%Y%m%d")


def _throttle() -> None:
    """确保两次真实请求之间至少间隔 :data:`_MIN_INTERVAL_S` 秒。

    进程内线程安全；跨进程不管（多进程同时打 GDELT 仍可能撞限流，届时按
    :class:`VendorRateLimitError` 走正常换源）。
    """
    global _last_call_at
    with _call_lock:
        wait = _MIN_INTERVAL_S - (time.monotonic() - _last_call_at)
        if wait > 0:
            logger.debug("GDELT 节流：等待 %.1fs", wait)
            time.sleep(wait)
        _last_call_at = time.monotonic()


def _format_articles(articles: list[dict], curr_date: str) -> str:
    lines = [f"## GDELT 全球新闻（截至 {curr_date}，共 {len(articles)} 条）", ""]
    for i, article in enumerate(articles, 1):
        title = str(article.get("title", "")).strip()
        domain = str(article.get("domain", "")).strip()
        seen = str(article.get("seendate", "")).strip()
        country = str(article.get("sourcecountry", "")).strip()
        url = str(article.get("url", "")).strip()
        when = f"{seen[:4]}-{seen[4:6]}-{seen[6:8]} {seen[9:11]}:{seen[11:13]}" if len(seen) >= 13 else seen
        meta = " · ".join(x for x in (when, domain, country) if x)
        lines.append(f"{i}. **{title}**")
        if meta:
            lines.append(f"   {meta}")
        if url:
            lines.append(f"   {url}")
    return "\n".join(lines)


def get_global_news(
    curr_date: Annotated[str, "参考日期 yyyy-mm-dd 或 yyyymmdd"] = "",
    look_back_days: Annotated[int, "回看天数"] = 7,
    limit: Annotated[int, "最大返回条数"] = 10,
    query: Annotated[str, "GDELT 查询串，留空用默认宏观/市场查询"] = "",
) -> str:
    """取全球新闻，返回 Markdown 字符串。

    Raises:
        VendorError: 日期格式非法、请求失败。
        VendorRateLimitError: GDELT 限流（HTTP 429）。
        NoMarketDataError: 查询窗口超出 DOC API 的三个月索引，或该窗口确无命中。
    """
    if not curr_date:
        from datetime import datetime

        curr_date = datetime.now().strftime("%Y-%m-%d")

    end = _gdelt_datetime(curr_date, end_of_day=True)
    start = f"{_shift_days(curr_date, max(1, look_back_days))}000000"

    params = {
        "query": query.strip() or _DEFAULT_QUERY,
        "mode": "artlist",
        "format": "json",
        "maxrecords": max(1, min(int(limit), 250)),
        "startdatetime": start,
        "enddatetime": end,
        "sort": "hybridrel",
    }

    try:
        _throttle()
        resp = requests.get(_API, params=params, timeout=_TIMEOUT)
    except requests.RequestException as exc:
        raise VendorError(f"GDELT 请求失败：{exc}") from exc

    if resp.status_code == 429:
        raise VendorRateLimitError("GDELT 限流 (HTTP 429)：同一 IP 每 5 秒只允许一次请求")
    if resp.status_code != 200:
        raise VendorError(f"GDELT 返回 HTTP {resp.status_code}")

    # 查询非法时 GDELT 会返回纯文本错误而不是 JSON
    try:
        payload = resp.json()
    except ValueError as exc:
        raise VendorError(f"GDELT 返回了非 JSON 响应：{resp.text[:200]}") from exc

    articles = payload.get("articles") or []
    if not articles:
        raise NoMarketDataError(
            curr_date,
            canonical=curr_date,
            detail=(
                f"GDELT 在 {start[:8]}~{end[:8]} 窗口内无命中；"
                f"注意 DOC API 只索引最近约 {_COVERAGE_DAYS} 天，更早的历史需要 GDELT 归档文件"
            ),
        )

    return _format_articles(articles, curr_date)
