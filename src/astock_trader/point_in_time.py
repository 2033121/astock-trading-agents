"""时间点门控（point-in-time）— 防止历史分析看到「未来才可知」的信息。

历史/回测运行（``astock-trader analyze 600519 --date 2025-06-01``）里，任何
在分析日之后才可知的内容都构成**前视偏差**（look-ahead bias）：

- 交易记忆里的反思 —— 结局是在分析日之后才知道的；
- 向量记忆里的历史分析 —— 检索时不看日期，会把「未来」的报告注入 prompt；
- 新闻流里的稿件 —— 发布时间晚于分析窗口，甚至没有发布时间。

这三处规则一样、写法容易各写一份，所以收敛到本模块。上游
`TradingAgents <https://github.com/TauricResearch/TradingAgents>`_ 在 v0.4.0
把同一类问题（#1251 / #1126 / #1220）统一处理，这里沿用同样的语义。

两类门控
--------
:func:`within_as_of`
    字符串日期门控，用于**记忆条目**：条目的「可知日」不晚于 ``as_of`` 才放行。
    ``as_of=None`` 表示实时运行，不做任何过滤。

:func:`in_window`
    带发布时间的窗口过滤，用于**内容流**（新闻等）。比较的是**北京时间的日历
    天**：先按市场所在时区把发布时间换算成当地日期，再判是否落在
    ``[start, end]`` 这几个日历天里。无发布时间的条目只在「窗口抵达当下」时保留。

两条规则的保守方向一致：**证明不了它在分析日之前可知，就不放行**。
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any

__all__ = [
    "CST",
    "in_window",
    "normalize_date",
    "to_local",
    "window_reaches_present",
    "within_as_of",
]

# 中国标准时间（UTC+8，无夏令时）。东方财富 / akshare 等国内数据源给出的发布
# 时间都是北京时间，且常常不带时区信息。这里用固定偏移而不是 ``zoneinfo``：
# Windows 上 ``ZoneInfo("Asia/Shanghai")`` 依赖外部 IANA 数据库，缺 tzdata 时
# 会直接抛异常，而本项目要在 Windows 上跑。
CST = timezone(timedelta(hours=8), "CST")

# 宽松匹配 ``2026-09-12`` / ``20260912`` / ``2026/09/12`` / ``2026-09-12 09:30:00``
_DATE_RE = re.compile(r"^\s*(\d{4})[-/]?(\d{2})[-/]?(\d{2})")


def normalize_date(value: Any) -> str | None:
    """把常见日期写法归一成 ``YYYY-MM-DD``；无法解析时返回 ``None``。

    接受 ``datetime`` / ``date`` 对象，以及 ``2026-09-12``、``20260912``、
    ``2026/09/12``、``2026-09-12 09:30:00`` 等字符串写法。
    非法日期（如 ``2026-02-30``）同样返回 ``None`` —— 宁可当作「不知道」，
    也不要把它当成一个能通过比较的字符串。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    match = _DATE_RE.match(str(value))
    if not match:
        return None
    year, month, day = (int(g) for g in match.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def within_as_of(date_value: Any, as_of: str | None) -> bool:
    """判断一条记录在 ``as_of`` 这个时间点上是否**已经可知**。

    Parameters
    ----------
    date_value : Any
        记录的「可知日」。对交易记忆是结局落地日，对向量记忆是分析日。
    as_of : str | None
        本次运行的分析日。``None`` 表示实时运行，不过滤（返回 ``True``）。

    Returns
    -------
    bool
        ``as_of`` 为 ``None`` 时恒为 ``True``；否则要求 ``date_value`` 可解析
        且不晚于 ``as_of``。**无法解析的一律返回 ``False``** —— 老条目没有
        记录可知日，回测中无法证明它当时已知，保守排除（实时运行不受影响）。
    """
    if as_of is None:
        return True

    normalized_as_of = normalize_date(as_of)
    if normalized_as_of is None:
        # as_of 本身无法解析：无法建立时间轴，保守不放行。
        return False

    normalized_date = normalize_date(date_value)
    if normalized_date is None:
        return False
    return normalized_date <= normalized_as_of


def to_local(dt: datetime, *, assume_tz: tzinfo = CST) -> datetime:
    """把 ``datetime`` 归一到目标时区（默认北京时间）。

    带时区信息的值按自身时区换算；naive 值按 *assume_tz* 解释 —— 默认北京时间，
    因为国内数据源（东方财富 / akshare）的发布时间就是北京时间。把北京时间当
    UTC 会让窗口整体偏移 8 小时，恰好放过「分析日次日凌晨」发布的稿件。
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=assume_tz)
    return dt.astimezone(assume_tz)


def window_reaches_present(start_dt: Any, end_dt: Any, *, today: date | None = None) -> bool:
    """分析窗口的右端是否已经抵达当下（即这是一次实时运行）。

    只有实时运行才允许保留「没有发布时间」的内容：回测里无时间戳的条目
    无法证明它不属于未来，必须丢弃。
    """
    normalized_end = normalize_date(end_dt)
    if normalized_end is None:
        return False
    reference = today or datetime.now(timezone.utc).date()
    return date.fromisoformat(normalized_end) >= reference


def in_window(
    pub_dt: datetime | None,
    start_dt: Any,
    end_dt: Any,
    *,
    today: date | None = None,
    assume_tz: tzinfo = CST,
) -> bool:
    """发布时间是否落在 ``[start, end]`` 这几个**日历天**内（按市场所在时区）。

    比较的是日历天，不是 UTC 瞬时区间。国内数据源的发布时间是北京时间，用 UTC
    半开区间判定会整体偏移 8 小时 —— 「分析日次日 00:01 发布」的稿件会被算成
    ``end`` 当天下午 4 点，正好漏进窗口。先换算到当地日期再比日历天就没有这个缝。

    Parameters
    ----------
    pub_dt : datetime | None
        发布时间。``None`` 表示该条目没有时间戳。
    start_dt, end_dt : Any
        窗口起止（含 ``end`` 当天）。
    today : date | None
        便于测试注入「今天」；默认取 UTC 当天。
    assume_tz : tzinfo
        naive 发布时间的时区假设，默认北京时间。

    Returns
    -------
    bool
        无发布时间的条目：仅当窗口抵达当下（实时运行）才返回 ``True``。
    """
    normalized_start = normalize_date(start_dt)
    normalized_end = normalize_date(end_dt)
    if normalized_start is None or normalized_end is None:
        # 窗口自己就无法确定：不能证明任何条目落在其中。
        return False

    if pub_dt is None:
        return window_reaches_present(normalized_start, normalized_end, today=today)

    published = to_local(pub_dt, assume_tz=assume_tz).date().isoformat()
    return normalized_start <= published <= normalized_end
