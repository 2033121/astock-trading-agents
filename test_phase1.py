"""Phase 1 integration test — verify resilience, schemas, and config."""
import sys
import os

# Ensure the package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

passed = 0
failed = 0

def check(name, fn):
    global passed, failed
    try:
        fn()
        print(f"  [PASS] {name}")
        passed += 1
    except Exception as e:
        print(f"  [FAIL] {name}: {e}")
        failed += 1

# ── 1. Resilience module ──
print("\n=== 1. Resilience Module ===")

def test_resilience_import():
    from astock_trader.llm_clients.resilience import ResilientInvoker, CircuitBreakerOpen
    invoker = ResilientInvoker(max_retries=2, base_delay=1, max_delay=5)
    assert invoker.max_retries == 2

check("ResilientInvoker import + init", test_resilience_import)

def test_circuit_breaker():
    from astock_trader.llm_clients.resilience import _CircuitBreaker
    cb = _CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
    assert cb.state == "CLOSED"
    assert cb.allow_request() == True
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "OPEN"
    assert cb.allow_request() == False
    import time; time.sleep(0.15)
    assert cb.state == "HALF_OPEN"
    assert cb.allow_request() == True
    cb.record_success()
    assert cb.state == "CLOSED"

check("CircuitBreaker state transitions", test_circuit_breaker)

def test_is_retryable():
    from astock_trader.llm_clients.resilience import _is_retryable
    assert _is_retryable(TimeoutError("test")) == True
    assert _is_retryable(ConnectionError("test")) == True
    assert _is_retryable(ValueError("test")) == False
    assert _is_retryable(RuntimeError("rate limit exceeded")) == True

check("_is_retryable exception classification", test_is_retryable)

def test_safe_invoke_with_mock():
    from astock_trader.llm_clients.resilience import safe_invoke
    class MockLLM:
        def invoke(self, messages):
            class R:
                content = "mock response"
            return R()
    result = safe_invoke(MockLLM(), [("human", "hi")], "test_agent")
    assert result == "mock response"

check("safe_invoke with mock LLM", test_safe_invoke_with_mock)

# ── 2. Pydantic Schemas ──
print("\n=== 2. Pydantic Schemas ===")

def test_market_signal():
    from astock_trader.agents.schemas import MarketSignal
    s = MarketSignal(trend="上涨趋势", summary="测试概述")
    assert s.trend == "上涨趋势"
    assert s.volume_signal == "正常"

check("MarketSignal model", test_market_signal)

def test_sentiment_signal():
    from astock_trader.agents.schemas import SentimentSignal
    s = SentimentSignal(sentiment_score=0.5, summary="情绪偏乐观")
    assert s.sentiment_score == 0.5
    assert s.sentiment_trend == "稳定"

check("SentimentSignal model", test_sentiment_signal)

def test_news_signal():
    from astock_trader.agents.schemas import NewsSignal
    s = NewsSignal(news_sentiment="利好", key_events=["政策利好"], summary="test")
    assert s.news_sentiment == "利好"

check("NewsSignal model", test_news_signal)

def test_fundamental_signal():
    from astock_trader.agents.schemas import FundamentalSignal
    s = FundamentalSignal(pe_ratio=15.2, valuation="合理", summary="估值合理")
    assert s.pe_ratio == 15.2

check("FundamentalSignal model", test_fundamental_signal)

def test_analyst_consensus():
    from astock_trader.agents.schemas import AnalystConsensus, PortfolioRating
    c = AnalystConsensus(
        bullish_signals=["技术面看涨"],
        bearish_signals=["估值偏高"],
        consensus_direction=PortfolioRating.OVERWEIGHT,
        confidence=0.7,
    )
    assert c.consensus_direction == PortfolioRating.OVERWEIGHT

check("AnalystConsensus model", test_analyst_consensus)

# ── 3. Robust Parsers ──
print("\n=== 3. Robust Parsers ===")

def test_parse_market_json():
    from astock_trader.agents.schemas import parse_market_signal
    raw = '{"trend": "上涨趋势", "support_level": 10.5, "resistance_level": 12.3, "summary": "技术面看涨"}'
    s = parse_market_signal(raw)
    assert s.trend == "上涨趋势"
    assert s.support_level == 10.5

check("parse_market_signal (JSON)", test_parse_market_json)

def test_parse_market_freetext():
    from astock_trader.agents.schemas import parse_market_signal
    raw = "当前股价处于上升趋势，支撑位约15.20元，阻力位在18.50元附近，成交量呈现放量态势"
    s = parse_market_signal(raw)
    assert s.trend == "上涨趋势"
    assert s.volume_signal == "放量"

check("parse_market_signal (free text)", test_parse_market_freetext)

def test_parse_sentiment_freetext():
    from astock_trader.agents.schemas import parse_sentiment_signal
    raw = "市场情绪正在改善，投资者信心回暖，情绪分数约0.3"
    s = parse_sentiment_signal(raw)
    assert s.sentiment_trend == "改善"

check("parse_sentiment_signal (free text)", test_parse_sentiment_freetext)

def test_parse_fundamental_pe():
    from astock_trader.agents.schemas import parse_fundamental_signal
    raw = "当前PE为25.3倍，PB约3.2倍，ROE达到18.5%，整体估值偏高"
    s = parse_fundamental_signal(raw)
    assert s.pe_ratio == 25.3
    assert s.pb_ratio == 3.2
    assert s.roe == 18.5
    assert s.valuation == "高估"

check("parse_fundamental_signal (PE/PB/ROE extraction)", test_parse_fundamental_pe)

def test_parse_news_markdown_block():
    from astock_trader.agents.schemas import parse_news_signal
    raw = '```json\n{"news_sentiment": "利好", "key_events": ["降准"], "summary": "政策利好"}\n```'
    s = parse_news_signal(raw)
    assert s.news_sentiment == "利好"
    assert "降准" in s.key_events

check("parse_news_signal (markdown block)", test_parse_news_markdown_block)

# ── 4. Config ──
print("\n=== 4. Default Config ===")

def test_config_keys():
    from astock_trader.default_config import DEFAULT_CONFIG
    assert DEFAULT_CONFIG["llm_max_retries"] == 3
    assert DEFAULT_CONFIG["circuit_breaker_threshold"] == 5
    assert DEFAULT_CONFIG["circuit_breaker_cooldown"] == 30
    assert DEFAULT_CONFIG["llm_retry_base_delay"] == 4
    assert DEFAULT_CONFIG["llm_retry_max_delay"] == 60

check("New config keys present", test_config_keys)

# ── 5. Existing models still work ──
print("\n=== 5. Backward Compatibility ===")

def test_existing_models():
    from astock_trader.agents.schemas import (
        ResearchPlan, TraderProposal, PortfolioDecision,
        PortfolioRating, TraderAction,
        render_research_plan, render_trader_proposal, render_pm_decision,
    )
    plan = ResearchPlan(
        recommendation=PortfolioRating.BUY,
        rationale="测试理由",
        strategic_actions="测试策略",
    )
    text = render_research_plan(plan)
    assert "买入" in text

    proposal = TraderProposal(
        action=TraderAction.BUY,
        reasoning="测试",
        entry_price=10.0,
    )
    text = render_trader_proposal(proposal)
    assert "FINAL TRANSACTION PROPOSAL" in text

check("Existing models + render functions", test_existing_models)

# ── Summary ──
print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed out of {passed+failed} tests")
if failed > 0:
    sys.exit(1)
else:
    print("All tests passed!")
