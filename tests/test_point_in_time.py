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
    report_is_known,
    run_as_of,
    statutory_disclosure_deadline,
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


# ────────────────────────────────────────────────────────────────
#  statutory_disclosure_deadline
# ────────────────────────────────────────────────────────────────


class TestStatutoryDisclosureDeadline:
    """定期报告的法定披露截止日 —— 该期报告最晚何时可知。"""

    def test_q1_deadline_is_april_30(self):
        assert statutory_disclosure_deadline("2025-03-31") == "2025-04-30"

    def test_half_year_deadline_is_august_31(self):
        assert statutory_disclosure_deadline("2025-06-30") == "2025-08-31"

    def test_q3_deadline_is_october_31(self):
        assert statutory_disclosure_deadline("2025-09-30") == "2025-10-31"

    def test_annual_deadline_is_next_year_april_30(self):
        """年报跨年：2024 年年报最晚 2025-04-30 披露。"""
        assert statutory_disclosure_deadline("2024-12-31") == "2025-04-30"

    def test_non_standard_period_end_returns_none(self):
        """非标准报告期末（如 5-15）没有法定截止日可言。"""
        assert statutory_disclosure_deadline("2025-05-15") is None

    def test_unparseable_returns_none(self):
        assert statutory_disclosure_deadline("不是日期") is None


# ────────────────────────────────────────────────────────────────
#  report_is_known
# ────────────────────────────────────────────────────────────────


class TestReportIsKnown:
    """财报在分析日是否已公开 —— 报告期结束 ≠ 可知。"""

    def test_none_as_of_disables_filter(self):
        assert report_is_known("2025-03-31", None) is True

    def test_period_end_alone_is_not_enough(self):
        """一季报 3-31 结束，但 4-15 时还没到截止日（4-30），不能放行。"""
        assert report_is_known("2025-03-31", "2025-04-15") is False

    def test_after_statutory_deadline_is_known(self):
        assert report_is_known("2025-03-31", "2025-04-30") is True
        assert report_is_known("2025-03-31", "2025-05-01") is True

    def test_annual_needs_next_year_may(self):
        assert report_is_known("2024-12-31", "2025-03-01") is False
        assert report_is_known("2024-12-31", "2025-05-01") is True

    def test_announcement_date_is_precise(self):
        """有公告日期就按公告日期：早于截止日披露也能放行。"""
        assert report_is_known("2025-03-31", "2025-04-12", ann_date="2025-04-10") is True

    def test_announcement_date_after_as_of_is_rejected(self):
        """公告日期晚于分析日：即便报告期已经过去也不放行。"""
        assert report_is_known("2025-03-31", "2025-04-12", ann_date="2025-04-20") is False

    def test_announcement_date_is_not_relaxed_by_earlier_deadline(self):
        """公告日期存在时只认它，不被更晚的法定截止日放宽。"""
        assert report_is_known("2025-03-31", "2025-04-15", ann_date="2025-06-01") is False

    def test_unparseable_announcement_falls_back_to_deadline(self):
        assert report_is_known("2025-03-31", "2025-05-01", ann_date="待定") is True

    def test_unknown_period_is_rejected(self):
        """认不出报告期：无法证明当时可知，保守排除。"""
        assert report_is_known("", "2025-05-01") is False

    def test_unparseable_as_of_rejects_everything(self):
        assert report_is_known("2025-03-31", "不是日期") is False


# ────────────────────────────────────────────────────────────────
#  run_as_of
# ────────────────────────────────────────────────────────────────


class TestRunAsOf:
    """运行日期 → 数据门控 as_of：历史运行才门控，实时运行不门控。"""

    def test_past_date_is_historical(self):
        assert run_as_of("2025-06-01", today=date(2026, 10, 2)) == "2025-06-01"

    def test_today_is_live(self):
        """实时运行不门控：数据源只会返回已披露的报告，再卡截止日会误伤新报告。"""
        assert run_as_of("2026-10-02", today=date(2026, 10, 2)) is None

    def test_future_date_is_live(self):
        assert run_as_of("2026-10-03", today=date(2026, 10, 2)) is None

    def test_compact_format_is_normalized(self):
        assert run_as_of("20250601", today=date(2026, 10, 2)) == "2025-06-01"

    def test_unparseable_date_is_live(self):
        """认不出运行日期时不引入额外过滤，避免把所有数据挡掉。"""
        assert run_as_of("", today=date(2026, 10, 2)) is None
        assert run_as_of("今天", today=date(2026, 10, 2)) is None
