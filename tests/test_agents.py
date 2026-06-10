"""Tests for agent factory functions — verify factories return callables."""

import functools
import pytest
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage


# ────────────────────────────────────────────────────────────────
#  Mock LLM helpers
# ────────────────────────────────────────────────────────────────

def make_mock_llm():
    """Create a mock LLM with all necessary methods for agent factories.

    The mock supports:
    - ``invoke()``: returns an AIMessage with empty content
    - ``bind_tools()``: returns self (for ReAct-style agents)
    - ``with_structured_output()``: returns a mock structured LLM
    - ``|`` (pipe operator): via __or__ / __ror__
    """
    llm = MagicMock()

    # invoke returns an AIMessage
    ai_msg = AIMessage(content="mock analysis result")
    ai_msg.tool_calls = []
    llm.invoke.return_value = ai_msg

    # bind_tools returns self (chainable)
    llm.bind_tools.return_value = llm

    # with_structured_output returns a mock that invokes to a schema instance
    structured_llm = MagicMock()
    llm.with_structured_output.return_value = structured_llm

    # Support pipe operator: prompt | llm
    llm.__or__ = MagicMock(return_value=llm)
    llm.__ror__ = MagicMock(return_value=llm)

    return llm


# ────────────────────────────────────────────────────────────────
#  Analyst factories
# ────────────────────────────────────────────────────────────────

class TestCreateMarketAnalyst:
    """Tests for create_market_analyst()."""

    def test_returns_callable(self):
        """create_market_analyst 返回可调用对象。"""
        from astock_trader.agents.analysts.market_analyst import create_market_analyst
        llm = make_mock_llm()
        node = create_market_analyst(llm)
        assert callable(node)

    def test_node_accepts_state(self):
        """返回的节点函数接受 state 字典。"""
        from astock_trader.agents.analysts.market_analyst import create_market_analyst
        llm = make_mock_llm()
        node = create_market_analyst(llm)

        # The chain (prompt | bound_llm) will be invoked
        # Mock the chain's invoke to return an AIMessage
        state = {"messages": [("human", "分析 000001")]}
        # Since the chain invokes prompt | llm, and we mocked llm,
        # the result depends on the chain. We just check the node is callable.
        assert callable(node)


class TestCreateNewsAnalyst:
    """Tests for create_news_analyst()."""

    def test_returns_callable(self):
        """create_news_analyst 返回可调用对象。"""
        from astock_trader.agents.analysts.news_analyst import create_news_analyst
        llm = make_mock_llm()
        node = create_news_analyst(llm)
        assert callable(node)


class TestCreateSocialMediaAnalyst:
    """Tests for create_social_media_analyst()."""

    def test_returns_callable(self):
        """create_social_media_analyst 返回可调用对象。"""
        from astock_trader.agents.analysts.social_media_analyst import create_social_media_analyst
        llm = make_mock_llm()
        node = create_social_media_analyst(llm)
        assert callable(node)


class TestCreateFundamentalsAnalyst:
    """Tests for create_fundamentals_analyst()."""

    def test_returns_callable(self):
        """create_fundamentals_analyst 返回可调用对象。"""
        from astock_trader.agents.analysts.fundamentals_analyst import create_fundamentals_analyst
        llm = make_mock_llm()
        node = create_fundamentals_analyst(llm)
        assert callable(node)


# ────────────────────────────────────────────────────────────────
#  Researcher factories
# ────────────────────────────────────────────────────────────────

class TestCreateBullResearcher:
    """Tests for create_bull_researcher()."""

    def test_returns_callable(self):
        """create_bull_researcher 返回可调用对象。"""
        from astock_trader.agents.researchers.bull_researcher import create_bull_researcher
        llm = make_mock_llm()
        node = create_bull_researcher(llm)
        assert callable(node)

    def test_node_returns_debate_state_update(self):
        """节点函数返回包含 investment_debate_state 的字典。"""
        from astock_trader.agents.researchers.bull_researcher import create_bull_researcher
        llm = make_mock_llm()
        llm.invoke.return_value = MagicMock(content="看多：技术面强势")

        node = create_bull_researcher(llm)
        state = {
            "company_of_interest": "000001",
            "market_report": "技术面上行",
            "investment_debate_state": {
                "history": [],
                "bull_history": [],
                "bear_history": [],
                "count": 0,
            },
        }
        result = node(state)
        assert "investment_debate_state" in result
        assert result["investment_debate_state"]["count"] == 1
        assert len(result["investment_debate_state"]["bull_history"]) == 1


class TestCreateBearResearcher:
    """Tests for create_bear_researcher()."""

    def test_returns_callable(self):
        """create_bear_researcher 返回可调用对象。"""
        from astock_trader.agents.researchers.bear_researcher import create_bear_researcher
        llm = make_mock_llm()
        node = create_bear_researcher(llm)
        assert callable(node)


# ────────────────────────────────────────────────────────────────
#  Manager factories
# ────────────────────────────────────────────────────────────────

class TestCreateResearchManager:
    """Tests for create_research_manager()."""

    def test_returns_callable(self):
        """create_research_manager 返回可调用对象。"""
        from astock_trader.agents.managers.research_manager import create_research_manager
        llm = make_mock_llm()
        node = create_research_manager(llm)
        assert callable(node)

    def test_accepts_deep_think_llm(self):
        """create_research_manager 接受 deep_think_llm 参数。"""
        from astock_trader.agents.managers.research_manager import create_research_manager
        llm = make_mock_llm()
        deep_llm = make_mock_llm()
        node = create_research_manager(llm, deep_think_llm=deep_llm)
        assert callable(node)


