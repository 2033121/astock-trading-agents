"""Tests for the researcher prose digest (Token strategy 2A, deterministic)."""

from __future__ import annotations

from astock_trader.graph.context_slimmer import (
    _compress_prose,
    _RESEARCHER_PROSE_LIMIT,
    slim_for_researchers,
    slim_gathered_reports,
)


def _long_report() -> str:
    prose = "这段文字纯粹是解释性陈述，没有任何数据支撑。" * 40
    return (
        "## 基本面扫描\n"
        f"{prose}\n\n"
        "## 关键财务指标\n"
        "- 营业收入增长率 12.3%\n"
        "- ROE 15.8\n"
        "- PE 18.5 倍\n\n"
        "## 估值结论\n"
        "综合评估当前估值处于行业中等偏下水平。\n"
    )


def test_compress_prose_short_body_untouched() -> None:
    body = "短正文，无需压缩。"
    assert _compress_prose(body, _RESEARCHER_PROSE_LIMIT) == body


def test_compress_prose_keeps_bullets_and_numbers() -> None:
    body = _long_report()[len("## 基本面扫描\n"):].strip()
    compressed = _compress_prose(body, 100)  # tiny threshold to force compression
    assert "营业收入增长率 12.3%" in compressed
    assert "ROE 15.8" in compressed
    assert "PE 18.5 倍" in compressed
    assert "综合评估当前估值处于行业中等偏下水平。" in compressed
    assert len(compressed) < len(body)


def test_compress_prose_first_sentence_only() -> None:
    prose = "这是一个首句。" + "后续填充句子应该被丢弃。" * 50
    compressed = _compress_prose(prose, 100)
    assert "后续填充句子" not in compressed
    assert compressed.startswith("这是一个首句。")


def test_slim_for_researchers_digests_large_reports() -> None:
    report = _long_report() * 3  # > 1500 char threshold
    slimmed = slim_for_researchers({"基本面分析": report})
    out = slimmed["基本面分析"]
    assert len(out) < len(report)
    # numeric evidence survives
    assert "12.3%" in out and "18.5" in out


def test_slimmer_researcher_path_in_gathered_reports() -> None:
    state = {"fundamentals_report": _long_report() * 3}
    out = slim_gathered_reports(state, "bear")
    assert "### 基本面分析" in out
    assert "12.3%" in out
