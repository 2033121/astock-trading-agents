"""监控引擎 —— 轮询行情、跑规则、去重、落盘、推送。

监控层与 ``analyze`` 流水线是**解耦**的：引擎只认识"行情 dict → 事件"，不知道
LLM、不知道 LangGraph。这样它可以脱离 LLM 独立跑（省钱、可长时间常驻），也可以
通过 :meth:`WatchEngine` 的 ``on_event`` 回调把事件交给上层去触发一次深度分析。

一个 tick 的顺序固定为：取数 → 求值 → 去重 → 落盘 → 推送。落盘先于推送，
所以通知发的过程中进程被杀，事件也不会丢。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime
from datetime import time as dtime
from typing import Any

from astock_trader.paths import project_path

from .events import MonitorEvent
from .notify import Notifier, build_notifier
from .rules import RuleSet, evaluate, load_rules
from .store import EventStore

logger = logging.getLogger(__name__)

__all__ = ["WatchEngine", "is_a_share_session"]

# A 股连续竞价时段（不考虑法定节假日 —— 节假日会照常轮询但拿不到新数据，
# 顶多多花几次请求；要精确到节假日需要交易日历，见 docs）
_MORNING = (dtime(9, 30), dtime(11, 30))
_AFTERNOON = (dtime(13, 0), dtime(15, 0))


def is_a_share_session(now: datetime | None = None) -> bool:
    """当前是否在 A 股连续竞价时段内（工作日 9:30-11:30 / 13:00-15:00，北京时间）。"""
    now = now or datetime.now()
    if now.weekday() >= 5:
        return False
    current = now.time()
    return (_MORNING[0] <= current <= _MORNING[1]) or (_AFTERNOON[0] <= current <= _AFTERNOON[1])


def _default_quote_fn(symbols: list[str]) -> list[dict[str, Any]]:
    from ..dataflows.realtime_data import get_realtime_quotes_batch

    return get_realtime_quotes_batch(symbols)


class WatchEngine:
    """把"盯盘"这件事跑起来的循环。

    Args:
        symbols: 监控标的（6 位代码或带前缀代码均可）。
        ruleset: 规则集；缺省用 :func:`load_rules` 的默认规则。
        notifier: 通知器；缺省 console。
        store: 事件台账；缺省写到 ``~/.astock_trader/monitor``。
        interval: 轮询间隔（秒）。
        cooldown_s: 同一 ``(标的, 规则)`` 的静默窗口，避免反复喊同一件事。
        quote_fn: 取行情函数，签名 ``(symbols) -> list[dict]``；可注入以便测试。
        on_event: 事件回调，可用来触发一次深度分析。
        only_market_hours: 非交易时段是否跳过轮询。
    """

    def __init__(
        self,
        symbols: list[str],
        *,
        ruleset: RuleSet | None = None,
        notifier: Notifier | None = None,
        store: EventStore | None = None,
        interval: int = 30,
        cooldown_s: float = 1800,
        quote_fn: Callable[[list[str]], list[dict[str, Any]]] | None = None,
        on_event: Callable[[MonitorEvent], None] | None = None,
        only_market_hours: bool = True,
    ):
        if not symbols:
            raise ValueError("监控标的不能为空")
        self.symbols = list(symbols)
        self.ruleset = ruleset or load_rules()
        self.notifier = notifier or build_notifier()
        self.store = store or EventStore(_default_store_dir())
        self.interval = max(1, int(interval))
        self.cooldown_s = float(cooldown_s)
        self.quote_fn = quote_fn or _default_quote_fn
        self.on_event = on_event
        self.only_market_hours = only_market_hours
        self.ticks = 0

    # -- 单次轮询 ------------------------------------------------------------

    def tick(self) -> list[MonitorEvent]:
        """跑一轮：取数 → 求值 → 去重 → 落盘 → 推送，返回本轮**新**事件。"""
        self.ticks += 1
        try:
            quotes = self.quote_fn(self.symbols)
        except Exception as exc:
            # 取数失败不该让常驻进程退出；下一轮再试。
            logger.warning("行情获取失败（第 %d 轮）：%s", self.ticks, exc)
            return []

        fresh: list[MonitorEvent] = []
        for event in evaluate(self.ruleset, quotes):
            if self.store.is_duplicate(event, self.cooldown_s):
                logger.debug("冷却期内跳过：%s", event.one_line())
                continue
            fresh.append(event)

        for event in fresh:
            self.store.append(event)
            self.store.mark_sent(event)

        for event in fresh:
            self.notifier.send(event)
            if self.on_event is not None:
                try:
                    self.on_event(event)
                except Exception as exc:
                    logger.warning("事件回调失败：%s", exc)

        return fresh

    # -- 循环 ----------------------------------------------------------------

    def run(
        self, *, once: bool = False, max_ticks: int | None = None, sleep_fn: Callable[[float], None] = time.sleep
    ) -> list[MonitorEvent]:
        """运行监控循环。

        Args:
            once: 只跑一轮就返回（便于手动检查规则是否写对）。
            max_ticks: 最多跑多少轮，``None`` 表示不限。
            sleep_fn: 休眠函数，测试时可替换成空实现。
        """
        collected: list[MonitorEvent] = []
        iterations = 0
        while True:
            iterations += 1
            if self.only_market_hours and not is_a_share_session():
                logger.info("当前非 A 股交易时段，跳过本轮轮询")
            else:
                collected.extend(self.tick())

            # 用**循环轮次**而不是成功取数次数来判定退出：交易时段门控会跳过 tick，
            # 使 self.ticks 不增长；若拿它做退出条件，非交易时段会永远退不出来。
            if once or (max_ticks is not None and iterations >= max_ticks):
                break
            sleep_fn(self.interval)
        return collected


def _default_store_dir() -> str:
    return project_path("monitor")
