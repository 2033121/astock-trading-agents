"""工具封装与 vendor 实现的签名一致性。

**为什么单独立一个文件**：``get_indicators`` 的封装从首次提交起就是断的 ——
封装暴露 ``(symbol, start_date, end_date)``，而 vendor 实现要的是
``(symbol, indicator, curr_date, look_back_days)``。调用时抛
``unexpected keyword argument 'start_date'``，技术分析师**一次都没拿到过**
均线 / MACD / RSI / BOLL，而这件事在 600 多项测试里没有任何一条能发现。

这里做的是**结构性**检查，不跑网络：把每个工具真实路由到的 vendor 函数取出
来，逐个比对参数名 —— 封装传的每一个关键字，vendor 都必须接得住。
"""

import importlib
import inspect
import re
from typing import Any, get_args, get_type_hints

import pytest
from langgraph.prebuilt import InjectedState

from astock_trader.dataflows.interface import _VENDOR_MODULES, VENDOR_METHODS

_ROUTE_CALL = re.compile(r'route_to_vendor\(\s*"([^"]+)"')


def _resolved_hints(func: Any) -> dict[str, Any]:
    """解析出真实的注解对象。

    工具模块普遍带 ``from __future__ import annotations``，annotations 全是**字符串**，
    直接 ``get_args`` 拿到的是空元组 —— 必须经 ``get_type_hints(include_extras=True)``
    才能还原 ``Annotated[..., InjectedState(...)]``。
    """
    try:
        return get_type_hints(func, include_extras=True)
    except Exception:  # pragma: no cover - 解析不了就退化成「没有注入参数」
        return {}


def _is_injected(param: inspect.Parameter, hints: dict[str, Any]) -> bool:
    """该参数是不是 LangGraph 注入的（``Annotated[..., InjectedState(...)]``）。

    注入参数由运行时从图状态填，**不会**转发给 vendor —— 例如 ``trade_date``
    注入进来后会被换算成 ``curr_date`` 再传下去。比对签名时必须把它排除，
    否则会把正确的封装误判成参数不匹配。
    """
    annotation = hints.get(param.name, param.annotation)
    return any(isinstance(arg, InjectedState) for arg in get_args(annotation))


def _all_agent_tools() -> list[Any]:
    """收集各分析师默认工具集里的全部工具。"""
    from astock_trader.graph.setup import _get_default_tools

    tools: dict[str, Any] = {}
    for key in ("market", "social", "news", "fundamentals"):
        for tool in _get_default_tools(key):
            tools[tool.name] = tool
    return list(tools.values())


def _routed_method(tool: Any) -> str | None:
    """从工具源码里读出它路由到的 method 名。"""
    try:
        source = inspect.getsource(tool.func)
    except (OSError, TypeError):
        return None
    match = _ROUTE_CALL.search(source)
    return match.group(1) if match else None


def _vendor_function(method: str):
    """取 method 的首选 vendor 实现。"""
    vendors = VENDOR_METHODS.get(method)
    if not vendors:
        return None
    label, func_name = next(iter(vendors.items()))
    module_path = _VENDOR_MODULES.get(label)
    if module_path is None:
        return None
    module = importlib.import_module(module_path)
    return getattr(module, func_name, None)


def _kwargs_passed_by(tool: Any) -> set[str]:
    """工具转手传给 vendor 的关键字参数名（不含 LangGraph 注入的参数）。"""
    hints = _resolved_hints(tool.func)
    return {p.name for p in inspect.signature(tool.func).parameters.values() if not _is_injected(p, hints)}


_TOOLS = _all_agent_tools()


@pytest.mark.parametrize("tool", _TOOLS, ids=lambda t: t.name)
def test_tool_routes_to_a_known_method(tool):
    method = _routed_method(tool)
    assert method, f"{tool.name} 没有走 route_to_vendor —— 数据源无法 fallback"
    assert method in VENDOR_METHODS, f"{tool.name} 路由到未注册的 method {method!r}"


