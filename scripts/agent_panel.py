#!/usr/bin/env python3
"""智能体进度侧边栏面板生成器 (v0.5)。

监听分析运行产生的 <symbol>_<date>_progress.jsonl，生成一个自动刷新的
HTML 面板 agent_panel.html：15 位智能体按阶段分组显示 等待/运行/完成/失败
状态、每节点耗时、当前焦点高亮，末尾展示最终评级。标准库零依赖。

用法:
    python3 scripts/agent_panel.py <progress.jsonl> [-o agent_panel.html]
    面板每 2 秒自动重读 JSONL（自身 meta refresh），可与 long-running 分析常驻。
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

# 流水线智能体（与 progress_recorder.AGENT_LABELS 保持一致）
PIPELINE = [
    ("Market Analyst", "技术分析师", "① 分析师"),
    ("Social Analyst", "舆情分析师", "① 分析师"),
    ("News Analyst", "新闻分析师", "① 分析师"),
    ("Fundamentals Analyst", "基本面分析师", "① 分析师"),
    ("Bull Researcher", "看多研究员", "② 多空辩论"),
    ("Bear Researcher", "看空研究员", "② 多空辩论"),
    ("Research Manager", "研究经理", "③ 裁决"),
    ("Trader", "交易员", "④ 交易计划"),
    ("Aggressive Analyst", "激进风控", "⑤ 风控辩论"),
    ("Conservative Analyst", "保守风控", "⑤ 风控辩论"),
    ("Neutral Analyst", "中性风控", "⑤ 风控辩论"),
    ("Portfolio Manager", "基金经理", "⑥ 最终决策"),
]
STATUS_TEXT = {"pending": "待运行", "running": "运行中", "done": "完成", "error": "失败"}


def read_events(path: Path) -> list[dict]:
    events: list[dict] = []
    if not path.is_file():
        return events
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # 半行写入时跳过，下轮刷新补上
    return events


def summarize(events: list[dict]) -> dict:
    """把事件流折叠为面板渲染所需摘要。

    一个 node 周期 = node_state(running) → node_end（相邻事件时间差即耗时），
    多轮辩论同节点保留最后一次时长。
    """
    states: dict[str, str] = {}
    errors: dict[str, str] = {}
    durations: dict[str, float] = {}
    started_at: dict[str, float] = {}
    rating = ""
    elapsed = ""

    for ev in events:
        node = ev.get("node")
        kind = ev.get("event")
        t = float(ev.get("t", 0))
        if node:
            if kind == "node_state" and ev.get("state") == "running":
                states[node] = "running"
                started_at[node] = t
            elif kind == "node_end":
                if started_at.get(node) is not None:
                    durations[node] = round(t - started_at[node], 1)
                states[node] = "done"
            elif kind == "node_error":
                errors[node] = (ev.get("error") or "")[:260]
                states[node] = "error"
        if kind == "run_complete":
            rating = ev.get("rating", rating)
            elapsed = ev.get("elapsed_s", elapsed)
    return {"states": states, "errors": errors, "durations": durations, "rating": rating, "elapsed": elapsed}


def render_rows(data: dict) -> str:
    rows: list[str] = []
    stages = ["① 分析师", "② 多空辩论", "③ 裁决", "④ 交易计划", "⑤ 风控辩论", "⑥ 最终决策"]
    for stage in stages:
        rows.append(f"<h4>{html.escape(stage)}</h4>")
        for node, label, st in PIPELINE:
            if st != stage:
                continue
            state = data["states"].get(node, "pending")
            dur = data["durations"].get(node)
            dur_s = f" · {dur:.1f}s" if dur else ""
            err = data["errors"].get(node)
            err_attr = f' title="{html.escape(err)}"' if err else ""
            rows.append(
                f"<div class='card {state}'{err_attr}>"
                "<span class='dot'></span><b>" + html.escape(label) + "</b>"
                f"<span class='nodeid'>{html.escape(node)}</span>"
                f"<span class='state'>{STATUS_TEXT[state]}{dur_s}</span></div>"
            )
    return "\n".join(rows)


def render_html(path: Path, data: dict) -> str:
    if data["rating"]:
        final = (
            f"<div class='final'>最终评级：<b>{html.escape(str(data['rating']))}</b>"
            f" · 用时 {html.escape(str(data['elapsed']))}s</div>"
        )
    else:
        final = "<div class='final final-none'>运行中…（面板每 2 秒自动刷新）</div>"
    title_html = html.escape(path.name)
    return (
        "<!doctype html><html lang='zh'><head><meta charset='utf-8'>\n"
        "<meta http-equiv='refresh' content='2'>\n"
        f"<title>智能体进度 · {title_html}</title><style>\n"
        "body{font-family:system-ui,'Microsoft YaHei',sans-serif;background:#0f172a;"
        "color:#e2e8f0;padding:14px;max-width:560px}\n"
        "h3{margin:4px 0 10px}h4{margin:14px 0 6px;color:#94a3b8;font-size:13px}\n"
        ".card{display:flex;align-items:center;gap:8px;background:#1e293b;border-radius:8px;"
        "padding:7px 10px;margin:4px 0;font-size:13px}\n"
        ".card b{flex:0 0 auto}\n"
        ".nodeid{color:#64748b;font-size:11px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}\n"
        ".state{font-size:12px;color:#94a3b8}\n"
        ".card.running{outline:2px solid #38bdf8;background:#1e3a5f}\n"
        ".card.done .state{color:#4ade80}\n"
        ".card.error{outline:2px solid #f87171}\n"
        ".dot{width:8px;height:8px;border-radius:50%;background:#475569;flex:0 0 auto}\n"
        ".card.running .dot{background:#fbbf24;animation:bl 1s infinite alternate}\n"
        ".card.done .dot{background:#4ade80}\n"
        ".card.error .dot{background:#f87171}\n"
        "@keyframes bl{from{opacity:.3}to{opacity:1}}\n"
        ".final{margin-top:14px;padding:10px;background:#1e293b;border-left:4px solid #4ade80;border-radius:6px}\n"
        ".final-none{border-left-color:#475569;color:#94a3b8}\n"
        "</style></head><body>\n"
        "<h3>🤖 A股智能决策 · 智能体进度面板</h3>\n" + render_rows(data) + "\n" + final + "\n</body></html>\n"
    )


def build(path: Path, out: Path) -> dict:
    data = summarize(read_events(path))
    out.write_text(render_html(path, data), encoding="utf-8")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成智能体进度 HTML 侧边栏面板")
    parser.add_argument("progress", help="<symbol>_<date>_progress.jsonl 路径")
    parser.add_argument("-o", "--output", default=None, help="输出 HTML（默认同目录 agent_panel.html）")
    args = parser.parse_args(argv)

    src = Path(args.progress)
    out = Path(args.output) if args.output else src.with_name("agent_panel.html")
    data = build(src, out)
    print(f"Panel written: {out} (rating: {data['rating'] or '运行中'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
