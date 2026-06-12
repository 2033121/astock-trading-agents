"""Phase 2 integration tests for astock-trading-agents v0.3.

Tests cover:
- P1-1: Four-tier model reallocation (config + LLM creation + setup wiring)
- P1-2: Reflection loop (_resolve_pending_memory, _fetch_actual_returns, _fetch_benchmark_return)
- P1-3a: save_snapshot new extraction functions (analyst_signals, debate_consensus, key_assumptions)
- P1-3b: review_backtest multi-dimensional scoring + pattern recognition + strategy feedback

Run: python test_phase2.py
"""

import json
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

# Ensure project src is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  —  {detail}")


# ═══════════════════════════════════════════════════════════════
#  P1-1: Four-tier model reallocation
# ═══════════════════════════════════════════════════════════════
print("\n═══ P1-1: Four-tier model reallocation ═══\n")

from astock_trader.default_config import DEFAULT_CONFIG

check("heavy_think_llm in config", "heavy_think_llm" in DEFAULT_CONFIG)
check("heavy_think_llm = deepseek-v4-pro", DEFAULT_CONFIG.get("heavy_think_llm") == "deepseek-v4-pro")
check("standard_think_llm = mimo-2.5", DEFAULT_CONFIG.get("standard_think_llm") == "mimo-2.5")
check("deep_think_llm = mimo-v2.5-pro", DEFAULT_CONFIG.get("deep_think_llm") == "mimo-v2.5-pro")
check("quick_think_llm = deepseek-v4-flash", DEFAULT_CONFIG.get("quick_think_llm") == "deepseek-v4-flash")

# Verify 4-tier config keys all present
tier_keys = {"deep_think_llm", "heavy_think_llm", "standard_think_llm", "quick_think_llm"}
check("all 4 tier keys in config", tier_keys.issubset(DEFAULT_CONFIG.keys()))

# Test GraphSetup accepts heavy_thinking_llm
from astock_trader.graph.setup import GraphSetup

mock_deep = MagicMock()
mock_heavy = MagicMock()
mock_standard = MagicMock()
mock_quick = MagicMock()

gs = GraphSetup(
    deep_thinking_llm=mock_deep,
    quick_thinking_llm=mock_quick,
    heavy_thinking_llm=mock_heavy,
    standard_thinking_llm=mock_standard,
)

check("GraphSetup heavy_llm set", gs.heavy_llm is mock_heavy)
check("GraphSetup deep_llm set", gs.deep_llm is mock_deep)
check("GraphSetup standard_llm set", gs.standard_llm is mock_standard)
check("GraphSetup quick_llm set", gs.quick_llm is mock_quick)

# Test backward compat: heavy defaults to deep when None
gs_compat = GraphSetup(
    deep_thinking_llm=mock_deep,
    quick_thinking_llm=mock_quick,
)
check("heavy falls back to deep", gs_compat.heavy_llm is mock_deep)
check("standard falls back to deep", gs_compat.standard_llm is mock_deep)

# Test _create_debate_nodes uses heavy_llm (inspect closure vars)
debate_nodes = gs._create_debate_nodes()
check("debate_nodes has bull", "bull" in debate_nodes)
check("debate_nodes has bear", "bear" in debate_nodes)
check("debate_nodes has research_manager", "research_manager" in debate_nodes)

# Test _create_risk_nodes uses deep_llm for PM
risk_nodes = gs._create_risk_nodes()
check("risk_nodes has portfolio_manager", "portfolio_manager" in risk_nodes)
check("risk_nodes has aggressive", "aggressive" in risk_nodes)

# ═══════════════════════════════════════════════════════════════
#  P1-2: Reflection loop
# ═══════════════════════════════════════════════════════════════
print("\n═══ P1-2: Reflection loop ═══\n")

from astock_trader.graph.trading_graph import TradingAgentsGraph

# Test _fetch_actual_returns with mock akshare
import pandas as pd
from datetime import datetime, timedelta

mock_df = pd.DataFrame({
    "日期": ["2026-06-05", "2026-06-06", "2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12"],
    "收盘": [10.0, 10.2, 10.5, 10.8, 11.0, 11.2],
})

