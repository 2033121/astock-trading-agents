"""Tests for the zero-dependency MCP stdio server (mcp_server.py)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _load_server_module():
    spec = importlib.util.spec_from_file_location("astock_mcp_server", _ROOT / "mcp_server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def mcp(tmp_path):
    payload = {
        "version": 1,
        "snapshots": [
            {
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "analysis_date": "2026-09-01",
                "final_rating": "买入",
                "price_at_analysis": 1500.0,
                "confidence": 0.8,
                "analyst_signals": {"market": "看多"},
                "key_reasons": ["高端酒景气"],
                "verified": True,
                "track_t5": 2.1,
                "snapshot_time": "2026-09-01T17:00:00",
            },
            {
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "analysis_date": "2026-09-08",
                "final_rating": "增持",
                "price_at_analysis": 1560.0,
                "confidence": 0.7,
                "analyst_signals": {"market": "看多", "news": "中性"},
                "key_reasons": ["提价预期"],
                "verified": False,
                "snapshot_time": "2026-09-08T17:00:00",
            },
            {
                "stock_code": "000001",
                "stock_name": "平安银行",
                "analysis_date": "2026-09-05",
                "final_rating": "持有",
                "price_at_analysis": 11.5,
            },
        ],
    }
    snap_file = tmp_path / "analysis_log.json"
    snap_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    mod = _load_server_module()
    return mod, str(snap_file)


def _load_server_module_with_env():
    return _load_module()


def _load_module():
    return _load_mod()


def _load_mod():
    return _load_real()


def _load_real():
    return _load_direct()


def _load_direct():
    return _load_final()


def _load_final():
    return _load_with_env()


def _load_with_env():
    spec = importlib.util.spec_from_file_location("astock_mcp_server", _ROOT / "mcp_server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_initialize(mcp):
    mod, _ = mcp
    resp = mod.MCPServer().handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert resp["id"] == 1
    assert resp["result"]["serverInfo"]["name"] == "astock-trading-agents"
    assert "tools" in resp["result"]["capabilities"]


def test_tools_list(mcp):
    mod, _ = mcp
    resp = mod.MCPServer().handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in resp["result"]["tools"]}
    assert {"analyze_stock", "list_snapshots", "get_snapshot", "read_recent_memories"} <= names


def test_list_snapshots_tool(mcp):
    mod, snap = mcp
    mod.SNAPSHOT_LOG_PATH = snap
    resp = mod.MCPServer().handle_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "list_snapshots", "arguments": {"stock_code": "600519"}},
        }
    )
    text = resp["result"]["content"][0]["text"]
    data = json.loads(text)
    assert data["count"] == 2
    assert data["snapshots"][0]["analysis_date"] == "2026-09-08"
    assert data["snapshots"][0]["rating"] == "增持"


def test_get_snapshot_trend(mcp):
    mod, snap = mcp
    mod.SNAPSHOT_LOG_PATH = snap
    resp = mod.MCPServer().handle_message(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "get_snapshot", "arguments": {"stock_code": "600519"}},
        }
    )
    data = json.loads(resp["result"]["content"][0]["text"])
    assert data["total"] == 2
    assert data["latest"]["rating"] == "增持"
    assert data["price_change_since_first"] == 4.0  # 1500 -> 1560


def test_method_not_found(mcp):
    mod, _ = mcp
    resp = mod.MCPServer().handle_message({"jsonrpc": "2.0", "id": 5, "method": "resources/list"})
    assert resp["error"]["code"] == -32601


def test_notification_returns_none(mcp):
    mod, _ = mcp
    assert mod.MCPServer().handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_stdio_end_to_end(mcp):
    """Full protocol round-trip in a subprocess, NDJSON in / out."""
    reqs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    proc = subprocess.run(
        [sys.executable, str(_ROOT / "mcp_server.py")],
        input="\n".join(json.dumps(r) for r in reqs) + "\n",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0
    responses = [json.loads(ln) for ln in proc.stdout.splitlines() if ln.strip()]
    assert [r["id"] for r in responses] == [1, 2]  # notification not echoed
    assert responses[1]["result"]["tools"]


# ── review_backtest tool ──────────────────────────────────────────


class _FakeProc:
    def __init__(self, stdout: str, returncode: int = 0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


def test_tools_list_includes_review_backtest(mcp):
    mod, _ = mcp
    resp = mod.MCPServer().handle_message({"jsonrpc": "2.0", "id": 9, "method": "tools/list"})
    assert "review_backtest" in {t["name"] for t in resp["result"]["tools"]}


def test_review_backtest_parses_summary(monkeypatch, mcp):
    mod, _ = mcp
    summary = {"total_reviewed": 5, "accuracy": 0.6}
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: _FakeProc(json.dumps(summary)))
    out = mod.review_backtest(days=0)
    assert out == summary


def test_review_backtest_html_guard(monkeypatch, mcp):
    mod, _ = mcp
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: _FakeProc("noise before\n{\"ok\": true}\ntrailing"))
    out = mod.review_backtest()
    assert out == {"ok": True}


def test_review_backtest_report_mode(monkeypatch, mcp):
    mod, _ = mcp
    md = "# 复盘报告\n- 准确率 60%"
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: _FakeProc(md))
    out = mod.review_backtest(report=True)
    assert out["report_markdown"].startswith("# 复盘报告")


def test_review_backtest_nonzero_exit(monkeypatch, mcp):
    mod, _ = mcp

    def boom(*a, **k):
        p = _FakeProc("", returncode=1)
        p.stderr = "Traceback"
        return p

    monkeypatch.setattr(mod.subprocess, "run", boom)
    out = mod.review_backtest()
    assert "error" in out
