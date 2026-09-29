"""反思闭环的持有窗口必须按**交易日**判定。

原实现用 ``datetime.now() - timedelta(days=5)``（自然日）判断条目「够不够旧」，
再用 ``target_idx = min(days, len(df) - 1)`` 取平仓价。两者叠加的后果是：国庆、
春节长假里 5 个自然日可能只含 1~2 个交易日，于是**1 日收益会被当作「5日收益」
写进记忆**，成为未来决策的「历史教训」。这类错误不会报错，只会安静地污染记忆。

现在判据是「已出现 ``days + 1`` 根**已收盘** K 线」，不足就保持 pending。
"""

from datetime import datetime, timedelta

import pandas as pd
import pytest

from astock_trader.agents.utils.memory import TradingMemoryLog
from astock_trader.graph.trading_graph import TradingAgentsGraph


def _bars(dates: list[str], closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"日期": dates, "收盘": closes})


def _days_ago(n: int) -> str:
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")


# ────────────────────────────────────────────────────────────────
#  _settled_bars
# ────────────────────────────────────────────────────────────────


class TestSettledBars:
    """把原始行情裁剪成「从决策日起、已收盘、连续」的交易日序列。"""

    def test_enough_bars_are_kept(self):
        df = _bars(["2025-01-02", "2025-01-03", "2025-01-06"], [10.0, 11.0, 12.0])
        out = TradingAgentsGraph._settled_bars(df, "2025-01-02", 2)
        assert out is not None
        assert len(out) == 3

    def test_insufficient_bars_return_none(self):
        """只有 2 根 K 线却要 5 日窗口 —— 窗口没走完，不能拿短窗口冒充。"""
        df = _bars(["2025-01-02", "2025-01-03"], [10.0, 11.0])
        assert TradingAgentsGraph._settled_bars(df, "2025-01-02", 5) is None

    def test_exactly_days_plus_one_bars_is_enough(self):
        dates = [f"2025-01-{d:02d}" for d in range(2, 8)]
        df = _bars(dates, [10.0 + i for i in range(6)])
        assert TradingAgentsGraph._settled_bars(df, "2025-01-02", 5) is not None

    def test_bars_before_trade_date_are_dropped(self):
        df = _bars(["2024-12-31", "2025-01-02", "2025-01-03"], [9.0, 10.0, 11.0])
        out = TradingAgentsGraph._settled_bars(df, "2025-01-02", 1)
        assert out is not None
        assert out.iloc[0]["日期"] == "2025-01-02"

    def test_todays_unsettled_bar_is_excluded(self):
        """当日 K 线可能还在变，用它结算等于把浮动价写成 T+N 结果。"""
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = _days_ago(1)
        df = _bars([yesterday, today], [10.0, 99.0])
        assert TradingAgentsGraph._settled_bars(df, yesterday, 1) is None

    def test_unsorted_input_is_sorted(self):
        df = _bars(["2025-01-06", "2025-01-02", "2025-01-03"], [12.0, 10.0, 11.0])
        out = TradingAgentsGraph._settled_bars(df, "2025-01-02", 2)
        assert out is not None
        assert list(out["日期"]) == ["2025-01-02", "2025-01-03", "2025-01-06"]

    def test_holiday_gap_is_fine(self):
        """长假只影响自然日跨度，不影响交易日计数。"""
        df = _bars(["2025-01-24", "2025-01-27", "2025-02-05", "2025-02-06"], [10.0, 10.5, 11.0, 11.5])
        out = TradingAgentsGraph._settled_bars(df, "2025-01-24", 3)
        assert out is not None
        assert out.iloc[3]["日期"] == "2025-02-06"

    @pytest.mark.parametrize(
        "df",
        [
            None,
            pd.DataFrame(),
            pd.DataFrame({"date": ["2025-01-02"], "close": [1.0]}),
            pd.DataFrame({"日期": ["2025-01-02"]}),
        ],
    )
    def test_unusable_frames_return_none(self, df):
        assert TradingAgentsGraph._settled_bars(df, "2025-01-02", 0) is None


# ────────────────────────────────────────────────────────────────
#  _forward_return
# ────────────────────────────────────────────────────────────────


class _Stub:
    """只带 ``_settled_bars`` 的壳，用来直接调 ``_forward_return``。"""

    _settled_bars = staticmethod(TradingAgentsGraph._settled_bars)


