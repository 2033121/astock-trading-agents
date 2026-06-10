"""风控管理 Agent 模块 — 包含激进、保守、中性三方风控分析师。"""

from astock_trader.agents.risk_mgmt.aggressive_debator import create_aggressive_debator
from astock_trader.agents.risk_mgmt.conservative_debator import create_conservative_debator
from astock_trader.agents.risk_mgmt.neutral_debator import create_neutral_debator

__all__ = [
    "create_aggressive_debator",
    "create_conservative_debator",
    "create_neutral_debator",
]
