"""外部校准接入 — 共享数据结构、来源标记与题域边界声明。

本模块定义本框架与第三方公开记分板（当前唯一候选：Headline Arena，见 issue #1）
对接时共用的数据结构。整个「外部校准」通道的定位是：

    反思闭环已经能用 akshare 拉实际收益自检「预测对不对」；外部校准通道补的是
    一个**不由自己运营**的机械结算记分板，让内部自评多一份外部参照。

三条硬约束（与 issue #1 的约定一致）
------------------------------------
1. **题域边界**：见 :data:`ASSET_DOMAIN_BOUNDARY`。外部结算测的不是 A 股个股判断力，
   任何引用外部校准结果的地方都必须同时呈现该声明。
2. **凭证纪律**：凭据只走环境变量，绝不入 repo；无凭据时全链路优雅降级为无操作。
3. **来源隔离**：第三方机械结算的一切记录都带 :data:`SOURCE_TAG` 标记，写入独立的
   :class:`~astock_trader.external_calibration.ledger.ExternalCalibrationLedger`，
   **不得**写入 :class:`~astock_trader.agents.utils.memory.TradingMemoryLog`。
   内部 akshare 自检与外部结算两套证据分开存放，避免串写。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

# ────────────────────────────────────────────────────────────────
#  来源标记与常量
# ────────────────────────────────────────────────────────────────

SOURCE_TAG = "external_headline_arena"
"""外部结算记录的统一来源标记（issue #1 约束 3）。"""

PROVIDER_HEADLINE_ARENA = "headline_arena"

DEFAULT_BASE_URL = "https://headlinearena.com/api/v1"

DIRECTIONS: tuple[str, ...] = ("bullish", "bearish", "neutral")

Direction = Literal["bullish", "bearish", "neutral"]

# 环境变量名（凭证纪律：只走环境变量，绝不落盘到 repo）
ENV_AGENT_ID = "HEADLINE_ARENA_AGENT_ID"
ENV_CLIENT_SECRET = "HEADLINE_ARENA_CLIENT_SECRET"
ENV_TOKEN = "HEADLINE_ARENA_TOKEN"
ENV_BASE_URL = "HEADLINE_ARENA_BASE_URL"

ASSET_DOMAIN_BOUNDARY = (
    "题域边界：Headline Arena 结算的是宏观期货与官方统计方向（黄金、原油、标普、"
    "美债、铜、美元指数、Civic Index 等），而本框架的预测对象是 A 股个股/ETF 评级。"
    "两条线测的不是同一件事——外部校准曲线反映的是「同一批 agent 换到宏观市场、"
    "换一套结算口径之后的校准度」，属于**通用反作弊参照**，"
    "**不能**作为本框架 A 股个股判断力的裁决。"
)


def now_iso() -> str:
    """当前 UTC 时间的 ISO 8601 字符串（秒级）。"""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ────────────────────────────────────────────────────────────────
