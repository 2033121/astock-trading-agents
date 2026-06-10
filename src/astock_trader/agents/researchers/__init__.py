"""研究员 Agent 模块 — 包含看多研究员和看空研究员。"""

from astock_trader.agents.researchers.bull_researcher import create_bull_researcher
from astock_trader.agents.researchers.bear_researcher import create_bear_researcher

__all__ = [
    "create_bull_researcher",
    "create_bear_researcher",
]
