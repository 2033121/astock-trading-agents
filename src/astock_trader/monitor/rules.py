"""监控规则 —— 把"什么算异动"写成可配置的声明，而不是散落在代码里的 if。

规则是普通的 dict，可以直接写在 ``~/.astock_trader/monitor.json`` 里::

    {"rules": [
      {"name": "涨超5%", "type": "change_pct", "direction": "up",   "threshold": 5,   "level": "notice"},
      {"name": "跌超5%", "type": "change_pct", "direction": "down", "threshold": 5,   "level": "warning"},
      {"name": "触及涨停", "type": "limit_move", "direction": "up",  "level": "critical"},
      {"name": "换手异动", "type": "turnover",  "threshold": 10,     "level": "info"}
    ]}

新增一种规则只需写一个 ``_eval_<type>`` 函数并加进 :data:`RULE_TYPES`，
不需要改动引擎。规则函数是**纯函数**：只读 quote dict，返回
``(message, metrics)`` 或 ``None``（未命中），因此可以脱离网络单测。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from .events import MonitorEvent

logger = logging.getLogger(__name__)

__all__ = ["Rule", "RuleSet", "evaluate", "RULE_TYPES", "load_rules"]


def _num(quote: dict[str, Any], key: str) -> float | None:
    value = quote.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: float | None, decimals: int = 2, suffix: str = "") -> str:
    return "N/A" if value is None else f"{value:,.{decimals}f}{suffix}"


# ---------------------------------------------------------------------------
# 规则实现：quote -> (message, metrics) | None
# ---------------------------------------------------------------------------


def _eval_change_pct(rule: dict[str, Any], quote: dict[str, Any]) -> tuple[str, dict] | None:
    pct = _num(quote, "change_pct")
    if pct is None:
        return None
    threshold = float(rule.get("threshold", 5.0))
    direction = rule.get("direction", "any")
    if direction == "up" and pct < threshold:
        return None
    if direction == "down" and pct > -threshold:
        return None
    if direction == "any" and abs(pct) < threshold:
        return None
    arrow = "涨" if pct >= 0 else "跌"
    message = f"{arrow}幅 {pct:+.2f}%（阈值 {threshold:g}%），现价 {_fmt(_num(quote, 'price'))}"
    return message, {"change_pct": pct, "price": _num(quote, "price"), "threshold": threshold}


def _eval_price(rule: dict[str, Any], quote: dict[str, Any]) -> tuple[str, dict] | None:
    price = _num(quote, "price")
    target = rule.get("value")
    if price is None or target is None:
        return None
    op = rule.get("op", ">=")
    target = float(target)
    hit = {
        ">": price > target,
        ">=": price >= target,
        "<": price < target,
        "<=": price <= target,
    }.get(op, False)
    if not hit:
        return None
    return f"现价 {_fmt(price)} {op} {_fmt(target)}", {"price": price, "op": op, "value": target}


def _eval_limit_move(rule: dict[str, Any], quote: dict[str, Any]) -> tuple[str, dict] | None:
    price = _num(quote, "price")
    limit_up = _num(quote, "limit_up")
    limit_down = _num(quote, "limit_down")
    direction = rule.get("direction", "any")
    tolerance = float(rule.get("tolerance_pct", 0.2)) / 100.0

    if direction in ("up", "any") and price and limit_up and price >= limit_up * (1 - tolerance):
        return f"触及涨停 {_fmt(limit_up)}（现价 {_fmt(price)}）", {"price": price, "limit_up": limit_up}
    if direction in ("down", "any") and price and limit_down and price <= limit_down * (1 + tolerance):
        return f"触及跌停 {_fmt(limit_down)}（现价 {_fmt(price)}）", {"price": price, "limit_down": limit_down}
    return None


def _eval_near_limit(rule: dict[str, Any], quote: dict[str, Any]) -> tuple[str, dict] | None:
    price = _num(quote, "price")
    limit_up = _num(quote, "limit_up")
    limit_down = _num(quote, "limit_down")
    within = float(rule.get("within_pct", 1.0))
    direction = rule.get("direction", "any")

    if direction in ("up", "any") and price and limit_up:
        gap = (limit_up - price) / limit_up * 100
        if 0 <= gap <= within:
            return f"距涨停仅 {gap:.2f}%（现价 {_fmt(price)} / 涨停 {_fmt(limit_up)}）", {
                "price": price,
                "limit_up": limit_up,
                "gap_pct": round(gap, 2),
            }
    if direction in ("down", "any") and price and limit_down:
        gap = (price - limit_down) / limit_down * 100
        if 0 <= gap <= within:
            return f"距跌停仅 {gap:.2f}%（现价 {_fmt(price)} / 跌停 {_fmt(limit_down)}）", {
                "price": price,
                "limit_down": limit_down,
                "gap_pct": round(gap, 2),
            }
    return None


def _eval_turnover(rule: dict[str, Any], quote: dict[str, Any]) -> tuple[str, dict] | None:
    turnover = _num(quote, "turnover_pct")
    threshold = float(rule.get("threshold", 10.0))
    if turnover is None or turnover < threshold:
        return None
    return f"换手率 {turnover:.2f}%（阈值 {threshold:g}%）", {"turnover_pct": turnover, "threshold": threshold}


def _eval_amount(rule: dict[str, Any], quote: dict[str, Any]) -> tuple[str, dict] | None:
    amount = _num(quote, "amount_wan")
    threshold = float(rule.get("threshold_wan", 100000.0))
    if amount is None or amount < threshold:
        return None
    return f"成交额 {amount / 10000:.2f} 亿（阈值 {threshold / 10000:g} 亿）", {
        "amount_wan": amount,
        "threshold_wan": threshold,
    }


def _eval_volume_ratio(rule: dict[str, Any], quote: dict[str, Any]) -> tuple[str, dict] | None:
    """量比 —— 腾讯行情独有字段，衡量当下成交相对近期均量的放大倍数。"""
    ratio = _num(quote, "volume_ratio")
    threshold = float(rule.get("threshold", 2.0))
    if ratio is None or ratio < threshold:
        return None
    return f"量比 {ratio:.2f}（阈值 {threshold:g}），成交明显放大", {
        "volume_ratio": ratio,
        "threshold": threshold,
    }


def _eval_amplitude(rule: dict[str, Any], quote: dict[str, Any]) -> tuple[str, dict] | None:
    amplitude = _num(quote, "amplitude_pct")
    threshold = float(rule.get("threshold", 5.0))
    if amplitude is None or amplitude < threshold:
        return None
    return f"振幅 {amplitude:.2f}%（阈值 {threshold:g}%）", {
        "amplitude_pct": amplitude,
        "threshold": threshold,
    }


RULE_TYPES: dict[str, Callable[[dict[str, Any], dict[str, Any]], tuple[str, dict] | None]] = {
    "change_pct": _eval_change_pct,
    "price": _eval_price,
    "limit_move": _eval_limit_move,
    "near_limit": _eval_near_limit,
    "turnover": _eval_turnover,
    "amount": _eval_amount,
    "volume_ratio": _eval_volume_ratio,
    "amplitude": _eval_amplitude,
}


class Rule:
    """一条已校验的规则。"""

    def __init__(self, spec: dict[str, Any]):
        rule_type = str(spec.get("type", "")).strip()
        if rule_type not in RULE_TYPES:
            raise ValueError(f"未知规则类型 {rule_type!r}；可用：{sorted(RULE_TYPES)}")
        self.type = rule_type
        self.name = str(spec.get("name") or rule_type)
        self.level = str(spec.get("level", "notice")).lower()
        self.spec = spec

    def evaluate(self, quote: dict[str, Any]) -> MonitorEvent | None:
        """对单条行情求值；命中则返回事件，否则 ``None``。"""
        hit = RULE_TYPES[self.type](self.spec, quote)
        if hit is None:
            return None
        message, metrics = hit
        return MonitorEvent(
            symbol=str(quote.get("symbol", "")),
            name=str(quote.get("name", "")),
            rule=self.name,
            level=self.level,
            message=message,
            metrics=metrics,
        )


class RuleSet:
    """一组规则的容器，支持按标的覆盖。"""

    def __init__(self, rules: list[Rule], per_symbol: dict[str, list[Rule]] | None = None):
        self.rules = rules
        self.per_symbol = per_symbol or {}

    def rules_for(self, symbol: str) -> list[Rule]:
        """取该标的适用的规则：全局规则 + 该标的的专属规则。"""
        return self.rules + self.per_symbol.get(symbol, [])

    def __len__(self) -> int:
        return len(self.rules) + sum(len(v) for v in self.per_symbol.values())


def evaluate(ruleset: RuleSet, quotes: list[dict[str, Any]]) -> list[MonitorEvent]:
    """对一批行情跑一遍规则，返回命中事件（可能为空）。"""
    events: list[MonitorEvent] = []
    for quote in quotes:
        for rule in ruleset.rules_for(str(quote.get("symbol", ""))):
            try:
                event = rule.evaluate(quote)
            except Exception as exc:  # 单条规则写错不该拖垮整个监控循环
                logger.warning("规则 %s 求值失败：%s", rule.name, exc)
                continue
            if event is not None:
                events.append(event)
    return events


# ---------------------------------------------------------------------------
# 默认规则与加载
# ---------------------------------------------------------------------------

DEFAULT_RULES: list[dict[str, Any]] = [
    {"name": "涨超5%", "type": "change_pct", "direction": "up", "threshold": 5, "level": "notice"},
    {"name": "跌超5%", "type": "change_pct", "direction": "down", "threshold": 5, "level": "warning"},
    {"name": "触及涨停", "type": "limit_move", "direction": "up", "level": "critical"},
    {"name": "触及跌停", "type": "limit_move", "direction": "down", "level": "critical"},
    {"name": "放量异动", "type": "volume_ratio", "threshold": 2.5, "level": "notice"},
    {"name": "换手异动", "type": "turnover", "threshold": 10, "level": "info"},
]


def load_rules(spec: dict[str, Any] | None = None) -> RuleSet:
    """从配置 dict 构建 :class:`RuleSet`；缺省用 :data:`DEFAULT_RULES`。

    期望结构::

        {"rules": [ {...}, ... ],
         "per_symbol": {"sh600519": [ {...} ]}}
    """
    spec = spec or {}
    raw_rules = spec.get("rules") or DEFAULT_RULES
    rules = [Rule(r) for r in raw_rules]

    per_symbol: dict[str, list[Rule]] = {}
    for symbol, specs in (spec.get("per_symbol") or {}).items():
        per_symbol[str(symbol)] = [Rule(r) for r in specs]

    return RuleSet(rules, per_symbol)
