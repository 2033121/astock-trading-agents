"""数据源错误层级与路由换源行为。

改动前的真实缺陷：数据源「软失败」时返回 ``"[ERROR] ..."`` 字符串，而
``route_to_vendor`` 把任何返回值都当成成功直接返回。于是**第一个数据源一报错，
整条 fallback 链就作废** —— 妙想配额用尽时，链上的 Tushare / 东方财富 / akshare
根本不会被尝试，Agent 拿到的是一句错误文本，被当成「数据」。

现在换源有两个触发条件：抛异常（按类型分类日志级别），或返回 ``[ERROR]`` 串。
"""

from unittest.mock import MagicMock, patch

import pytest

from astock_trader.dataflows import mx_data, tushare_data
from astock_trader.dataflows.errors import (
    NoMarketDataError,
    VendorError,
    VendorNotConfiguredError,
    VendorRateLimitError,
    is_failure_payload,
)
from astock_trader.dataflows.interface import VENDOR_METHODS, route_to_vendor

# ────────────────────────────────────────────────────────────────
#  is_failure_payload
# ────────────────────────────────────────────────────────────────


class TestIsFailurePayload:
    """软失败标记的识别边界。"""

    def test_plain_error_marker(self):
        assert is_failure_payload("[ERROR] 妙想 API 调用次数已达上限。") is True

    def test_embedded_marker(self):
        """akshare 的写法是「前缀 + [ERROR]」，不是以标记开头。"""
        assert is_failure_payload("get_stock_data(600519): [ERROR] akshare is not installed") is True

    def test_normal_payload_is_not_a_failure(self):
        assert is_failure_payload("## 600519 日线行情\n\n| 日期 | 收盘 |") is False

    def test_non_string_payloads_are_not_failures(self):
        assert is_failure_payload(None) is False
        assert is_failure_payload({"rows": []}) is False
        assert is_failure_payload(0) is False

    def test_informational_no_data_is_not_a_failure(self):
        """「查到了但确实没有数据」是信息性返回，不是数据源故障 —— 边界写清楚。"""
        assert is_failure_payload("get_fundamentals(600519): No fundamental data found.") is False


# ────────────────────────────────────────────────────────────────
#  路由换源
# ────────────────────────────────────────────────────────────────


def _mock_vendors(behaviours: dict[str, object], method: str = "get_fundamentals"):
    """构造一个按 vendor 名给出行为的 ``_import_vendor_module`` 替身。"""

    def _import(vendor):
        behaviour = behaviours[vendor]
        mod = MagicMock()
        func_name = VENDOR_METHODS[method][vendor]
        func = getattr(mod, func_name)
        if isinstance(behaviour, Exception):
            func.side_effect = behaviour
        else:
            func.return_value = behaviour
        return mod

    return _import


class TestRouterFallsBackOnSoftFailure:
    """软失败串必须触发换源，而不是被当成结果返回。"""

    def test_error_payload_falls_through_to_next_vendor(self):
        behaviours = {
            "tushare": "[ERROR] Tushare API 错误 (fina_indicator): 积分不足",
            "mx": "妙想返回的正常基本面数据",
            "akshare": "不该被用到",
        }
        with patch("astock_trader.dataflows.interface._import_vendor_module", side_effect=_mock_vendors(behaviours)):
            assert route_to_vendor("get_fundamentals", "600519") == "妙想返回的正常基本面数据"

    def test_all_payloads_failing_reports_last_reason(self):
        behaviours = {
            "tushare": "[ERROR] 甲数据源挂了",
            "mx": "[ERROR] 乙数据源也挂了",
            "akshare": "[ERROR] 丙数据源还是挂了",
        }
        with patch("astock_trader.dataflows.interface._import_vendor_module", side_effect=_mock_vendors(behaviours)):
            result = route_to_vendor("get_fundamentals", "600519")
        assert "[ERROR]" in result
        assert "丙数据源还是挂了" in result

    def test_single_vendor_failure_names_that_vendor(self):
        behaviours = {"akshare": "[ERROR] akshare is not installed"}
        with patch(
            "astock_trader.dataflows.interface._import_vendor_module",
            side_effect=_mock_vendors(behaviours, method="get_stock_data"),
        ):
            result = route_to_vendor("get_stock_data", "600519", "2025-01-01", "2025-02-01")
        assert "[ERROR]" in result
        assert "akshare" in result

    def test_successful_payload_is_returned_as_is(self):
        behaviours = {"akshare": "正常行情数据"}
        with patch(
            "astock_trader.dataflows.interface._import_vendor_module",
            side_effect=_mock_vendors(behaviours, method="get_stock_data"),
        ):
            assert route_to_vendor("get_stock_data", "600519") == "正常行情数据"


