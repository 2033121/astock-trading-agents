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
_DEFAULT_DECAY_WARN_DAYS = 90
_DEFAULT_DECAY_IGNORE_DAYS = 180

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
        decay_warn_days: int = 0,
        decay_ignore_days: int = 0,
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
        # Decay tiers: default warn=expiry_days, ignore=180
        self._decay_warn_days = decay_warn_days or _DEFAULT_DECAY_WARN_DAYS
        self._decay_ignore_days = decay_ignore_days or _DEFAULT_DECAY_IGNORE_DAYS
        self._feedback: dict[str, Any] | None = None
        self._gate_passed: bool = False
        self._age_days: int = 0
        self._decay_state: str = "fresh"
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
            "decay_state": self._decay_state,
            "age_days": self._age_days,
        }

    @property
    def decay_state(self) -> str:
        """Current decay tier: ``"fresh"``, ``"warning"``, or ``"expired"``.

        - ``fresh``: age < decay_warn_days, weight=1.0
        - ``warning``: decay_warn_days ≤ age < decay_ignore_days, weight=0.5
        - ``expired``: feedback not loaded or age ≥ decay_ignore_days
        """
        if self._feedback is None:
            return "expired"
        return self._decay_state

    @property
    def age_days(self) -> int:
        """Days since the feedback file was generated."""
        return self._age_days

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

        # Compute age for decay tiers
        generated_at = data.get("generated_at", "")
        if generated_at:
            try:
                gen_time = datetime.fromisoformat(generated_at)
                self._age_days = (datetime.now() - gen_time).days
            except (ValueError, TypeError):
                logger.debug("Could not parse generated_at: %s", generated_at)

        # Hard ignore: feedback past decay_ignore_days is fully rejected
        if self._age_days >= self._decay_ignore_days:
            logger.info(
                "Backtest feedback auto-ignored: %d days old (ignore threshold %d).",
                self._age_days,
                self._decay_ignore_days,
            )
            return

        # Determine decay state
        if self._age_days >= self._decay_warn_days:
            self._decay_state = "warning"
            logger.info(
                "Backtest feedback in WARNING zone: %d days old "
                "(warn=%d, ignore=%d). Injection weight reduced to 0.5x.",
                self._age_days,
                self._decay_warn_days,
                self._decay_ignore_days,
            )
        else:
            self._decay_state = "fresh"

        self._feedback = data

        # Quality gate check
        gate = data.get("quality_gate", {})
        total_verified = gate.get("total_verified", 0)
        gate_passed_flag = gate.get("passed", False)

        if total_verified >= self._min_verified and gate_passed_flag:
            self._gate_passed = True
            logger.info(
                "Backtest feedback loaded: %d verified snapshots, gate PASSED (decay=%s).",
                total_verified,
                self._decay_state,
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

        Decay behavior:
        - ``fresh``: full feedback, full character budget
        - ``warning``: halved character budget + "（回测反馈衰减中）" suffix
        - ``expired``: returns empty string

        Returns empty string when:
        - Feedback file not loaded
        - Quality gate not passed
        - Decay state is expired
        - Key not present in agent_feedback
        """
        if not self._gate_passed or self._feedback is None:
            return ""

        # Decay: expired → no injection
        if self._decay_state == "expired":
            return ""

        agent_fb = self._feedback.get("agent_feedback", {})
        text = agent_fb.get(key, "")

        if not text:
            return ""

        # Decay: warning → halved budget + notice
        if self._decay_state == "warning":
            effective_chars = max(int(max_chars * 0.5), 20)
            notice = "（回测反馈衰减中）"
            remaining = effective_chars - len(notice)
            if remaining < 10:
                remaining = effective_chars
                notice = ""
            # Truncate to effective budget
            if len(text) > remaining:
                truncated = text[:remaining]
                for sep in ("。", "，", ".", ","):
                    last_sep = truncated.rfind(sep)
                    if last_sep > remaining * 0.5:
                        truncated = truncated[: last_sep + 1]
                        break
                return truncated + notice
            return text + notice

        # Fresh: normal truncation
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
