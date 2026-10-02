"""监控层：规则求值、冷却去重、引擎循环、通知分发。

这一层被刻意设计成**不依赖网络也不依赖 LLM**：行情通过 ``quote_fn`` 注入，
通知通道是可替换的函数表，所以整层可以在毫秒级跑完，不需要起服务。
"""

from __future__ import annotations

import time
from datetime import datetime

import pytest

from astock_trader.monitor.engine import WatchEngine, is_a_share_session
from astock_trader.monitor.events import LEVEL_ORDER, MonitorEvent, event_from_dict
from astock_trader.monitor.notify import Notifier, build_notifier
from astock_trader.monitor.rules import Rule, evaluate, load_rules
from astock_trader.monitor.store import EventStore

# ────────────────────────────────────────────────────────────────
#  测试夹具
# ────────────────────────────────────────────────────────────────


def make_quote(**overrides) -> dict:
    """一条默认"平平无奇"的行情，测试里按需覆盖个别字段。"""
    quote = {
        "symbol": "sh600519",
        "code": "600519",
        "name": "贵州茅台",
        "price": 1258.62,
        "prev_close": 1235.58,
        "open": 1239.53,
        "high": 1268.00,
        "low": 1236.05,
        "change": 23.04,
        "change_pct": 1.86,
        "volume_lots": 38331.0,
        "amount_wan": 479725.0,
        "turnover_pct": 0.31,
        "volume_ratio": 1.36,
        "amplitude_pct": 2.59,
        "pe": 19.32,
        "pb": 6.26,
        "limit_up": 1359.14,
        "limit_down": 1112.02,
        "time": "20260930161458",
        "source": "tencent",
    }
    quote.update(overrides)
    return quote


# ────────────────────────────────────────────────────────────────
#  规则求值
# ────────────────────────────────────────────────────────────────


