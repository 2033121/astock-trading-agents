"""监控事件台账 —— 追加式 JSONL，和 ``progress_recorder`` 的落盘习惯保持一致。

为什么不用数据库：事件量小（一天几十到几百条），需要的是**可 grep、可追加、
不会因为进程被杀而损坏**。JSONL 满足这三点，且零依赖。

去重状态（每个 ``(symbol, rule)`` 上次推送时间）也存在同一个目录下，
这样进程重启后不会把同一个异动重复喊一遍。
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from .events import MonitorEvent, event_from_dict

logger = logging.getLogger(__name__)

__all__ = ["EventStore"]

_LEDGER_NAME = "monitor_events.jsonl"
_DEDUPE_NAME = "monitor_dedupe.json"


class EventStore:
    """事件台账 + 去重状态。"""

    def __init__(self, directory: str | os.PathLike[str]):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.ledger_path = self.dir / _LEDGER_NAME
        self.dedupe_path = self.dir / _DEDUPE_NAME
        self._dedupe: dict[str, float] = self._load_dedupe()

    # -- 事件落盘 ------------------------------------------------------------

    def append(self, event: MonitorEvent) -> None:
        try:
            with self.ledger_path.open("a", encoding="utf-8") as f:
                f.write(event.to_json() + "\n")
        except OSError as exc:
            logger.warning("监控事件写入失败：%s", exc)

    def recent(self, limit: int = 50) -> list[MonitorEvent]:
        """读最近 *limit* 条事件（文件不存在时返回空列表）。"""
        if not self.ledger_path.exists():
            return []
        try:
            lines = self.ledger_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            logger.warning("监控台账读取失败：%s", exc)
            return []
        events: list[MonitorEvent] = []
        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(event_from_dict(json.loads(line)))
            except (json.JSONDecodeError, TypeError) as exc:
                logger.debug("跳过损坏的台账行：%s", exc)
        return events

    # -- 去重 ----------------------------------------------------------------

    def _load_dedupe(self) -> dict[str, float]:
        if not self.dedupe_path.exists():
            return {}
        try:
            return {str(k): float(v) for k, v in json.loads(self.dedupe_path.read_text(encoding="utf-8")).items()}
        except (OSError, json.JSONDecodeError, ValueError, AttributeError) as exc:
            logger.debug("去重状态读取失败，按空处理：%s", exc)
            return {}

    def _save_dedupe(self) -> None:
        try:
            # 先写临时文件再替换，避免进程中途被杀留下半个 JSON
            tmp = self.dedupe_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._dedupe, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.dedupe_path)
        except OSError as exc:
            logger.warning("去重状态写入失败：%s", exc)

    @staticmethod
    def _key(event: MonitorEvent) -> str:
        return f"{event.symbol}|{event.rule}"

    def is_duplicate(self, event: MonitorEvent, cooldown_s: float) -> bool:
        """该事件是否在冷却窗口内已经推送过。"""
        if cooldown_s <= 0:
            return False
        last = self._dedupe.get(self._key(event))
        return last is not None and (time.time() - last) < cooldown_s

    def mark_sent(self, event: MonitorEvent) -> None:
        self._dedupe[self._key(event)] = time.time()
        self._save_dedupe()
