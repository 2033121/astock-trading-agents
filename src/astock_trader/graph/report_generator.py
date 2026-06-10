"""Report Generator — 生成可交互的 HTML 分析报告。

该模块是流水线的最后一环（纯 Python，不调用 LLM），
将各智能体产出汇总为一份带折叠面板、流水线可视化的 HTML 报告，
保存到指定目录。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────
#  Stage definitions (order matches the pipeline topology)
# ────────────────────────────────────────────────────────────────

STAGE_DEFS = [
    {
        "id": "market",
        "num": "1",
        "name": "市场分析师",
        "desc": "股价走势 / 估值 / 资金流向 / 技术面",
        "field": "market_report",
    },
    {
        "id": "sentiment",
        "num": "2",
        "name": "情绪分析师",
        "desc": "重大事件 / 融资融券 / 股东动向 / 机构观点",
        "field": "sentiment_report",
    },
    {
        "id": "news",
        "num": "3",
        "name": "新闻分析师",
        "desc": "最新动态 / 机构研报 / 行业对比 / 宏观环境",
        "field": "news_report",
    },
    {
        "id": "fundamentals",
        "num": "4",
        "name": "基本面分析师",
        "desc": "盈利能力 / 成长性 / 资产负债 / 现金流 / 分红",
        "field": "fundamentals_report",
    },
    {"id": "debate", "num": "5", "name": "多空辩论", "desc": "多头 vs 空头 → 辩论裁判裁决", "field": None},
    {
        "id": "research",
        "num": "6",
        "name": "研究主管",
        "desc": "综合各分析师报告，形成投资方案",
        "field": "investment_plan",
    },
    {
        "id": "trader",
        "num": "7",
        "name": "交易员",
        "desc": "制定具体可执行的交易计划",
        "field": "trader_investment_plan",
    },
    {"id": "risk", "num": "8", "name": "风控辩论", "desc": "风险评估辩论 → 风控裁判裁决", "field": None},
    {"id": "final", "num": "9", "name": "组合经理", "desc": "最终投资决策", "field": "final_trade_decision"},
    {"id": "summary", "num": "10", "name": "报告总结", "desc": "综合全部智能体产出，生成一页执行摘要", "field": None},
]


def generate_report(
    state: dict[str, Any],
    output_dir: str,
    rating: str = "",
    elapsed_seconds: float = 0,
) -> str:
    """Generate an interactive HTML report from the final pipeline state.

    Parameters
    ----------
    state : dict
        The final ``AgentState`` after graph execution.
    output_dir : str
        Directory where the HTML file will be saved.
    rating : str
        Extracted rating string (e.g. "买入").
    elapsed_seconds : float
        Total analysis duration in seconds.

    Returns
    -------
    str
        Absolute path to the generated HTML report file.
    """
    company = state.get("company_of_interest", "unknown")
    trade_date = state.get("trade_date", datetime.now().strftime("%Y-%m-%d"))

    # ── Build stage data ─────────────────────────────────────
    stages = []
    for defn in STAGE_DEFS:
        content = _extract_content(state, defn)
        if not content and defn["id"] != "summary":
            continue
        stages.append(
            {
                "id": defn["id"],
                "num": defn["num"],
                "name": defn["name"],
                "desc": defn["desc"],
                "content": content,
            }
        )

    # ── Build summary stage (always generated) ───────────────
    summary_text = _build_summary(state, company, trade_date, rating, elapsed_seconds)
    # Replace or append the summary stage
    summary_found = False
    for s in stages:
        if s["id"] == "summary":
            s["content"] = summary_text
            summary_found = True
            break
    if not summary_found:
        summary_def = STAGE_DEFS[-1]
        stages.append(
            {
                "id": "summary",
                "num": summary_def["num"],
                "name": summary_def["name"],
                "desc": summary_def["desc"],
                "content": summary_text,
            }
        )

    # ── Assemble data object ─────────────────────────────────
    report_data = {
        "stages": stages,
        "rating": rating,
        "elapsed": elapsed_seconds,
    }

    data_json = json.dumps(report_data, ensure_ascii=False)

    # ── Build HTML ───────────────────────────────────────────
    html = _HTML_TEMPLATE.replace("__DATA_PLACEHOLDER__", data_json)

    # ── Write file ───────────────────────────────────────────
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filename = f"{company}_{trade_date}_report.html"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info("Report generated: %s (%d bytes)", filepath, os.path.getsize(filepath))
    return filepath


# ────────────────────────────────────────────────────────────────
#  Internal helpers
# ────────────────────────────────────────────────────────────────


def _extract_content(state: dict[str, Any], defn: dict) -> str:
    """Extract the text content for a stage from the state."""
    sid = defn["id"]
    field = defn["field"]

    if field:
        return state.get(field, "")

    # Special cases: debate states
    if sid == "debate":
        debate = state.get("investment_debate_state") or {}
        return debate.get("judge_decision", "")

    if sid == "risk":
        risk = state.get("risk_debate_state") or {}
        return risk.get("judge_decision", "")

    if sid == "summary":
        return ""  # Built separately

    return ""


def _build_summary(
    state: dict[str, Any],
    company: str,
    trade_date: str,
    rating: str,
    elapsed: float,
) -> str:
    """Build a one-page executive summary from the pipeline state."""
    n_stages = len(STAGE_DEFS)
    total_chars = sum(len(state.get(d["field"], "")) for d in STAGE_DEFS if d["field"])
    debate = state.get("investment_debate_state") or {}
    risk = state.get("risk_debate_state") or {}
    total_chars += len(debate.get("judge_decision", ""))
    total_chars += len(risk.get("judge_decision", ""))

    # Extract key excerpts (first 120 chars of each report)
    def _excerpt(field: str, n: int = 120) -> str:
        text = state.get(field, "")
        if not text:
            return ""
        # Find the first meaningful line
        for line in text.split("\n"):
            line = line.strip().lstrip("#").lstrip("*").strip()
            if len(line) > 20:
                return line[:n] + ("..." if len(line) > n else "")
        return text[:n] + "..."

    # Build agent findings table
    agents_info = [
        ("市场分析师", "market_report"),
        ("情绪分析师", "sentiment_report"),
        ("新闻分析师", "news_report"),
        ("基本面分析师", "fundamentals_report"),
    ]

    rows = []
    for name, field in agents_info:
        excerpt = _excerpt(field, 100)
        rows.append(f"| **{name}** | {excerpt} | — |")

    # Debate rows
    debate_judge = debate.get("judge_decision", "")
    if debate_judge:
        rows.append(f"| **多空辩论** | {_excerpt_from_text(debate_judge, 100)} | — |")

    plan = state.get("investment_plan", "")
    if plan:
        rows.append(f"| **研究主管** | {_excerpt_from_text(plan, 100)} | — |")

    trader = state.get("trader_investment_plan", "")
    if trader:
        rows.append(f"| **交易员** | {_excerpt_from_text(trader, 100)} | — |")

    risk_judge = risk.get("judge_decision", "")
    if risk_judge:
        rows.append(f"| **风控辩论** | {_excerpt_from_text(risk_judge, 100)} | — |")

    final = state.get("final_trade_decision", "")
    if final:
        rows.append(f"| **组合经理** | {_excerpt_from_text(final, 100)} | **{rating}** |")

    table_rows = "\n".join(rows)

    summary = f"""## {company} 投资分析执行摘要

