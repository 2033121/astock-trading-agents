"""Tests for astock_trader.graph.conditional_logic — flow control routing."""

import pytest
from unittest.mock import MagicMock

from astock_trader.graph.conditional_logic import ConditionalLogic


# ────────────────────────────────────────────────────────────────
#  Fixtures
# ────────────────────────────────────────────────────────────────

@pytest.fixture
def logic():
    """Default ConditionalLogic with 1 debate round and 1 risk round."""
    return ConditionalLogic(max_debate_rounds=1, max_risk_discuss_rounds=1)


@pytest.fixture
def logic_2_rounds():
    """ConditionalLogic with 2 debate rounds and 2 risk rounds."""
    return ConditionalLogic(max_debate_rounds=2, max_risk_discuss_rounds=2)


def _make_message_with_tool_calls(tool_calls=None):
    """Create a mock AIMessage with tool_calls attribute."""
    msg = MagicMock()
    msg.tool_calls = tool_calls or []
    return msg


def _make_message_without_tool_calls():
    """Create a mock AIMessage without tool_calls."""
    msg = MagicMock(spec=[])  # empty spec = no attributes
    return msg


# ────────────────────────────────────────────────────────────────
#  Analyst tool-loop routing
# ────────────────────────────────────────────────────────────────

class TestShouldContinueMarket:
    """Tests for should_continue_market()."""

    def test_with_tool_calls_returns_tools_market(self, logic):
        """有 tool_calls 时路由到 tools_market。"""
        msg = _make_message_with_tool_calls([{"name": "get_stock_data", "args": {}}])
        state = {"messages": [msg]}
        assert logic.should_continue_market(state) == "tools_market"

    def test_without_tool_calls_returns_msg_clear(self, logic):
        """无 tool_calls 时路由到 Msg Clear Market。"""
        msg = _make_message_with_tool_calls([])  # empty tool_calls
        state = {"messages": [msg]}
        assert logic.should_continue_market(state) == "Msg Clear Market"

    def test_empty_messages_returns_msg_clear(self, logic):
        """空消息列表时路由到 Msg Clear Market。"""
        state = {"messages": []}
        assert logic.should_continue_market(state) == "Msg Clear Market"


class TestShouldContinueSocial:
    """Tests for should_continue_social()."""

    def test_with_tool_calls_returns_tools_social(self, logic):
        """有 tool_calls 时路由到 tools_social。"""
        msg = _make_message_with_tool_calls([{"name": "get_insider", "args": {}}])
        state = {"messages": [msg]}
        assert logic.should_continue_social(state) == "tools_social"

    def test_without_tool_calls_returns_msg_clear(self, logic):
        """无 tool_calls 时路由到 Msg Clear Social。"""
        msg = _make_message_with_tool_calls([])
        state = {"messages": [msg]}
        assert logic.should_continue_social(state) == "Msg Clear Social"


class TestShouldContinueNews:
    """Tests for should_continue_news()."""

    def test_with_tool_calls_returns_tools_news(self, logic):
        """有 tool_calls 时路由到 tools_news。"""
        msg = _make_message_with_tool_calls([{"name": "get_news", "args": {}}])
        state = {"messages": [msg]}
        assert logic.should_continue_news(state) == "tools_news"

    def test_without_tool_calls_returns_msg_clear(self, logic):
        """无 tool_calls 时路由到 Msg Clear News。"""
        msg = _make_message_with_tool_calls([])
        state = {"messages": [msg]}
        assert logic.should_continue_news(state) == "Msg Clear News"


class TestShouldContinueFundamentals:
    """Tests for should_continue_fundamentals()."""

    def test_with_tool_calls_returns_tools_fundamentals(self, logic):
        """有 tool_calls 时路由到 tools_fundamentals。"""
        msg = _make_message_with_tool_calls([{"name": "get_fundamentals", "args": {}}])
        state = {"messages": [msg]}
        assert logic.should_continue_fundamentals(state) == "tools_fundamentals"

    def test_without_tool_calls_returns_msg_clear(self, logic):
        """无 tool_calls 时路由到 Msg Clear Fundamentals。"""
        msg = _make_message_with_tool_calls([])
        state = {"messages": [msg]}
        assert logic.should_continue_fundamentals(state) == "Msg Clear Fundamentals"


# ────────────────────────────────────────────────────────────────
#  Investment debate routing
# ────────────────────────────────────────────────────────────────

