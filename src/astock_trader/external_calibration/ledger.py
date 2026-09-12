"""外部校准台账 — 与内部交易记忆**物理隔离**的追加式存储。

为什么必须隔离（issue #1 约束 3）
--------------------------------
内部交易的 ``TradingMemoryLog`` 存的是 akshare 自检出来的「自己说对不对」；
外部台账存的是第三方机械结算的「别人算你对不对」。两套证据一旦写进同一个文件，
后续的反思闭环就无法再区分「哪些教训来自自评、哪些来自外部裁定」，
外部结算也就失去了作为独立参照的意义。

因此本模块：

- 使用**独立文件**（默认 ``~/.astock_trader/external_calibration/headline_arena_ledger.jsonl``），
  与 ``trading_memory.log`` / ``memory/trading_memory.md`` 不共用任何路径；
- 拒绝构造指向内部交易记忆文件名的台账（:func:`_assert_isolated`），把误用拦在写入之前；
- 每条记录都带 ``source: external_headline_arena`` 标记，可随时按来源筛选审计。

存储格式
--------
JSONL，一行一条记录，``record_type`` 区分类型::

    {"record_type": "arena_settlement", "source": "external_headline_arena", ...}
    {"record_type": "local_stance",     "source": "external_headline_arena", ...}

追加式（append-only）+ 读取时「后者胜出」：同一条预测被平台重复结算或补发时，
新记录追加在尾部而不改写历史，读取时按最后一次出现取值。这样既有幂等性，
又保留了完整的结算溯源链。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from astock_trader.external_calibration.schema import (
    SOURCE_TAG,
    ArenaSettlement,
    LocalStance,
    now_iso,
)

logger = logging.getLogger(__name__)

_DEFAULT_PROJECT_DIR = os.path.join(os.path.expanduser("~"), ".astock_trader")
_DEFAULT_SUBDIR = "external_calibration"
_DEFAULT_LEDGER_FILE = "headline_arena_ledger.jsonl"

RECORD_SETTLEMENT = "arena_settlement"
RECORD_STANCE = "local_stance"

#: 内部交易记忆的保留文件名——台账绝不能占用它们
_FORBIDDEN_NAMES = frozenset({"trading_memory.log", "trading_memory.md"})


def _internal_memory_paths() -> set[Path]:
    """默认安装下内部交易记忆的绝对路径集合。"""
    base = Path(_DEFAULT_PROJECT_DIR)
    return {
        (base / "trading_memory.log").resolve(),
        (base / "memory" / "trading_memory.md").resolve(),
    }


def _assert_isolated(path: Path) -> None:
    """台账路径与内部交易记忆冲突时直接报错，避免两套证据串写。

    Raises
    ------
    ValueError
        台账文件名与内部记忆同名，或台账路径就是内部记忆文件本身。
    """
    resolved = path.resolve()
    if resolved.name in _FORBIDDEN_NAMES or resolved in _internal_memory_paths():
        raise ValueError(
            f"外部校准台账不能写入内部交易记忆路径（{resolved}）。"
            "外部结算与 akshare 自检必须分开存放，见 issue #1 约束 3。"
        )


class ExternalCalibrationLedger:
    """外部校准台账（追加式 JSONL）。

    Parameters
    ----------
    ledger_dir : str | None
        台账目录，默认 ``~/.astock_trader/external_calibration/``。
    ledger_file : str | None
        台账文件名，默认 ``headline_arena_ledger.jsonl``。
    project_dir : str | None
        项目根目录，仅在 ``ledger_dir`` 未给出时用于推导默认台账目录。
    """

    def __init__(
        self,
        ledger_dir: str | None = None,
        ledger_file: str | None = None,
        project_dir: str | None = None,
    ) -> None:
        if ledger_dir:
            self._dir = Path(ledger_dir)
        else:
            base = project_dir or _DEFAULT_PROJECT_DIR
            self._dir = Path(base) / _DEFAULT_SUBDIR
        self._file = ledger_file or _DEFAULT_LEDGER_FILE
        self._path = self._dir / self._file
        _assert_isolated(self._path)
        self._dir.mkdir(parents=True, exist_ok=True)

    # ─────────────────── 只读属性 ───────────────────

    @property
    def path(self) -> Path:
        """台账文件路径。"""
        return self._path

    @property
    def source_tag(self) -> str:
        """本台账统一使用的来源标记。"""
        return SOURCE_TAG

    # ─────────────────── 写入 ───────────────────

    def record_settlement(self, settlement: ArenaSettlement) -> bool:
        """追加一条第三方结算记录。

        Returns
        -------
        bool
            ``True`` 表示该 ``prediction_id`` 首次入库，``False`` 表示是更新
            （例如同一预测从 unresolved 变为已结算）。
        """
        pid = settlement.prediction_id
        if not pid:
            logger.warning("结算记录缺少 prediction_id，已丢弃（无法作为配对键）。")
            return False

        known = {s.prediction_id for s in self.load_settlements()}
        payload = settlement.to_dict()
        payload["record_type"] = RECORD_SETTLEMENT
        payload["source"] = SOURCE_TAG
        if not payload.get("ingested_at"):
            payload["ingested_at"] = now_iso()
        self._append(payload)
        return pid not in known

    def record_stance(self, stance: LocalStance, *, overwrite: bool = False) -> bool:
        """记录一条本地镜像判断。

        默认**写一次即冻结**（``overwrite=False``）：本地判断必须在看到结算结果
        之前落盘，否则事后无法证明它没有被反向污染。确需修正时显式传
        ``overwrite=True``，并在 ``rationale`` 中说明原因。

        Returns
        -------
        bool
            是否实际写入。
        """
        key = stance.challenge_id
        if not key:
            logger.warning("本地判断缺少 challenge_id，已丢弃（无法作为配对键）。")
            return False

        if not overwrite and key in self.load_stances():
            logger.warning(
                "challenge %s 已有冻结的本地判断，拒绝覆盖（如需修正请显式 overwrite=True）。",
                key,
            )
            return False

        payload = stance.to_dict()
        payload["record_type"] = RECORD_STANCE
        payload["source"] = SOURCE_TAG
        if not payload.get("recorded_at"):
            payload["recorded_at"] = now_iso()
        self._append(payload)
        return True

    def sync(self, client: Any, *, since: str | None = None) -> int:
        """从 arena 增量拉取预测历史并入库。

        Parameters
        ----------
        client : HeadlineArenaClient
            未配置凭据的客户端会直接产出 0 条（优雅跳过，不报错）。
        since : str | None
            ISO 8601 时间戳，仅同步该时刻之后的记录。

        Returns
        -------
        int
            新增（首次入库）的结算记录条数。
        """
        new_count = 0
        seen = 0
        for item in client.iter_predictions(since=since):
            seen += 1
            settlement = ArenaSettlement.from_api_item(item)
            if not settlement.prediction_id or not settlement.challenge_id:
                logger.debug("跳过缺少主键的预测条目：%s", item)
                continue
            if self.record_settlement(settlement):
                new_count += 1
        logger.info("外部校准同步完成：扫描 %d 条，新增 %d 条。", seen, new_count)
        return new_count

    # ─────────────────── 读取 ───────────────────

    def load_settlements(self) -> list[ArenaSettlement]:
        """读取全部结算记录（同一 ``prediction_id`` 以最后一次出现为准）。"""
        latest: dict[str, ArenaSettlement] = {}
        for record in self._iter_records(RECORD_SETTLEMENT):
            settlement = ArenaSettlement.from_dict(record)
            if settlement.prediction_id:
                latest[settlement.prediction_id] = settlement
        return sorted(latest.values(), key=lambda s: (s.created_at, s.prediction_id))

    def load_stances(self) -> dict[str, LocalStance]:
        """读取全部本地镜像判断（同一 ``challenge_id`` 以最后一次出现为准）。"""
        latest: dict[str, LocalStance] = {}
        for record in self._iter_records(RECORD_STANCE):
            stance = LocalStance.from_dict(record)
            if stance.challenge_id:
                latest[stance.challenge_id] = stance
        return latest

    def stats(self) -> dict[str, Any]:
        """台账概览，供 CLI / 日志输出。"""
        settlements = self.load_settlements()
        resolved = [s for s in settlements if s.is_resolved]
        return {
            "path": str(self._path),
            "source": SOURCE_TAG,
            "settlements": len(settlements),
            "resolved": len(resolved),
            "pending": len(settlements) - len(resolved),
            "stances": len(self.load_stances()),
        }

    # ─────────────────── 内部 ───────────────────

    def _append(self, payload: dict[str, Any]) -> None:
        """向台账追加一行 JSON。"""
        line = json.dumps(payload, ensure_ascii=False)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _iter_records(self, record_type: str) -> list[dict[str, Any]]:
        """读取指定类型的所有记录；损坏行跳过并告警。"""
        if not self._path.exists():
            return []
        out: list[dict[str, Any]] = []
        try:
            content = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("读取外部校准台账失败：%s", exc)
            return []
        for lineno, raw in enumerate(content.splitlines(), start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("外部校准台账第 %d 行不是合法 JSON，已跳过。", lineno)
                continue
            if isinstance(record, dict) and record.get("record_type") == record_type:
                out.append(record)
        return out


def default_ledger(project_dir: str | None = None) -> ExternalCalibrationLedger:
    """按默认位置构造台账。"""
    return ExternalCalibrationLedger(project_dir=project_dir)


__all__ = [
    "RECORD_SETTLEMENT",
    "RECORD_STANCE",
    "ExternalCalibrationLedger",
    "default_ledger",
]
