"""Pydantic structured output schemas — 结构化输出模型与渲染函数。

所有模型均使用 Pydantic v2 语法。
渲染函数将模型实例转换为中文 Markdown 字符串，供 Agent 消息传递使用。
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

# ────────────────────────────────────────────────────────────
#  枚举定义
# ────────────────────────────────────────────────────────────


class PortfolioRating(str, Enum):
    """投资组合评级（中文枚举值）。"""

    BUY = "买入"
    OVERWEIGHT = "增持"
    HOLD = "持有"
    UNDERWEIGHT = "减持"
    SELL = "卖出"


class TraderAction(str, Enum):
    """交易员动作。"""

    BUY = "买入"
    HOLD = "持有"
    SELL = "卖出"


# ────────────────────────────────────────────────────────────
#  结构化模型
# ────────────────────────────────────────────────────────────


class ResearchPlan(BaseModel):
    """研究员投资方案（辩论后产出）。"""

    recommendation: PortfolioRating = Field(description="投资评级")
    rationale: str = Field(description="推荐理由")
    strategic_actions: str = Field(description="策略建议")


class TraderProposal(BaseModel):
    """交易员具体交易提案。"""

    action: TraderAction = Field(description="交易动作")
    reasoning: str = Field(description="交易理由")
    entry_price: float | None = Field(description="建议入场价", default=None)
    stop_loss: float | None = Field(description="止损价", default=None)
    position_sizing: str | None = Field(description="仓位建议", default=None)


class PortfolioDecision(BaseModel):
    """基金经理最终投决。"""

    rating: PortfolioRating = Field(description="最终评级")
    executive_summary: str = Field(description="执行摘要")
    investment_thesis: str = Field(description="投资逻辑")
    price_target: float | None = Field(description="目标价", default=None)
    time_horizon: str | None = Field(description="持有周期", default=None)


# ────────────────────────────────────────────────────────────
#  渲染函数 — 将模型实例转换为中文 Markdown
# ────────────────────────────────────────────────────────────


def render_research_plan(plan: ResearchPlan) -> str:
    """将研究员方案渲染为中文 Markdown。"""
    lines = [
        f"**评级**: {plan.recommendation.value}",
        f"**理由**: {plan.rationale}",
        f"**策略建议**: {plan.strategic_actions}",
    ]
    return "\n\n".join(lines)


def render_trader_proposal(proposal: TraderProposal) -> str:
    """将交易员提案渲染为中文 Markdown。

    保留 ``FINAL TRANSACTION PROPOSAL`` 英文标记以确保与上游系统兼容。
    """
    action_label = proposal.action.value  # 买入 / 持有 / 卖出
    lines = [
        f"FINAL TRANSACTION PROPOSAL: **{action_label}**",
        "",
        f"**交易动作**: {action_label}",
        f"**交易理由**: {proposal.reasoning}",
    ]
    if proposal.entry_price is not None:
        lines.append(f"**建议入场价**: {proposal.entry_price}")
    if proposal.stop_loss is not None:
        lines.append(f"**止损价**: {proposal.stop_loss}")
    if proposal.position_sizing is not None:
        lines.append(f"**仓位建议**: {proposal.position_sizing}")
    return "\n".join(lines)


def render_pm_decision(decision: PortfolioDecision) -> str:
    """将基金经理最终决策渲染为中文 Markdown。"""
    lines = [
        f"**评级**: {decision.rating.value}",
        f"**执行摘要**: {decision.executive_summary}",
        f"**投资逻辑**: {decision.investment_thesis}",
    ]
    if decision.price_target is not None:
        lines.append(f"**目标价**: {decision.price_target}")
    if decision.time_horizon is not None:
        lines.append(f"**持有周期**: {decision.time_horizon}")
    return "\n\n".join(lines)


# ────────────────────────────────────────────────────────────
#  分析师结构化输出模型 (v0.3)
# ────────────────────────────────────────────────────────────


class MarketSignal(BaseModel):
    """技术面分析师结构化输出。"""

    trend: Literal["上涨趋势", "震荡", "下跌趋势"] = Field(description="趋势判断")
    support_level: float | None = Field(default=None, description="支撑位")
    resistance_level: float | None = Field(default=None, description="阻力位")
    volume_signal: Literal["放量", "缩量", "正常"] = Field(default="正常", description="量能信号")
    key_indicators: dict[str, float] = Field(default_factory=dict, description="关键指标 MACD/RSI/KDJ 等")
    risk_warnings: list[str] = Field(default_factory=list, description="风险提示")
    summary: str = Field(description="50-100字概述")


class SentimentSignal(BaseModel):
    """舆情分析师结构化输出。"""

    sentiment_score: float = Field(default=0.0, ge=-1.0, le=1.0, description="情绪分数 -1(极恐慌)~+1(极贪婪)")
    hot_topics: list[str] = Field(default_factory=list, description="热门话题")
    risk_events: list[str] = Field(default_factory=list, description="风险事件")
    sentiment_trend: Literal["改善", "稳定", "恶化"] = Field(default="稳定", description="情绪趋势")
    summary: str = Field(description="50-100字概述")


class NewsSignal(BaseModel):
    """新闻分析师结构化输出。"""

    news_sentiment: Literal["利好", "中性", "利空"] = Field(description="新闻情绪")
    key_events: list[str] = Field(default_factory=list, description="关键事件")
    policy_impact: str = Field(default="", description="政策影响分析")
    upcoming_events: list[str] = Field(default_factory=list, description="即将发生的重要事件")
    summary: str = Field(description="50-100字概述")


class FundamentalSignal(BaseModel):
    """基本面分析师结构化输出。"""

    pe_ratio: float | None = Field(default=None, description="市盈率")
    pb_ratio: float | None = Field(default=None, description="市净率")
    roe: float | None = Field(default=None, description="ROE (%)")
    revenue_growth: float | None = Field(default=None, description="营收增长率 (%)")
    net_profit_growth: float | None = Field(default=None, description="净利润增长率 (%)")
    valuation: Literal["低估", "合理", "高估"] = Field(default="合理", description="估值判断")
    industry_position: str = Field(default="", description="行业地位描述")
    industry_chain: list[str] = Field(default_factory=list, description="产业链上下游")
    summary: str = Field(description="50-100字概述")


class AnalystConsensus(BaseModel):
    """分析师共识汇总（研究经理裁判阶段产出）。"""

    bullish_signals: list[str] = Field(default_factory=list, description="看多信号")
    bearish_signals: list[str] = Field(default_factory=list, description="看空信号")
    consensus_direction: PortfolioRating = Field(description="共识方向")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="置信度")
    key_risks: list[str] = Field(default_factory=list, description="关键风险")


# ────────────────────────────────────────────────────────────
#  鲁棒解析器 (v0.3)
# ────────────────────────────────────────────────────────────

# Aliases for Chinese/English field name mapping
_TREND_ALIASES = {
    "上涨": "上涨趋势",
    "上涨趋势": "上涨趋势",
    "上升趋势": "上涨趋势",
    "bullish": "上涨趋势",
    "震荡": "震荡",
    "盘整": "震荡",
    "横盘": "震荡",
    "neutral": "震荡",
    "sideways": "震荡",
    "下跌": "下跌趋势",
    "下跌趋势": "下跌趋势",
    "下降趋势": "下跌趋势",
    "bearish": "下跌趋势",
}

_VOLUME_ALIASES = {
    "放量": "放量",
    "增量": "放量",
    "volume up": "放量",
    "缩量": "缩量",
    "减量": "缩量",
    "volume down": "缩量",
    "正常": "正常",
    "平稳": "正常",
    "normal": "正常",
}

_VALUATION_ALIASES = {
    "低估": "低估",
    "偏低": "低估",
    "undervalued": "低估",
    "合理": "合理",
    "fair": "合理",
    "fair value": "合理",
    "高估": "高估",
    "偏高": "高估",
    "overvalued": "高估",
}

_NEWS_SENTIMENT_ALIASES = {
    "利好": "利好",
    "正面": "利好",
    "positive": "利好",
    "bullish": "利好",
    "中性": "中性",
    "neutral": "中性",
    "利空": "利空",
    "负面": "利空",
    "negative": "利空",
    "bearish": "利空",
}


def _extract_json_block(raw: str) -> dict | None:
    """尝试从 LLM 输出中提取 JSON 对象。

    Strategy:
    1. Direct JSON parse
    2. Markdown code block extraction
    3. First { ... } match
    """
    import json as _json

    # 1. Direct parse
    try:
        return _json.loads(raw)
    except (_json.JSONDecodeError, TypeError):
        pass

    # 2. Markdown code block
    code_re = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)
    m = code_re.search(raw)
    if m:
        try:
            return _json.loads(m.group(1).strip())
        except (_json.JSONDecodeError, TypeError):
            pass

    # 3. First balanced braces
    brace = re.search(r"\{.*\}", raw, re.DOTALL)
    if brace:
        try:
            return _json.loads(brace.group(0))
        except (_json.JSONDecodeError, TypeError):
            pass

    return None


def _safe_float(val) -> float | None:
    """Safely convert to float, return None on failure."""
    if val is None:
        return None
    try:
        s = str(val).replace(",", "").replace("％", "%").replace("%", "")
        return float(s)
    except (ValueError, TypeError):
        return None


def _alias_resolve(value: str, alias_map: dict[str, str], default: str) -> str:
    """Resolve a value through an alias map (case-insensitive)."""
    if not value:
        return default
    normalized = value.strip().lower()
    for key, target in alias_map.items():
        if key.lower() in normalized or normalized in key.lower():
            return target
    return default


def parse_market_signal(raw: str) -> MarketSignal:
    """鲁棒解析技术面分析师输出为 MarketSignal。

    支持：纯 JSON、markdown code block、自由文本关键词提取。
    """
    data = _extract_json_block(raw)
    if data and isinstance(data, dict):
        # Normalize fields via aliases
        if "trend" in data:
            data["trend"] = _alias_resolve(str(data["trend"]), _TREND_ALIASES, "震荡")
        if "volume_signal" in data:
            data["volume_signal"] = _alias_resolve(str(data["volume_signal"]), _VOLUME_ALIASES, "正常")
        # Ensure summary exists
        if not data.get("summary"):
            data["summary"] = raw[:200]
        try:
            return MarketSignal.model_validate(data)
        except Exception:
            pass  # Fall through to text extraction

    # Fallback: extract from free text
    trend = _alias_resolve(raw, _TREND_ALIASES, "震荡")
    volume = _alias_resolve(raw, _VOLUME_ALIASES, "正常")

    # Try to extract numbers
    support = None
    resistance = None
    num_pattern = re.findall(r"[\d,]+\.?\d*", raw)
    if len(num_pattern) >= 2:
        support = _safe_float(num_pattern[0])
        resistance = _safe_float(num_pattern[1])

    return MarketSignal(
        trend=trend,
        support_level=support,
        resistance_level=resistance,
        volume_signal=volume,
        summary=raw[:200].strip(),
    )


def parse_sentiment_signal(raw: str) -> SentimentSignal:
    """鲁棒解析舆情分析师输出。"""
    data = _extract_json_block(raw)
    if data and isinstance(data, dict):
        if not data.get("summary"):
            data["summary"] = raw[:200]
        try:
            return SentimentSignal.model_validate(data)
        except Exception:
            pass

    # Fallback
    score = 0.0
    score_match = re.search(r"([-+]?\d+\.?\d*)", raw)
    if score_match:
        val = _safe_float(score_match.group(1))
        if val is not None and -1 <= val <= 1:
            score = val

    trend = "稳定"
    if any(w in raw for w in ("改善", "好转", "回暖", "积极")):
        trend = "改善"
    elif any(w in raw for w in ("恶化", "恐慌", "担忧", "消极")):
        trend = "恶化"

    return SentimentSignal(
        sentiment_score=score,
        sentiment_trend=trend,
        summary=raw[:200].strip(),
    )


def parse_news_signal(raw: str) -> NewsSignal:
    """鲁棒解析新闻分析师输出。"""
    data = _extract_json_block(raw)
    if data and isinstance(data, dict):
        if "news_sentiment" in data:
            data["news_sentiment"] = _alias_resolve(
                str(data["news_sentiment"]), _NEWS_SENTIMENT_ALIASES, "中性"
            )
        if not data.get("summary"):
            data["summary"] = raw[:200]
        try:
            return NewsSignal.model_validate(data)
        except Exception:
            pass

    # Fallback
    sentiment = _alias_resolve(raw, _NEWS_SENTIMENT_ALIASES, "中性")
    return NewsSignal(
        news_sentiment=sentiment,
        summary=raw[:200].strip(),
    )


def parse_fundamental_signal(raw: str) -> FundamentalSignal:
    """鲁棒解析基本面分析师输出。"""
    data = _extract_json_block(raw)
    if data and isinstance(data, dict):
        if "valuation" in data:
            data["valuation"] = _alias_resolve(
                str(data["valuation"]), _VALUATION_ALIASES, "合理"
            )
        if not data.get("summary"):
            data["summary"] = raw[:200]
        try:
            return FundamentalSignal.model_validate(data)
        except Exception:
            pass

    # Fallback: keyword extraction
    valuation = _alias_resolve(raw, _VALUATION_ALIASES, "合理")

    # Try to extract PE/PB/ROE from text
    pe = None
    pb = None
    roe = None
    pe_match = re.search(r"(?:PE|市盈率)[^\d]*([\d,]+\.?\d*)", raw, re.IGNORECASE)
    pb_match = re.search(r"(?:PB|市净率)[^\d]*([\d,]+\.?\d*)", raw, re.IGNORECASE)
    roe_match = re.search(r"(?:ROE|净资产收益率)[^\d]*([\d,]+\.?\d*)", raw, re.IGNORECASE)
    if pe_match:
        pe = _safe_float(pe_match.group(1))
    if pb_match:
        pb = _safe_float(pb_match.group(1))
    if roe_match:
        roe = _safe_float(roe_match.group(1))

    return FundamentalSignal(
        pe_ratio=pe,
        pb_ratio=pb,
        roe=roe,
        valuation=valuation,
        summary=raw[:200].strip(),
    )