@pytest.mark.parametrize("tool", _TOOLS, ids=lambda t: t.name)
def test_vendor_accepts_every_keyword_the_tool_passes(tool):
    """核心回归：封装传的关键字，vendor 必须全接得住。

    这就是 ``get_indicators`` 那个 bug 的形状 —— ``start_date`` / ``end_date``
    对 vendor 而言是不存在的参数。
    """
    method = _routed_method(tool)
    if not method:
        pytest.skip("no route_to_vendor call")
    vendor = _vendor_function(method)
    if vendor is None:
        pytest.skip(f"vendor for {method!r} not importable")

    signature = inspect.signature(vendor)
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values()):
        pytest.skip("vendor accepts **kwargs, cannot check statically")

    accepted = set(signature.parameters)
    unknown = _kwargs_passed_by(tool) - accepted
    assert not unknown, (
        f"{tool.name} 会传 {sorted(unknown)} 给 {method}，但 vendor 只接受 {sorted(accepted)} —— 调用必然抛 TypeError"
    )


@pytest.mark.parametrize("tool", _TOOLS, ids=lambda t: t.name)
def test_required_vendor_params_are_supplied_by_the_tool(tool):
    """反向检查：vendor 的必填参数，工具得给得了。

    否则会变成「vendor 少传参数」的另一种断法，同样只在真正调用时才炸。
    """
    method = _routed_method(tool)
    if not method:
        pytest.skip("no route_to_vendor call")
    vendor = _vendor_function(method)
    if vendor is None:
        pytest.skip(f"vendor for {method!r} not importable")

    required = {
        p.name
        for p in inspect.signature(vendor).parameters.values()
        if p.default is inspect.Parameter.empty
        and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    missing = required - _kwargs_passed_by(tool)
    assert not missing, f"{tool.name} 没有提供 {method} 的必填参数 {sorted(missing)}"


class TestKnownRegression:
    """把那次事故的具体形状钉住，防止回退。"""

    def test_get_indicators_tool_exposes_indicator_and_curr_date(self):
        from astock_trader.agents.utils.core_stock_tools import get_indicators

        params = set(inspect.signature(get_indicators.func).parameters)
        assert {"symbol", "indicator", "curr_date"} <= params
        # 旧封装暴露的那两个参数在 vendor 侧根本不存在
        assert "start_date" not in params
        assert "end_date" not in params

    def test_technical_indicators_tool_matches_its_vendor(self):
        from astock_trader.agents.utils.technical_indicators_tools import get_technical_indicators

        params = set(inspect.signature(get_technical_indicators.func).parameters)
        assert {"symbol", "start_date", "end_date"} == params

    def test_call_succeeds_with_tool_arguments(self, monkeypatch):
        """真调一次：用工具暴露的参数名去调 vendor，不能出参数错误。"""
        import pandas as pd

        from astock_trader.dataflows import akshare_data as A

        captured: dict = {}

        class _Stub:
            def stock_zh_a_daily(self, **kwargs):
                captured.update(kwargs)
                dates = pd.bdate_range("2026-06-01", periods=120)
                closes = [100.0 + i for i in range(120)]
                return pd.DataFrame(
                    {
                        "date": [d.date() for d in dates],
                        "open": closes,
                        "high": closes,
                        "low": closes,
                        "close": closes,
                        "volume": [1000.0] * 120,
                        "amount": [1.0e7] * 120,
                    }
                )

            def stock_zh_a_hist(self, **kwargs):
                raise ConnectionError("eastmoney blocked")

            def stock_zh_a_hist_tx(self, **kwargs):
                raise ConnectionError("tencent blocked")

        monkeypatch.setattr(A, "ak", _Stub())

        from astock_trader.agents.utils.core_stock_tools import get_indicators

        out = get_indicators.func(symbol="600519", indicator="rsi", curr_date="2026-09-30")
        assert "RSI (14)" in out
        assert captured["symbol"] == "sh600519"
