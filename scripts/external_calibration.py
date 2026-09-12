#!/usr/bin/env python3
"""外部校准试点工具（Headline Arena，issue #1）。

给反思闭环补一份**不由自己运营**的机械结算参照：同步平台结算记录 →
与提交前冻结的本地宏观判断配对 → 输出两条线比对报告。

用法:
    python3 external_calibration.py sync [--since ISO8601]
    python3 external_calibration.py mirror --challenge-id ID --direction bullish \
        --confidence 0.7 [--asset GC] [--rationale "..."] [--overwrite]
    python3 external_calibration.py status
    python3 external_calibration.py report [--json] [--out PATH]

环境变量（凭据纪律：只走环境变量，绝不入 repo）:
    HEADLINE_ARENA_AGENT_ID        arena agent 标识（公开读端点只需这一项）
    HEADLINE_ARENA_CLIENT_SECRET   仅换取 access token 时需要
    HEADLINE_ARENA_TOKEN           预置 bearer token（可选）
    HEADLINE_ARENA_BASE_URL        覆盖 API 根地址
    ASTOCK_EXTERNAL_CALIBRATION_DIR  覆盖台账目录

总开关默认关闭（default_config 的 enable_external_calibration）；本工具是显式调用的
试点工具，加 --force 可在开关关闭时照常运行。

注意：本工具只读平台数据 + 写本地台账，**不向平台提交任何预测**。
提交预测在试点期由人工完成（官方插件或网页端）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from astock_trader.default_config import DEFAULT_CONFIG  # noqa: E402
from astock_trader.external_calibration import (  # noqa: E402
    ASSET_DOMAIN_BOUNDARY,
    DIRECTIONS,
    ENV_AGENT_ID,
    ExternalCalibrationLedger,
    HeadlineArenaClient,
    LocalStance,
    reconcile,
    render_markdown,
)

_ENV_LEDGER_DIR = "ASTOCK_EXTERNAL_CALIBRATION_DIR"


def _build_ledger(args: argparse.Namespace) -> ExternalCalibrationLedger:
    """按 命令行参数 > 环境变量 > 配置项 > 项目默认 的优先级定位台账目录。"""
    ledger_dir = args.ledger_dir or os.environ.get(_ENV_LEDGER_DIR, "")
    if ledger_dir:
        return ExternalCalibrationLedger(ledger_dir=ledger_dir)
    configured = DEFAULT_CONFIG.get("external_calibration_dir") or ""
    if configured:
        return ExternalCalibrationLedger(ledger_dir=configured)
    return ExternalCalibrationLedger(project_dir=DEFAULT_CONFIG.get("project_dir") or None)


def _build_client(args: argparse.Namespace) -> HeadlineArenaClient:
    return HeadlineArenaClient(
        agent_id=args.agent_id or None,
        base_url=args.base_url or DEFAULT_CONFIG.get("headline_arena_base_url") or None,
        timeout=int(DEFAULT_CONFIG.get("headline_arena_timeout", 15)),
    )


def _check_enabled(args: argparse.Namespace) -> bool:
    """总开关关闭时给出提示；--force 可继续。"""
    if DEFAULT_CONFIG.get("enable_external_calibration") or getattr(args, "force", False):
        return True
    print(
        "外部校准接入默认关闭（enable_external_calibration = false）。\n"
        "试点期请用 --force 运行，或在配置中显式开启后再接自动通道。",
        file=sys.stderr,
    )
    return False


# ─────────────────── 子命令 ───────────────────


def cmd_sync(args: argparse.Namespace) -> int:
    """从平台拉取预测历史（含机械结算）写入本地台账。"""
    ledger = _build_ledger(args)
    client = _build_client(args)

    if not client.is_configured:
        print(
            f"未配置 {ENV_AGENT_ID}，无法定位 agent 的预测历史——已优雅跳过（退出码 0）。\n"
            "注册后把 agent id 写入该环境变量即可，无需改动代码。",
            file=sys.stderr,
        )
        return 0

    new_count = ledger.sync(client, since=args.since)
    stats = ledger.stats()
    print(f"同步完成：新增 {new_count} 条。")
    print(f"台账：{stats['path']}")
    print(
        f"结算记录 {stats['settlements']} 条（已结算 {stats['resolved']} / 待结算 {stats['pending']}），"
        f"本地镜像判断 {stats['stances']} 条。"
    )
    return 0


def cmd_mirror(args: argparse.Namespace) -> int:
    """在提交前冻结一条本地宏观判断（两条线配对的基准）。"""
    if args.direction not in DIRECTIONS:
        print(f"direction 必须是 {DIRECTIONS} 之一。", file=sys.stderr)
        return 2
    if not 0.0 <= args.confidence <= 1.0:
        print("confidence 必须在 0–1 之间。", file=sys.stderr)
        return 2

    ledger = _build_ledger(args)
    stance = LocalStance(
        challenge_id=args.challenge_id,
        direction=args.direction,
        confidence=args.confidence,
        asset=args.asset or "",
        rationale=args.rationale or "",
        origin=args.origin,
    )
    written = ledger.record_stance(stance, overwrite=args.overwrite)
    if written:
        print(f"已冻结本地判断：{args.challenge_id} → {args.direction} @ {args.confidence:.2f}")
    else:
        print(f"未写入（{args.challenge_id} 已存在冻结判断，需 --overwrite 显式修正）。", file=sys.stderr)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """打印台账概览与环境配置状态。"""
    ledger = _build_ledger(args)
    client = _build_client(args)
    stats = ledger.stats()
    print(f"台账文件：{stats['path']}")
    print(f"来源标记：{stats['source']}")
    print(f"结算记录：{stats['settlements']} 条（已结算 {stats['resolved']} / 待结算 {stats['pending']}）")
    print(f"本地镜像判断：{stats['stances']} 条")
    print()
    print(f"{ENV_AGENT_ID}：{'已配置' if client.is_configured else '未配置（读侧将优雅跳过）'}")
    print(f"token 凭据：{'已具备' if client.has_credentials else '未具备（公开端点不需要）'}")
    print(f"API 根地址：{client.base_url}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """生成两条线比对报告。"""
    ledger = _build_ledger(args)
    client = _build_client(args)

    calibration = None
    scorecard = None
    if client.is_configured and not args.no_fetch:
        calibration = client.fetch_calibration()
        scorecard = client.fetch_scorecard()

    report = reconcile(
        ledger,
        calibration=calibration,
        scorecard=scorecard,
        agent_id=client.agent_id,
    )

    if args.json:
        text = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    else:
        text = render_markdown(report)

    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"报告已写入：{args.out}")
    else:
        print(text)
    return 0


# ─────────────────── 入口 ───────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="外部校准试点工具（Headline Arena，issue #1）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=ASSET_DOMAIN_BOUNDARY,
    )
    parser.add_argument("--ledger-dir", default="", help=f"台账目录（默认取 {_ENV_LEDGER_DIR} 或项目默认）")
    parser.add_argument("--agent-id", default="", help=f"arena agent id（默认取 {ENV_AGENT_ID}）")
    parser.add_argument("--base-url", default="", help="API 根地址，覆盖默认值")
    parser.add_argument("--force", action="store_true", help="总开关关闭时仍运行（试点期用）")

    sub = parser.add_subparsers(dest="command", required=True)

    p_sync = sub.add_parser("sync", help="从平台拉取预测历史与结算结果")
    p_sync.add_argument("--since", default=None, help="ISO 8601 时间戳，仅同步该时刻之后的记录")
    p_sync.set_defaults(func=cmd_sync)

    p_mirror = sub.add_parser("mirror", help="在提交前冻结一条本地宏观判断")
    p_mirror.add_argument("--challenge-id", required=True, help="对应的 arena challenge id")
    p_mirror.add_argument("--direction", required=True, choices=list(DIRECTIONS), help="方向")
    p_mirror.add_argument("--confidence", type=float, required=True, help="主观概率 0–1")
    p_mirror.add_argument("--asset", default="", help="标的（如 GC/CL/ES），仅作可读性")
    p_mirror.add_argument("--rationale", default="", help="判断依据简述")
    p_mirror.add_argument(
        "--origin",
        default="manual",
        choices=["manual", "macro_assessment", "analyst_debate"],
        help="判断来源",
    )
    p_mirror.add_argument("--overwrite", action="store_true", help="覆盖已冻结的判断（需说明理由）")
    p_mirror.set_defaults(func=cmd_mirror)

    p_status = sub.add_parser("status", help="台账与环境配置概览")
    p_status.set_defaults(func=cmd_status)

    p_report = sub.add_parser("report", help="生成两条线比对报告")
    p_report.add_argument("--json", action="store_true", help="输出 JSON 而非 Markdown")
    p_report.add_argument("--out", default="", help="写入指定文件而非打印")
    p_report.add_argument("--no-fetch", action="store_true", help="不访问平台，仅用本地台账")
    p_report.set_defaults(func=cmd_report)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not _check_enabled(args):
        return 0
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
