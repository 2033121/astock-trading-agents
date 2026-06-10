"""Pydantic structured output schemas — 结构化输出模型与渲染函数。

所有模型均使用 Pydantic v2 语法。
渲染函数将模型实例转换为中文 Markdown 字符串，供 Agent 消息传递使用。
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

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
    entry_price: Optional[float] = Field(description="建议入场价", default=None)
    stop_loss: Optional[float] = Field(description="止损价", default=None)
    position_sizing: Optional[str] = Field(description="仓位建议", default=None)


class PortfolioDecision(BaseModel):
    """基金经理最终投决。"""

    rating: PortfolioRating = Field(description="最终评级")
    executive_summary: str = Field(description="执行摘要")
    investment_thesis: str = Field(description="投资逻辑")
    price_target: Optional[float] = Field(description="目标价", default=None)
    time_horizon: Optional[str] = Field(description="持有周期", default=None)


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
