"""GDELT 全球新闻源：时点门控、查询窗口、响应解析与限流处理。

全部用 mock 响应，不依赖外网 —— 一是测试要确定性，二是 GDELT 的 DOC API 对
**出口 IP** 有每 5 秒一次的硬限流，共享出口（代理/公司 NAT）下实测经常直接
429，把它写进测试会让 CI 随机变红。
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from astock_trader.dataflows.errors import NoMarketDataError, VendorError, VendorRateLimitError
from astock_trader.dataflows.gdelt_data import _gdelt_datetime, _shift_days, get_global_news


@pytest.fixture(autouse=True)
def _no_real_throttle(monkeypatch):
    """默认关掉真实节流。

    ``get_global_news`` 每次调用都会为了遵守 GDELT 的 5 秒限制而可能真的
    ``sleep``；测试里若不禁用，单测会平白慢上几十秒。需要验证节流本身的用例
    再把它调回 5 秒。
    """
    import astock_trader.dataflows.gdelt_data as mod

    monkeypatch.setattr(mod, "_MIN_INTERVAL_S", 0.0)
    monkeypatch.setattr(mod, "_last_call_at", 0.0)


_SAMPLE = {
    "articles": [
        {
            "url": "https://example.com/a",
            "title": "Fed holds rates steady",
            "seendate": "20260930T121500Z",
            "domain": "example.com",
            "language": "English",
            "sourcecountry": "United States",
        },
        {
            "url": "https://example.com/b",
            "title": "Oil supply disruption reported",
            "seendate": "20260929T080000Z",
            "domain": "news.example.org",
            "language": "English",
            "sourcecountry": "United Kingdom",
        },
    ]
}


def _resp(status=200, payload=None, text=None):
    resp = MagicMock()
    resp.status_code = status
    if payload is not None:
        resp.json.return_value = payload
    else:
        resp.json.side_effect = ValueError("not json")
    resp.text = text if text is not None else json.dumps(payload or {})
    return resp


# ────────────────────────────────────────────────────────────────
#  日期工具
# ────────────────────────────────────────────────────────────────


class TestDateHelpers:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("2026-09-30", "20260930000000"),
            ("20260930", "20260930000000"),
        ],
    )
    def test_start_of_day(self, raw, expected):
        assert _gdelt_datetime(raw) == expected

    def test_end_of_day(self):
        assert _gdelt_datetime("2026-09-30", end_of_day=True) == "20260930235959"

    def test_shift_days_crosses_month(self):
        assert _shift_days("2026-10-03", 7) == "20260926"

    def test_bad_date_raises(self):
        with pytest.raises(VendorError, match="yyyy-mm-dd"):
            _gdelt_datetime("2026/09/30")


# ────────────────────────────────────────────────────────────────
#  时点门控 —— 本模块最重要的行为
# ────────────────────────────────────────────────────────────────


class TestPointInTime:
    """查询窗口的上界必须钉死在分析日，不能看到分析日之后的报道。"""

    def test_enddatetime_pinned_to_analysis_date(self):
        with patch("astock_trader.dataflows.gdelt_data.requests.get", return_value=_resp(200, _SAMPLE)) as mock_get:
            get_global_news(curr_date="2026-09-30", look_back_days=7)
        params = mock_get.call_args.kwargs["params"]
        assert params["enddatetime"] == "20260930235959"
        assert params["startdatetime"] == "20260923000000"

    def test_window_bounds_do_not_overflow_analysis_date(self):
        with patch("astock_trader.dataflows.gdelt_data.requests.get", return_value=_resp(200, _SAMPLE)) as mock_get:
            get_global_news(curr_date="2026-09-30", look_back_days=1)
        params = mock_get.call_args.kwargs["params"]
        assert params["startdatetime"][:8] == "20260929"  # 前一天
        assert params["enddatetime"][:8] == "20260930"  # 分析日当天收尾

    def test_look_back_is_clamped_to_at_least_one_day(self):
        with patch("astock_trader.dataflows.gdelt_data.requests.get", return_value=_resp(200, _SAMPLE)) as mock_get:
            get_global_news(curr_date="2026-09-30", look_back_days=0)
        assert mock_get.call_args.kwargs["params"]["startdatetime"][:8] == "20260929"


# ────────────────────────────────────────────────────────────────
#  响应解析
# ────────────────────────────────────────────────────────────────


class TestParsing:
    def test_renders_markdown_with_key_fields(self):
        with patch("astock_trader.dataflows.gdelt_data.requests.get", return_value=_resp(200, _SAMPLE)):
            out = get_global_news(curr_date="2026-09-30")
        assert "GDELT 全球新闻" in out
        assert "Fed holds rates steady" in out
        assert "2026-09-30 12:15" in out  # seendate 被格式化成可读时间
        assert "example.com" in out
        assert "United States" in out
        assert "https://example.com/a" in out

    def test_limit_is_forwarded_and_capped(self):
        with patch("astock_trader.dataflows.gdelt_data.requests.get", return_value=_resp(200, _SAMPLE)) as mock_get:
            get_global_news(curr_date="2026-09-30", limit=999)
        assert mock_get.call_args.kwargs["params"]["maxrecords"] == 250  # GDELT 上限

    def test_custom_query_is_used(self):
        with patch("astock_trader.dataflows.gdelt_data.requests.get", return_value=_resp(200, _SAMPLE)) as mock_get:
            get_global_news(curr_date="2026-09-30", query="semiconductor export controls")
        assert mock_get.call_args.kwargs["params"]["query"] == "semiconductor export controls"

    def test_default_query_used_when_blank(self):
        with patch("astock_trader.dataflows.gdelt_data.requests.get", return_value=_resp(200, _SAMPLE)) as mock_get:
            get_global_news(curr_date="2026-09-30", query="   ")
        assert "A股" in mock_get.call_args.kwargs["params"]["query"]


# ────────────────────────────────────────────────────────────────
#  失败路径
# ────────────────────────────────────────────────────────────────


class TestFailureModes:
    """失败要抛出类型化错误，让路由层能按类型换源。"""

    def test_429_becomes_rate_limit_error(self):
        with (
            patch(
                "astock_trader.dataflows.gdelt_data.requests.get",
                return_value=_resp(429, text="Please limit requests"),
            ),
            pytest.raises(VendorRateLimitError),
        ):
            get_global_news(curr_date="2026-09-30")

    def test_other_http_error_becomes_vendor_error(self):
        with (
            patch("astock_trader.dataflows.gdelt_data.requests.get", return_value=_resp(503, text="oops")),
            pytest.raises(VendorError, match="HTTP 503"),
        ):
            get_global_news(curr_date="2026-09-30")

    def test_non_json_body_becomes_vendor_error(self):
        """查询非法时 GDELT 返回纯文本而不是 JSON。"""
        with (
            patch(
                "astock_trader.dataflows.gdelt_data.requests.get",
                return_value=_resp(200, text="<html>bad query</html>"),
            ),
            pytest.raises(VendorError, match="非 JSON"),
        ):
            get_global_news(curr_date="2026-09-30")

    def test_empty_result_becomes_no_market_data(self):
        with (
            patch("astock_trader.dataflows.gdelt_data.requests.get", return_value=_resp(200, {"articles": []})),
            pytest.raises(NoMarketDataError, match="索引"),
        ):
            get_global_news(curr_date="2020-01-01")

    def test_network_exception_becomes_vendor_error(self):
        import requests

        with (
            patch("astock_trader.dataflows.gdelt_data.requests.get", side_effect=requests.Timeout("boom")),
            pytest.raises(VendorError, match="请求失败"),
        ):
            get_global_news(curr_date="2026-09-30")


# ────────────────────────────────────────────────────────────────
#  节流
# ────────────────────────────────────────────────────────────────


class TestThrottle:
    """GDELT 每 5 秒只允许一次请求；连续调用必须被客户端的节流挡住。"""

    def test_second_call_waits(self, monkeypatch):
        import astock_trader.dataflows.gdelt_data as mod

        # 把节流调回真实值（autouse fixture 默认是 0）
        monkeypatch.setattr(mod, "_MIN_INTERVAL_S", 5.0)
        monkeypatch.setattr(mod, "_last_call_at", 0.0)
        sleeps: list[float] = []
        monkeypatch.setattr(mod.time, "sleep", lambda s: sleeps.append(s))

        with patch("astock_trader.dataflows.gdelt_data.requests.get", return_value=_resp(200, _SAMPLE)):
            get_global_news(curr_date="2026-09-30")  # 首次：无历史，不等待
            get_global_news(curr_date="2026-09-30")  # 紧随其后：应触发等待

        assert sleeps, "第二次调用应当触发节流等待"
        assert sleeps[0] > 0


# ────────────────────────────────────────────────────────────────
#  路由接入
# ────────────────────────────────────────────────────────────────


class TestRouting:
    def test_gdelt_registered_as_global_news_fallback(self):
        from astock_trader.dataflows.interface import VENDOR_METHODS

        assert VENDOR_METHODS["get_global_news"]["gdelt"] == "get_global_news"

    def test_module_mapping_present(self):
        from astock_trader.dataflows import interface

        assert interface._VENDOR_MODULES["gdelt"] == "astock_trader.dataflows.gdelt_data"
