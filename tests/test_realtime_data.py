"""实时行情源：代码归一化、腾讯字段解析、以及**历史日期门控**。

历史日期门控是这一层最重要的行为：实时快照是"此刻"的值，无法证明分析日当时
可知。它一旦被喂进 ``--date`` 历史回测就是前视偏差，所以必须硬拒绝，而不是
悄悄返回当天数据。
"""

from unittest.mock import MagicMock, patch

import pytest

from astock_trader.dataflows.errors import NoMarketDataError, VendorError
from astock_trader.dataflows.realtime_data import (
    get_realtime_quote,
    get_realtime_quotes_batch,
    parse_realtime_quote,
    to_prefixed_code,
)

# ────────────────────────────────────────────────────────────────
#  测试夹具：一条真实的腾讯行情记录（2026-09-30 收盘的贵州茅台）
# ────────────────────────────────────────────────────────────────

_TX_FIELDS = [
    "1",  # 0 未知
    "贵州茅台",  # 1 名称
    "600519",  # 2 代码
    "1258.62",  # 3 现价
    "1235.58",  # 4 昨收
    "1239.53",  # 5 今开
    "1258.62",  # 6 买一
    "1259.00",  # 7 卖一
    "100",  # 8
    "200",  # 9
    *([""] * 20),  # 10-29 买卖五档，测试用不到
    "20260930161458",  # 30 时间
    "23.04",  # 31 涨跌额
    "1.86",  # 32 涨跌幅
    "1268.00",  # 33 最高
    "1236.05",  # 34 最低
    "1258.62/38331/4797246636",  # 35 价/量/额
    "38331",  # 36 成交量（手）
    "479725",  # 37 成交额（万元）
    "0.31",  # 38 换手率
    "19.32",  # 39 PE
    "",  # 40
    "1268.00",  # 41
    "1236.05",  # 42
    "2.59",  # 43 振幅
    "15733.78",  # 44 流通市值
    "15733.78",  # 45 总市值（亿）
    "6.26",  # 46 PB
    "1359.14",  # 47 涨停价
    "1112.02",  # 48 跌停价
    "1.36",  # 49 量比
    "-29",  # 50 委差
    "1251.53",  # 51 均价
    "17.67",  # 52 市盈(动)
]

_TX_RAW = "~".join(_TX_FIELDS)


# ────────────────────────────────────────────────────────────────
#  to_prefixed_code
# ────────────────────────────────────────────────────────────────


class TestToPrefixedCode:
    """6 位代码 → 带交易所前缀的行情代码。"""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("600519", "sh600519"),
            ("688981", "sh688981"),  # 科创板
            ("000001", "sz000001"),
            ("300750", "sz300750"),  # 创业板
            ("002594", "sz002594"),  # 中小板
            ("430047", "bj430047"),  # 北交所
            ("830799", "bj830799"),
        ],
    )
    def test_prefix_by_board(self, raw, expected):
        assert to_prefixed_code(raw) == expected

    def test_already_prefixed_is_idempotent(self):
        assert to_prefixed_code("sh600519") == "sh600519"
        assert to_prefixed_code("SH600519") == "sh600519"

    def test_tushare_suffix_form(self):
        """兼容 Tushare 的 600519.SH 写法。"""
        assert to_prefixed_code("600519.SH") == "sh600519"


# ────────────────────────────────────────────────────────────────
#  parse_realtime_quote
# ────────────────────────────────────────────────────────────────


class TestParseRealtimeQuote:
    """腾讯字段下标解析。"""

    def test_parses_core_fields(self):
        quote = parse_realtime_quote("sh600519", _TX_RAW)
        assert quote is not None
        assert quote["name"] == "贵州茅台"
        assert quote["price"] == pytest.approx(1258.62)
        assert quote["prev_close"] == pytest.approx(1235.58)
        assert quote["change_pct"] == pytest.approx(1.86)
        assert quote["high"] == pytest.approx(1268.00)
        assert quote["low"] == pytest.approx(1236.05)

    def test_parses_extended_fields(self):
        quote = parse_realtime_quote("sh600519", _TX_RAW)
        assert quote["volume_ratio"] == pytest.approx(1.36)  # 量比，监控规则要用的字段
        assert quote["turnover_pct"] == pytest.approx(0.31)
        assert quote["amplitude_pct"] == pytest.approx(2.59)
        assert quote["limit_up"] == pytest.approx(1359.14)
        assert quote["limit_down"] == pytest.approx(1112.02)
        assert quote["source"] == "tencent"

    def test_limit_price_arithmetic_holds(self):
        """涨停价应当约等于昨收 ×1.1 —— 用一条真实记录交叉验证字段没串位。"""
        quote = parse_realtime_quote("sh600519", _TX_RAW)
        assert quote["limit_up"] == pytest.approx(quote["prev_close"] * 1.1, abs=0.05)

    def test_truncated_record_is_rejected(self):
        """字段不够的记录（指数、退市等）不应被当成有效行情。"""
        assert parse_realtime_quote("sh600519", "1~贵州茅台~600519~1258.62") is None

    def test_zero_price_is_rejected(self):
        """停牌时价格可能是 0，不能当成有效快照。"""
        fields = list(_TX_FIELDS)
        fields[3] = "0"
        assert parse_realtime_quote("sh600519", "~".join(fields)) is None


