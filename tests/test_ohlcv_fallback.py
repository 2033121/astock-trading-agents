"""日线行情的多源 fallback 与单位归一化。

为什么需要这组测试：东方财富 ``push2his`` 会按**出口 IP** 在服务端 WAF 层拦截
（akshare issues #6100 / #6198 / #6561 / #7098），表现为 TLS 成功但 HTTP 被
RST，UA / Referer / TLS 指纹全部无效。之前只有一个源，它一挂整条技术面分析
就没有输入 —— 而下游照样会产出一份措辞确定的报告。

同时锁住三个源的**单位差异**：新浪 volume 是「股」，腾讯 1.18.x 的 ``amount``
列其实是「手」，同一列名在不同版本里含义还不一样。单位错 100 倍不会报错，
只会静默算错均线。
"""

import datetime as dt

import pandas as pd
import pytest

from astock_trader.dataflows import akshare_data as A
from astock_trader.dataflows.errors import NoMarketDataError

_DAY = dt.date(2026, 9, 30)


# ── 三个源各自的原始返回结构（照抄实测字段）────────────────────


def _em_frame():
    """东方财富：中文列名，成交量「手」，成交额「元」。"""
    return pd.DataFrame(
        {
            "日期": ["2026-09-30"],
            "开盘": [1239.53],
            "收盘": [1258.62],
            "最高": [1268.0],
            "最低": [1236.05],
            "成交量": [38331],
            "成交额": [4797246636.0],
        }
    )


def _sina_frame():
    """新浪：volume「股」，amount「元」。"""
    return pd.DataFrame(
        {
            "date": [_DAY],
            "open": [1239.53],
            "high": [1268.0],
            "low": [1236.05],
            "close": [1258.62],
            "volume": [3833098.0],
            "amount": [4797246636.0],
            "outstanding_share": [1250081601.0],
        }
    )


def _tx_old_frame():
    """腾讯（akshare 1.18.x）：只有 6 列，``amount`` 实为成交量「手」。"""
    return pd.DataFrame(
        {
            "date": [_DAY],
            "open": [1239.53],
            "close": [1258.62],
            "high": [1268.0],
            "low": [1236.05],
            "amount": [38331.0],
        }
    )


def _tx_new_frame():
    """腾讯（akshare >= 1.19）：``volume``「股」+ ``amount``「元」。"""
    return pd.DataFrame(
        {
            "date": [_DAY],
            "open": [1239.53],
            "close": [1258.62],
            "high": [1268.0],
            "low": [1236.05],
            "volume": [3833098.0],
            "amount": [4797246636.0],
        }
    )


class _FakeAk:
    """可编排的 akshare 替身：哪些接口抛错、返回什么，由构造参数决定。"""

    def __init__(self, em=None, sina=None, tx=None):
        self._em, self._sina, self._tx = em, sina, tx
        self.calls: list[tuple[str, dict]] = []

    def _serve(self, name, payload, **kwargs):
        self.calls.append((name, kwargs))
        if isinstance(payload, Exception):
            raise payload
        return payload

    def stock_zh_a_hist(self, **kwargs):
        return self._serve("stock_zh_a_hist", self._em, **kwargs)

    def stock_zh_a_daily(self, **kwargs):
        return self._serve("stock_zh_a_daily", self._sina, **kwargs)

    def stock_zh_a_hist_tx(self, **kwargs):
        return self._serve("stock_zh_a_hist_tx", self._tx, **kwargs)


@pytest.fixture
def fake_ak(monkeypatch):
    def _install(em=None, sina=None, tx=None):
        stub = _FakeAk(em=em, sina=sina, tx=tx)
        monkeypatch.setattr(A, "ak", stub)
        return stub

    return _install