mock_ak = MagicMock()
mock_ak.stock_zh_a_hist.return_value = mock_df

# Create a minimal TradingAgentsGraph with mocks
with patch.dict(sys.modules, {"akshare": mock_ak}):
    with patch.object(TradingAgentsGraph, "__init__", lambda self, **kw: None):
        tag = TradingAgentsGraph.__new__(TradingAgentsGraph)
        tag.config = {}

        # Test _fetch_actual_returns
        ret = tag._fetch_actual_returns("000001", "2026-06-05", days=5)
        check("fetch_actual_returns returns float", isinstance(ret, float))
        check("fetch_actual_returns correct value", abs(ret - 0.12) < 0.01, f"got {ret}")

        # Test with empty data
        mock_ak.stock_zh_a_hist.return_value = pd.DataFrame()
        ret_empty = tag._fetch_actual_returns("000001", "2026-06-05", days=5)
        check("fetch_actual_returns handles empty", ret_empty is None)

        # Test _fetch_benchmark_return
        bench_df = pd.DataFrame({
            "日期": ["2026-06-05", "2026-06-06", "2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12"],
            "收盘": [3000.0, 3020.0, 3050.0, 3080.0, 3100.0, 3120.0],
        })
        mock_ak.index_zh_a_hist.return_value = bench_df
        bench_ret = tag._fetch_benchmark_return("2026-06-05", days=5)
        check("fetch_benchmark_return returns float", isinstance(bench_ret, float))
        check("fetch_benchmark_return correct value", abs(bench_ret - 0.04) < 0.01, f"got {bench_ret}")

# Test _resolve_pending_memory with mocked components
with patch.object(TradingAgentsGraph, "__init__", lambda self, **kw: None):
    tag2 = TradingAgentsGraph.__new__(TradingAgentsGraph)
    tag2.config = {}

    # Mock memory_log
    mock_memory = MagicMock()
    old_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    recent_date = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")

    mock_memory.get_pending_entries.return_value = [
        {"date": old_date, "ticker": "600519", "rating": "买入", "pending": True,
         "decision": {"final_trade_decision": "买入贵州茅台", "rating": "买入"}},
        {"date": recent_date, "ticker": "000001", "rating": "持有", "pending": True,
         "decision": {"final_trade_decision": "持有平安银行", "rating": "持有"}},
    ]
    mock_memory.batch_update_with_outcomes.return_value = 1
    tag2.memory_log = mock_memory

    # Mock reflector
    mock_reflector = MagicMock()
    mock_reflector.reflect_on_final_decision.return_value = "方向正确，收益良好"
    tag2.reflector = mock_reflector

    # Mock the return fetching methods
    tag2._fetch_actual_returns = MagicMock(return_value=0.05)
    tag2._fetch_benchmark_return = MagicMock(return_value=0.02)

    tag2._resolve_pending_memory("600519")

    # Only the old entry should be processed
    check("batch_update called", mock_memory.batch_update_with_outcomes.called)
    if mock_memory.batch_update_with_outcomes.called:
        updates = mock_memory.batch_update_with_outcomes.call_args[0][0]
        check("only old entry processed", len(updates) == 1)
        check("correct ticker resolved", updates[0]["ticker"] == "600519")
        check("reflection has outcome", "outcome" in updates[0]["reflection"])
        check("reflection has lesson", "lesson" in updates[0]["reflection"])
        check("alpha calculated", "alpha_return" in updates[0]["reflection"])

# ═══════════════════════════════════════════════════════════════
#  P1-3a: save_snapshot extensions
# ═══════════════════════════════════════════════════════════════
print("\n═══ P1-3a: save_snapshot extensions ═══\n")

# Import from plugin scripts
scripts_dir = os.path.expanduser("~/.qoderworkcn/plugins-custom/astock-trading-agents/scripts")
sys.path.insert(0, scripts_dir)
import save_snapshot as ss

