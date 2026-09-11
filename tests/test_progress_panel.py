"""Tests for per-agent progress recorder and the sidebar panel generator (v0.5)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from astock_trader.graph.progress_recorder import (
    NodeProgressRecorder,
    default_progress_path,
    with_callback_config,
)

_ROOT = Path(__file__).resolve().parents[1]


def _panel_mod():
    spec = importlib.util.spec_from_file_location("astock_agent_panel", _ROOT / "scripts" / "agent_panel.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pretty_node_has_label_and_stage() -> None:
    from astock_trader.graph.progress_recorder import pretty_node

    label, stage = pretty_node("Market Analyst")
    assert label == "技术分析师"
    assert stage == "① 分析师"

    label, _ = pretty_node("Portfolio Manager")
    assert label == "基金经理"

    label, _ = pretty_node("tools_market")
    assert "工具" in label  # 适配 ReAct 工具子轮


def test_recorder_writes_events(tmp_path) -> None:
    rec = NodeProgressRecorder(str(tmp_path / "p.jsonl"))
    cfg = with_callback_config({"recursion_limit": 50}, rec)
    assert len(cfg["callbacks"]) == 1
    assert cfg["recursion_limit"] == 50
    assert with_callback_config({}, None) == {}

    # simulate a callback flow
    rec.on_chain_start({"name": "Market Analyst"}, {}, run_id="r1")
    rec.on_chain_end({}, run_id="r1")
    rec.on_chain_start({"name": "Bull Researcher"}, {}, run_id="r2", parent_run_id="r1")
    rec.on_chain_end({}, run_id="r2")
    rec.mark_complete("增持", 42.0)

    lines = [json.loads(x) for x in (tmp_path / "p.jsonl").read_text(encoding="utf-8").splitlines()]
    assert lines[0]["event"] == "node_state" and lines[0]["state"] == "running"
    assert lines[0]["label"] == "技术分析师"  # 中文标牌已适配
    assert any(ev["event"] == "node_end" and ev["node"] == "Market Analyst" for ev in lines)
    assert lines[-1]["rating"] == "增持" and lines[-1]["elapsed_s"] == 42.0


def test_recorder_skips_unknown_nodes(tmp_path) -> None:
    path = tmp_path / "q.jsonl"
    rec = NodeProgressRecorder(str(path))
    rec.on_chain_start({"name": "<module>"}, {}, run_id="r")
    rec.on_chain_end({}, run_id="r")
    # 全部节点被过滤后不应写任何事件（文件可能尚未创建）
    assert not path.exists() or path.read_text(encoding="utf-8").strip() == ""


def test_default_progress_path(tmp_path) -> None:
    p = default_progress_path(str(tmp_path), "600519", "2026-09-11")
    assert p.name == "600519_20260911_progress.jsonl"


# ── panel generator ──────────────────────────────────────────────────


def _write_log(tmp_path, events: list[dict]) -> Path:
    path = tmp_path / "600519_20260911_progress.jsonl"
    path.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
        encoding="utf-8",
    )
    return path


def test_panel_full_flow(tmp_path) -> None:
    mod = _panel_mod()
    events = [
        {"t": 0.5, "event": "node_state", "node": "Market Analyst", "state": "running"},
        {"t": 4.2, "event": "node_end", "node": "Market Analyst"},
        {"t": 4.3, "event": "node_state", "node": "Bull Researcher", "state": "running"},
        {"t": 9.0, "event": "node_end", "node": "Bull Researcher"},
        {"t": 4.4, "event": "node_state", "node": "Bear Researcher", "state": "running"},
        {"t": 4.5, "event": "node_error", "node": "Bear Researcher", "error": "boom"},
        {"t": 10.0, "event": "run_complete", "rating": "增持", "elapsed_s": 10.4},
    ]
    log_file = _write_log(tmp_path, events)
    data = mod.summarize(mod.read_events(log_file))

    assert data["states"]["Market Analyst"] == "done"
    assert data["durations"]["Market Analyst"] == 3.7
    assert data["states"]["Bull Researcher"] == "done"
    assert data["states"]["Bear Researcher"] == "error"
    assert data["errors"]["Bear Researcher"] == "boom"
    assert data["rating"] == "增持"

    out = tmp_path / "agent_panel.html"
    mod.build(log_file, out)
    html_text = out.read_text(encoding="utf-8")
    assert "最终评级：<b>增持</b>" in html_text
    assert "用时 10.4s" in html_text
    assert "http-equiv='refresh' content='2'" in html_text  # 自刷新侧边栏


def test_panel_empty_run(tmp_path) -> None:
    mod = _panel_mod()
    log_file = _write_log(tmp_path, [])
    out = tmp_path / "panel.html"
    mod.build(log_file, out)
    text = out.read_text(encoding="utf-8")
    assert "运行中…" in text
    assert text.count("card pending") == 12  # 12 位智能体全部 待运行