#  数据结构
# ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LocalStance:
    """本地镜像判断 —— 在外部结算**之前**冻结记录，事后不可回填。

    试点方案要求「每天向 arena 提交与 agent 内部宏观判断同源的方向性预测」。
    该内部判断必须先落盘、再提交，否则事后无法证明它没有被结算结果反向污染。

    Attributes
    ----------
    challenge_id : str
        对应的 arena challenge 标识，是两条线配对的唯一键。
    asset : str
        标的（如 ``GC``/``CL``/``ES``），仅作可读性用途。
    direction : str
        ``bullish`` / ``bearish`` / ``neutral``。
    confidence : float
        本框架给出的主观概率，0–1。
    rationale : str
        判断依据的简短说明。
    origin : str
        该判断的来源（``macro_assessment`` / ``manual`` / ``analyst_debate``）。
    recorded_at : str
        冻结时间（ISO 8601）。
    source : str
        固定为 :data:`SOURCE_TAG`，保证与内部交易记忆分区。
    """

    challenge_id: str
    direction: str
    confidence: float
    asset: str = ""
    rationale: str = ""
    origin: str = "manual"
    recorded_at: str = ""
    source: str = SOURCE_TAG

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LocalStance:
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass(frozen=True)
class ArenaSettlement:
    """一条 arena 预测及其（机械）结算结果。

    字段与 Headline Arena ``GET /api/v1/eval/agents/{agent_id}/predictions`` 的
    ``PredictionHistoryItem`` 对齐，并附加本框架的溯源信息。
    """

    prediction_id: str
    challenge_id: str
    asset: str
    direction: str
    confidence: float
    created_at: str
    question: str = ""
    result: str | None = None
    """结算结果：``bullish`` / ``bearish`` / ``neutral``；未结算为 ``None``。"""
    is_correct: bool | None = None
    score: float | None = None
    ingested_at: str = ""
    source: str = SOURCE_TAG
    payload: dict[str, Any] = field(default_factory=dict)
    """平台原始返回，完整保留结算溯源（金额/时间戳/分值等）。"""

    @property
    def is_resolved(self) -> bool:
        """是否已由平台机械结算。"""
        return self.result is not None

    @property
    def is_hit(self) -> bool | None:
        """方向是否正确；未结算返回 ``None``。"""
        if not self.is_resolved:
            return None
        if self.is_correct is not None:
            return bool(self.is_correct)
        return self.direction == self.result

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ArenaSettlement:
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def from_api_item(cls, item: dict[str, Any], *, ingested_at: str = "") -> ArenaSettlement:
        """把平台 ``PredictionHistoryItem`` 映射为 :class:`ArenaSettlement`。

        平台字段缺失时不抛异常——无法确定主键的条目由调用方丢弃。
        """
        return cls(
            prediction_id=str(item.get("prediction_id", "")),
            challenge_id=str(item.get("challenge_id", "")),
            asset=str(item.get("asset", "")),
            direction=str(item.get("direction", "")),
            confidence=float(item.get("confidence") or 0.0),
            created_at=str(item.get("created_at", "")),
            question=str(item.get("question") or ""),
            result=item.get("result"),
            is_correct=item.get("is_correct"),
            score=item.get("score"),
            ingested_at=ingested_at or now_iso(),
            source=SOURCE_TAG,
            payload=dict(item),
        )


@dataclass(frozen=True)
class LineStats:
    """一条预测线的机械统计（方向命中率 + 校准度）。"""

    label: str
    n: int = 0
    hits: int = 0
    hit_rate: float | None = None
    avg_confidence: float | None = None
    brier: float | None = None
    """Brier 分数：``mean((confidence - outcome)^2)``，越小越校准。"""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CalibrationBucketRow:
    """平台公开校准曲线上的一个置信度分箱。"""

    bucket: str
    n: int
    avg_confidence: float
    hit_rate: float
    low_sample: bool = False

    @property
    def gap(self) -> float:
        """``命中率 - 平均置信度``；正值=偏保守，负值=过度自信。"""
        return self.hit_rate - self.avg_confidence

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["gap"] = self.gap
        return data


@dataclass
class ReconciliationReport:
    """两条线的比对结果（试点两周后要交付的东西）。"""

    generated_at: str
    agent_id: str = ""
    boundary: str = ASSET_DOMAIN_BOUNDARY
    arena: LineStats = field(default_factory=lambda: LineStats(label="arena"))
    mirror: LineStats | None = None
    matched_pairs: int = 0
    agreement_rate: float | None = None
    pending: int = 0
    buckets: list[CalibrationBucketRow] = field(default_factory=list)
    scorecard: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "agent_id": self.agent_id,
            "boundary": self.boundary,
            "arena": self.arena.to_dict(),
            "mirror": self.mirror.to_dict() if self.mirror else None,
            "matched_pairs": self.matched_pairs,
            "agreement_rate": self.agreement_rate,
            "pending": self.pending,
            "buckets": [b.to_dict() for b in self.buckets],
            "scorecard": self.scorecard,
            "notes": list(self.notes),
        }