class TestShouldContinueDebate:
    """Tests for should_continue_debate()."""

    def test_bullish_prefix_routes_to_bear(self, logic):
        """看多前缀 -> Bear Researcher。"""
        state = {
            "investment_debate_state": {
                "count": 0,
                "current_response": "看多：技术面强势突破",
            }
        }
        assert logic.should_continue_debate(state) == "Bear Researcher"

    def test_bearish_prefix_routes_to_bull(self, logic):
        """看空前缀 -> Bull Researcher。"""
        state = {
            "investment_debate_state": {
                "count": 0,
                "current_response": "看空：估值过高",
            }
        }
        assert logic.should_continue_debate(state) == "Bull Researcher"

    def test_neutral_text_routes_to_bull(self, logic):
        """中性文本（无看多/看空前缀）-> Bull Researcher。"""
        state = {
            "investment_debate_state": {
                "count": 0,
                "current_response": "需要进一步分析",
            }
        }
        assert logic.should_continue_debate(state) == "Bull Researcher"

    def test_count_exceeds_threshold_routes_to_research_manager(self, logic):
        """count >= 2*rounds -> Research Manager。"""
        state = {
            "investment_debate_state": {
                "count": 2,  # 2 >= 2*1
                "current_response": "看多：继续看多",
            }
        }
        assert logic.should_continue_debate(state) == "Research Manager"

    def test_count_at_threshold_routes_to_research_manager(self, logic_2_rounds):
        """count == 2*max_rounds -> Research Manager。"""
        state = {
            "investment_debate_state": {
                "count": 4,  # 4 >= 2*2
                "current_response": "看空：坚持看空",
            }
        }
        assert logic_2_rounds.should_continue_debate(state) == "Research Manager"

    def test_count_below_threshold_continues_debate(self, logic_2_rounds):
        """count < 2*max_rounds 时继续辩论。"""
        state = {
            "investment_debate_state": {
                "count": 3,  # 3 < 2*2=4
                "current_response": "看多：仍然看多",
            }
        }
        assert logic_2_rounds.should_continue_debate(state) == "Bear Researcher"

    def test_empty_state_defaults_to_bull(self, logic):
        """空 state 默认路由到 Bull Researcher。"""
        state = {"investment_debate_state": {}}
        assert logic.should_continue_debate(state) == "Bull Researcher"

    def test_missing_debate_state_defaults_to_bull(self, logic):
        """缺少 debate state 时默认路由到 Bull Researcher。"""
        state = {}
        assert logic.should_continue_debate(state) == "Bull Researcher"


# ────────────────────────────────────────────────────────────────
#  Risk analysis routing
# ────────────────────────────────────────────────────────────────

class TestShouldContinueRiskAnalysis:
    """Tests for should_continue_risk_analysis()."""

    def test_aggressive_speaker_routes_to_conservative(self, logic):
        """激进派发言 -> Conservative Analyst。"""
        state = {
            "risk_debate_state": {
                "count": 1,
                "latest_speaker": "激进派",
            }
        }
        assert logic.should_continue_risk_analysis(state) == "Conservative Analyst"

    def test_conservative_speaker_routes_to_neutral(self, logic):
        """保守派发言 -> Neutral Analyst。"""
        state = {
            "risk_debate_state": {
                "count": 2,
                "latest_speaker": "保守派",
            }
        }
        assert logic.should_continue_risk_analysis(state) == "Neutral Analyst"

    def test_neutral_speaker_routes_to_aggressive(self, logic):
        """中性派发言 -> Aggressive Analyst。"""
        state = {
            "risk_debate_state": {
                "count": 1,
                "latest_speaker": "中性派",
            }
        }
        assert logic.should_continue_risk_analysis(state) == "Aggressive Analyst"

    def test_unknown_speaker_routes_to_aggressive(self, logic):
        """未知发言者 -> Aggressive Analyst（默认）。"""
        state = {
            "risk_debate_state": {
                "count": 1,
                "latest_speaker": "unknown",
            }
        }
        assert logic.should_continue_risk_analysis(state) == "Aggressive Analyst"

    def test_empty_speaker_routes_to_aggressive(self, logic):
        """空发言者 -> Aggressive Analyst。"""
        state = {
            "risk_debate_state": {
                "count": 1,
                "latest_speaker": "",
            }
        }
        assert logic.should_continue_risk_analysis(state) == "Aggressive Analyst"

    def test_count_exceeds_threshold_routes_to_pm(self, logic):
        """count >= 3*rounds -> Portfolio Manager。"""
        state = {
            "risk_debate_state": {
                "count": 3,  # 3 >= 3*1
                "latest_speaker": "激进派",
            }
        }
        assert logic.should_continue_risk_analysis(state) == "Portfolio Manager"

    def test_count_at_threshold_routes_to_pm(self, logic_2_rounds):
        """count == 3*max_rounds -> Portfolio Manager。"""
        state = {
            "risk_debate_state": {
                "count": 6,  # 6 >= 3*2
                "latest_speaker": "保守派",
            }
        }
        assert logic_2_rounds.should_continue_risk_analysis(state) == "Portfolio Manager"

    def test_count_below_threshold_continues_rotation(self, logic_2_rounds):
        """count < 3*max_rounds 时继续轮转。"""
        state = {
            "risk_debate_state": {
                "count": 5,  # 5 < 3*2=6
                "latest_speaker": "保守派",
            }
        }
        assert logic_2_rounds.should_continue_risk_analysis(state) == "Neutral Analyst"

    def test_missing_risk_state_defaults_to_aggressive(self, logic):
        """缺少 risk state 时默认路由到 Aggressive Analyst。"""
        state = {}
        assert logic.should_continue_risk_analysis(state) == "Aggressive Analyst"

    def test_aggressive_prefix_match(self, logic):
        """激进 前缀匹配即可路由。"""
        state = {
            "risk_debate_state": {
                "count": 1,
                "latest_speaker": "激进",  # 仅前缀
            }
        }
        assert logic.should_continue_risk_analysis(state) == "Conservative Analyst"

    def test_conservative_prefix_match(self, logic):
        """保守 前缀匹配即可路由。"""
        state = {
            "risk_debate_state": {
                "count": 1,
                "latest_speaker": "保守",  # 仅前缀
            }
        }
        assert logic.should_continue_risk_analysis(state) == "Neutral Analyst"
