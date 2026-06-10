"""astock_trader.graph — LangGraph pipeline orchestration layer.

Public API::

    from astock_trader.graph import TradingAgentsGraph

    graph = TradingAgentsGraph(selected_analysts=["market", "news"])
    state, rating = graph.propagate("000001", "2025-06-10")
"""

from astock_trader.graph.conditional_logic import ConditionalLogic
from astock_trader.graph.propagation import Propagator
from astock_trader.graph.reflection import Reflector
from astock_trader.graph.setup import GraphSetup
from astock_trader.graph.signal_processing import SignalProcessor
from astock_trader.graph.trading_graph import TradingAgentsGraph

__all__ = [
    "ConditionalLogic",
    "GraphSetup",
    "Propagator",
    "Reflector",
    "SignalProcessor",
    "TradingAgentsGraph",
]
