"""Tests for astock_trader.dataflows.interface — vendor routing system."""

import pytest
from unittest.mock import MagicMock, patch

from astock_trader.dataflows.interface import (
    VENDOR_METHODS,
    route_to_vendor,
    list_available_methods,
    _import_vendor_module,
)
from astock_trader.dataflows.config import set_config, get_config


# ────────────────────────────────────────────────────────────────
#  Fixtures
# ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_config():
    """Each test starts with a clean config."""
    set_config({})
    yield
    set_config({})


@pytest.fixture(autouse=True)
def clear_module_cache():
    """Clear the vendor module cache between tests."""
    from astock_trader.dataflows import interface
    interface._module_cache.clear()
    yield
    interface._module_cache.clear()


# ────────────────────────────────────────────────────────────────
#  VENDOR_METHODS structure
# ────────────────────────────────────────────────────────────────

class TestVendorMethodsTable:
    """Tests for the VENDOR_METHODS routing table."""

    def test_core_methods_exist(self):
        """核心数据方法均在路由表中。"""
        assert "get_stock_data" in VENDOR_METHODS
        assert "get_indicators" in VENDOR_METHODS
        assert "get_fundamentals" in VENDOR_METHODS
        assert "get_news" in VENDOR_METHODS

    def test_stock_data_has_akshare_vendor(self):
        """get_stock_data 的 vendor 包含 akshare。"""
        assert "akshare" in VENDOR_METHODS["get_stock_data"]

    def test_news_has_multiple_vendors(self):
        """get_news 有多个 vendor（eastmoney + akshare fallback）。"""
        assert len(VENDOR_METHODS["get_news"]) >= 2

    def test_all_known_methods_present(self):
        """所有已知方法都在表中。"""
        expected = [
            "get_stock_data",
            "get_indicators",
            "get_fundamentals",
            "get_balance_sheet",
            "get_cashflow",
            "get_income_statement",
            "get_news",
            "get_global_news",
            "get_insider_transactions",
        ]
        for method in expected:
            assert method in VENDOR_METHODS, f"Missing method: {method}"


# ────────────────────────────────────────────────────────────────
#  route_to_vendor — dispatch
# ────────────────────────────────────────────────────────────────

class TestRouteToVendorDispatch:
    """Tests for route_to_vendor dispatching."""

    def test_unknown_method_returns_error(self):
        """未知方法返回错误字符串。"""
        result = route_to_vendor("nonexistent_method")
        assert "[ERROR]" in result
        assert "nonexistent_method" in result

    def test_dispatches_to_correct_function(self):
        """正确分发到 vendor 函数。"""
        mock_module = MagicMock()
        mock_module.get_stock_data.return_value = "stock_data_result"

        with patch(
            "astock_trader.dataflows.interface._import_vendor_module",
            return_value=mock_module,
        ):
            result = route_to_vendor("get_stock_data", "000001", "20250101", "20250601")
            assert result == "stock_data_result"
            mock_module.get_stock_data.assert_called_once_with(
                "000001", "20250101", "20250601"
            )

    def test_kwargs_forwarded(self):
        """关键字参数被正确转发。"""
        mock_module = MagicMock()
        mock_module.get_news.return_value = "news_result"

        with patch(
            "astock_trader.dataflows.interface._import_vendor_module",
            return_value=mock_module,
        ):
            result = route_to_vendor("get_news", "000001", count=5)
            assert result == "news_result"
            mock_module.get_news.assert_called_once_with("000001", count=5)


# ────────────────────────────────────────────────────────────────
#  route_to_vendor — vendor fallback
# ────────────────────────────────────────────────────────────────

class TestVendorFallback:
    """Tests for vendor fallback logic."""

    def test_fallback_when_primary_fails(self):
        """主 vendor 失败时回退到备用 vendor。"""
        call_count = {"n": 0}

        def mock_import(vendor):
            call_count["n"] += 1
            mod = MagicMock()
            if vendor in ("mx", "tushare", "eastmoney"):
                # Primary, secondary and tertiary fail
                mod.get_news.side_effect = RuntimeError(f"{vendor} down")
            elif vendor == "akshare":
                # Fallback succeeds
                mod.get_news.return_value = "akshare_news"
            return mod

        with patch(
            "astock_trader.dataflows.interface._import_vendor_module",
            side_effect=mock_import,
        ):
            result = route_to_vendor("get_news", "000001")
            assert result == "akshare_news"

    def test_all_vendors_fail_returns_error(self):
        """所有 vendor 都失败时返回错误字符串。"""
        def mock_import(vendor):
            mod = MagicMock()
            # Make all functions raise
            getattr(mod, VENDOR_METHODS["get_stock_data"][vendor]).side_effect = RuntimeError("fail")
            return mod

        with patch(
            "astock_trader.dataflows.interface._import_vendor_module",
            side_effect=mock_import,
        ):
            result = route_to_vendor("get_stock_data")
            assert "[ERROR]" in result

    def test_module_import_failure_falls_back(self):
        """vendor 模块导入失败时回退。"""
        def mock_import(vendor):
            if vendor == "eastmoney":
                return None  # Import failed
            mod = MagicMock()
            mod.get_news.return_value = "akshare_fallback"
            return mod

        with patch(
            "astock_trader.dataflows.interface._import_vendor_module",
            side_effect=mock_import,
        ):
            result = route_to_vendor("get_news", "000001")
            assert result == "akshare_fallback"


