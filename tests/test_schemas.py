"""Tests for astock_trader.agents.schemas — Pydantic models and render functions."""

import pytest
from pydantic import ValidationError

from astock_trader.agents.schemas import (
    PortfolioDecision,
    PortfolioRating,
    ResearchPlan,
    TraderAction,
    TraderProposal,
    render_pm_decision,
    render_research_plan,
    render_trader_proposal,
)


# ────────────────────────────────────────────────────────────────
#  PortfolioRating enum
# ────────────────────────────────────────────────────────────────

class TestPortfolioRating:
    """Tests for the PortfolioRating enum."""

    def test_all_five_ratings_exist(self):
        """五级评级全部存在。"""
        assert PortfolioRating.BUY.value == "买入"
        assert PortfolioRating.OVERWEIGHT.value == "增持"
        assert PortfolioRating.HOLD.value == "持有"
        assert PortfolioRating.UNDERWEIGHT.value == "减持"
        assert PortfolioRating.SELL.value == "卖出"

    def test_enum_count(self):
        """恰好五个评级。"""
        assert len(PortfolioRating) == 5

    def test_enum_is_str(self):
        """枚举值同时是 str 子类。"""
        assert isinstance(PortfolioRating.BUY, str)
        assert PortfolioRating.BUY == "买入"

    def test_enum_lookup_by_value(self):
        """可通过中文值反向查找枚举成员。"""
        assert PortfolioRating("买入") is PortfolioRating.BUY
        assert PortfolioRating("卖出") is PortfolioRating.SELL


# ────────────────────────────────────────────────────────────────
#  TraderAction enum
# ────────────────────────────────────────────────────────────────

class TestTraderAction:
    """Tests for the TraderAction enum."""

    def test_actions(self):
        assert TraderAction.BUY.value == "买入"
        assert TraderAction.HOLD.value == "持有"
        assert TraderAction.SELL.value == "卖出"


# ────────────────────────────────────────────────────────────────
#  ResearchPlan
# ────────────────────────────────────────────────────────────────

class TestResearchPlan:
    """Tests for the ResearchPlan model."""

    def test_creation_with_required_fields(self):
        """使用必填字段创建 ResearchPlan。"""
        plan = ResearchPlan(
            recommendation=PortfolioRating.BUY,
            rationale="技术面 breakout",
            strategic_actions="分批建仓",
        )
        assert plan.recommendation == PortfolioRating.BUY
        assert plan.rationale == "技术面 breakout"
        assert plan.strategic_actions == "分批建仓"

    def test_creation_with_string_rating(self):
        """中文字符串可自动转换为枚举。"""
        plan = ResearchPlan(
            recommendation="增持",
            rationale="基本面良好",
            strategic_actions="逢低加仓",
        )
        assert plan.recommendation is PortfolioRating.OVERWEIGHT

    def test_missing_required_field_raises(self):
        """缺少必填字段应抛出 ValidationError。"""
        with pytest.raises(ValidationError):
            ResearchPlan(recommendation="买入")  # missing rationale & strategic_actions

    def test_invalid_rating_raises(self):
        """无效评级应抛出 ValidationError。"""
        with pytest.raises(ValidationError):
            ResearchPlan(
                recommendation="无效评级",
                rationale="test",
                strategic_actions="test",
            )


# ────────────────────────────────────────────────────────────────
#  TraderProposal
# ────────────────────────────────────────────────────────────────

class TestTraderProposal:
    """Tests for the TraderProposal model."""

    def test_creation_minimal(self):
        """仅必填字段即可创建。"""
        proposal = TraderProposal(
            action=TraderAction.BUY,
            reasoning="看多信号明确",
        )
        assert proposal.action == TraderAction.BUY
        assert proposal.reasoning == "看多信号明确"
        assert proposal.entry_price is None
        assert proposal.stop_loss is None
        assert proposal.position_sizing is None

    def test_creation_with_all_optionals(self):
        """所有可选字段均可设置。"""
        proposal = TraderProposal(
            action="买入",
            reasoning="突破确认",
            entry_price=15.5,
            stop_loss=14.0,
            position_sizing="20%",
        )
        assert proposal.entry_price == 15.5
        assert proposal.stop_loss == 14.0
        assert proposal.position_sizing == "20%"

    def test_optional_fields_default_none(self):
        """可选字段默认为 None。"""
        proposal = TraderProposal(action="持有", reasoning="观望")
        assert proposal.entry_price is None
        assert proposal.stop_loss is None
        assert proposal.position_sizing is None


# ────────────────────────────────────────────────────────────────
#  PortfolioDecision
# ────────────────────────────────────────────────────────────────

class TestPortfolioDecision:
    """Tests for the PortfolioDecision model."""

    def test_creation_with_all_fields(self):
        """使用全部字段创建。"""
        decision = PortfolioDecision(
            rating=PortfolioRating.BUY,
            executive_summary="综合看多",
            investment_thesis="多维度共振",
            price_target=20.0,
            time_horizon="3个月",
        )
        assert decision.rating == PortfolioRating.BUY
        assert decision.executive_summary == "综合看多"
        assert decision.investment_thesis == "多维度共振"
        assert decision.price_target == 20.0
        assert decision.time_horizon == "3个月"

    def test_optional_fields_default_none(self):
        """price_target 和 time_horizon 默认为 None。"""
        decision = PortfolioDecision(
            rating="持有",
            executive_summary="中性",
            investment_thesis="无明显方向",
        )
        assert decision.price_target is None
        assert decision.time_horizon is None