class TestRouterHandlesTypedErrors:
    """带类型的异常按行为换源，并给出合适的日志级别。"""

    @pytest.mark.parametrize(
        "exc",
        [
            VendorNotConfiguredError("缺少 MX_APIKEY"),
            VendorRateLimitError("配额用尽"),
            NoMarketDataError("600519", detail="空结果"),
            VendorError("网络不可达"),
            RuntimeError("意料之外的错误"),
        ],
    )
    def test_any_failure_moves_to_next_vendor(self, exc):
        behaviours = {"tushare": exc, "mx": "mx 的正常数据", "akshare": "不该被用到"}
        with patch("astock_trader.dataflows.interface._import_vendor_module", side_effect=_mock_vendors(behaviours)):
            assert route_to_vendor("get_fundamentals", "600519") == "mx 的正常数据"

    def test_not_configured_logs_at_debug_not_warning(self, caplog):
        """缺 key 是预期内的，不该刷 warning —— 否则真故障会被淹没。"""
        behaviours = {"tushare": VendorNotConfiguredError("缺少 TUSHARE_TOKEN"), "mx": "ok"}
        with (
            caplog.at_level("DEBUG", logger="astock_trader.dataflows.interface"),
            patch(
                "astock_trader.dataflows.interface._import_vendor_module",
                side_effect=_mock_vendors(behaviours),
            ),
        ):
            route_to_vendor("get_fundamentals", "600519")

        tushare_records = [r for r in caplog.records if "tushare" in r.getMessage()]
        assert tushare_records, "应当留下一条关于 tushare 的日志"
        assert all(r.levelname == "DEBUG" for r in tushare_records)

    def test_rate_limit_logs_at_warning(self, caplog):
        behaviours = {"tushare": VendorRateLimitError("积分不足"), "mx": "ok"}
        with (
            caplog.at_level("DEBUG", logger="astock_trader.dataflows.interface"),
            patch(
                "astock_trader.dataflows.interface._import_vendor_module",
                side_effect=_mock_vendors(behaviours),
            ),
        ):
            route_to_vendor("get_fundamentals", "600519")

        assert any(r.levelname == "WARNING" and "tushare" in r.getMessage() for r in caplog.records)

    def test_vendor_not_configured_is_also_a_value_error(self):
        """保留 ValueError 兼容：历史调用点捕 ValueError 仍然有效。"""
        with pytest.raises(ValueError):
            raise VendorNotConfiguredError("x")

    def test_no_market_data_message_mentions_canonical_symbol(self):
        exc = NoMarketDataError("600519", canonical="600519.SH", detail="陈旧数据")
        assert "600519" in str(exc)
        assert "600519.SH" in str(exc)
        assert "陈旧数据" in str(exc)


class TestRouteToVendorUnchangedBehaviour:
    """这些是改动前就有的契约，必须保持。"""

    def test_unknown_method_returns_error(self):
        result = route_to_vendor("nonexistent_method")
        assert "[ERROR]" in result
        assert "nonexistent_method" in result

    def test_module_import_failure_falls_back(self):
        def _import(vendor):
            if vendor == "mx":
                return None
            mod = MagicMock()
            mod.get_news.return_value = f"{vendor}_news"
            return mod

        with patch("astock_trader.dataflows.interface._import_vendor_module", side_effect=_import):
            assert route_to_vendor("get_news", "600519") == "tushare_news"

    def test_missing_function_in_module_falls_back(self):
        def _import(vendor):
            mod = MagicMock(spec=[])  # 没有任何函数属性
            return mod

        with patch("astock_trader.dataflows.interface._import_vendor_module", side_effect=_import):
            result = route_to_vendor("get_news", "600519")
        assert "[ERROR]" in result