# ────────────────────────────────────────────────────────────────
#  历史日期门控
# ────────────────────────────────────────────────────────────────


class TestHistoricalDateGuard:
    """实时源只服务运行当天 —— 这是防前视偏差的第一道门。"""

    def test_historical_date_is_refused(self):
        with pytest.raises(VendorError, match="不能服务历史日期"):
            get_realtime_quotes_batch(["600519"], curr_date="2025-06-01")

    def test_today_is_allowed(self):
        from datetime import datetime

        today = datetime.now().strftime("%Y-%m-%d")
        with patch("astock_trader.dataflows.realtime_data._get", return_value=f'v_sh600519="{_TX_RAW}";'):
            quotes = get_realtime_quotes_batch(["600519"], curr_date=today)
        assert len(quotes) == 1

    def test_none_date_is_allowed(self):
        """不给日期（监控场景）视为"现在"，应当放行。"""
        with patch("astock_trader.dataflows.realtime_data._get", return_value=f'v_sh600519="{_TX_RAW}";'):
            quotes = get_realtime_quotes_batch(["600519"])
        assert len(quotes) == 1


# ────────────────────────────────────────────────────────────────
#  取数与兜底
# ────────────────────────────────────────────────────────────────


class TestFetchAndFallback:
    """腾讯主源、新浪兜底、全失败报错。"""

    def test_tencent_primary(self):
        with patch("astock_trader.dataflows.realtime_data._get", return_value=f'v_sh600519="{_TX_RAW}";'):
            quotes = get_realtime_quotes_batch(["600519"])
        assert quotes[0]["source"] == "tencent"
        assert quotes[0]["name"] == "贵州茅台"

    def test_sina_fallback_when_tencent_empty(self):
        sina_body = "贵州茅台,1239.53,1235.58,1258.62,1268.00,1236.05,0,0," + "38331" + ",4797246636" + ",," * 20
        sina_body += "2026-09-30,16:14:58,00"
        with patch(
            "astock_trader.dataflows.realtime_data._get",
            side_effect=['var hq_str_sh600519="";', f'var hq_str_sh600519="{sina_body}";'],
        ):
            quotes = get_realtime_quotes_batch(["600519"])
        assert quotes[0]["source"] == "sina"
        assert quotes[0]["price"] == pytest.approx(1258.62)
        assert quotes[0]["change_pct"] == pytest.approx(1.86, abs=0.01)

    def test_all_sources_empty_raises(self):
        with (
            patch("astock_trader.dataflows.realtime_data._get", return_value=""),
            pytest.raises(NoMarketDataError),
        ):
            get_realtime_quotes_batch(["600519"])

    def test_empty_symbol_list_raises(self):
        with pytest.raises(NoMarketDataError):
            get_realtime_quotes_batch([])

    def test_markdown_table_renders(self):
        with patch("astock_trader.dataflows.realtime_data._get", return_value=f'v_sh600519="{_TX_RAW}";'):
            table = get_realtime_quote("600519")
        assert "实时行情快照" in table
        assert "贵州茅台" in table
        assert "1,258.62" in table
        assert "量比" in table

    def test_http_request_failure_raises_vendor_error(self):
        import requests

        with (
            patch("astock_trader.dataflows.realtime_data.requests.get", side_effect=requests.Timeout("boom")),
            pytest.raises(VendorError, match="请求失败"),
        ):
            get_realtime_quotes_batch(["600519"])


# ────────────────────────────────────────────────────────────────
#  路由表接入
# ────────────────────────────────────────────────────────────────


class TestVendorRouting:
    def test_realtime_method_is_registered(self):
        from astock_trader.dataflows.interface import VENDOR_METHODS

        assert "get_realtime_quote" in VENDOR_METHODS
        assert VENDOR_METHODS["get_realtime_quote"] == {"realtime": "get_realtime_quote"}

    def test_routes_through_interface(self):
        mock_module = MagicMock()
        mock_module.get_realtime_quote.return_value = "MOCK_TABLE"
        from astock_trader.dataflows import interface

        with patch.object(interface, "_import_vendor_module", return_value=mock_module):
            result = interface.route_to_vendor("get_realtime_quote", "600519")
        assert result == "MOCK_TABLE"
