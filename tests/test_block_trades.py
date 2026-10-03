"""大宗交易（内部人活动代理指标）。

**为什么单独立一个文件**：这个工具从写下起就没成功过 —— 它调用的是
``ak.stock_dzjy_mingxi`` 和 ``ak.stock_dzjy_detail``，而**这两个函数在 akshare 里
根本不存在**（实测 ``module 'akshare' has no attribute 'stock_dzjy_mingxi'``）。
路由表还把它标给了 ``akshare`` 模块，而实现其实住在 ``eastmoney_news`` 里。

于是情绪分析师长期拿不到大宗数据，只在报告里写一句「数据源异常」—— 又一个
「静默降级成看起来正常的输出」的例子。

现在的实现走 ``ak.stock_dzjy_mrmx``（东财「大宗交易-每日明细」），并带时点门控。
"""

import datetime as dt

import pandas as pd
import pytest

from astock_trader.dataflows import eastmoney_news as EN
from astock_trader.dataflows.interface import VENDOR_METHODS

_DAY = "2026-09-30"


def _market_frame():
    """模拟东财「每日明细」：按区间返回**全市场**成交，需要自己按代码筛。"""
    return pd.DataFrame(
        {
            "序号": [1, 2, 3, 4],
            "交易日期": [dt.date(2026, 9, 28), dt.date(2026, 9, 29), dt.date(2026, 9, 30), dt.date(2026, 10, 8)],
            "证券代码": ["600519", "000155", "600519", "600519"],
            "证券简称": ["贵州茅台", "川能动力", "贵州茅台", "贵州茅台"],
            "收盘价": [1243.88, 10.70, 1258.62, 1260.0],
            "成交价": [1240.00, 10.55, 1255.00, 1261.0],
            "折溢率": [-0.31, -1.40, -0.29, 0.08],
            "成交量": [12.5, 300.0, 8.2, 5.0],
            "成交额": [15500.0, 3165.0, 10291.0, 6305.0],
            "买方营业部": ["机构专用", "某营业部", "机构专用", "机构专用"],
            "卖方营业部": ["某营业部", "机构专用", "某营业部", "某营业部"],
        }
    )


class _FakeAk:
    def __init__(self, payload):
        self._payload = payload
        self.calls: list[dict] = []

    def stock_dzjy_mrmx(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


@pytest.fixture
def fake_ak(monkeypatch):
    def _install(payload):
        stub = _FakeAk(payload)
        monkeypatch.setattr(EN, "ak", stub)
        return stub

    return _install


class TestRouting:
    def test_vendor_label_points_at_the_module_that_owns_it(self):
        # 实现住在 eastmoney_news，路由表却曾标成 akshare（那里没有这个函数）
        assert VENDOR_METHODS["get_insider_transactions"] == {"eastmoney": "get_insider_transactions"}


class TestSymbolFiltering:
    def test_only_the_requested_symbol_is_returned(self, fake_ak):
        fake_ak(_market_frame())
        out = EN.get_insider_transactions("600519", curr_date=_DAY)

        assert "600519" in out
        # 全市场里那条 000155 的记录不能混进来
        assert "000155" not in out

    def test_symbol_in_any_format_matches(self, fake_ak):
        fake_ak(_market_frame())
        for symbol in ("600519", "sh600519", "600519.SH"):
            assert "无大宗交易记录" not in EN.get_insider_transactions(symbol, curr_date=_DAY)

    def test_symbol_without_any_trade_gets_a_distinct_message(self, fake_ak):
        """「这只票没有成交」和「取数失败」必须是两句话。"""
        fake_ak(_market_frame())
        out = EN.get_insider_transactions("000001", curr_date=_DAY)

        assert "无大宗交易记录" in out
        assert "ERROR" not in out
        assert "全市场同期有成交" in out  # 明确说明不是数据源挂了


class TestPointInTime:
    def test_future_trades_are_dropped(self, fake_ak):
        """分析日是 9-30，那条 10-08 的成交当时不可知，必须剔除。"""
        fake_ak(_market_frame())
        out = EN.get_insider_transactions("600519", curr_date=_DAY)

        assert "2026-09-30" in out
        assert "2026-10-08" not in out

    def test_live_run_keeps_everything(self, fake_ak):
        # curr_date=None 表示实时运行，不做门控
        fake_ak(_market_frame())
        out = EN.get_insider_transactions("600519")
        assert "2026-10-08" in out

    def test_invalid_curr_date_is_rejected(self, fake_ak):
        stub = fake_ak(_market_frame())
        out = EN.get_insider_transactions("600519", curr_date="not-a-date")
        assert "invalid curr_date" in out
        assert stub.calls == []  # 不该白跑一次网络


class TestFailures:
    def test_akshare_error_is_surfaced(self, fake_ak):
        fake_ak(RuntimeError("eastmoney datacenter unreachable"))
        out = EN.get_insider_transactions("600519", curr_date=_DAY)
        assert "ERROR" in out
        assert "eastmoney datacenter unreachable" in out

    def test_empty_market_frame(self, fake_ak):
        fake_ak(pd.DataFrame())
        out = EN.get_insider_transactions("600519", curr_date=_DAY)
        assert "全市场在" in out and "无大宗交易记录" in out


class TestDateFormat:
    def test_window_is_sent_as_yyyymmdd(self, fake_ak):
        stub = fake_ak(_market_frame())
        EN.get_insider_transactions("600519", curr_date="2026-09-30")

        kwargs = stub.calls[0]
        assert kwargs["symbol"] == "A股"  # 东财该接口的取值是 'A股'，不是 '沪深A股'
        assert kwargs["end_date"] == "20260930"
        assert kwargs["start_date"] < kwargs["end_date"]

    def test_output_declares_units(self, fake_ak):
        fake_ak(_market_frame())
        out = EN.get_insider_transactions("600519", curr_date=_DAY)
        assert "万股" in out and "万元" in out
        assert "折溢率为负表示折价成交" in out
