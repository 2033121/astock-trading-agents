"""Tests for the PM deterministic decision matrix (Token strategy 2A)."""

from __future__ import annotations

from astock_trader.agents.managers.portfolio_manager import (
    _build_decision_matrix,
    _extract_numbers,
    _rating_direction,
)


def _state() -> dict:
    return {
        "investment_plan": "建议增持，目标价 120 元，预期收益 15%，止损 8%。",
        "trader_investment_plan": "分三档仓位建仓（30/40/30），首笔止损价位 9.80 元。",
        "risk_debate_state": {
            "aggressive_history": ["激进派认为该股仍在突破趋势中，建议加大仓位。"],
            "conservative_history": ["保守派强调高估值风险，上行空间不足，建议止损。"],
            "neutral_history": ["中性派认为评级应保守，建议持有。"],
        },
        "past_context": "上次操作：2026-06 收益 5%，评级持有。",
    }


def test_rating_direction_by_rating_text() -> None:
    assert _rating_direction("建议增持，目标价 100") == "看多"
    assert _rating_direction("评级：减持") == "看空"
    assert _rating_direction("给出行持有评级") == "中性"


def test_extract_numbers_filters_value_lines() -> None:
    nums = _extract_numbers(" ## 方案\n买入目标价 12.5 元\n风险提示无数字\n预期止损 10%")
    assert any("目标价 12.5" in n for n in nums)
    assert any("止损 10%" in n for n in nums)


def test_matrix_contains_direction_counts_and_sources() -> None:
    matrix = _build_decision_matrix(_state())
    assert "决策矩阵" in matrix
    assert "方向分布" in matrix
    assert "研究员投资方案" in matrix and "交易员交易计划" in matrix
    assert "激进派风控：看多" in matrix or "激进派风控：中性" in matrix
    assert "目标价 12.5" in matrix or "止损 8%" in matrix


def test_matrix_sources_match_directions() -> None:
    matrix = _build_decision_matrix(_state())
    # 保守派应判为看空方向
    assert "保守派风控：看空" in matrix
    # 中性派探究
    assert "中性派风控：中性" in matrix


def test_matrix_empty_state() -> None:
    assert _build_decision_matrix({}) == ""
