"""Typer CLI — ``astock-trader`` command-line interface.

Provides four top-level commands:

* ``analyze``  — run the multi-agent analysis pipeline
* ``history``  — view past analysis records
* ``memory``   — manage the decision memory log
* ``config``   — inspect and modify runtime configuration

Invocation::

    astock-trader analyze 000001
    astock-trader analyze 600519 --date 2025-06-01 --provider deepseek
    astock-trader history 000001 --limit 5
    astock-trader memory show
    astock-trader config --show
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# ────────────────────────────────────────────────────────────────
#  App setup
# ────────────────────────────────────────────────────────────────

app = typer.Typer(
    name="astock-trader",
    help="A股多Agent量化交易决策框架 — 基于 LangGraph 的多角色辩论式分析",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()

# ────────────────────────────────────────────────────────────────
#  Helpers
# ────────────────────────────────────────────────────────────────

_DEFAULT_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".astock_trader")
_USER_CONFIG_PATH = os.path.join(_DEFAULT_CONFIG_DIR, "user_config.json")


def _load_user_config() -> dict[str, Any]:
    """Load user-level config overrides (persisted via ``config --set``)."""
    if os.path.exists(_USER_CONFIG_PATH):
        try:
            with open(_USER_CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_user_config(cfg: dict[str, Any]) -> None:
    """Persist user-level config to disk."""
    Path(_DEFAULT_CONFIG_DIR).mkdir(parents=True, exist_ok=True)
    with open(_USER_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _build_config(
    provider: str | None = None,
    deep_model: str | None = None,
    quick_model: str | None = None,
    base_url: str | None = None,
    language: str = "Chinese",
    checkpoint: bool = False,
    max_debate_rounds: int = 1,
    max_risk_discuss_rounds: int = 1,
) -> dict[str, Any]:
    """Merge DEFAULT_CONFIG + user config + CLI overrides."""
    from astock_trader.default_config import DEFAULT_CONFIG

    cfg = {**DEFAULT_CONFIG}
    user_cfg = _load_user_config()
    cfg.update(user_cfg)

    if provider is not None:
        cfg["llm_provider"] = provider
    if deep_model is not None:
        cfg["deep_think_llm"] = deep_model
    if quick_model is not None:
        cfg["quick_think_llm"] = quick_model
    if base_url is not None:
        cfg["backend_url"] = base_url
    if language != "Chinese":
        cfg["output_language"] = language
    cfg["checkpoint_enabled"] = checkpoint
    cfg["max_debate_rounds"] = max_debate_rounds
    cfg["max_risk_discuss_rounds"] = max_risk_discuss_rounds

    return cfg


def _format_state_summary(state: dict[str, Any], rating: str) -> str:
    """Build a Markdown summary of the analysis results."""
    company = state.get("company_of_interest", "?")
    trade_date = state.get("trade_date", "?")

    sections = [
        f"# {company} 分析结果",
        f"**交易日期**: {trade_date}",
        f"**最终评级**: **{rating}**",
        "",
        "---",
        "",
    ]

    # Analyst reports
    report_fields = [
        ("market_report", "市场/技术面分析"),
        ("sentiment_report", "市场情绪分析"),
        ("news_report", "新闻舆情分析"),
        ("fundamentals_report", "基本面分析"),
    ]
    for field, title in report_fields:
        content = state.get(field, "")
        if content:
            sections.append(f"## {title}")
            sections.append(content[:2000])
            sections.append("")

    # Investment debate
    debate = state.get("investment_debate_state", {})
    if debate:
        judge = debate.get("judge_decision", "")
        if judge:
            sections.append("## 研究员综合方案")
            sections.append(judge[:2000])
            sections.append("")

    # Trader plan
    trader_plan = state.get("trader_investment_plan", "")
    if trader_plan:
        sections.append("## 交易员计划")
        sections.append(trader_plan[:2000])
        sections.append("")

    # Risk debate
    risk = state.get("risk_debate_state", {})
    if risk:
        judge = risk.get("judge_decision", "")
        if judge:
            sections.append("## 风控综合评估")
            sections.append(judge[:2000])
            sections.append("")

    # Final decision
    decision = state.get("final_trade_decision", "")
    if decision:
        sections.append("## 最终交易决策")
        sections.append(decision)
        sections.append("")

    return "\n".join(sections)


# ════════════════════════════════════════════════════════════════
#  Commands
# ════════════════════════════════════════════════════════════════


@app.command()
def analyze(
    symbol: str = typer.Argument(..., help="股票代码，如 000001、600519"),
    date: str | None = typer.Option(None, "--date", "-d", help="交易日期 YYYY-MM-DD，默认今天"),
    provider: str = typer.Option("openai", "--provider", "-p", help="LLM 提供商 (openai/deepseek/qwen/glm/...)"),
    deep_model: str | None = typer.Option(None, "--deep-model", help="深度思考模型名称"),
    quick_model: str | None = typer.Option(None, "--quick-model", help="快速思考模型名称"),
    base_url: str | None = typer.Option(None, "--base-url", help="自定义 API 基础 URL"),
    language: str = typer.Option("Chinese", "--language", "-l", help="输出语言 (Chinese/English)"),
    analysts: str | None = typer.Option(
        None,
        "--analysts",
        "-a",
        help="分析师组合，逗号分隔 (market,social,news,fundamentals)",
    ),
    debate_rounds: int = typer.Option(1, "--debate-rounds", help="多空辩论轮数"),
    risk_rounds: int = typer.Option(1, "--risk-rounds", help="风控讨论轮数"),
    checkpoint: bool = typer.Option(False, "--checkpoint", help="启用 SQLite 检查点（崩溃恢复）"),
    output: str | None = typer.Option(None, "--output", "-o", help="输出文件路径 (JSON)"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="安静模式，仅输出结果"),
) -> None:
    """运行多 Agent 分析流水线。

    示例:

        astock-trader analyze 000001

        astock-trader analyze 600519 --date 2025-06-01 --provider deepseek

        astock-trader analyze 300750 --analysts market,fundamentals --debate-rounds 2
    """
    # ── Resolve date ──────────────────────────────────────────
    trade_date = date or datetime.now().strftime("%Y-%m-%d")

    # ── Resolve analysts ─────────────────────────────────────
    valid_analysts = ["market", "social", "news", "fundamentals"]
    if analysts:
        selected = [a.strip() for a in analysts.split(",")]
        for a in selected:
            if a not in valid_analysts:
                console.print(f"[red]无效的分析师: {a}[/red]  可选: {', '.join(valid_analysts)}")
                raise typer.Exit(1)
    else:
        selected = valid_analysts

    # ── Build config ──────────────────────────────────────────
    config = _build_config(
        provider=provider,
        deep_model=deep_model,
        quick_model=quick_model,
        base_url=base_url,
        language=language,
        checkpoint=checkpoint,
        max_debate_rounds=debate_rounds,
        max_risk_discuss_rounds=risk_rounds,
    )

    if not quiet:
        # ── Banner ────────────────────────────────────────────
        header = Table(show_header=False, box=None, padding=(0, 2))
        header.add_column(style="bold cyan")
        header.add_column()
        header.add_row("标的", symbol)
        header.add_row("日期", trade_date)
        header.add_row("提供商", config["llm_provider"])
        header.add_row("深度模型", config["deep_think_llm"])
        header.add_row("快速模型", config["quick_think_llm"])
        header.add_row("分析师", ", ".join(selected))
        header.add_row("辩论轮数", str(debate_rounds))
        header.add_row("风控轮数", str(risk_rounds))

        console.print(
            Panel(
                header,
                title="[bold]A股多Agent分析[/bold]",
                border_style="blue",
            )
        )

    # ── Run pipeline ──────────────────────────────────────────
    try:
        from astock_trader.graph.trading_graph import TradingAgentsGraph

        if not quiet:
            console.print("\n[bold yellow]正在初始化 Agent 图...[/bold yellow]")

        graph = TradingAgentsGraph(
            selected_analysts=selected,
            debug=False,
            config=config,
        )

        if not quiet:
            console.print("[bold yellow]正在执行分析流水线（这可能需要几分钟）...[/bold yellow]\n")

        start_time = time.time()
        final_state, rating = graph.propagate(symbol, trade_date)
        elapsed = time.time() - start_time

    except Exception as exc:
        console.print(f"\n[bold red]分析失败: {exc}[/bold red]")
        if not quiet:
            console.print_exception(show_locals=False)
        raise typer.Exit(1)

    # ── Display results ───────────────────────────────────────
    if not quiet:
        console.print(f"\n[bold green]分析完成[/bold green] (耗时 {elapsed:.1f}s)\n")

    # Rating badge
    rating_colors = {
        "买入": "bold green",
        "增持": "green",
        "持有": "yellow",
        "减持": "red",
        "卖出": "bold red",
    }
    color = rating_colors.get(rating, "white")

    if not quiet:
        rating_panel = Panel(
            Text(f" {rating} ", style=color, justify="center"),
            title=f"[bold]{symbol} 最终评级[/bold]",
            border_style=color,
            width=40,
        )
        console.print(rating_panel)
        console.print()

    # Full summary
    summary_md = _format_state_summary(final_state, rating)

    if not quiet:
        console.print(Markdown(summary_md))

    # ── Save output ───────────────────────────────────────────
    output_path = output
    if output_path is None:
        results_dir = config.get(
            "results_dir",
            os.path.expanduser("~/.astock_trader/logs"),
        )
        Path(results_dir).mkdir(parents=True, exist_ok=True)
        output_path = os.path.join(
            results_dir,
            f"{symbol}_{trade_date}_result.json",
        )

    try:
        serialisable = _serialise_state(final_state)
        serialisable["_rating"] = rating
        serialisable["_elapsed_seconds"] = round(elapsed, 1)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(serialisable, f, ensure_ascii=False, indent=2)

        if not quiet:
            console.print(f"\n[dim]结果已保存到: {output_path}[/dim]")
    except Exception as exc:
        console.print(f"[yellow]保存结果失败: {exc}[/yellow]")

    # Also print rating to stdout in quiet mode
    if quiet:
        console.print(f"{symbol}\t{trade_date}\t{rating}")


@app.command()
def history(
    symbol: str | None = typer.Argument(None, help="股票代码（留空显示全部）"),
    limit: int = typer.Option(10, "--limit", "-n", help="显示条数"),
) -> None:
    """查看分析历史记录。"""
    from astock_trader.agents.utils.memory import TradingMemoryLog

    mem = TradingMemoryLog()

    try:
        entries = mem._load_all_entries()
    except Exception as exc:
        console.print(f"[red]读取记忆日志失败: {exc}[/red]")
        raise typer.Exit(1)

    if not entries:
        console.print("[dim]暂无分析历史。[/dim]")
        return

    # Filter by symbol
    if symbol:
        entries = [e for e in entries if e["ticker"] == symbol]

    # Sort by date descending, take top N
    entries.sort(key=lambda e: e["date"], reverse=True)
    entries = entries[:limit]

    table = Table(
        title=f"分析历史 {'— ' + symbol if symbol else ''}（最近 {limit} 条）",
        show_lines=True,
    )
    table.add_column("日期", style="cyan", width=12)
    table.add_column("标的", style="bold", width=10)
    table.add_column("评级", justify="center", width=8)
    table.add_column("状态", width=10)
    table.add_column("摘要", max_width=60)

    rating_styles = {
        "买入": "bold green",
        "增持": "green",
        "持有": "yellow",
        "减持": "red",
        "卖出": "bold red",
    }

    for e in entries:
        rating = e.get("rating", "?")
        status = "[red]pending[/red]" if e["pending"] else "[green]resolved[/green]"
        style = rating_styles.get(rating, "white")

        # Brief summary from decision
        decision = e.get("decision", {})
        summary = ""
        if isinstance(decision, dict):
            summary = decision.get("action", "")
            if decision.get("reasoning"):
                summary += f" — {decision['reasoning'][:40]}..."

        table.add_row(
            e["date"],
            e["ticker"],
            Text(rating, style=style),
            status,
            summary,
        )

    console.print(table)


@app.command()
def memory(
    action: str = typer.Argument("show", help="操作: show / clear / resolve"),
    symbol: str | None = typer.Option(None, "--symbol", "-s", help="股票代码"),
) -> None:
    """管理决策记忆日志。

    \b
    show    — 显示所有记忆条目
    clear   — 清除指定标的（或全部）记忆
    resolve — 列出所有 pending 条目
    """
    from astock_trader.agents.utils.memory import TradingMemoryLog

    mem = TradingMemoryLog()

    if action == "show":
        try:
            entries = mem._load_all_entries()
        except Exception as exc:
            console.print(f"[red]读取失败: {exc}[/red]")
            raise typer.Exit(1)

        if not entries:
            console.print("[dim]记忆日志为空。[/dim]")
            return

        for e in entries:
            status = "pending" if e["pending"] else "resolved"
            console.print(
                Panel(
                    json.dumps(
                        {
                            "date": e["date"],
                            "ticker": e["ticker"],
                            "rating": e["rating"],
                            "status": status,
                            "decision": e.get("decision", {}),
                            "reflection": e.get("reflection"),
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    title=f"[{e['date']}] {e['ticker']} — {e['rating']}",
                    border_style="blue" if not e["pending"] else "yellow",
                )
            )

    elif action == "clear":
        if symbol:
            console.print(f"[yellow]清除 {symbol} 的记忆需要手动编辑记忆日志文件。[/yellow]")
            console.print(f"[dim]文件路径: {mem._path}[/dim]")
        else:
            if typer.confirm("确认清除所有记忆条目？此操作不可撤销。"):
                try:
                    mem._rewrite_all([])
                    console.print("[green]记忆已清除。[/green]")
                except Exception as exc:
                    console.print(f"[red]清除失败: {exc}[/red]")
                    raise typer.Exit(1)

    elif action == "resolve":
        pending = mem.get_pending_entries()
        if not pending:
            console.print("[dim]没有 pending 状态的条目。[/dim]")
            return

        table = Table(title="Pending 记忆条目")
        table.add_column("日期", style="cyan")
        table.add_column("标的", style="bold")
        table.add_column("评级")
        table.add_column("决策摘要", max_width=60)

        for e in pending:
            decision = e.get("decision", {})
            summary = ""
            if isinstance(decision, dict):
                summary = decision.get("action", "")
            table.add_row(e["date"], e["ticker"], e.get("rating", "?"), summary)

        console.print(table)
        console.print("\n[dim]提示: 使用 Python API 的 batch_update_with_outcomes() 方法来标记已解决。[/dim]")

    else:
        console.print(f"[red]未知操作: {action}[/red]  可选: show / clear / resolve")
        raise typer.Exit(1)


@app.command("config")
def config_cmd(
    show: bool = typer.Option(False, "--show", help="显示当前完整配置"),
    set_key: str | None = typer.Option(None, "--set", help="设置配置项键名"),
    set_value: str | None = typer.Option(None, "--value", help="配置项值"),
    reset: bool = typer.Option(False, "--reset", help="重置为默认配置"),
) -> None:
    """查看和修改配置。

    \b
    示例:
        astock-trader config --show
        astock-trader config --set llm_provider --value deepseek
        astock-trader config --set deep_think_llm --value deepseek-reasoner
        astock-trader config --reset
    """

    if reset:
        if typer.confirm("确认重置为用户默认配置？"):
            _save_user_config({})
            console.print("[green]已重置为默认配置。[/green]")
        return

    if show:
        cfg = _build_config()
        console.print(
            Panel(
                json.dumps(cfg, ensure_ascii=False, indent=2, default=str),
                title="当前配置",
                border_style="blue",
            )
        )
        return

    if set_key and set_value is not None:
        user_cfg = _load_user_config()

        # Type coercion for known boolean / numeric keys
        bool_keys = {"checkpoint_enabled"}
        int_keys = {
            "max_debate_rounds",
            "max_risk_discuss_rounds",
            "max_recur_limit",
            "memory_log_max_entries",
        }

        if set_key in bool_keys:
            user_cfg[set_key] = set_value.lower() in ("true", "1", "yes")
        elif set_key in int_keys:
            try:
                user_cfg[set_key] = int(set_value)
            except ValueError:
                console.print(f"[red]值必须是整数: {set_value}[/red]")
                raise typer.Exit(1)
        else:
            user_cfg[set_key] = set_value

        _save_user_config(user_cfg)
        console.print(f"[green]已设置: {set_key} = {user_cfg[set_key]}[/green]")
        return

    # Default: show brief config summary
    cfg = _build_config()
    table = Table(title="配置概要", show_lines=True)
    table.add_column("键", style="bold cyan")
    table.add_column("值")

    important_keys = [
        "llm_provider",
        "deep_think_llm",
        "quick_think_llm",
        "backend_url",
        "output_language",
        "checkpoint_enabled",
        "max_debate_rounds",
        "max_risk_discuss_rounds",
        "max_recur_limit",
        "project_dir",
        "results_dir",
    ]
    for key in important_keys:
        table.add_row(key, str(cfg.get(key, "(未设置)")))

    console.print(table)


# ────────────────────────────────────────────────────────────────
#  Utilities
# ────────────────────────────────────────────────────────────────


def _serialise_state(state: dict[str, Any]) -> dict[str, Any]:
    """Convert AgentState to a JSON-serialisable dictionary."""
    result: dict[str, Any] = {}
    for key, value in state.items():
        if key == "messages":
            # Serialise messages to dicts
            msgs = []
            for m in value:
                msg_dict: dict[str, Any] = {"type": getattr(m, "type", "unknown")}
                if hasattr(m, "content"):
                    msg_dict["content"] = m.content
                if hasattr(m, "name") and m.name:
                    msg_dict["name"] = m.name
                if hasattr(m, "tool_calls") and m.tool_calls:
                    msg_dict["tool_calls"] = [
                        {"name": tc.get("name", ""), "args": tc.get("args", {})} for tc in m.tool_calls
                    ]
                msgs.append(msg_dict)
            result[key] = msgs
        elif isinstance(value, dict):
            result[key] = value
        elif isinstance(value, (list, tuple)):
            result[key] = list(value)
        else:
            try:
                json.dumps(value)
                result[key] = value
            except (TypeError, ValueError):
                result[key] = str(value)
    return result


# ────────────────────────────────────────────────────────────────
#  Entry point guard
# ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app()
