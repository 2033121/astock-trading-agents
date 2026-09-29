"""交易记忆日志的时间点门控（上游 TradingAgents #1251 同类修复）。

``get_past_context`` 此前不看运行日期：历史/回测运行（``--date 2025-06-01``）会
把「结局是在 2026 年才落地」的教训注入 prompt，等于让模型提前知道答案。
现在每个 resolved 条目都记录 ``resolved_date``（结局落地的那个交易日），
``as_of`` 查询据此过滤。
"""

import pytest

from astock_trader.agents.utils.memory import TradingMemoryLog


@pytest.fixture
def log(tmp_path):
    return TradingMemoryLog(memory_dir=str(tmp_path), memory_file="trading_memory.log")


def _resolved_entry(log, ticker, trade_date, resolved_date, lesson="教训内容"):
    """写入一条 pending 决策并立刻结算，返回结算后的条目。"""
    log.store_decision(ticker, trade_date, {"rating": "买入"})
    log.batch_update_with_outcomes(
        [
            {
                "ticker": ticker,
                "trade_date": trade_date,
                "resolved_date": resolved_date,
                "reflection": {
                    "outcome": "5日收益 +3.0%",
                    "raw_return": 0.03,
                    "alpha_return": 0.01,
                    "lesson": lesson,
                    "resolved_date": resolved_date,
                },
            }
        ]
    )
    return log._load_all_entries()[-1]


class TestResolvedDatePersistence:
    """落地日必须能落盘、能读回。"""

    def test_resolved_date_is_stored_and_parsed(self, log):
        entry = _resolved_entry(log, "600519", "2026-01-05", "2026-01-12")
        assert entry["pending"] is False
        assert entry["resolved"] == "2026-01-12"

    def test_resolved_date_survives_rewrite(self, log):
        """轮转/重写整份文件后仍能读回 —— 否则时间点门控会静默失效。"""
        _resolved_entry(log, "600519", "2026-01-05", "2026-01-12")
        entries = log._load_all_entries()
        log._rewrite_all(entries)
        assert log._load_all_entries()[0]["resolved"] == "2026-01-12"

    def test_reflection_date_is_used_as_fallback(self, log):
        """顶层没给 resolved_date 时，退到 reflection 里的那个。"""
        log.store_decision("600519", "2026-01-05", {"rating": "买入"})
        log.batch_update_with_outcomes(
            [
                {
                    "ticker": "600519",
                    "trade_date": "2026-01-05",
                    "reflection": {"lesson": "x", "resolved_date": "2026-01-09"},
                }
            ]
        )
        assert log._load_all_entries()[0]["resolved"] == "2026-01-09"

    def test_missing_resolved_date_stays_unknown(self, log):
        """没有落地日就记为未知，不猜一个日期。"""
        log.store_decision("600519", "2026-01-05", {"rating": "买入"})
        log.batch_update_with_outcomes(
            [{"ticker": "600519", "trade_date": "2026-01-05", "reflection": {"lesson": "x"}}]
        )
        assert log._load_all_entries()[0]["resolved"] is None


class TestAsOfGating:
    """``as_of`` 过滤语义。"""

    def test_lesson_resolved_after_run_date_is_hidden(self, log):
        """决策在 01-05，结局 01-12 才落地；01-07 的分析不该看到它。"""
        _resolved_entry(log, "600519", "2026-01-05", "2026-01-12", lesson="超预期的反弹")

        assert log.get_past_context("600519", as_of="2026-01-07") == "暂无历史决策记录。"
        assert "超预期的反弹" in log.get_past_context("600519", as_of="2026-01-12")
        assert "超预期的反弹" in log.get_past_context("600519", as_of="2026-02-01")

    def test_no_as_of_keeps_live_behaviour(self, log):
        """实时运行（不传 as_of）行为不变。"""
        _resolved_entry(log, "600519", "2026-01-05", "2026-01-12", lesson="超预期的反弹")
        assert "超预期的反弹" in log.get_past_context("600519")

    def test_legacy_entry_without_date_excluded_in_backtest(self, log):
        """迁移前的老条目在回测里保守排除，但实时运行仍然可见。"""
        log.store_decision("600519", "2026-01-05", {"rating": "买入"})
        log.batch_update_with_outcomes(
            [{"ticker": "600519", "trade_date": "2026-01-05", "reflection": {"lesson": "老教训"}}]
        )

        assert log.get_past_context("600519", as_of="2026-06-01") == "暂无历史决策记录。"
        assert "老教训" in log.get_past_context("600519")

    def test_cross_ticker_lessons_are_gated_too(self, log):
        """跨标的教训同样受门控 —— 泄漏不区分标的是不是同一个。"""
        _resolved_entry(log, "000001", "2026-01-05", "2026-02-20", lesson="别的票的教训")
        assert log.get_past_context("600519", as_of="2026-02-01") == "暂无历史决策记录。"
        assert "别的票的教训" in log.get_past_context("600519", as_of="2026-02-20")

    def test_mixed_entries_filter_independently(self, log):
        """同一批里旧教训放行、新教训拦住。"""
        _resolved_entry(log, "600519", "2026-01-05", "2026-01-12", lesson="已落地的教训")
        _resolved_entry(log, "600519", "2026-03-01", "2026-03-10", lesson="还没发生的教训")

        context = log.get_past_context("600519", as_of="2026-02-01")
        assert "已落地的教训" in context
        assert "还没发生的教训" not in context

    def test_resolved_date_is_surfaced_in_context(self, log):
        """注入文本里带上落地日，模型才知道这条教训有多旧。"""
        _resolved_entry(log, "600519", "2026-01-05", "2026-01-12")
        assert "结局落地日: 2026-01-12" in log.get_past_context("600519", as_of="2026-02-01")


class TestPendingEntriesUnaffected:
    """pending 条目本来就不会被注入，门控只需保证不误放行。"""

    def test_pending_entry_never_appears(self, log):
        log.store_decision("600519", "2026-01-05", {"rating": "买入"})
        assert log.get_past_context("600519", as_of="2026-06-01") == "暂无历史决策记录。"

    def test_pending_entries_still_listed_for_resolution(self, log):
        log.store_decision("600519", "2026-01-05", {"rating": "买入"})
        assert len(log.get_pending_entries()) == 1
