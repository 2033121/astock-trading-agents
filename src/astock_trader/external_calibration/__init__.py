"""外部校准接入 — 反思闭环的第三方参照通道（issue #1 试点支撑）。

背景
----
本框架的反思闭环已经能把「预测对不对」当一等信息处理：跟踪历史预测 →
akshare 拉实际收益 → LLM 生成反思教训 → 写回记忆。缺的一环是不由自己运营的
**外部记分板**：内部自评说进步了，第三方的机械结算是否同意？

`Headline Arena <https://headlinearena.com>`_ 提供这样的公开结算：结算规则出题时冻结、
平台按真实行情机械结算、记分卡与校准曲线公开可复查。

当前状态：**试点支撑，非自动接入**
---------------------------------
按 issue #1 的约定，正式接入 PR 之前先跑一轮人工试点。本包只提供试点所需的三件事：

1. :class:`~astock_trader.external_calibration.ledger.ExternalCalibrationLedger`
   —— 隔离存放第三方结算记录与提交前冻结的本地判断；
2. :class:`~astock_trader.external_calibration.arena_client.HeadlineArenaClient`
   —— 只读拉取公开的预测历史/校准曲线/记分卡，无凭据时优雅跳过；
3. :func:`~astock_trader.external_calibration.reconciliation.reconcile`
   —— 把两条线配对成比对报告。

本包**不包含自动提交预测的代码**，也不把任何外部结果写入内部交易记忆。

快速开始
--------
::

    export HEADLINE_ARENA_AGENT_ID=<你的 arena agent id>   # 公开读端点只需这一项
    python3 scripts/external_calibration.py sync           # 拉取预测历史与结算
    python3 scripts/external_calibration.py report         # 生成两条线比对报告

三条硬约束见 :mod:`astock_trader.external_calibration.schema`。
"""

from __future__ import annotations

from astock_trader.external_calibration.arena_client import HeadlineArenaClient, default_client
from astock_trader.external_calibration.ledger import (
    RECORD_SETTLEMENT,
    RECORD_STANCE,
    ExternalCalibrationLedger,
    default_ledger,
)
from astock_trader.external_calibration.reconciliation import build_buckets, reconcile, render_markdown
from astock_trader.external_calibration.schema import (
    ASSET_DOMAIN_BOUNDARY,
    DEFAULT_BASE_URL,
    DIRECTIONS,
    ENV_AGENT_ID,
    ENV_BASE_URL,
    ENV_CLIENT_SECRET,
    ENV_TOKEN,
    PROVIDER_HEADLINE_ARENA,
    SOURCE_TAG,
    ArenaSettlement,
    CalibrationBucketRow,
    LineStats,
    LocalStance,
    ReconciliationReport,
    now_iso,
)

__all__ = [
    "ASSET_DOMAIN_BOUNDARY",
    "DEFAULT_BASE_URL",
    "DIRECTIONS",
    "ENV_AGENT_ID",
    "ENV_BASE_URL",
    "ENV_CLIENT_SECRET",
    "ENV_TOKEN",
    "PROVIDER_HEADLINE_ARENA",
    "RECORD_SETTLEMENT",
    "RECORD_STANCE",
    "SOURCE_TAG",
    "ArenaSettlement",
    "CalibrationBucketRow",
    "ExternalCalibrationLedger",
    "HeadlineArenaClient",
    "LineStats",
    "LocalStance",
    "ReconciliationReport",
    "build_buckets",
    "default_client",
    "default_ledger",
    "now_iso",
    "reconcile",
    "render_markdown",
]