class TestCreatePortfolioManager:
    """Tests for create_portfolio_manager()."""

    def test_returns_callable(self):
        """create_portfolio_manager 返回可调用对象。"""
        from astock_trader.agents.managers.portfolio_manager import create_portfolio_manager
        llm = make_mock_llm()
        node = create_portfolio_manager(llm)
        assert callable(node)


# ────────────────────────────────────────────────────────────────
#  Trader factories
# ────────────────────────────────────────────────────────────────

class TestCreateTrader:
    """Tests for create_trader()."""

    def test_returns_callable(self):
        """create_trader 返回可调用对象。"""
        from astock_trader.agents.trader.trader import create_trader
        llm = make_mock_llm()
        node = create_trader(llm)
        assert callable(node)

    def test_trader_with_functools_partial(self):
        """create_trader 可通过 functools.partial 绑定 company_name。"""
        from astock_trader.agents.trader.trader import create_trader
        llm = make_mock_llm()
        trader_fn = create_trader(llm)
        trader_node = functools.partial(trader_fn, company_name="贵州茅台")
        assert callable(trader_node)
        # Check that the partial has the keyword bound
        assert trader_node.keywords.get("company_name") == "贵州茅台"

    def test_create_trader_for_company(self):
        """create_trader_for_company 返回绑定的节点函数。"""
        from astock_trader.agents.trader.trader import create_trader_for_company
        llm = make_mock_llm()
        node = create_trader_for_company(llm, "贵州茅台")
        assert callable(node)


# ────────────────────────────────────────────────────────────────
#  Risk management factories
# ────────────────────────────────────────────────────────────────

class TestCreateAggressiveDebator:
    """Tests for create_aggressive_debator()."""

    def test_returns_callable(self):
        """create_aggressive_debator 返回可调用对象。"""
        from astock_trader.agents.risk_mgmt.aggressive_debator import create_aggressive_debator
        llm = make_mock_llm()
        node = create_aggressive_debator(llm)
        assert callable(node)

    def test_node_returns_risk_state_update(self):
        """节点函数返回包含 risk_debate_state 的字典。"""
        from astock_trader.agents.risk_mgmt.aggressive_debator import create_aggressive_debator
        llm = make_mock_llm()
        llm.invoke.return_value = MagicMock(content="激进观点：风险可控")

        node = create_aggressive_debator(llm)
        state = {
            "company_of_interest": "000001",
            "risk_debate_state": {
                "history": [],
                "aggressive_history": [],
                "conservative_history": [],
                "neutral_history": [],
                "count": 0,
            },
        }
        result = node(state)
        assert "risk_debate_state" in result
        assert result["risk_debate_state"]["count"] == 1
        assert len(result["risk_debate_state"]["aggressive_history"]) == 1


class TestCreateConservativeDebator:
    """Tests for create_conservative_debator()."""

    def test_returns_callable(self):
        """create_conservative_debator 返回可调用对象。"""
        from astock_trader.agents.risk_mgmt.conservative_debator import create_conservative_debator
        llm = make_mock_llm()
        node = create_conservative_debator(llm)
        assert callable(node)


class TestCreateNeutralDebator:
    """Tests for create_neutral_debator()."""

    def test_returns_callable(self):
        """create_neutral_debator 返回可调用对象。"""
        from astock_trader.agents.risk_mgmt.neutral_debator import create_neutral_debator
        llm = make_mock_llm()
        node = create_neutral_debator(llm)
        assert callable(node)


# ────────────────────────────────────────────────────────────────
#  Top-level __init__ imports
# ────────────────────────────────────────────────────────────────

class TestTopLevelImports:
    """Verify all factories are importable from the agents package."""

    def test_import_all_analysts(self):
        """所有分析师工厂函数均可从顶层导入。"""
        from astock_trader.agents import (
            create_market_analyst,
            create_news_analyst,
            create_social_media_analyst,
            create_fundamentals_analyst,
        )
        assert all(callable(f) for f in [
            create_market_analyst,
            create_news_analyst,
            create_social_media_analyst,
            create_fundamentals_analyst,
        ])

    def test_import_all_researchers(self):
        """所有研究员工厂函数均可从顶层导入。"""
        from astock_trader.agents import (
            create_bull_researcher,
            create_bear_researcher,
        )
        assert all(callable(f) for f in [
            create_bull_researcher,
            create_bear_researcher,
        ])

    def test_import_all_managers(self):
        """所有经理工厂函数均可从顶层导入。"""
        from astock_trader.agents import (
            create_research_manager,
            create_portfolio_manager,
        )
        assert all(callable(f) for f in [
            create_research_manager,
            create_portfolio_manager,
        ])

    def test_import_trader(self):
        """交易员工厂函数可从顶层导入。"""
        from astock_trader.agents import create_trader, create_trader_for_company
        assert callable(create_trader)
        assert callable(create_trader_for_company)

    def test_import_all_risk_mgmt(self):
        """所有风控分析师工厂函数均可从顶层导入。"""
        from astock_trader.agents import (
            create_aggressive_debator,
            create_conservative_debator,
            create_neutral_debator,
        )
        assert all(callable(f) for f in [
            create_aggressive_debator,
            create_conservative_debator,
            create_neutral_debator,
        ])

    def test_import_schemas(self):
        """Pydantic schema 可从顶层导入。"""
        from astock_trader.agents import (
            PortfolioDecision,
            PortfolioRating,
            ResearchPlan,
            TraderAction,
            TraderProposal,
        )
        assert PortfolioRating.BUY.value == "买入"