# ────────────────────────────────────────────────────────────────
#  route_to_vendor — config preferred vendor
# ────────────────────────────────────────────────────────────────

class TestPreferredVendor:
    """Tests for preferred vendor from config."""

    def test_preferred_vendor_used_first(self):
        """配置中的首选 vendor 优先使用。"""
        set_config({"data_vendor": "akshare"})

        mock_module = MagicMock()
        mock_module.get_news.return_value = "akshare_preferred"

        with patch(
            "astock_trader.dataflows.interface._import_vendor_module",
            return_value=mock_module,
        ):
            result = route_to_vendor("get_news", "000001")
            assert result == "akshare_preferred"

    def test_invalid_preferred_vendor_ignored(self):
        """无效的首选 vendor 被忽略，使用默认顺序。"""
        set_config({"data_vendor": "nonexistent_vendor"})

        mock_module = MagicMock()
        mock_module.get_stock_data.return_value = "default_vendor_result"

        with patch(
            "astock_trader.dataflows.interface._import_vendor_module",
            return_value=mock_module,
        ):
            result = route_to_vendor("get_stock_data")
            assert result == "default_vendor_result"


# ────────────────────────────────────────────────────────────────
#  _import_vendor_module
# ────────────────────────────────────────────────────────────────

class TestImportVendorModule:
    """Tests for _import_vendor_module()."""

    def test_unknown_vendor_returns_none(self):
        """未知 vendor 返回 None。"""
        result = _import_vendor_module("nonexistent_vendor")
        assert result is None

    def test_known_vendor_returns_module_or_none(self):
        """已知 vendor 返回模块或 None（取决于依赖是否安装）。"""
        # akshare module may or may not be installed
        result = _import_vendor_module("akshare")
        # Either a module or None (if akshare not installed)
        assert result is None or hasattr(result, "get_stock_data")

    def test_module_cached(self):
        """模块导入后被缓存。"""
        from astock_trader.dataflows import interface

        # Manually inject a mock into cache
        mock_mod = MagicMock()
        interface._module_cache["test_vendor"] = mock_mod

        result = _import_vendor_module("test_vendor")
        assert result is mock_mod


# ────────────────────────────────────────────────────────────────
#  list_available_methods
# ────────────────────────────────────────────────────────────────

class TestListAvailableMethods:
    """Tests for list_available_methods()."""

    def test_returns_dict(self):
        """返回字典类型。"""
        result = list_available_methods()
        assert isinstance(result, dict)

    def test_contains_known_methods(self):
        """结果包含已知方法键。"""
        result = list_available_methods()
        assert "get_stock_data" in result
        assert "get_news" in result

    def test_values_are_lists(self):
        """每个方法的值是一个 vendor 列表。"""
        result = list_available_methods()
        for method, vendors in result.items():
            assert isinstance(vendors, list)


# ────────────────────────────────────────────────────────────────
#  Config integration
# ────────────────────────────────────────────────────────────────

class TestConfigIntegration:
    """Tests for dataflows config get/set."""

    def test_set_and_get_config(self):
        """set_config 和 get_config 正常工作。"""
        set_config({"data_vendor": "akshare", "custom_key": "value"})
        cfg = get_config()
        assert cfg["data_vendor"] == "akshare"
        assert cfg["custom_key"] == "value"

    def test_set_none_resets(self):
        """set_config(None) 重置为空字典。"""
        set_config({"some_key": "some_value"})
        set_config(None)
        assert get_config() == {}

    def test_set_empty_dict_resets(self):
        """set_config({}) 重置为空字典。"""
        set_config({"key": "val"})
        set_config({})
        assert get_config() == {}