class TestRuleTypes:
    """每种规则类型的命中/不命中边界。"""

    def test_change_pct_up_hits_above_threshold(self):
        rule = Rule({"name": "涨超5%", "type": "change_pct", "direction": "up", "threshold": 5})
        assert rule.evaluate(make_quote(change_pct=5.01)) is not None
        assert rule.evaluate(make_quote(change_pct=4.99)) is None

    def test_change_pct_down_only_fires_on_falls(self):
        rule = Rule({"name": "跌超5%", "type": "change_pct", "direction": "down", "threshold": 5})
        assert rule.evaluate(make_quote(change_pct=-5.5)) is not None
        assert rule.evaluate(make_quote(change_pct=5.5)) is None  # 大涨不该触发"跌超"

    def test_change_pct_any_uses_absolute_value(self):
        rule = Rule({"name": "异动", "type": "change_pct", "direction": "any", "threshold": 5})
        assert rule.evaluate(make_quote(change_pct=-6.0)) is not None
        assert rule.evaluate(make_quote(change_pct=6.0)) is not None

    @pytest.mark.parametrize(
        ("op", "value", "price", "expected"),
        [
            ("<", 2000, 1258.62, True),
            ("<", 1000, 1258.62, False),
            (">=", 1258.62, 1258.62, True),
            ("<=", 1000, 1258.62, False),
        ],
    )
    def test_price_operators(self, op, value, price, expected):
        rule = Rule({"name": "价位", "type": "price", "op": op, "value": value})
        assert (rule.evaluate(make_quote(price=price)) is not None) is expected

    def test_limit_move_up(self):
        rule = Rule({"name": "触及涨停", "type": "limit_move", "direction": "up"})
        assert rule.evaluate(make_quote(price=1359.14)) is not None
        assert rule.evaluate(make_quote(price=1350.0)) is None  # 距涨停尚远

    def test_limit_move_down(self):
        rule = Rule({"name": "触及跌停", "type": "limit_move", "direction": "down"})
        assert rule.evaluate(make_quote(price=1112.02)) is not None

    def test_limit_move_tolerance(self):
        """容差内的"准涨停"也算命中（成交价常差一分钱）。"""
        rule = Rule({"name": "触及涨停", "type": "limit_move", "direction": "up", "tolerance_pct": 0.2})
        assert rule.evaluate(make_quote(price=1358.0)) is not None

    def test_near_limit_reports_gap(self):
        rule = Rule({"name": "逼近涨停", "type": "near_limit", "direction": "up", "within_pct": 1.0})
        event = rule.evaluate(make_quote(price=1355.0))
        assert event is not None
        assert "距涨停" in event.message

    def test_turnover_threshold(self):
        rule = Rule({"name": "换手异动", "type": "turnover", "threshold": 10})
        assert rule.evaluate(make_quote(turnover_pct=12.5)) is not None
        assert rule.evaluate(make_quote(turnover_pct=0.31)) is None

    def test_volume_ratio_threshold(self):
        """量比是腾讯独有字段；缺失时规则应当安静地不命中，而不是报错。"""
        rule = Rule({"name": "放量", "type": "volume_ratio", "threshold": 2.0})
        assert rule.evaluate(make_quote(volume_ratio=3.1)) is not None
        assert rule.evaluate(make_quote(volume_ratio=1.36)) is None
        assert rule.evaluate(make_quote(volume_ratio=None)) is None

    def test_amplitude_threshold(self):
        rule = Rule({"name": "振幅", "type": "amplitude", "threshold": 5})
        assert rule.evaluate(make_quote(amplitude_pct=7.2)) is not None

    def test_amount_threshold_uses_wan(self):
        rule = Rule({"name": "大额", "type": "amount", "threshold_wan": 100000})
        assert rule.evaluate(make_quote(amount_wan=479725.0)) is not None
        assert rule.evaluate(make_quote(amount_wan=50000.0)) is None

    def test_missing_field_does_not_crash(self):
        """缺字段的行情（例如新浪兜底缺量比）不应让规则抛异常。"""
        rule = Rule({"name": "放量", "type": "volume_ratio", "threshold": 2.0})
        assert rule.evaluate({"symbol": "sh600519", "name": "X"}) is None

    def test_unknown_rule_type_is_rejected_at_construction(self):
        with pytest.raises(ValueError, match="未知规则类型"):
            Rule({"name": "x", "type": "no_such_rule"})


class TestRuleSet:
    def test_per_symbol_rules_apply_only_to_that_symbol(self):
        ruleset = load_rules(
            {
                "rules": [{"name": "涨超5%", "type": "change_pct", "direction": "up", "threshold": 5}],
                "per_symbol": {
                    "sh600519": [{"name": "任何涨幅", "type": "change_pct", "direction": "up", "threshold": 0.1}]
                },
            }
        )
        events = evaluate(ruleset, [make_quote(symbol="sh600519", change_pct=1.86)])
        names = {e.rule for e in events}
        assert names == {"任何涨幅"}  # 全局的 5% 没到，专属的 0.1% 到了

        other = evaluate(ruleset, [make_quote(symbol="sz000001", change_pct=1.86)])
        assert other == []  # 专属规则不作用于别的标的

    def test_default_rules_load_when_spec_empty(self):
        ruleset = load_rules(None)
        assert len(ruleset) >= 4

    def test_broken_rule_does_not_abort_others(self, monkeypatch):
        """单条规则写错不该拖垮整批求值。"""
        ruleset = load_rules(
            {"rules": [{"name": "涨超0.1%", "type": "change_pct", "direction": "up", "threshold": 0.1}]}
        )

        def boom(_spec, _quote):
            raise RuntimeError("坏了")

        monkeypatch.setitem(
            __import__("astock_trader.monitor.rules", fromlist=["RULE_TYPES"]).RULE_TYPES, "change_pct", boom
        )
        assert evaluate(ruleset, [make_quote()]) == []


# ────────────────────────────────────────────────────────────────
#  事件模型
# ────────────────────────────────────────────────────────────────