class _FakeAkshare:
    """伪造 akshare：只实现反思闭环用到的两个行情接口。"""

    def __init__(self, stock_bars: pd.DataFrame | None, index_bars: pd.DataFrame | None = None):
        self.stock_bars = stock_bars
        self.index_bars = index_bars
        self.calls: list[tuple[str, dict]] = []

    def stock_zh_a_hist(self, **kwargs):
        self.calls.append(("stock", kwargs))
        return self.stock_bars

    def index_zh_a_hist(self, **kwargs):
        self.calls.append(("index", kwargs))
        return self.index_bars


@pytest.fixture
def fake_akshare(monkeypatch):
    def _install(stock_bars, index_bars=None):
        fake = _FakeAkshare(stock_bars, index_bars)
        monkeypatch.setitem(__import__("sys").modules, "akshare", fake)
        return fake

    return _install


_SIX_BARS = _bars(
    ["2025-03-03", "2025-03-04", "2025-03-05", "2025-03-06", "2025-03-07", "2025-03-10"],
    [100.0, 101.0, 102.0, 103.0, 104.0, 110.0],
)


class TestForwardReturn:
    """收益率与平仓日的计算。"""

    def test_return_uses_exactly_days_bars(self, fake_akshare):
        fake_akshare(_SIX_BARS)
        outcome = TradingAgentsGraph._forward_return(_Stub(), ticker="600519", trade_date="2025-03-03", days=5)
        assert outcome is not None
        raw_return, exit_date = outcome
        assert exit_date == "2025-03-10"  # 第 5 个交易日后
        assert raw_return == pytest.approx(0.10)  # 100 -> 110

    def test_incomplete_window_returns_none(self, fake_akshare):
        """只有 3 根 K 线却要 5 日窗口 —— 返回 None 让条目保持 pending。"""
        fake_akshare(_SIX_BARS.iloc[:3])
        assert TradingAgentsGraph._forward_return(_Stub(), ticker="600519", trade_date="2025-03-03", days=5) is None

    def test_benchmark_uses_index_endpoint(self, fake_akshare):
        fake = fake_akshare(_SIX_BARS, _SIX_BARS)
        outcome = TradingAgentsGraph._forward_return(_Stub(), ticker=None, trade_date="2025-03-03", days=5, index=True)
        assert outcome is not None
        assert fake.calls[0][0] == "index"
        assert fake.calls[0][1]["symbol"] == "000300"

    def test_stock_path_requests_adjusted_prices(self, fake_akshare):
        fake = fake_akshare(_SIX_BARS)
        TradingAgentsGraph._forward_return(_Stub(), ticker="600519", trade_date="2025-03-03", days=5)
        assert fake.calls[0][1]["adjust"] == "qfq"

    def test_fetch_failure_returns_none(self, fake_akshare):
        fake_akshare(None)
        assert TradingAgentsGraph._forward_return(_Stub(), ticker="600519", trade_date="2025-03-03", days=5) is None

    def test_invalid_trade_date_returns_none(self, fake_akshare):
        fake_akshare(_SIX_BARS)
        assert TradingAgentsGraph._forward_return(_Stub(), ticker="600519", trade_date="not-a-date", days=1) is None

    def test_zero_entry_price_returns_none(self, fake_akshare):
        bars = _bars(["2025-03-03", "2025-03-04"], [0.0, 10.0])
        fake_akshare(bars)
        assert TradingAgentsGraph._forward_return(_Stub(), ticker="600519", trade_date="2025-03-03", days=1) is None


# ────────────────────────────────────────────────────────────────
#  _resolve_pending_memory
# ────────────────────────────────────────────────────────────────


class _ReflectorSpy:
    def __init__(self):
        self.calls: list[dict] = []

    def reflect_on_final_decision(self, final_decision, raw_return, alpha_return):
        self.calls.append({"final_decision": final_decision, "raw_return": raw_return, "alpha_return": alpha_return})
        return "反思文本"


class _GraphStub:
    """走真实 ``_resolve_pending_memory`` 逻辑所需的最小依赖。"""

    _settled_bars = staticmethod(TradingAgentsGraph._settled_bars)

    def __init__(self, memory_log):
        self.memory_log = memory_log
        self.reflector = _ReflectorSpy()

    def _forward_return(self, *, ticker, trade_date, days, index=False):
        # 复用真实实现，只是行情来自假 akshare
        return TradingAgentsGraph._forward_return(self, ticker=ticker, trade_date=trade_date, days=days, index=index)


def _resolve(graph):
    TradingAgentsGraph._resolve_pending_memory(graph, "600519")


@pytest.fixture
def memory_log(tmp_path):
    return TradingMemoryLog(memory_dir=str(tmp_path), memory_file="trading_memory.log")


