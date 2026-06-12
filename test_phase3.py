"""Phase 3 integration tests for astock-trading-agents v0.3.

Tests cover:
- P2-1: Context slimmer (per-node trimming, section scoring, master entry point)
- P2-2: Market memory (TF-IDF indexing, search, format_for_prompt, persistence)
- Pipeline integration (config keys, GraphSetup context_slimming, TradingAgentsGraph market_memory)

Run: python test_phase3.py
"""

import json
import os
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

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
#  P2-1: Context Slimmer
# ═══════════════════════════════════════════════════════════════
print("\n═══ P2-1: Context Slimmer ═══\n")

from astock_trader.graph.context_slimmer import (
    slim_for_portfolio_manager,
    slim_for_risk_analysts,
    slim_for_researchers,
    slim_for_trader,
    slim_gathered_reports,
    _split_report_into_sections,
    _score_section,
    _REPORT_SMALL_THRESHOLD,
)

# Test section splitting
sample_report = """## 市场分析

股票处于上涨趋势，均线多头排列。

### 技术指标
1. MA5上穿MA10
2. MACD金叉信号

### 风险评估
短期存在回调压力，但中期向好。

## 结论
建议买入，目标价1200元。"""

sections = _split_report_into_sections(sample_report)
check("section splitting works", len(sections) >= 2, f"got {len(sections)} sections")

# Test section scoring
score_conclusion = _score_section("## 结论", "建议买入", ["评级", "结论", "建议"])
score_detail = _score_section("### 技术指标", "MA5上穿MA10", ["评级", "结论"])
check("conclusion scores higher", score_conclusion > score_detail,
      f"conclusion={score_conclusion}, detail={score_detail}")

# Test slim_for_portfolio_manager (heavy compression)
long_report = "## 详细分析\n" + "这是一段很长的市场分析内容。" * 200
long_report += "\n\n## 结论\n综合评估，建议买入该股票，目标价100元。"
reports = {"市场/技术面分析": long_report}
slimmed_pm = slim_for_portfolio_manager(reports)
check("PM slimming reduces size", len(slimmed_pm["市场/技术面分析"]) < len(long_report),
      f"original={len(long_report)}, slimmed={len(slimmed_pm['市场/技术面分析'])}")

# Test slim_for_risk_analysts (moderate compression)
risk_report = "## 风险因素\n" + "市场波动风险较大，建议控制仓位。\n" * 50
risk_report += "\n\n## 增长潜力\n公司业绩持续增长。" * 20
reports_risk = {"市场/技术面分析": risk_report}
slimmed_risk = slim_for_risk_analysts(reports_risk)
check("risk slimming works", isinstance(slimmed_risk, dict))

# Test slim_for_trader (no compression)
reports_full = {"市场/技术面分析": "完整报告内容" * 100}
slimmed_trader = slim_for_trader(reports_full)
check("trader reports unchanged", slimmed_trader == reports_full)

# Test small report bypass
small_reports = {"市场/技术面分析": "短报告"}
slimmed_small = slim_for_portfolio_manager(small_reports)
check("small report bypass", slimmed_small == small_reports)

# Test slim_gathered_reports (master entry point)
mock_state = {
    "market_report": "市场处于上涨趋势，放量上涨。" * 20,
    "sentiment_report": "市场情绪偏多，机构资金流入。" * 15,
    "news_report": "公司发布利好公告，业绩超预期。" * 15,
    "fundamentals_report": "公司基本面稳健，估值合理。" * 15,
}

result_trader = slim_gathered_reports(mock_state, "trader")
check("trader gets full reports", "市场处于上涨趋势" in result_trader)

result_pm = slim_gathered_reports(mock_state, "portfolio_manager")
check("PM gets slimmed reports", len(result_pm) <= len(result_trader))

result_empty = slim_gathered_reports({}, "trader")
check("empty state handled", "暂无" in result_empty)

# Test disable switch
result_disabled = slim_gathered_reports(mock_state, "portfolio_manager", enable=False)
check("disable switch works", len(result_disabled) > 0)