class TestMonitorEvent:
    def test_severity_ordering(self):
        low = MonitorEvent("sh600519", "贵州茅台", "r", "info", "m")
        high = MonitorEvent("sh600519", "贵州茅台", "r", "critical", "m")
        assert low.severity < high.severity
        assert LEVEL_ORDER["critical"] > LEVEL_ORDER["warning"] > LEVEL_ORDER["notice"] > LEVEL_ORDER["info"]

    def test_json_roundtrip_preserves_chinese(self):
        event = MonitorEvent("sh600519", "贵州茅台", "涨超5%", "notice", "涨幅 +6.00%")
        restored = event_from_dict(__import__("json").loads(event.to_json()))
        assert restored.name == "贵州茅台"
        assert restored.rule == "涨超5%"
        assert restored.message == "涨幅 +6.00%"

    def test_event_from_dict_ignores_unknown_keys(self):
        """旧台账里多出来的字段不该让读取炸掉。"""
        restored = event_from_dict(
            {"symbol": "s", "name": "n", "rule": "r", "level": "info", "message": "m", "future": 1}
        )
        assert restored.symbol == "s"


# ────────────────────────────────────────────────────────────────
#  台账与冷却
# ────────────────────────────────────────────────────────────────


class TestEventStore:
    def test_append_and_recent(self, tmp_path):
        store = EventStore(tmp_path)
        store.append(MonitorEvent("sh600519", "贵州茅台", "涨超5%", "notice", "m1"))
        store.append(MonitorEvent("sz000001", "平安银行", "跌超5%", "warning", "m2"))
        recent = store.recent()
        assert len(recent) == 2
        assert recent[0].symbol == "sh600519"
        assert recent[1].name == "平安银行"

    def test_recent_on_missing_file_is_empty(self, tmp_path):
        assert EventStore(tmp_path / "nope").recent() == []

    def test_corrupt_line_is_skipped(self, tmp_path):
        store = EventStore(tmp_path)
        store.append(MonitorEvent("sh600519", "贵州茅台", "r", "info", "good"))
        with store.ledger_path.open("a", encoding="utf-8") as f:
            f.write("{ 这不是 JSON\n")
        assert len(store.recent()) == 1

    def test_cooldown_suppresses_repeat(self, tmp_path):
        store = EventStore(tmp_path)
        event = MonitorEvent("sh600519", "贵州茅台", "涨超5%", "notice", "m")
        assert store.is_duplicate(event, cooldown_s=1800) is False
        store.mark_sent(event)
        assert store.is_duplicate(event, cooldown_s=1800) is True

    def test_cooldown_expires(self, tmp_path):
        store = EventStore(tmp_path)
        event = MonitorEvent("sh600519", "贵州茅台", "涨超5%", "notice", "m")
        store.mark_sent(event)
        store._dedupe[store._key(event)] = time.time() - 10
        assert store.is_duplicate(event, cooldown_s=5) is False

    def test_cooldown_zero_disables_suppression(self, tmp_path):
        store = EventStore(tmp_path)
        event = MonitorEvent("sh600519", "贵州茅台", "涨超5%", "notice", "m")
        store.mark_sent(event)
        assert store.is_duplicate(event, cooldown_s=0) is False

    def test_dedupe_survives_restart(self, tmp_path):
        """冷却状态要落盘，否则重启进程会把同一个异动重复喊一遍。"""
        event = MonitorEvent("sh600519", "贵州茅台", "涨超5%", "notice", "m")
        EventStore(tmp_path).mark_sent(event)
        assert EventStore(tmp_path).is_duplicate(event, cooldown_s=1800) is True

    def test_dedupe_key_includes_rule(self, tmp_path):
        """同一标的不同规则互不影响。"""
        store = EventStore(tmp_path)
        a = MonitorEvent("sh600519", "贵州茅台", "涨超5%", "notice", "m")
        b = MonitorEvent("sh600519", "贵州茅台", "触及涨停", "critical", "m")
        store.mark_sent(a)
        assert store.is_duplicate(b, cooldown_s=1800) is False


