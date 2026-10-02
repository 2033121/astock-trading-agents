"""监控层 —— 常驻盯盘、规则触发、多通道推送。

与 ``graph``（LLM 深度分析流水线）刻意解耦：

* 监控层不依赖 LLM，能长时间常驻跑，成本只有行情请求；
* 它通过 :class:`~astock_trader.monitor.engine.WatchEngine` 的 ``on_event``
  回调把"值得深挖"的事件交给上层，由上层决定要不要触发一次 ``analyze``。

最小用法::

    from astock_trader.monitor import WatchEngine, build_notifier, load_rules

    engine = WatchEngine(
        ["600519", "000001"],
        ruleset=load_rules({"rules": [...]}),
        notifier=build_notifier({"channels": [{"type": "wecom", "url": "..."}]}),
        interval=30,
    )
    engine.run()
"""

from .engine import WatchEngine, is_a_share_session
from .events import MonitorEvent
from .notify import Notifier, build_notifier
from .rules import DEFAULT_RULES, Rule, RuleSet, evaluate, load_rules
from .store import EventStore

__all__ = [
    "DEFAULT_RULES",
    "EventStore",
    "MonitorEvent",
    "Notifier",
    "Rule",
    "RuleSet",
    "WatchEngine",
    "build_notifier",
    "evaluate",
    "is_a_share_session",
    "load_rules",
]