class TestResolvePendingMemory:
    """结算资格、落地日与基准缺失的处理。"""

    def _install(self, monkeypatch, stock_bars, index_bars=None):
        import sys

        fake = _FakeAkshare(stock_bars, index_bars)
        monkeypatch.setitem(sys.modules, "akshare", fake)
        return fake

    def test_incomplete_window_leaves_entry_pending(self, memory_log, monkeypatch):
        """核心回归：日历上够旧但交易日不够，条目必须保持 pending。"""
        # 决策在 6 个自然日之前，日历预筛会放行
        trade_date = _days_ago(6)
        recent = [
            (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d"),
            (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d"),
        ]
        self._install(monkeypatch, _bars(recent, [100.0, 102.0]))

        memory_log.store_decision("600519", trade_date, {"rating": "买入", "final_trade_decision": "买入"})
        graph = _GraphStub(memory_log)
        _resolve(graph)

        assert len(memory_log.get_pending_entries()) == 1, "窗口没走完就不该结算"
        assert graph.reflector.calls == []

    def test_complete_window_resolves_with_exit_date(self, memory_log, monkeypatch):
        trade_date = _days_ago(30)
        dates = [(datetime.now() - timedelta(days=20 - i)).strftime("%Y-%m-%d") for i in range(6)]
        self._install(monkeypatch, _bars(dates, [100.0, 101.0, 102.0, 103.0, 104.0, 110.0]), _bars(dates, [100.0] * 6))

        memory_log.store_decision("600519", trade_date, {"rating": "买入", "final_trade_decision": "买入"})
        graph = _GraphStub(memory_log)
        _resolve(graph)

        entries = memory_log._load_all_entries()
        assert entries[0]["pending"] is False
        # 平仓日就是第 5 个交易日 —— 也是时间点门控用的结局落地日
        assert entries[0]["resolved"] == dates[5]
        assert entries[0]["reflection"]["raw_return"] == pytest.approx(0.10)
        assert entries[0]["reflection"]["holding_days"] == 5
        assert entries[0]["reflection"]["hold_end"] == dates[5]
        assert "5日收益" in entries[0]["reflection"]["outcome"]
        assert len(graph.reflector.calls) == 1

    def test_benchmark_failure_records_alpha_as_unknown(self, memory_log, monkeypatch):
        """基准拉不到时不要假装超额为 0 —— 记为未知。"""
        trade_date = _days_ago(30)
        dates = [(datetime.now() - timedelta(days=20 - i)).strftime("%Y-%m-%d") for i in range(6)]
        self._install(monkeypatch, _bars(dates, [100.0, 101.0, 102.0, 103.0, 104.0, 110.0]), None)

        memory_log.store_decision("600519", trade_date, {"rating": "买入"})
        graph = _GraphStub(memory_log)
        _resolve(graph)

        entry = memory_log._load_all_entries()[0]
        assert entry["reflection"]["alpha_return"] is None
        assert "超额未获取" in entry["reflection"]["outcome"]

    def test_resolved_entry_visible_only_after_exit_date(self, memory_log, monkeypatch):
        """结算出来的教训在平仓日之前的分析里不可见。"""
        trade_date = _days_ago(30)
        dates = [(datetime.now() - timedelta(days=20 - i)).strftime("%Y-%m-%d") for i in range(6)]
        self._install(monkeypatch, _bars(dates, [100.0, 101.0, 102.0, 103.0, 104.0, 110.0]), _bars(dates, [100.0] * 6))

        memory_log.store_decision("600519", trade_date, {"rating": "买入", "final_trade_decision": "买入"})
        _resolve(_GraphStub(memory_log))

        exit_date = dates[5]
        before = (datetime.strptime(exit_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        assert memory_log.get_past_context("600519", as_of=before) == "暂无历史决策记录。"
        assert "反思文本" in memory_log.get_past_context("600519", as_of=exit_date)

    def test_no_pending_entries_is_a_noop(self, memory_log, monkeypatch):
        self._install(monkeypatch, None)
        graph = _GraphStub(memory_log)
        _resolve(graph)  # 不应抛异常
        assert graph.reflector.calls == []

    def test_recent_entry_skipped_by_calendar_prefilter(self, memory_log, monkeypatch):
        """刚做出的决策连行情都不用拉 —— 日历预筛先挡掉。"""
        fake = self._install(monkeypatch, _SIX_BARS)
        memory_log.store_decision("600519", datetime.now().strftime("%Y-%m-%d"), {"rating": "买入"})
        _resolve(_GraphStub(memory_log))
        assert fake.calls == []
        assert len(memory_log.get_pending_entries()) == 1
