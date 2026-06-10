"""分析师 Agent 模块 — 包含技术面、新闻、舆情、基本面四个分析师。"""

from astock_trader.agents.analysts.market_analyst import create_market_analyst
from astock_trader.agents.analysts.news_analyst import create_news_analyst
from astock_trader.agents.analysts.social_media_analyst import create_social_media_analyst
from astock_trader.agents.analysts.fundamentals_analyst import create_fundamentals_analyst

__all__ = [
    "create_market_analyst",
    "create_news_analyst",
    "create_social_media_analyst",
    "create_fundamentals_analyst",
]