# ═══════════════════════════════════════════════════════════════
#  P2-2: Market Memory (Vector Store)
# ═══════════════════════════════════════════════════════════════
print("\n═══ P2-2: Market Memory ═══\n")

from astock_trader.memory.market_memory import (
    MarketMemory,
    AnalysisRecord,
    _split_analysis_text,
    _extract_keywords,
    _TfIdfIndex,
)

# Test text splitting
long_analysis = "## 市场分析\n" + "贵州茅台股价持续走高。" * 100
segments = _split_analysis_text(long_analysis)
check("analysis splitting works", len(segments) >= 1)

# Test keyword extraction
text_with_keywords = "贵州茅台 白酒行业 估值 市盈率 增长 龙头 消费 投资"
keywords = _extract_keywords(text_with_keywords)
check("keywords extracted", len(keywords) >= 1)
check("keywords reasonable count", len(keywords) <= 15)

# Test TF-IDF index directly
index = _TfIdfIndex()
rec1 = AnalysisRecord(
    ticker="600519", date="2026-06-01", chunk_index=0,
    content="贵州茅台白酒龙头，业绩持续增长，估值合理",
    rating="买入",
)
rec2 = AnalysisRecord(
    ticker="000001", date="2026-06-01", chunk_index=0,
    content="平安银行金融股，利率下行压力较大，估值偏低",
    rating="持有",
)
index.add(rec1)
index.add(rec2)

results = index.search("白酒 业绩 增长", top_k=2)
check("TF-IDF search returns results", len(results) >= 1)
check("TF-IDF search relevant first", results[0].ticker == "600519",
      f"got {results[0].ticker}")

# Test MarketMemory (TF-IDF backend)
mem = MarketMemory(backend="tfidf")
check("MarketMemory init", mem.record_count == 0)

# Index some analyses
n1 = mem.index_analysis(
    "600519", "2026-06-01",
    "贵州茅台白酒龙头，高端消费品牌护城河深，业绩增长确定性强，当前估值处于历史低位",
    rating="买入",
)
check("index returns chunk count", n1 >= 1)

n2 = mem.index_analysis(
    "000001", "2026-06-02",
    "平安银行金融板块，受利率下行影响净息差收窄，但零售转型持续推进",
    rating="持有",
)
check("second analysis indexed", n2 >= 1)
check("record count updated", mem.record_count >= 2)

# Test search
search_results = mem.search("白酒龙头估值", top_k=3)
check("search returns results", len(search_results) >= 1)
check("search finds relevant", any(r.ticker == "600519" for r in search_results))

# Test search_by_ticker
ticker_results = mem.search_by_ticker("600519")
check("search_by_ticker works", len(ticker_results) >= 1)
check("search_by_ticker correct", all(r.ticker == "600519" for r in ticker_results))

# Test format_for_prompt
formatted = mem.format_for_prompt(search_results)
check("format_for_prompt non-empty", len(formatted) > 0)
check("format contains header", "历史分析参考" in formatted)
check("format contains ticker", "600519" in formatted)

# Test format with empty results
empty_formatted = mem.format_for_prompt([])
check("empty format returns empty", empty_formatted == "")

# Test get_analysis_context
ctx = mem.get_analysis_context("600519", "2026-06-01")
check("get_analysis_context works", len(ctx) > 0)
check("get_analysis_context correct", "贵州茅台" in ctx)

# Test persistence
tmp_dir = tempfile.mkdtemp()
try:
    mem.persist_dir = Path(tmp_dir)
    mem.save()

    # Check files exist
    check("persist creates files",
          (Path(tmp_dir) / "all_records.json").exists() or
          (Path(tmp_dir) / "analysis_texts.json").exists())

    # Load into new instance
    mem2 = MarketMemory(backend="tfidf", persist_dir=tmp_dir)
    mem2.load()
    check("load restores records", mem2.record_count >= 2)
    check("load restores texts", len(mem2.get_analysis_context("600519", "2026-06-01")) > 0)

    # Test clear
    mem2.clear()
    check("clear works", mem2.record_count == 0)