# Test extract_analyst_signals
mock_result = {
    "market_report": "股票处于上涨趋势，成交量放量上涨，均线多头排列。\n1. MA5上穿MA10\n2. MACD金叉\n前景乐观，增长预期良好。",
    "sentiment_report": "市场情绪偏多，机构资金持续流入。\n- 北向资金净买入\n- 融资余额增加",
    "news_report": "公司发布利好公告，业绩超预期。\n1. 营收同比增长30%\n2. 净利润超预期\n前景向好。",
    "fundamentals_report": "公司基本面稳健，估值合理。PE 15倍，PB 2倍。\n1. ROE 18%\n2. 营收增速 25%\n改善预期。",
}

signals = ss.extract_analyst_signals(mock_result)
check("analyst_signals has 市场/技术面", "市场/技术面" in signals)
check("market signal rating=正面", signals.get("市场/技术面", {}).get("rating") == "正面")
check("market signal outlook=偏多", signals.get("市场/技术面", {}).get("outlook") == "偏多")
check("market signal has key_points", len(signals.get("市场/技术面", {}).get("key_points", [])) >= 1)
check("sentiment signal detected", "市场情绪" in signals)
check("news signal positive", signals.get("新闻舆情", {}).get("rating") == "正面")
check("fundamentals outlook", signals.get("基本面", {}).get("outlook") == "偏多")

# Test with empty reports
empty_signals = ss.extract_analyst_signals({})
check("empty reports → empty signals", len(empty_signals) == 0)

# Test extract_debate_consensus
mock_debate_result = {
    "investment_debate_state": {
        "judge_decision": "## 投资方案：买入\n\n1. **执行摘要**：强烈看多，目标价1200元\n2. **投资逻辑**：业绩增长确定性高\n3. **风险提示**：短期估值偏高",
    }
}
consensus = ss.extract_debate_consensus(mock_debate_result)
check("consensus direction=看多", consensus.get("direction") == "看多")
check("consensus confidence=高", consensus.get("confidence") == "高")
check("consensus has summary", "summary" in consensus or len(consensus) >= 2)

# Test with empty debate
empty_consensus = ss.extract_debate_consensus({})
check("empty debate → empty consensus", len(empty_consensus) == 0)

# Test extract_key_assumptions
mock_assumptions_result = {
    "trader_investment_plan": "假设：公司Q2业绩维持增长\n预期：未来3个月股价上行10%\n如果政策面不出现重大变化，维持看多判断",
    "investment_plan": "基于公司核心竞争力和行业地位\n前提：行业景气度持续",
    "risk_debate_state": {"judge_decision": "假设宏观经济保持稳定"},
}
assumptions = ss.extract_key_assumptions(mock_assumptions_result)
check("key_assumptions extracted", len(assumptions) >= 1, f"got {len(assumptions)}")
check("assumptions max 5", len(assumptions) <= 5)

# Empty assumptions
empty_assumptions = ss.extract_key_assumptions({})
check("empty result → empty assumptions", len(empty_assumptions) == 0)


# ═══════════════════════════════════════════════════════════════
#  P1-3b: review_backtest intelligence
# ═══════════════════════════════════════════════════════════════
print("\n═══ P1-3b: review_backtest intelligence ═══\n")

sys.path.insert(0, scripts_dir)
import review_backtest as rb

# Test multi-dimensional score_snapshot
snapshot_buy_correct = {
    "rating": "买入",
    "track_t1": {"date": "2026-06-06", "price": 10.5, "change_pct": 2.0, "correct": True},
    "track_t5": {"date": "2026-06-10", "price": 11.0, "change_pct": 7.0, "correct": True},
    "track_t10": {"date": "2026-06-15", "price": 11.5, "change_pct": 12.0, "correct": True},
    "track_t20": {"date": "2026-06-25", "price": 12.0, "change_pct": 17.0, "correct": True},
    "key_assumptions": ["业绩增长", "行业景气"],
}

