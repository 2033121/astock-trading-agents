"""Tests for the LLM node response cache (Token strategy 3)."""

from __future__ import annotations

from types import SimpleNamespace

from astock_trader.llm_clients.semantic_cache import (
    SemanticCache,
    cached_invoke,
    normalize_prompt,
)


class _FakeLLM:
    """Records invoke calls and returns a stub response."""

    def __init__(self) -> None:
        self.calls = 0
        self.model_name = "fake-model"

    def invoke(self, messages):
        self.calls += 1
        return SimpleNamespace(content=f"answer-{self.calls}")


def test_normalize_prompt_folds_whitespace_and_punct() -> None:
    assert normalize_prompt("评级：买入！目标价 ——120 元") == normalize_prompt("评级买入目标价120元")
    assert normalize_prompt("a \n\t b") == "ab"


def test_exact_hit_within_ttl() -> None:
    cache = SemanticCache(ttl_minutes=10)
    llm = _FakeLLM()
    msgs = [("human", "分析贵州茅台 2026-09-11 看多论点")]
    first = cached_invoke(llm, msgs, "Bull Researcher", cache)
    second = cached_invoke(llm, msgs, "Bull Researcher", cache)
    assert first == second == "answer-1"
    assert llm.calls == 1
    assert cache.hits == 1
    assert len(cache) == 1


def test_different_agent_no_cross_hit() -> None:
    cache = SemanticCache()
    llm1, llm2 = _FakeLLM(), _FakeLLM()
    msgs = [("human", "同样的文本")]
    cached_invoke(llm1, msgs, "Bull Researcher", cache)
    cached_invoke(llm2, msgs, "Bear Researcher", cache)
    assert llm1.calls == 1 and llm2.calls == 1


def test_similarity_hit_reuses_response() -> None:
    cache = SemanticCache(ttl_minutes=10, similarity_threshold=0.9)
    llm = _FakeLLM()
    base = "对 600519 的看多论证：" + "毛利率高、品牌护城河深、提价空间充足。" * 30
    msgs1 = [("human", base)]
    msgs2 = [("human", "对  600519 的看多论证：" + "毛利率高、品牌护城河深、提价空间充足。" * 30)]
    first = cached_invoke(llm, msgs1, "Bull Researcher", cache)
    second = cached_invoke(llm, msgs2, "Bull Researcher", cache)
    assert first == second
    assert llm.calls == 1  # near-duplicate did not re-invoke


def test_ttl_expiry_forces_recompute() -> None:
    cache = SemanticCache(ttl_minutes=0.01)  # 0.6 s
    llm = _FakeLLM()
    msgs = [("human", "会过期的提问")]
    cached_invoke(llm, msgs, "Trader", cache)
    import time

    time.sleep(0.8)
    out = cached_invoke(llm, msgs, "Trader", cache)
    assert out == "answer-2" and llm.calls == 2


def test_lru_eviction() -> None:
    cache = SemanticCache(ttl_minutes=10, max_entries=2)
    llm = _FakeLLM()
    for i in range(3):
        cached_invoke(llm, [("human", f"问题 {i}")], "Trader", cache)
    assert llm.calls == 3
    assert len(cache) <= 2
    # evicted oldest entry (问题 0) should miss now
    cached_invoke(llm, [("human", "问题 0")], "Trader", cache)
    assert llm.calls == 4


def test_disabled_cache_passthrough() -> None:
    llm = _FakeLLM()
    msgs = [("human", "无缓存调用")]
    assert cached_invoke(llm, msgs, "Trader", None) == "answer-1"


def test_put_returns_nothing_when_ttl_zero() -> None:
    cache = SemanticCache(ttl_minutes=0)
    cache.put("m", "Trader", [("human", "x")], "y")
    assert len(cache) == 0
