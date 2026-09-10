#!/usr/bin/env python3
"""Zero-dependency MCP stdio server for astock-trading-agents.

Expose the framework's capabilities to any MCP-compatible client
(Claude Desktop / any MCP host) over stdio JSON-RPC 2.0:

- ``analyze_stock``        — run the full 15-agent pipeline (spawns the CLI)
- ``list_snapshots``       — recent decision snapshots (latest-first)
- ``get_snapshot``         — one stock's latest snapshot + tracking trend
- ``read_recent_memories`` — recent entries of the trading decision memory log

No third-party packages are required (implements the MCP handshake subset:
``initialize`` / ``tools/list`` / ``tools/call`` / ``ping``).

Usage::

    python mcp_server.py            # stdio loop, NDJSON requests
    ASTOCK_SNAPSHOT_LOG_PATH=... python mcp_server.py   # custom snapshot log
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

SNAPSHOT_LOG_PATH = os.environ.get(
    "ASTOCK_SNAPSHOT_LOG_PATH",
    r"D:\stock\trading-agents\analysis_log.json",
)
MEMORY_LOG_PATH = os.environ.get(
    "ASTOCK_MEMORY_LOG_PATH",
    os.path.expanduser("~/.astock_trader/memory/trading_memory.md"),
)
CLI_TIMEOUT_SECONDS = int(os.environ.get("ASTOCK_MCP_CLI_TIMEOUT", "1200"))  # 20min

SERVER_INFO = {"name": "astock-trading-agents", "version": "0.4.0"}
PROTOCOL_VERSION = "2024-11-05"


# --------------------------------------------------------------------------
# Tool implementations (pure functions, independently testable)
# --------------------------------------------------------------------------


def review_backtest(days: int = 0, report: bool = False) -> dict[str, Any]:
    """Run the backtest review (scripts/review_backtest.py) and return its summary.

    Reviews historical snapshots' ratings against realised prices
    (akshare), updates T+1/T+5/T+10/T+20 tracking and accuracy stats.
    """
    script = Path(__file__).resolve().parent / "scripts" / "review_backtest.py"
    if not script.is_file():
        return {"error": f"Script not found: {script}"}
    cmd = [sys.executable, str(script), "--days", str(max(int(days), 0))]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=CLI_TIMEOUT_SECONDS, check=False
        )
    except subprocess.TimeoutExpired:
        return {"error": f"review_backtest timed out after {CLI_TIMEOUT_SECONDS}s"}
    if proc.returncode != 0:
        return {"error": proc.stderr.strip()[-2000:] or f"exit {proc.returncode}"}
    stdout = proc.stdout.strip()
    if report:
        return {"summary": None, "report_markdown": stdout}
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        start, end = stdout.find("{"), stdout.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(stdout[start : end + 1])
            except json.JSONDecodeError as exc:
                return {"error": f"Unparseable review output: {exc}", "raw_tail": stdout[-800:]}
        return {"error": "No JSON on stdout", "raw_tail": stdout[-800:]}


def _load_snapshots() -> list[dict[str, Any]]:
    path = Path(SNAPSHOT_LOG_PATH)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    snaps = data.get("snapshots", []) if isinstance(data, dict) else []
    return [s for s in snaps if isinstance(s, dict)]


def _snapshot_summary(s: dict[str, Any]) -> dict[str, Any]:
    prev = s.get("previous_analysis") or {}
    return {
        "stock_code": s.get("stock_code"),
        "stock_name": s.get("stock_name"),
        "analysis_date": s.get("analysis_date"),
        "rating": s.get("final_rating"),
        "price_at_analysis": s.get("price_at_analysis"),
        "confidence": s.get("confidence"),
        "analyst_signals": s.get("analyst_signals"),
        "key_reasons": (s.get("key_reasons") or [])[:3],
        "tracking": {f"t{k}": s.get(f"track_t{k}") for k in (1, 5, 10, 20) if s.get(f"track_t{k}") is not None},
        "verified": s.get("verified", False),
        "has_previous_comparison": bool(prev),
        "snapshot_time": s.get("snapshot_time"),
    }


def list_snapshots(stock_code: str | None = None, limit: int = 10) -> dict[str, Any]:
    snaps = _load_snapshots()
    if stock_code:
        snaps = [s for s in snaps if s.get("stock_code") == stock_code]
    snaps.sort(key=lambda s: s.get("analysis_date", ""), reverse=True)
    return {"count": len(snaps), "snapshots": [_snapshot_summary(s) for s in snaps[: max(limit, 1)]]}


def get_snapshot(stock_code: str) -> dict[str, Any]:
    snaps = [s for s in _load_snapshots() if s.get("stock_code") == stock_code]
    if not snaps:
        return {"error": f"No snapshots for {stock_code}"}
    snaps.sort(key=lambda s: s.get("analysis_date", ""), reverse=True)
    latest = snaps[0]
    result: dict[str, Any] = {"latest": _snapshot_summary(latest), "total": len(snaps)}
    # rating trend across history
    trend = [{"date": s.get("analysis_date"), "rating": s.get("final_rating")} for s in snaps]
    result["rating_trend"] = trend
    if len(snaps) >= 2:
        prices = [s.get("price_at_analysis") for s in snaps if isinstance(s.get("price_at_analysis"), (int, float))]
        if len(prices) >= 2:
            result["price_change_since_first"] = (
                round((prices[0] - prices[-1]) / prices[-1] * 100, 2) if prices[-1] else None
            )
    return result


def read_recent_memories(limit: int = 10) -> dict[str, Any]:
    path = Path(MEMORY_LOG_PATH)
    if not path.is_file():
        return {"error": f"Memory log not found at {MEMORY_LOG_PATH}"}
    try:
        lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError as exc:
        return {"error": f"Cannot read memory log: {exc}"}
    return {"count": len(lines), "entries": lines[-max(limit, 1) :]}


def analyze_stock(symbol: str, date: str | None = None, analysts: str | None = None) -> dict[str, Any]:
    """Run the full pipeline via the CLI and return a compact JSON summary."""
    cli_snippet = (
        "import sys; "
        "from astock_trader.cli.main import app; "
        "sys.exit(app(standalone_mode=True))"
    )
    cmd = [sys.executable, "-c", cli_snippet, "analyze", symbol]
    if date:
        cmd += ["--date", date]
    if analysts:
        cmd += ["--analysts", analysts]
    cmd += ["--quiet", "--output", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=CLI_TIMEOUT_SECONDS, check=False)
    except subprocess.TimeoutExpired:
        return {"error": f"Pipeline timed out after {CLI_TIMEOUT_SECONDS}s", "symbol": symbol}
    if proc.returncode != 0:
        return {"error": proc.stderr.strip()[-2000:] or f"exit {proc.returncode}", "symbol": symbol}
    stdout = proc.stdout.strip()
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        # CLI with --output - prints JSON; be tolerant of progress noise
        start = stdout.find("{")
        end = stdout.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(stdout[start : end + 1])
            except json.JSONDecodeError as exc:
                return {"error": f"Unparseable output: {exc}", "raw_tail": stdout[-800:]}
        else:
            return {"error": "No JSON on stdout", "raw_tail": stdout[-800:]}
    return {
        "symbol": symbol,
        "date": date,
        "rating": data.get("rating") or data.get("signal"),
        "decision_text": (data.get("final_trade_decision") or "")[:2000],
        "report_path": data.get("report_path"),
        "elapsed_seconds": data.get("_elapsed_seconds"),
    }


# --------------------------------------------------------------------------
# Tool registry
# --------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "name": "analyze_stock",
        "description": "对一只A股运行 15-agent 完整分析管线，返回最终评级与摘要（耗时约 2-5 分钟）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "股票代码，如 600519"},
                "date": {"type": "string", "description": "交易日期 YYYY-MM-DD，默认今天"},
                "analysts": {"type": "string", "description": "逗号分隔的分析师子集，如 market,fundamentals"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "list_snapshots",
        "description": "列出最近的分析快照（含评级、追踪 T+1/T+5/T+10/T+20 收益）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "stock_code": {"type": "string", "description": "可选，按股票代码过滤"},
                "limit": {"type": "integer", "description": "返回条数上限，默认 10"},
            },
        },
    },
    {
        "name": "get_snapshot",
        "description": "获取一只股票的最新快照、历史评级时间线与累计价格变化。",
        "inputSchema": {
            "type": "object",
            "properties": {"stock_code": {"type": "string", "description": "股票代码"}},
            "required": ["stock_code"],
        },
    },
    {
        "name": "read_recent_memories",
        "description": "读取最近的交易决策记忆条目（反思闭环的结论）。",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "条数，默认 10"}},
        },
    },
    {
        "name": "review_backtest",
        "description": "回测复盘：将历史快照评级与实际行情对照，更新 T+1/5/10/20 追踪与准确率统计（可选输出 Markdown 报告）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "只回测分析日期距今 >= N 天的记录，默认 0（全部）"},
                "report": {"type": "boolean", "description": "true 时返回 Markdown 复盘报告"},
            },
        },
    },
]

_TOOL_FUNCS = {
    "analyze_stock": analyze_stock,
    "list_snapshots": list_snapshots,
    "get_snapshot": get_snapshot,
    "read_recent_memories": read_recent_memories,
    "review_backtest": review_backtest,
}


# --------------------------------------------------------------------------
# MCP protocol dispatch (independently testable)
# --------------------------------------------------------------------------


def _dispatch_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    func = _TOOL_FUNCS.get(name)
    if func is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        return dict(func(**(arguments or {})))
    except TypeError as exc:
        return {"error": f"Invalid arguments for {name}: {exc}"}


class MCPServer:
    """Message-level MCP server; ``handle_message`` is pure and unit-testable."""

    def __init__(self) -> None:
        self.tools = TOOLS

    def handle_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method", "")
        msg_id = message.get("id")
        if method == "initialize":
            return self._result(
                msg_id,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": SERVER_INFO,
                },
            )
        if method == "ping":
            return self._result(msg_id, {})
        if method == "tools/list":
            return self._result(msg_id, {"tools": self.tools})
        if method == "tools/call":
            params = message.get("params") or {}
            result = _dispatch_tool(str(params.get("name")), params.get("arguments") or {})
            text = json.dumps(result, ensure_ascii=False, indent=2)
            return self._result(msg_id, {"content": [{"type": "text", "text": text}]})
        if msg_id is not None and method and not method.startswith("internal/"):
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
        return None

    @staticmethod
    def _result(msg_id: int | str | None, payload: dict[str, Any] | list) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "result": payload}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)

    server = MCPServer()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {exc}"}}
        else:
            response = server.handle_message(message)
            if response is None:  # notification / unknown
                continue
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