# ────────────────────────────────────────────────────────────────
#  render_research_plan
# ────────────────────────────────────────────────────────────────

class TestRenderResearchPlan:
    """Tests for render_research_plan()."""

    def test_output_contains_rating(self):
        """渲染输出包含 **评级** 标签。"""
        plan = ResearchPlan(
            recommendation="买入",
            rationale="技术突破",
            strategic_actions="分批建仓",
        )
        output = render_research_plan(plan)
        assert "**评级**: 买入" in output

    def test_output_contains_rationale(self):
        """渲染输出包含理由。"""
        plan = ResearchPlan(
            recommendation="增持",
            rationale="基本面持续改善",
            strategic_actions="逐步加仓",
        )
        output = render_research_plan(plan)
        assert "**理由**: 基本面持续改善" in output

    def test_output_contains_strategy(self):
        """渲染输出包含策略建议。"""
        plan = ResearchPlan(
            recommendation="持有",
            rationale="震荡行情",
            strategic_actions="保持观望",
        )
        output = render_research_plan(plan)
        assert "**策略建议**: 保持观望" in output

    def test_output_is_multiline(self):
        """渲染输出是多行文本。"""
        plan = ResearchPlan(
            recommendation="卖出",
            rationale="破位下行",
            strategic_actions="止损离场",
        )
        output = render_research_plan(plan)
        lines = output.strip().split("\n")
        assert len(lines) >= 3


# ────────────────────────────────────────────────────────────────
#  render_trader_proposal
# ────────────────────────────────────────────────────────────────

class TestRenderTraderProposal:
    """Tests for render_trader_proposal()."""

    def test_output_contains_final_proposal_marker(self):
        """渲染输出包含 FINAL TRANSACTION PROPOSAL 标记。"""
        proposal = TraderProposal(
            action="买入",
            reasoning="信号确认",
        )
        output = render_trader_proposal(proposal)
        assert "FINAL TRANSACTION PROPOSAL" in output

    def test_output_contains_action(self):
        """渲染输出包含交易动作。"""
        proposal = TraderProposal(
            action="卖出",
            reasoning="止盈离场",
        )
        output = render_trader_proposal(proposal)
        assert "卖出" in output

    def test_output_includes_optional_fields_when_set(self):
        """可选字段有值时出现在输出中。"""
        proposal = TraderProposal(
            action="买入",
            reasoning="突破",
            entry_price=100.0,
            stop_loss=95.0,
            position_sizing="30%",
        )
        output = render_trader_proposal(proposal)
        assert "入场价" in output
        assert "100.0" in output
        assert "止损价" in output
        assert "95.0" in output
        assert "仓位建议" in output
        assert "30%" in output

    def test_output_excludes_optional_fields_when_none(self):
        """可选字段为 None 时不出现在输出中。"""
        proposal = TraderProposal(
            action="持有",
            reasoning="等待",
        )
        output = render_trader_proposal(proposal)
        assert "入场价" not in output
        assert "止损价" not in output
        assert "仓位建议" not in output


# ────────────────────────────────────────────────────────────────
#  render_pm_decision
# ────────────────────────────────────────────────────────────────

class TestRenderPmDecision:
    """Tests for render_pm_decision()."""

    def test_output_contains_rating_label(self):
        """渲染输出包含 **评级** 标签。"""
        decision = PortfolioDecision(
            rating="买入",
            executive_summary="强烈看多",
            investment_thesis="技术面+基本面共振",
        )
        output = render_pm_decision(decision)
        assert "**评级**" in output
        assert "买入" in output

    def test_output_contains_summary(self):
        """渲染输出包含执行摘要。"""
        decision = PortfolioDecision(
            rating="增持",
            executive_summary="稳健增长",
            investment_thesis="业绩超预期",
        )
        output = render_pm_decision(decision)
        assert "**执行摘要**: 稳健增长" in output

    def test_output_contains_thesis(self):
        """渲染输出包含投资逻辑。"""
        decision = PortfolioDecision(
            rating="减持",
            executive_summary="风险偏高",
            investment_thesis="估值过高",
        )
        output = render_pm_decision(decision)
        assert "**投资逻辑**: 估值过高" in output

    def test_output_includes_price_target_when_set(self):
        """目标价有值时出现在输出中。"""
        decision = PortfolioDecision(
            rating="买入",
            executive_summary="看多",
            investment_thesis="趋势向上",
            price_target=50.0,
        )
        output = render_pm_decision(decision)
        assert "目标价" in output
        assert "50.0" in output

    def test_output_includes_time_horizon_when_set(self):
        """持有周期有值时出现在输出中。"""
        decision = PortfolioDecision(
            rating="持有",
            executive_summary="中性",
            investment_thesis="等待催化",
            time_horizon="6个月",
        )
        output = render_pm_decision(decision)
        assert "持有周期" in output
        assert "6个月" in output

    def test_output_excludes_optional_fields_when_none(self):
        """可选字段为 None 时不出现在输出中。"""
        decision = PortfolioDecision(
            rating="卖出",
            executive_summary="止损",
            investment_thesis="破位",
        )
        output = render_pm_decision(decision)
        assert "目标价" not in output
        assert "持有周期" not in output
