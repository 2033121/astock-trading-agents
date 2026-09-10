"""Guard tests for the shared system prompt prefix (Token strategy 2B).

The prefix must stay byte-stable across all 11 LLM nodes so providers can hit
their prompt/KV cache; these tests catch accidental re-wiring or a node that
stopped using the prefix.
"""

from __future__ import annotations

import pathlib

import pytest

from astock_trader.agents.utils.prompt_prefix import SYSTEM_PREFIX

_AGENTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "src" / "astock_trader" / "agents"

# 11 LLM nodes: 4 analysts + 2 debaters + 3 risk debators + 2 managers + trader
_ANALYSTS = [
    "analysts/fundamentals_analyst.py",
    "analysts/market_analyst.py",
    "analysts/news_analyst.py",
    "analysts/social_media_analyst.py",
]
_INVOKE_FILES = [
    "researchers/bull_researcher.py",
    "researchers/bear_researcher.py",
    "risk_mgmt/aggressive_debator.py",
    "risk_mgmt/conservative_debator.py",
    "risk_mgmt/neutral_debator.py",
    "managers/research_manager.py",
    "managers/portfolio_manager.py",
    "trader/trader.py",
]


def test_prefix_is_substantial_and_placeholder_free() -> None:
    assert len(SYSTEM_PREFIX) >= 100
    assert "{" not in SYSTEM_PREFIX  # 防意外进入 f-string 格式化占位符


@pytest.mark.parametrize("rel", _ANALYSTS + _INVOKE_FILES)
def test_every_node_references_prefix(rel: str) -> None:
    text = (_AGENTS_DIR / rel).read_text(encoding="utf-8")
    assert "from astock_trader.agents.utils.prompt_prefix import SYSTEM_PREFIX" in text
    assert "SYSTEM_PREFIX" in text


@pytest.mark.parametrize("rel", _INVOKE_FILES)
def test_invoke_sites_put_system_prefix_first(rel: str) -> None:
    """human-only 节点必须是 [("system", SYSTEM_PREFIX), ("human", ...)] 顺序。"""
    text = (_AGENTS_DIR / rel).read_text(encoding="utf-8")
    flat = "".join(text.split())
    assert (
        'llm.invoke([("system",SYSTEM_PREFIX),("human"' in flat
        or 'prompt_messages=[("system",SYSTEM_PREFIX),("human"' in flat
    )


@pytest.mark.parametrize("rel", _ANALYSTS)
def test_analyst_system_starts_with_prefix(rel: str) -> None:
    """分析师节点在 system 模板中以 SYSTEM_PREFIX 拼接开头。"""
    text = (_AGENTS_DIR / rel).read_text(encoding="utf-8")
    assert '"system",' in text
    assert 'SYSTEM_PREFIX + "\\n\\n" +' in text
