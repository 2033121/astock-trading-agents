"""两条线比对 — 第三方机械结算 vs 本地镜像判断。

试点要回答的问题（issue #1）
---------------------------
「自己的记忆系统说进步了，第三方的校准曲线是否同意？」

本模块把台账里的两套记录配对成两条线：

- **arena 线**：我们真正提交给平台的预测 + 平台机械结算的对错 + 公开校准曲线。
- **本地镜像线**：同一批 challenge 上，本框架在**结算前冻结**的宏观方向判断，
  用平台的冻结结果机械打分。

两条线若方向一致、命中率同向，说明「内部自评」与「外部裁定」互不矛盾，
可以推进正式接入 PR；若不一致，这份比对数据本身就是有价值的结果。

注意：本地镜像线是「宏观判断的转写」，不是 A 股个股评级的命中率
—— 后者由内部反思闭环单独跟踪，两者不可互相替代（见 :data:`ASSET_DOMAIN_BOUNDARY`）。
"""

from __future__ import annotations

import logging
from statistics import fmean
from typing import Any

from astock_trader.external_calibration.schema import (
    ASSET_DOMAIN_BOUNDARY,
    CalibrationBucketRow,
    LineStats,
    ReconciliationReport,
    now_iso,
)

logger = logging.getLogger(__name__)

#: 低于该样本量时在报告里显式提示结论不可靠
_MIN_RELIABLE_N = 20


def _line_stats(label: str, pairs: list[tuple[float, bool]]) -> LineStats:
    """由 ``(置信度, 是否命中)`` 序列计算一条线的统计量。"""
    n = len(pairs)
    if n == 0:
        return LineStats(label=label)
    hits = sum(1 for _, correct in pairs if correct)
    brier = fmean((confidence - (1.0 if correct else 0.0)) ** 2 for confidence, correct in pairs)
    return LineStats(
        label=label,
        n=n,
        hits=hits,
        hit_rate=hits / n,
        avg_confidence=fmean(confidence for confidence, _ in pairs),
        brier=brier,
    )


def build_buckets(calibration: dict[str, Any] | None) -> list[CalibrationBucketRow]:
    """把平台校准曲线的原始分箱映射为 :class:`CalibrationBucketRow` 列表。"""
    if not isinstance(calibration, dict):
        return []
    rows: list[CalibrationBucketRow] = []
    for raw in calibration.get("buckets") or []:
        if not isinstance(raw, dict):
            continue
        try:
            rows.append(
                CalibrationBucketRow(
                    bucket=str(raw.get("bucket", "")),
                    n=int(raw.get("n") or 0),
                    avg_confidence=float(raw.get("avg_confidence") or 0.0),
                    hit_rate=float(raw.get("hit_rate") or 0.0),
                    low_sample=bool(raw.get("low_sample", False)),
                )
            )
        except (TypeError, ValueError):
            logger.debug("跳过无法解析的校准分箱：%s", raw)
    return rows


