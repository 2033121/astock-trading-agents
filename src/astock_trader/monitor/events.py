"""监控事件模型 —— 规则命中后产生的可落盘、可推送的结构化记录。

一个 :class:`MonitorEvent` 就是"某个标的在某个时刻因为某条规则值得你看一眼"。
它是监控层与外部世界（JSONL 台账、通知通道、可选的深度分析）之间**唯一**的
数据契约，所以字段要稳定、可序列化。
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

__all__ = ["MonitorEvent", "LEVEL_ORDER"]

# 严重度由低到高；通知层按 min_level 过滤
LEVEL_ORDER: dict[str, int] = {"info": 10, "notice": 20, "warning": 30, "critical": 40}


@dataclass
class MonitorEvent:
    """一条监控事件。

    Attributes:
        symbol: 带交易所前缀的行情代码，如 ``sh600519``。
        name: 标的中文名。
        rule: 命中的规则名（如 ``change_pct``）。
        level: 严重度，取值见 :data:`LEVEL_ORDER`。
        message: 给人看的一句话，直接进通知正文。
        metrics: 触发时的关键数值快照（现价、涨跌幅……），便于事后复盘。
        ts: Unix 时间戳（秒）。
        event_id: 稳定短 id，用于去重与外部引用。
    """

    symbol: str
    name: str
    rule: str
    level: str
    message: str
    metrics: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    @property
    def severity(self) -> int:
        return LEVEL_ORDER.get(self.level, 0)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    def from_dict_ts(self) -> str:
        """本地时间的可读时间戳，用于日志与通知标题。"""
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.ts))

    def one_line(self) -> str:
        return f"[{self.level.upper()}] {self.from_dict_ts()} {self.symbol} {self.name} — {self.message}"


def event_from_dict(payload: dict[str, Any]) -> MonitorEvent:
    """从 :meth:`MonitorEvent.to_dict` 的输出还原（忽略未知字段，容忍旧台账）。"""
    known = {f for f in MonitorEvent.__dataclass_fields__}
    return MonitorEvent(**{k: v for k, v in payload.items() if k in known})