finally:
    shutil.rmtree(tmp_dir, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════
#  Pipeline Integration
# ═══════════════════════════════════════════════════════════════
print("\n═══ Pipeline Integration ═══\n")

from astock_trader.default_config import DEFAULT_CONFIG

# Config keys
check("enable_context_slimming in config", "enable_context_slimming" in DEFAULT_CONFIG)
check("enable_context_slimming default True", DEFAULT_CONFIG.get("enable_context_slimming") is True)
check("enable_vector_memory in config", "enable_vector_memory" in DEFAULT_CONFIG)
check("enable_vector_memory default True", DEFAULT_CONFIG.get("enable_vector_memory") is True)
check("vector_memory_backend in config", "vector_memory_backend" in DEFAULT_CONFIG)
check("vector_memory_dir in config", "vector_memory_dir" in DEFAULT_CONFIG)

# GraphSetup accepts context_slimming
from astock_trader.graph.setup import GraphSetup

mock_deep = MagicMock()
mock_quick = MagicMock()

gs = GraphSetup(
    deep_thinking_llm=mock_deep,
    quick_thinking_llm=mock_quick,
    context_slimming=True,
)
check("GraphSetup context_slimming stored", gs.context_slimming is True)

gs_off = GraphSetup(
    deep_thinking_llm=mock_deep,
    quick_thinking_llm=mock_quick,
    context_slimming=False,
)
check("GraphSetup slimming off stored", gs_off.context_slimming is False)

# Test _gather_reports_for with slimming enabled
mock_state = {
    "market_report": "市场上涨趋势明显" * 100,
    "sentiment_report": "情绪偏多" * 50,
    "news_report": "利好消息频出" * 50,
    "fundamentals_report": "基本面稳健" * 50,
}

result_slim = gs._gather_reports_for(mock_state, "portfolio_manager")
check("_gather_reports_for PM returns text", len(result_slim) > 0)

result_full = gs_off._gather_reports_for(mock_state, "portfolio_manager")
check("_gather_reports_for disabled returns text", len(result_full) > 0)
check("slimmed shorter than full", len(result_slim) <= len(result_full))

# TradingAgentsGraph market_memory attribute (mock init)
from astock_trader.graph.trading_graph import TradingAgentsGraph

with patch.object(TradingAgentsGraph, "__init__", lambda self, **kw: None):
    tag = TradingAgentsGraph.__new__(TradingAgentsGraph)
    tag.config = {"enable_vector_memory": True, "vector_memory_backend": "tfidf"}
    tag.market_memory = None

    # Test _index_in_memory with mock market_memory
    mock_mm = MagicMock()
    mock_mm.index_analysis.return_value = 3
    tag.market_memory = mock_mm

    test_state = {
        "market_report": "市场分析报告内容",
        "sentiment_report": "情绪分析内容",
        "news_report": "",
        "fundamentals_report": "基本面分析内容",
        "final_trade_decision": "最终交易决策",
    }
    tag._index_in_memory("600519", "2026-06-01", test_state, "买入")

    check("index_analysis called", mock_mm.index_analysis.called)
    if mock_mm.index_analysis.called:
        call_args = mock_mm.index_analysis.call_args
        check("correct ticker passed", call_args.kwargs.get("ticker") == "600519" or
              call_args[1].get("ticker") == "600519")
        check("correct rating passed", call_args.kwargs.get("rating") == "买入" or
              call_args[1].get("rating") == "买入")
    check("save called after index", mock_mm.save.called)

    # Test with market_memory=None
    tag.market_memory = None
    tag._index_in_memory("000001", "2026-06-01", test_state, "持有")
    check("no crash when memory is None", True)


# ═══════════════════════════════════════════════════════════════
#  Summary
# ═══════════════════════════════════════════════════════════════
print(f"\n{'═' * 55}")
print(f"  Phase 3 Tests: {PASS} passed, {FAIL} failed, {PASS + FAIL} total")
print(f"{'═' * 55}\n")

sys.exit(0 if FAIL == 0 else 1)
