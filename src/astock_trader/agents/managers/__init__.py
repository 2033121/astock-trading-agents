"""经理 Agent 模块 — 包含研究经理和组合经理。"""

from astock_trader.agents.managers.portfolio_manager import create_portfolio_manager
from astock_trader.agents.managers.research_manager import create_research_manager

__all__ = [
    "create_research_manager",
    "create_portfolio_manager",
]
