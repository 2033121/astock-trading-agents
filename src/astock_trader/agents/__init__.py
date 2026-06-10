"""Agent 模块 — 包含所有角色的 Agent 定义、工厂函数与结构化输出模型。

Agent 通过工厂函数 ``create_xxx(llm)`` 创建，返回可直接用于 LangGraph 的节点函数。
"""

# ── 分析师 ────────────────────────────────────────────────────
from astock_trader.agents.analysts import (
    create_fundamentals_analyst,
    create_market_analyst,
    create_news_analyst,
    create_social_media_analyst,
)

# ── 经理 ──────────────────────────────────────────────────────
from astock_trader.agents.managers import (
    create_portfolio_manager,
    create_research_manager,
)

# ── 研究员 ────────────────────────────────────────────────────
from astock_trader.agents.researchers import (
    create_bear_researcher,
    create_bull_researcher,
)

# ── 风控分析师 ────────────────────────────────────────────────
from astock_trader.agents.risk_mgmt import (
    create_aggressive_debator,
    create_conservative_debator,
    create_neutral_debator,
)
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

# ── 交易员 ────────────────────────────────────────────────────
from astock_trader.agents.trader import (
    create_trader,
    create_trader_for_company,
)

__all__ = [
    # 结构化输出模型
    "PortfolioDecision",
    "PortfolioRating",
    "ResearchPlan",
    "TraderAction",
    "TraderProposal",
    "render_pm_decision",
    "render_research_plan",
    "render_trader_proposal",
    # 分析师工厂
    "create_market_analyst",
    "create_news_analyst",
    "create_social_media_analyst",
    "create_fundamentals_analyst",
    # 研究员工厂
    "create_bull_researcher",
    "create_bear_researcher",
    # 经理工厂
    "create_research_manager",
    "create_portfolio_manager",
    # 交易员工厂
    "create_trader",
    "create_trader_for_company",
    # 风控分析师工厂
    "create_aggressive_debator",
    "create_conservative_debator",
    "create_neutral_debator",
]