def reconcile(
    ledger: Any,
    *,
    calibration: dict[str, Any] | None = None,
    scorecard: dict[str, Any] | None = None,
    agent_id: str = "",
    generated_at: str | None = None,
) -> ReconciliationReport:
    """配对两条线并生成比对报告。

    Parameters
    ----------
    ledger : ExternalCalibrationLedger
        外部校准台账。
    calibration : dict | None
        平台公开校准曲线的原始响应（``GET /eval/agents/{id}/calibration``）。
    scorecard : dict | None
        平台公开记分卡的原始响应。
    agent_id : str
        写入报告的 agent 标识。
    generated_at : str | None
        报告生成时间，默认当前 UTC 时间。

    Returns
    -------
    ReconciliationReport
    """
    settlements = ledger.load_settlements()
    stances = ledger.load_stances()
    resolved = [s for s in settlements if s.is_resolved]

    arena_line = _line_stats("arena", [(s.confidence, bool(s.is_hit)) for s in resolved])

    matched: list[tuple[Any, Any]] = []
    for settlement in resolved:
        stance = stances.get(settlement.challenge_id)
        if stance is not None:
            matched.append((stance, settlement))

    mirror_pairs = [(stance.confidence, stance.direction == settlement.result) for stance, settlement in matched]
    mirror_line = _line_stats("local_mirror", mirror_pairs) if matched else None

    agreement: float | None = None
    if matched:
        agree = sum(1 for stance, settlement in matched if stance.direction == settlement.direction)
        agreement = agree / len(matched)

    notes: list[str] = [
        "arena 线来自平台机械结算，结算规则在出题时冻结，不可回改。",
        "本地镜像线是「提交前冻结」的内部宏观方向判断，用平台冻结结果机械打分；"
        "它衡量的是宏观判断的转写质量，不等价于本框架 A 股个股评级的命中率。",
    ]
    if not settlements:
        notes.append("台账为空：请先运行 `sync` 从 arena 拉取预测历史。")
    if resolved and not matched:
        notes.append(
            "本批已结算预测没有配对的本地镜像判断，`mirror` 一条线为空；后续请在提交前用 `mirror` 子命令冻结内部判断。"
        )
    if resolved and arena_line.n < _MIN_RELIABLE_N:
        notes.append(f"已结算样本仅 {arena_line.n} 条（建议 ≥ {_MIN_RELIABLE_N} 条），结论仅供方向性参考。")
    if mirror_line is not None and mirror_line.n < _MIN_RELIABLE_N:
        notes.append(
            f"本地镜像线仅 {mirror_line.n} 条（建议 ≥ {_MIN_RELIABLE_N} 条），"
            "其命中率与一致率都不足以支撑结论——不要看到 100% 就当成校准良好。"
        )
    if resolved and matched and len(matched) < len(resolved):
        notes.append(f"配对覆盖率 {len(matched)}/{len(resolved)}：未配对的已结算预测不计入镜像线，抽样偏差可能很大。")

    return ReconciliationReport(
        generated_at=generated_at or now_iso(),
        agent_id=agent_id,
        boundary=ASSET_DOMAIN_BOUNDARY,
        arena=arena_line,
        mirror=mirror_line,
        matched_pairs=len(matched),
        agreement_rate=agreement,
        pending=len(settlements) - len(resolved),
        buckets=build_buckets(calibration),
        scorecard=dict(scorecard) if isinstance(scorecard, dict) else {},
        notes=notes,
    )


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def _num(value: float | None, digits: int = 3) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def render_markdown(report: ReconciliationReport) -> str:
    """把比对报告渲染成可供 issue 回帖/文档引用的 Markdown。"""
    lines: list[str] = [
        "# 外部校准比对报告（Headline Arena）",
        "",
        f"> 生成时间：{report.generated_at}" + (f"　|　agent：`{report.agent_id}`" if report.agent_id else ""),
        "",
        f"> ⚠️ **{report.boundary}**",
        "",
        "## 两条线",
        "",
        "| 线 | 已结算样本 | 命中 | 命中率 | 平均置信度 | Brier（越低越校准） |",
        "|---|---:|---:|---:|---:|---:|",
        f"| arena（第三方机械结算） | {report.arena.n} | {report.arena.hits} | "
        f"{_pct(report.arena.hit_rate)} | {_num(report.arena.avg_confidence)} | {_num(report.arena.brier)} |",
    ]
    if report.mirror is not None:
        lines.append(
            f"| 本地镜像（内部宏观判断） | {report.mirror.n} | {report.mirror.hits} | "
            f"{_pct(report.mirror.hit_rate)} | {_num(report.mirror.avg_confidence)} | {_num(report.mirror.brier)} |"
        )
    else:
        lines.append("| 本地镜像（内部宏观判断） | 0 | — | — | — | — |")

    lines += [
        "",
        f"- 配对样本：{report.matched_pairs} 条；未结算：{report.pending} 条。",
        f"- 两条线方向一致率：{_pct(report.agreement_rate)}。",
        "",
        "## 平台公开校准曲线",
        "",
    ]

    if report.buckets:
        lines += [
            "| 置信度分箱 | n | 平均置信度 | 实测命中率 | 偏差（命中率 − 置信度） | 小样本 |",
            "|---|---:|---:|---:|---:|:--:|",
        ]
        for row in report.buckets:
            lines.append(
                f"| {row.bucket} | {row.n} | {_num(row.avg_confidence)} | {_num(row.hit_rate)} | "
                f"{row.gap:+.3f} | {'是' if row.low_sample else ''} |"
            )
        lines += [
            "",
            "> 偏差为正=偏保守（低估自己），为负=过度自信。小样本（n < 5）分箱仅供观察。",
        ]
    else:
        lines.append("_本期没有取到校准曲线（未配置 agent_id，或平台暂无可校准样本）。_")

    if report.scorecard:
        card = report.scorecard
        lines += [
            "",
            "## 平台记分卡",
            "",
            f"- 综合得分：{card.get('overall_score', '—')}　|　排名：{card.get('rank', '—')}"
            f"　|　分位：{card.get('percentile', '—')}　|　趋势：{card.get('trend', '—')}",
            f"- 累计预测：{card.get('total_predictions', '—')} 条。",
        ]

    if report.notes:
        lines += ["", "## 口径说明", ""]
        lines += [f"- {note}" for note in report.notes]

    lines.append("")
    return "\n".join(lines)


__all__ = ["build_buckets", "reconcile", "render_markdown"]
