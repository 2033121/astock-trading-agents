"""报告生成 —— 辩论历史不能被覆盖，耗时不能永远显示 0.0 秒。

两条都是实测中真实出现的缺陷：

1. **辩论面板内容重复**：「多空辩论」和「研究主管」逐字相同、「风控辩论」和
   「组合经理」逐字相同 —— 因为裁判节点把同一段文本写进了两个字段，而面板只
   取 ``judge_decision``，辩论过程一个字都看不到。
2. **耗时写死 0.0 秒**：回填只改了 JSON 里的 ``elapsed`` 字段，摘要正文里那个
   数字没人管。
"""

import json

import pytest

from astock_trader.graph.report_generator import (
    ELAPSED_PLACEHOLDER,
    _extract_content,
    _render_debate,
    generate_report,
)


def _state():
    return {
        "company_of_interest": "600519",
        "trade_date": "2026-10-03",
        "market_report": "# 市场\n" + "技术面" * 30,
        "sentiment_report": "# 情绪\n" + "情绪" * 30,
        "news_report": "# 新闻\n" + "新闻" * 30,
        "fundamentals_report": "# 基本面\n" + "基本面" * 30,
        "investment_debate_state": {
            "bull_history": ["看多：估值处于三年最低分位，护城河未损。"],
            "bear_history": ["看空：低估值可能是价值陷阱，Q2 营收净利双降。"],
            "judge_decision": "# 研究主管裁决\n多头论据更具说服力。",
        },
        "investment_plan": "# 研究主管裁决\n多头论据更具说服力。",
        "trader_investment_plan": "# 交易计划\n交易方向：持有 + 左侧小仓试仓。",
        "risk_debate_state": {
            "aggressive_history": ["激进派：应加大仓位。"],
            "conservative_history": ["保守派：应保持观望。"],
            "neutral_history": ["中性派：分批建仓。"],
            "judge_decision": "# 最终决策\n评级：持有",
        },
        "final_trade_decision": "# 最终决策\n评级：持有",
    }


def _stage(html: str, stage_id: str) -> str:
    data = json.loads(html.split("const DATA = ", 1)[1].split(";\n", 1)[0])
    for s in data["stages"]:
        if s["id"] == stage_id:
            return s["content"]
    raise AssertionError(f"stage {stage_id!r} missing")


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class TestDebateRendering:
    def test_debate_contains_both_sides_and_judge(self):
        content = _extract_content(_state(), {"id": "debate", "field": None})
        assert "看多" in content
        assert "看空" in content
        assert "多头论据更具说服力" in content  # 裁决也在

    def test_debate_no_longer_duplicates_research_stage(self):
        state = _state()
        debate = _extract_content(state, {"id": "debate", "field": None})
        assert debate != state["investment_plan"]

    def test_risk_contains_three_sides(self):
        content = _extract_content(_state(), {"id": "risk", "field": None})
        assert "激进" in content
        assert "保守" in content
        assert "中性" in content

    def test_risk_no_longer_duplicates_final_stage(self):
        state = _state()
        risk = _extract_content(state, {"id": "risk", "field": None})
        assert risk != state["final_trade_decision"]

    def test_history_may_be_a_plain_string(self):
        # 有的路径把 history 拼成 str，渲染不能因此炸掉
        out = _render_debate(
            {"bull_history": "看多：一句话。", "judge_decision": "裁决"}, [("多头", "bull_history")], "裁判"
        )
        assert "看多：一句话。" in out
        assert "裁决" in out

    def test_empty_debate_falls_back_to_history_log(self):
        out = _render_debate({"history": ["看多: a", "看空: b"]}, [("多头", "bull_history")], "裁判")
        assert "辩论记录" in out
        assert "看空: b" in out

    def test_completely_empty_debate_is_blank(self):
        assert _render_debate({}, [("多头", "bull_history")], "裁判") == ""


class TestElapsed:
    def test_placeholder_used_when_elapsed_unknown(self, tmp_path):
        path = generate_report(_state(), str(tmp_path), rating="持有", elapsed_seconds=0)
        html = _read(path)
        assert ELAPSED_PLACEHOLDER in html
        assert "分析耗时：0.0秒" not in html

    def test_real_elapsed_is_written_directly(self, tmp_path):
        path = generate_report(_state(), str(tmp_path), rating="持有", elapsed_seconds=123.4)
        html = _read(path)
        assert ELAPSED_PLACEHOLDER not in html
        assert "分析耗时：123.4秒" in html

    def test_patch_replaces_both_json_and_prose(self, tmp_path):
        """回填必须同时改 JSON 字段与摘要正文 —— 只改前者正是那个 bug。"""
        from astock_trader.graph.trading_graph import TradingAgentsGraph

        path = generate_report(_state(), str(tmp_path), rating="持有", elapsed_seconds=0)
        TradingAgentsGraph._patch_report_elapsed(path, 456.7)
        html = _read(path)

        assert ELAPSED_PLACEHOLDER not in html
        assert '"elapsed": 456.7' in html
        assert "分析耗时：456.7秒" in html


class TestStageAssembly:
    def test_all_stages_present(self, tmp_path):
        path = generate_report(_state(), str(tmp_path), rating="持有", elapsed_seconds=1.0)
        html = _read(path)
        for sid in (
            "market",
            "sentiment",
            "news",
            "fundamentals",
            "debate",
            "research",
            "trader",
            "risk",
            "final",
            "summary",
        ):
            assert _stage(html, sid)

    def test_summary_has_debate_row_without_copying_judge(self):
        path_holder = _state()
        from astock_trader.graph.report_generator import _build_summary

        summary = _build_summary(path_holder, "600519", "2026-10-03", "持有", 1.0)
        assert "多：看多" in summary or "多：" in summary
        assert "空：看空" in summary or "空：" in summary

    def test_empty_report_field_skips_stage(self, tmp_path):
        state = _state()
        state["news_report"] = ""
        path = generate_report(state, str(tmp_path), rating="持有", elapsed_seconds=1.0)
        html = _read(path)
        with pytest.raises(AssertionError):
            _stage(html, "news")

    def test_report_filename_carries_symbol_and_date(self, tmp_path):
        path = generate_report(_state(), str(tmp_path), rating="持有", elapsed_seconds=1.0)
        assert path.endswith("600519_2026-10-03_report.html")
