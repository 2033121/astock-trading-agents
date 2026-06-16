"""回测反馈消费模块 — 读取 Expert Suite 产出的 backtest_feedback.json 并格式化注入。

本模块是反馈回路的**被动接收端**。它只负责：
1. 读取并验证 JSON 文件
2. 执行质量门禁检查
3. 为各管线节点格式化反馈文本

反馈内容由独立的 Expert Suite Plugin 生成，两者通过 JSON 契约解耦。
当质量门禁未通过或文件不存在时，所有方法返回空字符串（安全无操作）。

Quality gates
-------------
- ``min_total_verified``: 至少 N 个已验证快照（默认 10）
- ``expiry_days``: 反馈生成时间距今不超过 N 天（默认 90）
- ``schema_version``: JSON schema 版本必须为 1
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
#  Defaults
# ────────────────────────────────────────────────────────────────

_DEFAULT_FEEDBACK_FILE = "backtest_feedback.json"
_SCHEMA_VERSION = 1
_DEFAULT_MIN_VERIFIED = 10
_DEFAULT_EXPIRY_DAYS = 90

# Per-injection character limits (Chinese text, ~1.5 tokens per char)
_MAX_ANALYST_CHARS = 120
_MAX_DEBATER_CHARS = 100
_MAX_MANAGER_CHARS = 100
_MAX_RISK_CHARS = 80
_MAX_PM_CHARS = 150


class BacktestFeedbackConsumer:
    """Read and format backtest feedback for pipeline injection.

    Parameters
    ----------
    feedback_path : str
        Path to ``backtest_feedback.json``.  When empty, defaults to
        ``~/.astock_trader/backtest_feedback.json``.
    min_verified : int
        Minimum number of verified snapshots required to pass quality gate.
    expiry_days : int
        Maximum age (days) of the feedback file before it expires.
    """

    def __init__(
        self,
        feedback_path: str = "",
        min_verified: int = _DEFAULT_MIN_VERIFIED,
        expiry_days: int = _DEFAULT_EXPIRY_DAYS,
    ) -> None:
        if feedback_path:
            self._path = Path(feedback_path)
        else:
            self._path = (
                Path(os.path.expanduser("~/.astock_trader"))
                / _DEFAULT_FEEDBACK_FILE
            )
        self._min_verified = min_verified
        self._expiry_days = expiry_days
        self._feedback: dict[str, Any] | None = None
        self._gate_passed: bool = False
        self._load()

    # ────────────────────────────────────────────────────────────
    #  Public API — per-agent feedback getters
    # ────────────────────────────────────────────────────────────

    def get_analyst_feedback(self) -> str:
        """Feedback for the 4 analyst nodes (Market/Social/News/Fundamentals).

        Focuses on dimension-level reliability and bias patterns.
        """
        return self._safe_get("analysts", _MAX_ANALYST_CHARS)

    def get_debater_feedback(self, role: str) -> str:
        """Feedback for Bull or Bear Researcher.

        Parameters
        ----------
        role : str
            ``"bull"`` or ``"bear"``.
        """
        key = "bull_researcher" if role == "bull" else "bear_researcher"
        return self._safe_get(key, _MAX_DEBATER_CHARS)

    def get_manager_feedback(self) -> str:
        """Feedback for the Research Manager (debate judge)."""
        return self._safe_get("research_manager", _MAX_MANAGER_CHARS)

    def get_risk_feedback(self, role: str) -> str:
        """Feedback for risk analysts (Aggressive/Conservative/Neutral).

        Parameters
        ----------
        role : str
            ``"aggressive"``, ``"conservative"``, or ``"neutral"``.
        """
        key = "risk_analysts"  # shared feedback for all risk roles
        return self._safe_get(key, _MAX_RISK_CHARS)

    def get_pm_feedback(self) -> str:
        """Feedback for the Portfolio Manager (final decision maker).

        Returns the most comprehensive feedback since PM makes the
        final rating decision.
        """
        return self._safe_get("portfolio_manager", _MAX_PM_CHARS)

    @property
    def is_active(self) -> bool:
        """Whether the quality gate passed and feedback is available."""
        return self._gate_passed and self._feedback is not None

    @property
    def quality_info(self) -> dict[str, Any]:
        """Return quality gate details for logging/debugging."""
        if self._feedback is None:
            return {"loaded": False, "gate_passed": False}
        gate = self._feedback.get("quality_gate", {})
        return {
            "loaded": True,
            "gate_passed": self._gate_passed,
            "total_verified": gate.get("total_verified", 0),
            "generated_at": self._feedback.get("generated_at", ""),
            "schema_version": self._feedback.get("schema_version", 0),
        }

    # ────────────────────────────────────────────────────────────
    #  Internal
    # ────────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load and validate the feedback JSON file."""
        if not self._path.exists():
            logger.debug(
                "Backtest feedback file not found: %s (this is normal for new installations)",
                self._path,
            )
            return

        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load backtest feedback: %s", exc)
            return

        # Schema version check
        if data.get("schema_version") != _SCHEMA_VERSION:
            logger.warning(
                "Backtest feedback schema version mismatch: expected %d, got %s. Ignoring.",
                _SCHEMA_VERSION,
                data.get("schema_version"),
            )
            return

        # Expiry check
        generated_at = data.get("generated_at", "")
        if generated_at:
            try:
                gen_time = datetime.fromisoformat(generated_at)
                age_days = (datetime.now() - gen_time).days
                if age_days > self._expiry_days:
                    logger.info(
                        "Backtest feedback expired: %d days old (max %d). Ignoring.",
                        age_days,
                        self._expiry_days,
                    )
                    return
            except (ValueError, TypeError):
                logger.debug("Could not parse generated_at: %s", generated_at)

        self._feedback = data

        # Quality gate check
        gate = data.get("quality_gate", {})
        total_verified = gate.get("total_verified", 0)
        gate_passed_flag = gate.get("passed", False)

        if total_verified >= self._min_verified and gate_passed_flag:
            self._gate_passed = True
            logger.info(
                "Backtest feedback loaded: %d verified snapshots, gate PASSED.",
                total_verified,
            )
        else:
            self._gate_passed = False
            logger.info(
                "Backtest feedback loaded but gate NOT passed: "
                "%d/%d verified snapshots required.",
                total_verified,
                self._min_verified,
            )

    def _safe_get(self, key: str, max_chars: int) -> str:
        """Safely retrieve and truncate a feedback field.

        Returns empty string when:
        - Feedback file not loaded
        - Quality gate not passed
        - Key not present in agent_feedback
        """
        if not self._gate_passed or self._feedback is None:
            return ""

        agent_fb = self._feedback.get("agent_feedback", {})
        text = agent_fb.get(key, "")

        if not text:
            return ""

        # Truncate to character limit (preserve sentence boundaries)
        if len(text) > max_chars:
            truncated = text[:max_chars]
            # Try to cut at last sentence boundary
            for sep in ("。", "，", ".", ","):
                last_sep = truncated.rfind(sep)
                if last_sep > max_chars * 0.5:
                    truncated = truncated[: last_sep + 1]
                    break
            return truncated

        return text