# ────────────────────────────────────────────────────────────────
#  通知分发
# ────────────────────────────────────────────────────────────────


class TestNotifier:
    def test_min_level_filters_low_severity(self):
        notifier = Notifier([{"type": "console"}], min_level="warning")
        assert notifier.should_send(MonitorEvent("s", "n", "r", "critical", "m")) is True
        assert notifier.should_send(MonitorEvent("s", "n", "r", "info", "m")) is False

    def test_falls_back_to_console_when_no_channels(self):
        assert build_notifier(None).channels == [{"type": "console"}]
        assert build_notifier({"channels": []}).channels == [{"type": "console"}]

    def test_unknown_channel_is_dropped(self):
        notifier = build_notifier({"channels": [{"type": "telepathy"}]})
        assert notifier.channels == [{"type": "console"}]

    def test_webhook_posts_event_payload(self):
        posted = {}

        def fake_post(url, *, json_body=None, data=None, headers=None):
            posted["url"] = url
            posted["body"] = json_body

        import astock_trader.monitor.notify as notify_mod

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(notify_mod, "_post", fake_post)
            notifier = Notifier([{"type": "webhook", "url": "https://example.com/hook"}])
            assert notifier.send(MonitorEvent("sh600519", "贵州茅台", "涨超5%", "notice", "m")) == 1
        assert posted["url"] == "https://example.com/hook"
        assert posted["body"]["symbol"] == "sh600519"

    def test_wecom_uses_text_msgtype(self):
        posted = {}

        def fake_post(url, *, json_body=None, data=None, headers=None):
            posted["body"] = json_body

        import astock_trader.monitor.notify as notify_mod

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(notify_mod, "_post", fake_post)
            Notifier([{"type": "wecom", "url": "https://qyapi.weixin.qq.com/x"}]).send(
                MonitorEvent("sh600519", "贵州茅台", "涨超5%", "notice", "内容")
            )
        assert posted["body"]["msgtype"] == "text"
        assert "贵州茅台" in posted["body"]["text"]["content"]

    def test_channel_failure_is_swallowed(self):
        """通知挂掉不该让监控循环停摆。"""

        def boom(url, *, json_body=None, data=None, headers=None):
            raise ConnectionError("通道挂了")

        import astock_trader.monitor.notify as notify_mod

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(notify_mod, "_post", boom)
            notifier = Notifier([{"type": "webhook", "url": "https://x"}])
            assert notifier.send(MonitorEvent("s", "n", "r", "critical", "m")) == 0  # 不抛出，只返回 0

    def test_missing_required_credential_fails_that_channel_only(self):
        notifier = Notifier([{"type": "serverchan"}])
        assert notifier.send_raw("t", "b") == 0


# ────────────────────────────────────────────────────────────────
#  交易时段
# ────────────────────────────────────────────────────────────────


class TestMarketSession:
    @pytest.mark.parametrize(
        ("moment", "expected"),
        [
            (datetime(2026, 9, 30, 10, 0), True),  # 周三上午
            (datetime(2026, 9, 30, 14, 0), True),  # 周三下午
            (datetime(2026, 9, 30, 12, 0), False),  # 午休
            (datetime(2026, 9, 30, 9, 0), False),  # 开盘前
            (datetime(2026, 9, 30, 16, 0), False),  # 收盘后
            (datetime(2026, 10, 3, 10, 0), False),  # 周六
            (datetime(2026, 10, 4, 10, 0), False),  # 周日
        ],
    )
    def test_session_boundaries(self, moment, expected):
        assert is_a_share_session(moment) is expected


# ────────────────────────────────────────────────────────────────
#  引擎
# ────────────────────────────────────────────────────────────────


