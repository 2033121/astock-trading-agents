"""时间点门控原语（``astock_trader.point_in_time``）的单元测试。

这些规则是防前视偏差（look-ahead bias）的地基：历史/回测运行里任何「分析日之后
才可知」的内容都不该出现在 prompt 里。保守方向统一为「证明不了它当时已知，就不
放行」。
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from astock_trader.point_in_time import (
    CST,
    in_window,
    normalize_date,
    to_local,
    window_reaches_present,
    within_as_of,
)

# ────────────────────────────────────────────────────────────────
#  normalize_date
# ────────────────────────────────────────────────────────────────


class TestNormalizeDate:
    """常见日期写法归一化。"""

    def test_iso_string(self):
        assert normalize_date("2026-09-12") == "2026-09-12"

    def test_compact_string(self):
        assert normalize_date("20260912") == "2026-09-12"

    def test_slash_string(self):
        assert normalize_date("2026/09/12") == "2026-09-12"

    def test_datetime_string_keeps_date_part(self):
        assert normalize_date("2026-09-12 09:30:00") == "2026-09-12"

    def test_datetime_object(self):
        assert normalize_date(datetime(2026, 9, 12, 15, 0)) == "2026-09-12"

    def test_date_object(self):
        assert normalize_date(date(2026, 9, 12)) == "2026-09-12"

    def test_none_returns_none(self):
        assert normalize_date(None) is None

    def test_garbage_returns_none(self):
        assert normalize_date("上周三") is None

    def test_impossible_date_returns_none(self):
        """2 月 30 日不存在：宁可当作「不知道」，也不要当成能比较的字符串。"""
        assert normalize_date("2026-02-30") is None


# ────────────────────────────────────────────────────────────────
#  within_as_of
# ────────────────────────────────────────────────────────────────


class TestWithinAsOf:
    """字符串日期门控。"""

    def test_none_as_of_disables_filter(self):
        """实时运行（as_of=None）不受过滤影响。"""
        assert within_as_of("2026-09-12", None) is True
        assert within_as_of(None, None) is True

    def test_same_day_is_allowed(self):
        assert within_as_of("2026-09-12", "2026-09-12") is True

    def test_earlier_date_is_allowed(self):
        assert within_as_of("2026-01-05", "2026-09-12") is True

    def test_later_date_is_rejected(self):
        """结局在分析日之后才落地 —— 这就是前视偏差。"""
        assert within_as_of("2026-09-13", "2026-09-12") is False

    def test_unknown_date_is_rejected(self):
        """老条目没记落地日：无法证明当时已知，保守排除。"""
        assert within_as_of(None, "2026-09-12") is False
        assert within_as_of("", "2026-09-12") is False
        assert within_as_of("某年某月", "2026-09-12") is False

    def test_unparseable_as_of_rejects_everything(self):
        """as_of 自己无法解析时建立不了时间轴，一律不放行。"""
        assert within_as_of("2026-01-05", "不是日期") is False

    @pytest.mark.parametrize("value", ["2026-09-12", "20260912", "2026/09/12 08:00"])
    def test_formats_are_equivalent(self, value):
        assert within_as_of(value, "2026-09-12") is True


# ────────────────────────────────────────────────────────────────
#  to_local
# ────────────────────────────────────────────────────────────────


class TestToLocal:
    """时区归一：naive 值按北京时间解释，不是 UTC。"""

    def test_naive_is_read_as_beijing_time(self):
        """14:00（北京时间）== 06:00 UTC；若误当 UTC 会整体偏移 8 小时。"""
        local = to_local(datetime(2026, 9, 12, 14, 0))
        assert local.utcoffset() == timedelta(hours=8)
        assert local.hour == 14

    def test_aware_value_keeps_its_own_zone(self):
        aware = datetime(2026, 9, 12, 6, 0, tzinfo=timezone.utc)
        local = to_local(aware)
        assert local.hour == 14  # 06:00 UTC == 14:00 北京时间
        assert local.utcoffset() == timedelta(hours=8)

    def test_custom_assumption(self):
        naive = datetime(2026, 9, 12, 6, 0)
        assert to_local(naive, assume_tz=timezone.utc).utcoffset() == timedelta(0)

    def test_cst_offset(self):
        assert CST.utcoffset(None).total_seconds() == 8 * 3600


# ────────────────────────────────────────────────────────────────
#  window_reaches_present
# ────────────────────────────────────────────────────────────────


class TestWindowReachesPresent:
    """窗口右端是否已抵达当下。"""

    def test_today_is_live(self):
        assert window_reaches_present("2026-09-06", "2026-09-12", today=date(2026, 9, 12)) is True

    def test_past_window_is_not_live(self):
        assert window_reaches_present("2025-05-01", "2025-05-07", today=date(2026, 9, 12)) is False

    def test_unparseable_end_is_not_live(self):
        assert window_reaches_present("2025-05-01", "nan", today=date(2026, 9, 12)) is False


# ────────────────────────────────────────────────────────────────
#  in_window
# ────────────────────────────────────────────────────────────────


class TestInWindow:
    """带发布时间的窗口过滤（按北京时间的日历天比较）。"""

    def test_timestamp_inside_window_is_kept(self):
        assert in_window(datetime(2025, 5, 3, 10, 0), "2025-05-01", "2025-05-07") is True

    def test_late_evening_on_end_date_is_kept(self):
        """end 当天 23:30 发布的稿件仍属于窗口。"""
        assert in_window(datetime(2025, 5, 7, 23, 30), "2025-05-01", "2025-05-07") is True

    def test_next_day_just_after_midnight_is_dropped(self):
        """次日 00:01（北京时间）已经是未来，必须丢弃。"""
        assert in_window(datetime(2025, 5, 8, 0, 1), "2025-05-01", "2025-05-07") is False

    def test_early_morning_next_day_is_dropped(self):
        """次日凌晨 07:00 北京时间：按 UTC 解释会误判为落在窗口内。"""
        assert in_window(datetime(2025, 5, 8, 7, 0), "2025-05-01", "2025-05-07") is False

    def test_before_window_is_dropped(self):
        assert in_window(datetime(2025, 4, 30, 10, 0), "2025-05-01", "2025-05-07") is False

    def test_undated_kept_only_in_live_window(self):
        """无发布时间：实时窗口保留，历史窗口丢弃。"""
        assert in_window(None, "2025-05-01", "2025-05-07", today=date(2025, 5, 7)) is True
        assert in_window(None, "2025-05-01", "2025-05-07", today=date(2026, 9, 12)) is False

    def test_unparseable_window_rejects_everything(self):
        assert in_window(datetime(2025, 5, 3), "not-a-date", "2025-05-07") is False
        assert in_window(None, "2025-05-01", "not-a-date") is False

    def test_aware_timestamp_is_converted(self):
        """带时区的时间戳按自身时区换算，不受北京时间假设影响。"""
        # 2025-05-08 00:30 UTC 已经是 end(05-07) 之后
        assert in_window(datetime(2025, 5, 8, 0, 30, tzinfo=timezone.utc), "2025-05-01", "2025-05-07") is False
