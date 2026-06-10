"""交易记忆日志系统 — 持久化存储交易决策与反思。

文件格式
--------
每条记录以 ``<!-- ENTRY_END -->`` 分隔，内部包含:
- 头部: ``[date | ticker | rating | pending]``
- ``DECISION`` 块: 存储原始决策信息
- ``REFLECTION`` 块: 存储事后反思（仅 resolved 条目有）

系统会自动轮转：保留最近的 resolved 条目（同标的最多 5 条 + 跨标的最多 3 条）
以及所有 pending 条目。
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 默认记忆文件路径
_DEFAULT_MEMORY_DIR = os.path.join(os.path.expanduser("~"), ".astock_trader")
_DEFAULT_MEMORY_FILE = "trading_memory.log"

_ENTRY_SEPARATOR = "<!-- ENTRY_END -->"
_HEADER_PATTERN = re.compile(r"\[(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\]")


class TradingMemoryLog:
    """交易记忆日志管理器。

    Parameters
    ----------
    memory_dir : str | None
        记忆文件存放目录，默认 ``~/.astock_trader/``。
    memory_file : str | None
        记忆文件名，默认 ``trading_memory.log``。
    """

    def __init__(
        self,
        memory_dir: Optional[str] = None,
        memory_file: Optional[str] = None,
    ) -> None:
        self._dir = memory_dir or _DEFAULT_MEMORY_DIR
        self._file = memory_file or _DEFAULT_MEMORY_FILE
        self._path = Path(self._dir) / self._file
        Path(self._dir).mkdir(parents=True, exist_ok=True)

    # ─────────────────── 公共 API ───────────────────

    def store_decision(
        self,
        ticker: str,
        trade_date: str,
        final_decision: dict[str, Any],
    ) -> None:
        """存储一条新的交易决策（pending 状态）。

        Parameters
        ----------
        ticker : str
            股票代码。
        trade_date : str
            交易日期 (yyyy-mm-dd)。
        final_decision : dict
            决策内容，至少包含 ``rating`` (str) 字段。
        """
        rating = final_decision.get("rating", "unknown")
        entry = self._format_entry(
            date=trade_date,
            ticker=ticker,
            rating=rating,
            pending=True,
            decision=final_decision,
            reflection=None,
        )
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(entry)
        logger.info(f"已存储决策: {ticker} @ {trade_date} -> {rating}")

    def get_pending_entries(self) -> list[dict[str, Any]]:
        """获取所有 pending（尚未反思）的条目。"""
        entries = self._load_all_entries()
        return [e for e in entries if e["pending"]]

    def get_past_context(
        self,
        ticker: str,
        n_same: int = 5,
        n_cross: int = 3,
    ) -> str:
        """获取历史决策上下文，用于注入到 Prompt 中。

        Parameters
        ----------
        ticker : str
            当前分析的股票代码。
        n_same : int
            同一标的最近的已解决条目数。
        n_cross : int
            其他标的最近的已解决条目数。

        Returns
        -------
        str
            格式化的历史上下文文本。
        """
        entries = self._load_all_entries()
        resolved = [e for e in entries if not e["pending"]]

        same_ticker = [e for e in resolved if e["ticker"] == ticker]
        cross_ticker = [e for e in resolved if e["ticker"] != ticker]

        # 按日期降序
        same_ticker.sort(key=lambda x: x["date"], reverse=True)
        cross_ticker.sort(key=lambda x: x["date"], reverse=True)

        same_recent = same_ticker[:n_same]
        cross_recent = cross_ticker[:n_cross]

        if not same_recent and not cross_recent:
            return "暂无历史决策记录。"

        lines: list[str] = []
        if same_recent:
            lines.append(f"## {ticker} 历史决策")
            for e in same_recent:
                lines.append(self._format_entry_text(e))
        if cross_recent:
            lines.append("## 其他标的历史决策")
            for e in cross_recent:
                lines.append(self._format_entry_text(e))

        return "\n".join(lines)

    def batch_update_with_outcomes(
        self,
        updates: list[dict[str, Any]],
    ) -> int:
        """批量更新 pending 条目，添加反思结果。

        Parameters
        ----------
        updates : list[dict]
            每个元素包含:
            - ``ticker`` (str): 股票代码
            - ``trade_date`` (str): 原始交易日期
            - ``reflection`` (dict): 反思内容
            - ``new_rating`` (str, optional): 更新后的评级

        Returns
        -------
        int
            成功更新的条目数。
        """
        entries = self._load_all_entries()
        updated_count = 0

        # 建立 (ticker, date) -> reflection 映射
        update_map: dict[tuple[str, str], dict[str, Any]] = {}
        for u in updates:
            key = (u["ticker"], u["trade_date"])
            update_map[key] = u

        for entry in entries:
            if not entry["pending"]:
                continue
            key = (entry["ticker"], entry["date"])
            if key in update_map:
                upd = update_map[key]
                entry["pending"] = False
                entry["reflection"] = upd.get("reflection", {})
                if "new_rating" in upd:
                    entry["rating"] = upd["new_rating"]
                updated_count += 1

        # 重写文件
        self._rewrite_all(entries)
        logger.info(f"批量更新完成: {updated_count}/{len(updates)} 条已更新")
        return updated_count

    # ─────────────────── 内部方法 ───────────────────

    def _apply_rotation(self, max_same: int = 10, max_cross: int = 10) -> None:
        """轮转旧条目，防止文件无限增长。

        保留规则:
        - 所有 pending 条目
        - 每个标的最近的 resolved 条目（最多 max_same 条）
        - 其他标的最近的 resolved 条目（总共最多 max_cross 条）
        """
        entries = self._load_all_entries()
        pending = [e for e in entries if e["pending"]]
        resolved = [e for e in entries if not e["pending"]]

        # 按 ticker 分组
        by_ticker: dict[str, list[dict]] = {}
        for e in resolved:
            by_ticker.setdefault(e["ticker"], []).append(e)

        kept: list[dict] = []
        cross_kept = 0
        for ticker, group in sorted(by_ticker.items(), key=lambda x: x[0]):
            group.sort(key=lambda e: e["date"], reverse=True)
            keep_count = min(len(group), max_same)
            for e in group[:keep_count]:
                if cross_kept < max_cross:
                    kept.append(e)
                    cross_kept += 1

        all_kept = pending + kept
        all_kept.sort(key=lambda e: e["date"])
        self._rewrite_all(all_kept)

    def _load_all_entries(self) -> list[dict[str, Any]]:
        """从文件加载所有条目。"""
        if not self._path.exists():
            return []

        content = self._path.read_text(encoding="utf-8")
        raw_entries = content.split(_ENTRY_SEPARATOR)
        entries: list[dict[str, Any]] = []

        for raw in raw_entries:
            raw = raw.strip()
            if not raw:
                continue
            entry = self._parse_entry(raw)
            if entry:
                entries.append(entry)

        return entries

    def _parse_entry(self, text: str) -> Optional[dict[str, Any]]:
        """解析单个条目文本为字典。"""
        header_match = _HEADER_PATTERN.search(text)
        if not header_match:
            return None

        date = header_match.group(1).strip()
        ticker = header_match.group(2).strip()
        rating = header_match.group(3).strip()
        pending_str = header_match.group(4).strip().lower()
        pending = pending_str == "pending"

        # 提取 DECISION 块
        decision: dict[str, Any] = {}
        decision_match = re.search(
            r"DECISION\s*\n(.*?)(?=\n\s*REFLECTION|\n\s*" + re.escape(_ENTRY_SEPARATOR) + r"|\Z)",
            text,
            re.DOTALL,
        )
        if decision_match:
            try:
                decision = json.loads(decision_match.group(1).strip())
            except json.JSONDecodeError:
                decision = {"raw": decision_match.group(1).strip()}

        # 提取 REFLECTION 块
        reflection: Optional[dict[str, Any]] = None
        reflection_match = re.search(
            r"REFLECTION\s*\n(.*?)(?=\n\s*" + re.escape(_ENTRY_SEPARATOR) + r"|\Z)",
            text,
            re.DOTALL,
        )
        if reflection_match:
            try:
                reflection = json.loads(reflection_match.group(1).strip())
            except json.JSONDecodeError:
                reflection = {"raw": reflection_match.group(1).strip()}

        return {
            "date": date,
            "ticker": ticker,
            "rating": rating,
            "pending": pending,
            "decision": decision,
            "reflection": reflection,
        }

    def _rewrite_all(self, entries: list[dict[str, Any]]) -> None:
        """重写整个记忆文件。"""
        with open(self._path, "w", encoding="utf-8") as f:
            for entry in entries:
                text = self._format_entry(
                    date=entry["date"],
                    ticker=entry["ticker"],
                    rating=entry["rating"],
                    pending=entry["pending"],
                    decision=entry.get("decision", {}),
                    reflection=entry.get("reflection"),
                )
                f.write(text)

    @staticmethod
    def _format_entry(
        date: str,
        ticker: str,
        rating: str,
        pending: bool,
        decision: dict[str, Any],
        reflection: Optional[dict[str, Any]],
    ) -> str:
        """格式化一个条目为文本。"""
        pending_str = "pending" if pending else "resolved"
        lines = [
            f"[{date} | {ticker} | {rating} | {pending_str}]",
            "",
            "DECISION",
            json.dumps(decision, ensure_ascii=False, indent=2),
        ]
        if reflection is not None:
            lines.extend([
                "",
                "REFLECTION",
                json.dumps(reflection, ensure_ascii=False, indent=2),
            ])
        lines.extend(["", _ENTRY_SEPARATOR, ""])
        return "\n".join(lines)

    @staticmethod
    def _format_entry_text(entry: dict[str, Any]) -> str:
        """将条目格式化为供 Prompt 使用的简洁文本。"""
        parts = [
            f"- **{entry['ticker']}** ({entry['date']}): 评级={entry['rating']}",
        ]
        decision = entry.get("decision", {})
        if isinstance(decision, dict):
            if "action" in decision:
                parts.append(f"  操作: {decision['action']}")
            if "reasoning" in decision:
                parts.append(f"  理由: {decision['reasoning']}")
            if "final_trade_decision" in decision:
                parts.append(f"  决策: {decision['final_trade_decision']}")
        reflection = entry.get("reflection")
        if reflection and isinstance(reflection, dict):
            if "outcome" in reflection:
                parts.append(f"  结果: {reflection['outcome']}")
            if "lesson" in reflection:
                parts.append(f"  教训: {reflection['lesson']}")
        return "\n".join(parts)
