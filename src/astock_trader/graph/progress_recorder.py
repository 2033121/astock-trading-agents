"""Per-agent progress recorder — feeds the agent sidebar panel.

Writes every pipeline node start/end/error to a JSONL file while the graph
runs, so any host (DSH sidebar panel / codex CLI tail / zcode) can watch all
15 agents' progress live:

```json
{"ts": ..., "event": "node_start", "node": "Market Analyst", "ts_ms": 1234}
{"ts": ..., "event": "node_end",   "node": "Market Analyst", "duration_ms": 4021}
{"ts": ..., "event": "node_error", "node": "...", "error": "..."}
{"ts": ..., "event": "run_complete", "rating": "增持", "elapsed_s": 88.2}
```

Install as a LangChain callback handler into the graph invoke ``config``:

```python
recorder = NodeProgressRecorder(path)
graph.invoke(state, config={"callbacks": [recorder], **thread_config})
```

The known-node mo table maps graph node ids to human-facing Chinese labels
and stages, so the panel UI is host-friendly (per-agent adaptation).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:  # langchain_core only needed at runtime inside the graph process
    from langchain_core.callbacks import BaseCallbackHandler
except ImportError:  # pragma: no cover - allows pure-tooling import

    class BaseCallbackHandler:  # type: ignore[no-redef]
        pass


# ── Per-agent display adaptation ────────────────────────────────────

AGENT_LABELS: dict[str, dict[str, str]] = {
    "Market Analyst": {"label": "技术分析师", "stage": "① 分析师"},
    "Social Analyst": {"label": "舆情分析师", "stage": "① 分析师"},
    "News Analyst": {"label": "新闻分析师", "stage": "① 分析师"},
    "Fundamentals Analyst": {"label": "基本面分析师", "stage": "① 分析师"},
    "tools_market": {"label": "技术分析·工具", "stage": "① 分析师"},
    "Msg Clear Fundamentals": {"label": "基本面收尾", "stage": "① 分析师"},
    "Bull Researcher": {"label": "看多研究员", "stage": "② 多空辩论"},
    "Bear Researcher": {"label": "看空研究员", "stage": "② 多空辩论"},
    "Research Manager": {"label": "研究经理", "stage": "③ 裁决"},
    "Trader": {"label": "交易员", "stage": "④ 交易计划"},
    "Aggressive Analyst": {"label": "激进风控", "stage": "⑤ 风控辩论"},
    "Conservative Analyst": {"label": "保守风控", "stage": "⑤ 风控辩论"},
    "Neutral Analyst": {"label": "中性风控", "stage": "⑤ 风控辩论"},
    "Portfolio Manager": {"label": "基金经理", "stage": "⑥ 最终决策"},
}

_EXEC_NODES = {
    "tools",  # ReAct tool-loop nodes (analysts)
    "Msg Clear Fundamentals",
}


def pretty_node(node: str) -> tuple[str, str]:
    """Return (human_label, stage) for a graph node id."""
    meta = AGENT_LABELS.get(node)
    if meta:
        return meta["label"], meta["stage"]
    if node.startswith("tools_"):
        return f"{node.removeprefix('tools_').capitalize()}·工具", "① 分析师"
    if node.startswith("Msg Clear"):
        return f"{node.removeprefix('Msg Clear ')}·收尾", "① 分析师"
    return node, "流水线"


class NodeProgressRecorder(BaseCallbackHandler):
    """Append node-level run events to a JSONL progress file.

    Only trims to known/interesting chain runs so embedded tool runs (ReAct
    loops inside analysts) still record but the file stays readable.
    """

    def __init__(self, path: str | os.PathLike[str], *, min_node_ms: int = 0) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.started = time.time()
        self.t0 = time.monotonic()
        self.name_of: dict[str, str] = {}  # run_id -> graph node id
        self.depth: dict[str, int] = {}
        self.nodes_done = 0
        self.lock = threading.Lock()

    # -- helpers / callback interface ----------------------------------------

    def on_chain_start(
        self, serialized: Any, inputs: Any, *, run_id: str, parent_run_id: str | None = None, **kwargs: Any
    ) -> None:  # noqa: D401
        node = self._node_name(serialized, inputs, kwargs)
        if not node:
            return
        with self.lock:
            self.name_of[str(run_id)] = node
            self.depth[str(run_id)] = 1 if parent_run_id is None else 0
        self._append_event("node_state", node, state="running")

    def on_chain_end(self, outputs: Any, *, run_id: str, **kwargs: Any) -> None:
        node = self.name_of.pop(str(run_id), None)
        if node is None:
            return
        with self.lock:
            self.nodes_done += 1
        self._append_event("node_end", node)

    def on_chain_error(self, error: Any, *, run_id: str, **kwargs: Any) -> None:
        node = self.name_of.pop(str(run_id), None)
        if node is None:
            return
        self._append_event(
            "node_error",
            node,
            error=str(error).splitlines()[0][:300],
        )

    # -- public API ----------------------------------------------------------

    def mark_complete(self, rating: str, elapsed_s: float) -> None:
        self._append_event(
            "run_complete",
            rating=rating,
            elapsed_s=elapsed_s,
        )

    def mark_error(self, error: str) -> None:
        self._append_event("run_error", error=error[:400])

    # -- internals -----------------------------------------------------------

    @staticmethod
    def _node_name(serialized: Any, inputs: Any, kwargs: Any) -> str | None:
        name = None
        if isinstance(serialized, dict):
            name = serialized.get("name") or serialized.get("id")
        if not name:
            name = kwargs.get("name") or kwargs.get("run_name") or serialized
        if isinstance(name, (list, tuple)):
            name = name[-1] if name else None
        if isinstance(name, list):
            name = name[-1] if name else None
        if not isinstance(name, str) or not name:
            return None
        # Ignore low-value internal chains; keep node-like names.
        junk = {"Msg Clear Fundamentals", "LangGraph", "<module>", "Runnable"}
        if name in junk or name.startswith("Runnable"):
            return None
        return name

    def _append_event(
        self,
        event: str,
        node: str | None = None,
        *,
        state: str | None = None,
        error: str | None = None,
        rating: str | None = None,
        elapsed_s: float | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "ts": round(time.time(), 2),
            "t": round(time.monotonic() - self.t0, 2),
            "event": event,
        }
        if node is not None:
            label, stage = pretty_node(node)
            payload["node"] = node
            payload["label"] = label
            payload["stage"] = stage
        if state is not None:
            payload["state"] = state
        if error is not None:
            payload["error"] = error
        if rating is not None:
            payload["rating"] = rating
        if elapsed_s is not None:
            payload["elapsed_s"] = elapsed_s
        with self.lock:
            try:
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(payload, ensure_ascii=False) + "\n")
            except OSError as exc:
                logger.warning("Progress recorder write failed: %s", exc)


def with_callback_config(config: dict[str, Any], recorder: Any) -> dict[str, Any]:
    """Merge ``recorder`` into an invoke ``config`` (callbacks list).

    Non-destructive: returns a new dict; callbacks lists are appended.
    """
    if recorder is None:
        return dict(config)
    merged = dict(config)
    callbacks = list(merged.get("callbacks") or [])
    callbacks.append(recorder)
    merged["callbacks"] = callbacks
    return merged


def default_progress_path(results_dir: str, company: str, trade_date: str) -> Path:
    """Default JSONL path: <results_dir>/<company>_<date>_progress.jsonl."""
    company = "".join(ch for ch in company if ch.isalnum())[:12]
    safe_date = trade_date.replace("-", "") or "default"
    return Path(results_dir) / f"{company}_{safe_date}_progress.jsonl"


__all__ = [
    "NodeProgressRecorder",
    "AGENT_LABELS",
    "pretty_node",
    "default_progress_path",
]