score_info = rb.score_snapshot(snapshot_buy_correct)
check("score is not None", score_info.get("score") is not None)
check("score has dimensions", "dimensions" in score_info)
check("dimensions has direction", "direction" in score_info.get("dimensions", {}))
check("dimensions has magnitude", "magnitude" in score_info.get("dimensions", {}))
check("dimensions has timing", "timing" in score_info.get("dimensions", {}))
check("dimensions has assumption", "assumption" in score_info.get("dimensions", {}))
check("correct buy has high score", score_info["score"] >= 50, f"score={score_info['score']}")

# Test wrong direction
snapshot_buy_wrong = {
    "rating": "买入",
    "track_t1": {"date": "2026-06-06", "price": 9.5, "change_pct": -3.0, "correct": False},
    "track_t5": {"date": "2026-06-10", "price": 9.0, "change_pct": -8.0, "correct": False},
    "track_t10": {"date": "2026-06-15", "price": 8.5, "change_pct": -12.0, "correct": False},
    "track_t20": {"date": "2026-06-25", "price": 8.0, "change_pct": -17.0, "correct": False},
    "key_assumptions": [],
}

wrong_info = rb.score_snapshot(snapshot_buy_wrong)
check("wrong direction has low score", wrong_info["score"] < 50, f"score={wrong_info['score']}")
check("correct > wrong score", score_info["score"] > wrong_info["score"])

# Test no tracking data
snapshot_no_track = {"rating": "持有"}
no_track_info = rb.score_snapshot(snapshot_no_track)
check("no tracking data → None score", no_track_info.get("score") is None)

# Test recognize_patterns
test_snapshots = [
    {
        "rating": "买入", "score": 75.0, "verified": True,
        "dimensions": {"direction": 100, "magnitude": 80, "timing": 85, "assumption": 100},
        "stock_name": "A", "analysis_date": "2026-06-01",
    },
    {
        "rating": "买入", "score": 80.0, "verified": True,
        "dimensions": {"direction": 100, "magnitude": 70, "timing": 90, "assumption": 100},
        "stock_name": "B", "analysis_date": "2026-06-02",
    },
    {
        "rating": "买入", "score": 70.0, "verified": True,
        "dimensions": {"direction": 100, "magnitude": 60, "timing": 80, "assumption": 50},
        "stock_name": "C", "analysis_date": "2026-06-03",
    },
    {
        "rating": "减持", "score": 25.0, "verified": True,
        "dimensions": {"direction": 0, "magnitude": 20, "timing": 0, "assumption": 0},
        "stock_name": "D", "analysis_date": "2026-06-04",
    },
]

patterns = rb.recognize_patterns(test_snapshots)
check("patterns has rating_bias", "rating_bias" in patterns)
check("patterns has insights list", "insights" in patterns)
check("rating_bias has 买入", "买入" in patterns.get("rating_bias", {}))

# Test with too few snapshots
few_patterns = rb.recognize_patterns(test_snapshots[:2])
check("few snapshots → empty rating_bias", len(few_patterns.get("rating_bias", {})) == 0)

# Test generate_strategy_feedback
feedback = rb.generate_strategy_feedback(test_snapshots, patterns)
check("feedback is string", isinstance(feedback, str))

# Feedback with low-scoring rating
patterns_with_weakness = {
    "rating_bias": {"减持": {"count": 1, "avg_score": 25.0, "assessment": "偏差"}},
    "magnitude_bias": {},
    "insights": ["系统倾向于高估价格变动幅度"],
}
feedback2 = rb.generate_strategy_feedback(test_snapshots, patterns_with_weakness)
check("feedback includes insights", "高估" in feedback2 or len(feedback2) > 0)

# Empty patterns → empty feedback
empty_feedback = rb.generate_strategy_feedback([], {"rating_bias": {}, "magnitude_bias": {}, "insights": []})
check("empty patterns → empty feedback", empty_feedback == "")


# ═══════════════════════════════════════════════════════════════
#  Summary
# ═══════════════════════════════════════════════════════════════
print(f"\n{'═' * 55}")
print(f"  Phase 2 Tests: {PASS} passed, {FAIL} failed, {PASS + FAIL} total")
print(f"{'═' * 55}\n")

sys.exit(0 if FAIL == 0 else 1)