class TestSourceFallback:
    def test_eastmoney_preferred_when_healthy(self, fake_ak):
        stub = fake_ak(em=_em_frame(), sina=_sina_frame(), tx=_tx_old_frame())
        df, source, err = A._fetch_ohlcv("600519", "2026-09-01", "2026-09-30")

        assert err is None
        assert "东方财富" in source
        assert [c[0] for c in stub.calls] == ["stock_zh_a_hist"]  # 没白跑后面两个
        assert df["volume"].iloc[0] == 38331  # 手

    def test_falls_back_to_sina_when_eastmoney_blocked(self, fake_ak):
        # 本机的真实情形：东财被服务端断连
        stub = fake_ak(
            em=ConnectionError("Remote end closed connection without response"),
            sina=_sina_frame(),
            tx=_tx_old_frame(),
        )
        df, source, err = A._fetch_ohlcv("600519", "2026-09-01", "2026-09-30")

        assert err is None
        assert "新浪" in source
        assert [c[0] for c in stub.calls] == ["stock_zh_a_hist", "stock_zh_a_daily"]

    def test_falls_back_to_tencent_as_last_resort(self, fake_ak):
        fake_ak(
            em=ConnectionError("blocked"),
            sina=ValueError("sina down"),
            tx=_tx_old_frame(),
        )
        df, source, err = A._fetch_ohlcv("600519", "2026-09-01", "2026-09-30")
        assert err is None
        assert "腾讯" in source

    def test_all_sources_failed_reports_every_reason(self, fake_ak):
        fake_ak(
            em=ConnectionError("eastmoney reset"),
            sina=ValueError("sina empty"),
            tx=TimeoutError("tx timeout"),
        )
        df, source, err = A._fetch_ohlcv("600519", "2026-09-01", "2026-09-30")

        assert df is None
        assert source == ""
        # 每个源各自的原因都要留下 —— 「东财被断连」和「新浪返回空」是不同故障
        assert "eastmoney" in err
        assert "sina" in err
        assert "tencent" in err

    def test_empty_frame_is_treated_as_failure(self, fake_ak):
        fake_ak(em=pd.DataFrame(), sina=_sina_frame(), tx=_tx_old_frame())
        _, source, err = A._fetch_ohlcv("600519", "2026-09-01", "2026-09-30")
        assert err is None
        assert "新浪" in source

    def test_explicit_source_subset(self, fake_ak):
        stub = fake_ak(em=_em_frame(), sina=_sina_frame())
        _, source, _ = A._fetch_ohlcv("600519", "2026-09-01", "2026-09-30", sources=("sina",))
        assert "新浪" in source
        assert [c[0] for c in stub.calls] == ["stock_zh_a_daily"]


class TestUnitNormalisation:
    """volume 统一成「手」，turnover 统一成「元」。"""

    def test_sina_shares_converted_to_lots(self, fake_ak):
        fake_ak(em=ConnectionError("blocked"), sina=_sina_frame())
        df, _, _ = A._fetch_ohlcv("600519", "2026-09-01", "2026-09-30")
        assert df["volume"].iloc[0] == pytest.approx(38330.98, rel=1e-4)  # 3,833,098 股 / 100
        assert df["turnover"].iloc[0] == pytest.approx(4797246636.0)

    def test_tencent_old_schema_amount_is_lots(self, fake_ak):
        # 1.18.x：列名叫 amount，实为成交量（手），且没有成交额
        fake_ak(em=ConnectionError("blocked"), sina=ConnectionError("blocked"), tx=_tx_old_frame())
        df, _, _ = A._fetch_ohlcv("600519", "2026-09-01", "2026-09-30")
        assert df["volume"].iloc[0] == 38331
        assert pd.isna(df["turnover"].iloc[0])  # 不能拿 amount 冒充成交额

    def test_tencent_new_schema_volume_is_shares(self, fake_ak):
        # >=1.19：volume 是股、amount 是元 —— 同一列名含义变了，必须分开处理
        fake_ak(em=ConnectionError("blocked"), sina=ConnectionError("blocked"), tx=_tx_new_frame())
        df, _, _ = A._fetch_ohlcv("600519", "2026-09-01", "2026-09-30")
        assert df["volume"].iloc[0] == pytest.approx(38330.98, rel=1e-4)
        assert df["turnover"].iloc[0] == pytest.approx(4797246636.0)


class TestDateHandling:
    def test_dashed_dates_accepted_and_converted(self, fake_ak):
        stub = fake_ak(em=_em_frame())
        A._fetch_ohlcv("600519", "2026-09-01", "2026-09-30")
        kwargs = stub.calls[0][1]
        # akshare 要 YYYYMMDD，工具层传的是 yyyy-mm-dd
        assert kwargs["start_date"] == "20260901"
        assert kwargs["end_date"] == "20260930"

    def test_compact_dates_accepted(self, fake_ak):
        stub = fake_ak(em=_em_frame())
        A._fetch_ohlcv("600519", "20260901", "20260930")
        assert stub.calls[0][1]["start_date"] == "20260901"

    def test_invalid_date_rejected_before_any_call(self, fake_ak):
        stub = fake_ak(em=_em_frame())
        df, _, err = A._fetch_ohlcv("600519", "not-a-date", "2026-09-30")
        assert df is None
        assert "invalid date range" in err
        assert stub.calls == []

    def test_reversed_range_rejected(self, fake_ak):
        stub = fake_ak(em=_em_frame())
        df, _, err = A._fetch_ohlcv("600519", "2026-09-30", "2026-09-01")
        assert df is None
        assert "later than" in err
        assert stub.calls == []

    def test_prefixed_symbol_for_sina_and_tencent(self, fake_ak):
        stub = fake_ak(em=ConnectionError("x"), sina=_sina_frame())
        A._fetch_ohlcv("600519", "2026-09-01", "2026-09-30")
        assert stub.calls[1][1]["symbol"] == "sh600519"

    def test_bare_symbol_for_eastmoney(self, fake_ak):
        stub = fake_ak(em=_em_frame())
        A._fetch_ohlcv("600519", "2026-09-01", "2026-09-30")
        assert stub.calls[0][1]["symbol"] == "600519"