**报告日期：{trade_date} | 评级：{rating} | 分析耗时：{elapsed:.1f}秒**

---

### 核心结论

{_excerpt("final_trade_decision", 200)}

---

### 各智能体核心发现

| 智能体 | 核心发现 | 信号 |
|:---|:---|:---:|
{table_rows}

---

### 分析流程回溯

本报告由 **{n_stages} 个智能体** 协作完成，总耗时 {elapsed:.1f} 秒，产出约 {total_chars:,} 字。
多空辩论和风控辩论环节采用对抗式论证，确保投资决策经过充分质疑和检验。

> **一句话总结：{_excerpt("final_trade_decision", 150)}**"""

    return summary


def _excerpt_from_text(text: str, n: int = 120) -> str:
    """Extract the first meaningful line from text."""
    for line in text.split("\n"):
        line = line.strip().lstrip("#").lstrip("*").lstrip("-").strip()
        if len(line) > 20:
            return line[:n] + ("..." if len(line) > n else "")
    return text[:n] + "..." if len(text) > n else text


# ════════════════════════════════════════════════════════════════
#  HTML Template (single-file, uses marked.js from CDN)
# ════════════════════════════════════════════════════════════════

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股多智能体分析报告</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.0/marked.min.js"></script>
<style>
  :root {
    --bg: #0f1117; --surface: #1a1d27; --surface2: #242836;
    --border: #2d3348; --text: #e4e7ef; --text2: #8b92a8;
    --accent: #6c8cff; --accent2: #4ecdc4;
    --buy: #22c55e; --sell: #ef4444; --warn: #f59e0b;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.7;
    padding: 20px; max-width: 960px; margin: 0 auto;
  }
  .header { text-align: center; padding: 32px 0 24px; border-bottom: 1px solid var(--border); margin-bottom: 24px; }
  .header h1 { font-size: 28px; font-weight: 700; margin-bottom: 8px; letter-spacing: 1px; }
  .header .subtitle { color: var(--text2); font-size: 14px; }
  .rating-badge { display: inline-block; background: var(--buy); color: #fff; font-size: 20px; font-weight: 700; padding: 8px 32px; border-radius: 8px; margin: 16px 0 8px; letter-spacing: 2px; }
  .rating-badge.sell { background: var(--sell); }
  .rating-badge.hold { background: var(--warn); }
  .elapsed { color: var(--text2); font-size: 13px; margin-top: 4px; }
  .pipeline { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; justify-content: center; padding: 20px 0; margin-bottom: 24px; border-bottom: 1px solid var(--border); }
  .pipeline-node { display: flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: 6px; font-size: 12px; font-weight: 500; cursor: pointer; transition: all 0.2s; background: var(--surface); border: 1px solid var(--border); color: var(--text2); }
  .pipeline-node:hover, .pipeline-node.active { background: var(--surface2); border-color: var(--accent); color: var(--text); }
  .pipeline-node .pnum { display: inline-flex; align-items: center; justify-content: center; width: 20px; height: 20px; border-radius: 50%; background: var(--border); color: var(--text2); font-size: 11px; font-weight: 700; flex-shrink: 0; }
  .pipeline-node.active .pnum, .pipeline-node:hover .pnum { background: var(--accent); color: #fff; }
  .pipeline-arrow { color: var(--border); font-size: 14px; flex-shrink: 0; }
  .stage-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; margin-bottom: 16px; overflow: hidden; transition: border-color 0.2s; }
  .stage-card:hover { border-color: var(--accent); }
  .stage-header { display: flex; align-items: center; gap: 12px; padding: 16px 20px; cursor: pointer; user-select: none; transition: background 0.15s; }
  .stage-header:hover { background: var(--surface2); }
  .stage-num { display: flex; align-items: center; justify-content: center; width: 32px; height: 32px; border-radius: 50%; background: var(--accent); color: #fff; font-size: 14px; font-weight: 700; flex-shrink: 0; }
  .stage-card.debate .stage-num { background: var(--warn); }
  .stage-card.final .stage-num { background: var(--buy); }
  .stage-card.summary .stage-num { background: linear-gradient(135deg, var(--accent), var(--accent2)); }
  .stage-card.summary { border-color: var(--accent); }
  .stage-info { flex: 1; min-width: 0; }
  .stage-name { font-size: 16px; font-weight: 600; }
  .stage-desc { font-size: 12px; color: var(--text2); margin-top: 2px; }
  .stage-toggle { color: var(--text2); font-size: 18px; transition: transform 0.25s; flex-shrink: 0; }
  .stage-card.open .stage-toggle { transform: rotate(180deg); }
  .stage-body { max-height: 0; overflow: hidden; transition: max-height 0.35s ease; }
  .stage-card.open .stage-body { max-height: 8000px; }
  .stage-content { padding: 0 20px 20px; border-top: 1px solid var(--border); padding-top: 16px; }
  .md-content h1 { font-size: 20px; margin: 16px 0 10px; font-weight: 700; }
  .md-content h2 { font-size: 18px; margin: 16px 0 8px; font-weight: 600; border-bottom: 1px solid var(--border); padding-bottom: 6px; }
  .md-content h3 { font-size: 16px; margin: 14px 0 6px; font-weight: 600; }
  .md-content h4 { font-size: 14px; margin: 12px 0 4px; font-weight: 600; }
  .md-content p { margin: 8px 0; }
  .md-content ul, .md-content ol { padding-left: 24px; margin: 8px 0; }
  .md-content li { margin: 4px 0; }
  .md-content strong { color: var(--accent2); }
  .md-content blockquote { border-left: 3px solid var(--accent); padding: 8px 16px; margin: 10px 0; background: var(--surface2); border-radius: 0 6px 6px 0; font-size: 14px; }
  .md-content table { width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 13px; }
  .md-content th, .md-content td { border: 1px solid var(--border); padding: 8px 12px; text-align: left; }
  .md-content th { background: var(--surface2); font-weight: 600; }
  .md-content hr { border: none; border-top: 1px solid var(--border); margin: 16px 0; }
  .md-content code { background: var(--surface2); padding: 2px 6px; border-radius: 4px; font-size: 13px; }
  .md-content em { color: var(--text2); }
  .controls { display: flex; gap: 8px; margin-bottom: 20px; flex-wrap: wrap; }
  .controls button { background: var(--surface); border: 1px solid var(--border); color: var(--text2); padding: 6px 16px; border-radius: 6px; font-size: 13px; cursor: pointer; transition: all 0.15s; }
  .controls button:hover { background: var(--surface2); border-color: var(--accent); color: var(--text); }
  @media (max-width: 640px) { body { padding: 12px; } .header h1 { font-size: 22px; } .pipeline-node { font-size: 11px; padding: 4px 8px; } .stage-content { padding: 0 14px 14px; padding-top: 12px; } }
</style>
</head>
<body>
<div class="header">
  <h1 id="stockTitle"></h1>
  <div class="subtitle" id="subtitle"></div>
  <div class="rating-badge" id="ratingBadge"></div>
  <div class="elapsed" id="elapsedInfo"></div>
</div>
<div class="pipeline" id="pipeline"></div>
<div class="controls">
  <button onclick="expandAll()">全部展开</button>
  <button onclick="collapseAll()">全部收起</button>
  <button onclick="expandOnly(['market','fundamentals','debate','final','summary'])">只看关键阶段</button>
</div>
<div id="stages"></div>
<script>
const DATA = __DATA_PLACEHOLDER__;
const ICONS = {
  market: '\u{1F4CA}', sentiment: '\u{1F4AC}', news: '\u{1F4F0}', fundamentals: '\u{1F4C8}',
  debate: '\u2694\uFE0F', research: '\u{1F52C}', trader: '\u{1F4B9}', risk: '\u{1F6E1}\uFE0F',
  final: '\u{1F3E6}', summary: '\u{1F4CB}'
};

function init() {
  const company = DATA.stages.length > 0 ? '' : '';
  document.getElementById('stockTitle').textContent = 'A\u80A1\u591A\u667A\u80FD\u4F53\u5206\u6790\u62A5\u544A';
  document.getElementById('subtitle').textContent =
    '\u80A1\u7968: ' + (DATA.company || '') + ' \u00B7 ' + (DATA.trade_date || '');

  const badge = document.getElementById('ratingBadge');
  badge.textContent = DATA.rating;
  const r = DATA.rating || '';
  if (r.includes('\u5356\u51FA') || r.includes('\u51CF\u6301')) badge.classList.add('sell');
  else if (r.includes('\u6301\u6709')) badge.classList.add('hold');

  document.getElementById('elapsedInfo').textContent =
    '\u5206\u6790\u8017\u65F6 ' + DATA.elapsed + ' \u79D2 \u00B7 ' +
    DATA.stages.length + ' \u4E2A\u667A\u80FD\u4F53\u534F\u4F5C \u00B7 ' +
    DATA.stages.reduce(function(s, st) { return s + st.content.length; }, 0).toLocaleString() + ' \u5B57';

  var pl = document.getElementById('pipeline');
  DATA.stages.forEach(function(s, i) {
    if (i > 0) {
      var arrow = document.createElement('span');
      arrow.className = 'pipeline-arrow';
      arrow.textContent = '\u2192';
      pl.appendChild(arrow);
    }
    var node = document.createElement('div');
    node.className = 'pipeline-node';
    node.innerHTML = '<span class="pnum">' + s.num + '</span>' + s.name;
    node.onclick = (function(sid) {
      return function() {
        var card = document.getElementById('card-' + sid);
        card.scrollIntoView({ behavior: 'smooth', block: 'start' });
        if (!card.classList.contains('open')) card.classList.add('open');
      };
    })(s.id);
    pl.appendChild(node);
  });

  var container = document.getElementById('stages');
  DATA.stages.forEach(function(s) {
    var isDebate = s.id === 'debate' || s.id === 'risk';
    var isFinal = s.id === 'final';
    var isSummary = s.id === 'summary';
    var cls = isDebate ? 'debate' : (isFinal ? 'final' : (isSummary ? 'summary' : ''));
    var card = document.createElement('div');
    card.className = 'stage-card ' + cls;
    card.id = 'card-' + s.id;
    var rendered = marked.parse(s.content);
    card.innerHTML =
      '<div class="stage-header" onclick="toggleCard(\'' + s.id + '\')">' +
        '<div class="stage-num">' + s.num + '</div>' +
        '<div class="stage-info">' +
          '<div class="stage-name">' + (ICONS[s.id] || '') + ' ' + s.name + '</div>' +
          '<div class="stage-desc">' + s.desc + '</div>' +
        '</div>' +
        '<div class="stage-toggle">\u25BC</div>' +
      '</div>' +
      '<div class="stage-body">' +
        '<div class="stage-content md-content">' + rendered + '</div>' +
      '</div>';
    container.appendChild(card);
  });
}

function toggleCard(id) { document.getElementById('card-' + id).classList.toggle('open'); }
function expandAll() { document.querySelectorAll('.stage-card').forEach(function(c) { c.classList.add('open'); }); }
function collapseAll() { document.querySelectorAll('.stage-card').forEach(function(c) { c.classList.remove('open'); }); }
function expandOnly(ids) {
  document.querySelectorAll('.stage-card').forEach(function(c) {
    var sid = c.id.replace('card-', '');
    c.classList.toggle('open', ids.indexOf(sid) !== -1);
  });
}

marked.setOptions({ breaks: true, gfm: true, headerIds: false, mangle: false });
init();
</script>
</body>
</html>"""