# ────────────────────────────────────────────────────────────────
#  各数据源产出的错误类型
# ────────────────────────────────────────────────────────────────


class TestMxErrorClassification:
    """妙想 API 状态码 → 错误类型。"""

    def test_success_passes_through(self):
        payload = {"status": 0, "data": 1}
        assert mx_data._ensure_ok(payload, "查询") == payload

    def test_quota_code_is_rate_limit(self):
        with pytest.raises(VendorRateLimitError):
            mx_data._ensure_ok({"status": 1, "code": 113, "message": "quota"}, "查询")

    def test_invalid_key_code_is_not_configured(self):
        with pytest.raises(VendorNotConfiguredError):
            mx_data._ensure_ok({"status": 1, "code": 114, "message": "bad key"}, "查询")

    def test_stringified_code_still_classified(self):
        """API 有时把 code 当字符串返回。"""
        with pytest.raises(VendorRateLimitError):
            mx_data._ensure_ok({"status": 1, "code": "113", "message": "quota"}, "查询")

    def test_other_failures_are_generic_vendor_errors(self):
        with pytest.raises(VendorError) as excinfo:
            mx_data._ensure_ok({"status": 9, "code": 500, "message": "boom"}, "估值查询")
        assert not isinstance(excinfo.value, (VendorRateLimitError, VendorNotConfiguredError))
        assert "估值查询" in str(excinfo.value)

    def test_missing_api_key_raises_not_configured(self, monkeypatch):
        monkeypatch.delenv("MX_APIKEY", raising=False)
        with pytest.raises(VendorNotConfiguredError):
            mx_data._headers()

    def test_transport_error_becomes_vendor_error(self, monkeypatch):
        monkeypatch.setenv("MX_APIKEY", "dummy")

        def _boom(**kwargs):
            raise mx_data.requests.exceptions.ConnectionError("no route")

        monkeypatch.setattr(mx_data.requests, "post", _boom)
        wrapped = mx_data._safe_call(lambda: mx_data.get_fundamentals("600519"))
        with pytest.raises(VendorError):
            wrapped()


class TestTushareErrorClassification:
    """Tushare 的错误分类。"""

    def test_missing_token_raises_not_configured(self, monkeypatch):
        monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
        with pytest.raises(VendorNotConfiguredError):
            tushare_data._get_token()

    @pytest.mark.parametrize("msg", ["积分不足", "每分钟最多访问该接口 200 次", "权限不足"])
    def test_rate_limit_hint_becomes_rate_limit_error(self, monkeypatch, msg):
        monkeypatch.setenv("TUSHARE_TOKEN", "dummy")
        response = MagicMock()
        response.json.return_value = {"code": -1, "msg": msg}
        monkeypatch.setattr(tushare_data.requests, "post", lambda *a, **k: response)

        with pytest.raises(VendorRateLimitError):
            tushare_data._call_api("fina_indicator")

    def test_other_api_error_becomes_vendor_error(self, monkeypatch):
        monkeypatch.setenv("TUSHARE_TOKEN", "dummy")
        response = MagicMock()
        response.json.return_value = {"code": -1, "msg": "接口不存在"}
        monkeypatch.setattr(tushare_data.requests, "post", lambda *a, **k: response)

        with pytest.raises(VendorError) as excinfo:
            tushare_data._call_api("nope")
        assert not isinstance(excinfo.value, VendorRateLimitError)

    def test_successful_call_returns_data(self, monkeypatch):
        monkeypatch.setenv("TUSHARE_TOKEN", "dummy")
        response = MagicMock()
        response.json.return_value = {"code": 0, "data": {"fields": [], "items": []}}
        monkeypatch.setattr(tushare_data.requests, "post", lambda *a, **k: response)

        assert tushare_data._call_api("daily_basic") == {"fields": [], "items": []}

    def test_transport_error_becomes_vendor_error(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise tushare_data.requests.exceptions.Timeout("slow")

        monkeypatch.setattr(tushare_data.requests, "post", _boom)
        wrapped = tushare_data._safe_call(lambda: tushare_data._call_api("daily_basic"))
        with pytest.raises(VendorError):
            wrapped()