class TestWatchEngine:
    def _engine(self, tmp_path, quotes, **kwargs):
        ruleset = load_rules({"rules": [{"name": "涨超5%", "type": "change_pct", "direction": "up", "threshold": 5}]})
        return WatchEngine(
            ["600519"],
            ruleset=ruleset,
            notifier=Notifier([{"type": "console"}], min_level="info"),
            store=EventStore(tmp_path),
            quote_fn=lambda _symbols: quotes,
            only_market_hours=False,
            **kwargs,
        )

    def test_tick_emits_event_on_hit(self, tmp_path):
        engine = self._engine(tmp_path, [make_quote(change_pct=6.2)])
        events = engine.tick()
        assert len(events) == 1
        assert events[0].symbol == "sh600519"
        assert events[0].rule == "涨超5%"

    def test_tick_silent_when_no_hit(self, tmp_path):
        engine = self._engine(tmp_path, [make_quote(change_pct=1.0)])
        assert engine.tick() == []

    def test_event_is_persisted(self, tmp_path):
        engine = self._engine(tmp_path, [make_quote(change_pct=6.2)])
        engine.tick()
        assert len(EventStore(tmp_path).recent()) == 1

    def test_second_tick_is_suppressed_by_cooldown(self, tmp_path):
        engine = self._engine(tmp_path, [make_quote(change_pct=6.2)], cooldown_s=1800)
        assert len(engine.tick()) == 1
        assert engine.tick() == []

    def test_quote_failure_does_not_kill_loop(self, tmp_path):
        """取数抛异常时本轮跳过，进程不退出。"""

        def boom(_symbols):
            raise ConnectionError("行情源挂了")

        ruleset = load_rules(None)
        engine = WatchEngine(
            ["600519"],
            ruleset=ruleset,
            notifier=Notifier([{"type": "console"}]),
            store=EventStore(tmp_path),
            quote_fn=boom,
            only_market_hours=False,
        )
        assert engine.tick() == []
        assert engine.ticks == 1

    def test_on_event_callback_receives_event(self, tmp_path):
        seen = []
        engine = self._engine(tmp_path, [make_quote(change_pct=6.2)], on_event=seen.append)
        engine.tick()
        assert len(seen) == 1
        assert isinstance(seen[0], MonitorEvent)

    def test_callback_failure_does_not_lose_event(self, tmp_path):
        def boom(_event):
            raise RuntimeError("回调挂了")

        engine = self._engine(tmp_path, [make_quote(change_pct=6.2)], on_event=boom)
        assert len(engine.tick()) == 1
        assert len(EventStore(tmp_path).recent()) == 1  # 落盘先于回调，事件不会丢

    def test_empty_symbols_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="不能为空"):
            WatchEngine([], store=EventStore(tmp_path))

    def test_run_once_returns_and_stops(self, tmp_path):
        engine = self._engine(tmp_path, [make_quote(change_pct=6.2)])
        events = engine.run(once=True)
        assert len(events) == 1
        assert engine.ticks == 1

    def test_run_respects_max_ticks(self, tmp_path):
        engine = self._engine(tmp_path, [make_quote(change_pct=1.0)])
        engine.run(max_ticks=3, sleep_fn=lambda _s: None)
        assert engine.ticks == 3

    def test_run_skips_outside_session_when_gated(self, tmp_path):
        """门控跳过 tick 时，max_ticks 仍必须能退出循环。

        回归测试：退出条件原先用的是成功取数次数（``self.ticks``），而交易日
        门控会跳过 tick 使它不增长，导致非交易时段 ``max_ticks`` 永远达不到 ——
        进程会卡在循环里出不来。改成按循环轮次计数后才不会挂死。
        """
        engine = self._engine(tmp_path, [make_quote(change_pct=6.2)])
        engine.only_market_hours = True
        engine.run(max_ticks=1, sleep_fn=lambda _s: None)
        # 断言的是"时段门控生效时不取数"，与跑测试的具体时间无关
        assert engine.ticks == (0 if not is_a_share_session() else 1)