class TestAkshareMissing:
    def test_none_akshare_is_an_error(self, monkeypatch):
        monkeypatch.setattr(A, "ak", None)
        df, _, err = A._fetch_ohlcv("600519", "2026-09-01", "2026-09-30")
        assert df is None
        assert "akshare is not installed" in err


class TestGetStockData:
    def test_header_names_the_serving_source(self, fake_ak):
        fake_ak(em=ConnectionError("blocked"), sina=_sina_frame())
        out = A.get_stock_data("600519", "2026-09-01", "2026-09-30")
        assert "source:" in out
        assert "新浪" in out
        assert "volume 单位「手」" in out
        assert "2026-09-30" in out

    def test_failure_surfaces_all_reasons(self, fake_ak):
        fake_ak(em=ConnectionError("a"), sina=ConnectionError("b"), tx=ConnectionError("c"))
        out = A.get_stock_data("600519", "2026-09-01", "2026-09-30")
        assert "all OHLCV sources failed" in out


def _long_sina_frame(days: int = 200):
    """造一段足够算 MA60 的上升序列。"""
    dates = pd.bdate_range("2026-01-01", periods=days)
    closes = [100.0 + i for i in range(days)]
    return pd.DataFrame(
        {
            "date": [d.date() for d in dates],
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [10000.0 + i for i in range(days)],
            "amount": [1.0e8 + i for i in range(days)],
        }
    )


class TestGetTechnicalIndicators:
    def test_bundle_has_ma_band_and_signal(self, fake_ak):
        fake_ak(em=ConnectionError("blocked"), sina=_long_sina_frame())
        out = A.get_technical_indicators("600519", "2026-08-01", "2026-09-30")

        for col in ("ma5", "ma10", "ma20", "ma60"):
            assert col in out
        assert "信号解读" in out
        assert "source:" in out
        assert "均线多头排列" in out  # 单调上升序列必然是多头排列

    def test_rejects_reversed_range(self, fake_ak):
        fake_ak(em=_em_frame())
        out = A.get_technical_indicators("600519", "2026-09-30", "2026-09-01")
        assert "later than" in out

    def test_rejects_unparseable_range(self, fake_ak):
        fake_ak(em=_em_frame())
        out = A.get_technical_indicators("600519", "nope", "2026-09-30")
        assert "invalid date range" in out

    def test_no_trading_days_in_window(self, fake_ak):
        fake_ak(em=ConnectionError("x"), sina=_long_sina_frame())
        out = A.get_technical_indicators("600519", "2030-01-01", "2030-02-01")
        assert "no trading days" in out

    def test_insufficient_history(self, fake_ak):
        fake_ak(em=ConnectionError("x"), sina=_long_sina_frame(days=3))
        out = A.get_technical_indicators("600519", "2026-08-01", "2026-09-30")
        assert "insufficient history" in out


class TestIndicatorsUseFallback:
    def test_get_indicators_survives_eastmoney_outage(self, fake_ak):
        fake_ak(em=ConnectionError("blocked"), sina=_long_sina_frame())
        out = A.get_indicators("600519", "rsi", "2026-09-30")
        assert "RSI (14)" in out
        assert "ERROR" not in out

    def test_unknown_indicator_short_circuits(self, fake_ak):
        # 指标名拼错时不该浪费一次网络往返
        stub = fake_ak(em=_em_frame())
        out = A.get_indicators("600519", "not_an_indicator", "2026-09-30")
        assert "Unknown indicator" in out
        assert stub.calls == []

    def test_lookahead_not_included(self, fake_ak):
        # curr_date 之后的 K 线不能进指标计算
        fake_ak(em=ConnectionError("x"), sina=_long_sina_frame())
        out = A.get_indicators("600519", "boll", "2026-05-15")
        assert "as of 2026-05-15" in out


class TestNoMarketDataErrorContract:
    def test_unknown_source_raises_typed_error(self, fake_ak):
        fake_ak()
        with pytest.raises(NoMarketDataError):
            A._fetch_raw("nasdaq", "600519", "20260901", "20260930", "qfq")
