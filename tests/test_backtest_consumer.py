"""Tests for BacktestFeedbackConsumer module."""

import json
import os
import tempfile
from datetime import datetime, timedelta

import pytest

from astock_trader.agents.utils.backtest_consumer import BacktestFeedbackConsumer


def _make_feedback(
    *,
    total_verified: int = 15,
    gate_passed: bool = True,
    schema_version: int = 1,
    days_ago: int = 5,
    agent_feedback: dict | None = None,
) -> dict:
    """Helper to create a valid feedback dict."""
    generated_at = (datetime.now() - timedelta(days=days_ago)).isoformat()
    fb = {
        "schema_version": schema_version,
        "generated_at": generated_at,
        "generated_by": "test",
        "quality_gate": {
            "total_verified": total_verified,
            "passed": gate_passed,
        },
        "agent_feedback": agent_feedback or {
            "analysts": "分析师反馈文本",
            "bull_researcher": "多头反馈文本",
            "bear_researcher": "空头反馈文本",
            "research_manager": "研究经理反馈文本",
            "risk_analysts": "风控反馈文本",
            "portfolio_manager": "基金经理综合反馈文本，包含评级校准和历史表现数据",
        },
        "expiry": (datetime.now() + timedelta(days=85)).isoformat(),
    }
    return fb


def _write_feedback(path: str, data: dict) -> None:
    """Write feedback dict to file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


# ────────────────────────────────────────────────────────────────
#  File loading
# ────────────────────────────────────────────────────────────────


class TestFileLoading:
    def test_missing_file_returns_inactive(self, tmp_path):
        """Consumer with no feedback file should be inactive."""
        consumer = BacktestFeedbackConsumer(
            feedback_path=str(tmp_path / "nonexistent.json"),
        )
        assert not consumer.is_active
        assert consumer.get_analyst_feedback() == ""

    def test_valid_file_loads(self, tmp_path):
        """Consumer should load and pass gate for valid data."""
        path = str(tmp_path / "feedback.json")
        _write_feedback(path, _make_feedback())
        consumer = BacktestFeedbackConsumer(feedback_path=path)
        assert consumer.is_active

    def test_invalid_json_returns_inactive(self, tmp_path):
        """Consumer should handle corrupt JSON gracefully."""
        path = str(tmp_path / "feedback.json")
        with open(path, "w") as f:
            f.write("{invalid json")
        consumer = BacktestFeedbackConsumer(feedback_path=path)
        assert not consumer.is_active


# ────────────────────────────────────────────────────────────────
#  Quality gate
# ────────────────────────────────────────────────────────────────


class TestQualityGate:
    def test_insufficient_verified_fails_gate(self, tmp_path):
        """Gate should fail when total_verified < min_verified."""
        path = str(tmp_path / "feedback.json")
        _write_feedback(path, _make_feedback(total_verified=5))
        consumer = BacktestFeedbackConsumer(feedback_path=path, min_verified=10)
        assert not consumer.is_active
        assert consumer.get_analyst_feedback() == ""

    def test_gate_passed_field_false(self, tmp_path):
        """Gate should fail when passed=false even with enough snapshots."""
        path = str(tmp_path / "feedback.json")
        _write_feedback(path, _make_feedback(total_verified=20, gate_passed=False))
        consumer = BacktestFeedbackConsumer(feedback_path=path)
        assert not consumer.is_active

    def test_exact_threshold_passes(self, tmp_path):
        """Gate should pass when total_verified == min_verified."""
        path = str(tmp_path / "feedback.json")
        _write_feedback(path, _make_feedback(total_verified=10))
        consumer = BacktestFeedbackConsumer(feedback_path=path, min_verified=10)
        assert consumer.is_active


# ────────────────────────────────────────────────────────────────
#  Schema validation
# ────────────────────────────────────────────────────────────────


class TestSchemaValidation:
    def test_wrong_schema_version_rejected(self, tmp_path):
        """Consumer should reject files with wrong schema version."""
        path = str(tmp_path / "feedback.json")
        _write_feedback(path, _make_feedback(schema_version=99))
        consumer = BacktestFeedbackConsumer(feedback_path=path)
        assert not consumer.is_active

    def test_missing_schema_version_rejected(self, tmp_path):
        """Consumer should reject files without schema_version."""
        path = str(tmp_path / "feedback.json")
        data = _make_feedback()
        del data["schema_version"]
        _write_feedback(path, data)
        consumer = BacktestFeedbackConsumer(feedback_path=path)
        assert not consumer.is_active


# ────────────────────────────────────────────────────────────────
#  Expiry
# ────────────────────────────────────────────────────────────────


class TestExpiry:
    def test_expired_feedback_rejected(self, tmp_path):
        """Consumer should reject feedback past decay_ignore_days."""
        path = str(tmp_path / "feedback.json")
        _write_feedback(path, _make_feedback(days_ago=200))
        consumer = BacktestFeedbackConsumer(
            feedback_path=path, decay_ignore_days=180,
        )
        assert not consumer.is_active

    def test_fresh_feedback_accepted(self, tmp_path):
        """Consumer should accept feedback within fresh window."""
        path = str(tmp_path / "feedback.json")
        _write_feedback(path, _make_feedback(days_ago=10))
        consumer = BacktestFeedbackConsumer(feedback_path=path, expiry_days=90)
        assert consumer.is_active


# ────────────────────────────────────────────────────────────────
#  Per-agent feedback getters
# ────────────────────────────────────────────────────────────────


class TestFeedbackGetters:
    def _make_consumer(self, tmp_path, **kwargs) -> BacktestFeedbackConsumer:
        path = str(tmp_path / "feedback.json")
        _write_feedback(path, _make_feedback(**kwargs))
        return BacktestFeedbackConsumer(feedback_path=path)

    def test_analyst_feedback(self, tmp_path):
        consumer = self._make_consumer(tmp_path)
        result = consumer.get_analyst_feedback()
        assert "分析师" in result

    def test_bull_debater_feedback(self, tmp_path):
        consumer = self._make_consumer(tmp_path)
        result = consumer.get_debater_feedback("bull")
        assert "多头" in result

    def test_bear_debater_feedback(self, tmp_path):
        consumer = self._make_consumer(tmp_path)
        result = consumer.get_debater_feedback("bear")
        assert "空头" in result

    def test_manager_feedback(self, tmp_path):
        consumer = self._make_consumer(tmp_path)
        result = consumer.get_manager_feedback()
        assert "研究经理" in result

    def test_risk_feedback(self, tmp_path):
        consumer = self._make_consumer(tmp_path)
        result = consumer.get_risk_feedback("aggressive")
        assert "风控" in result

    def test_pm_feedback(self, tmp_path):
        consumer = self._make_consumer(tmp_path)
        result = consumer.get_pm_feedback()
        assert "基金经理" in result

    def test_missing_key_returns_empty(self, tmp_path):
        """Getter for non-existent key should return empty string."""
        path = str(tmp_path / "feedback.json")
        _write_feedback(path, _make_feedback(agent_feedback={"other_key": "value"}))
        consumer = BacktestFeedbackConsumer(feedback_path=path)
        assert consumer.is_active
        assert consumer.get_analyst_feedback() == ""


# ────────────────────────────────────────────────────────────────
#  Truncation
# ────────────────────────────────────────────────────────────────


class TestTruncation:
    def test_long_text_truncated(self, tmp_path):
        """Feedback exceeding max_chars should be truncated at sentence boundary."""
        long_text = "第一句话。" + "第二句很长的内容" * 50 + "。第三句话。"
        path = str(tmp_path / "feedback.json")
        _write_feedback(path, _make_feedback(
            agent_feedback={"analysts": long_text},
        ))
        consumer = BacktestFeedbackConsumer(feedback_path=path)
        result = consumer.get_analyst_feedback()
        assert len(result) <= 120 + 10  # allow some slack for sentence boundary

    def test_short_text_unchanged(self, tmp_path):
        """Feedback within max_chars should not be modified."""
        short_text = "简短反馈"
        path = str(tmp_path / "feedback.json")
        _write_feedback(path, _make_feedback(
            agent_feedback={"analysts": short_text},
        ))
        consumer = BacktestFeedbackConsumer(feedback_path=path)
        assert consumer.get_analyst_feedback() == short_text


# ────────────────────────────────────────────────────────────────
#  Quality info
# ────────────────────────────────────────────────────────────────


class TestQualityInfo:
    def test_quality_info_when_loaded(self, tmp_path):
        path = str(tmp_path / "feedback.json")
        _write_feedback(path, _make_feedback(total_verified=20))
        consumer = BacktestFeedbackConsumer(feedback_path=path)
        info = consumer.quality_info
        assert info["loaded"] is True
        assert info["total_verified"] == 20
        assert info["gate_passed"] is True

    def test_quality_info_when_missing(self, tmp_path):
        consumer = BacktestFeedbackConsumer(
            feedback_path=str(tmp_path / "nope.json"),
        )
        info = consumer.quality_info
        assert info["loaded"] is False
        assert info["gate_passed"] is False


# ────────────────────────────────────────────────────────────────
#  Decay tiers (Phase 3)
# ────────────────────────────────────────────────────────────────


class TestDecay:
    """Three-tier decay: fresh → warning (0.5x) → expired (0x)."""

    def _make_consumer(self, tmp_path, days_ago: int, **kwargs) -> BacktestFeedbackConsumer:
        path = str(tmp_path / "feedback.json")
        _write_feedback(path, _make_feedback(days_ago=days_ago))
        return BacktestFeedbackConsumer(feedback_path=path, **kwargs)

    # ── Fresh tier ──────────────────────────────────────────────

    def test_fresh_state_within_warn_days(self, tmp_path):
        """Feedback at 10 days should be fresh (warn=90)."""
        consumer = self._make_consumer(tmp_path, days_ago=10)
        assert consumer.decay_state == "fresh"
        assert consumer.is_active

    def test_fresh_returns_full_feedback(self, tmp_path):
        """Fresh feedback should return full text without suffix."""
        consumer = self._make_consumer(tmp_path, days_ago=5)
        result = consumer.get_analyst_feedback()
        assert "衰减" not in result
        assert result == "分析师反馈文本"

    def test_age_days_property(self, tmp_path):
        consumer = self._make_consumer(tmp_path, days_ago=12)
        assert consumer.age_days == 12

    # ── Warning tier ────────────────────────────────────────────

    def test_warning_state_between_warn_and_ignore(self, tmp_path):
        """Feedback at 100 days should be in warning zone (warn=90, ignore=180)."""
        consumer = self._make_consumer(
            tmp_path, days_ago=100, decay_warn_days=90, decay_ignore_days=180,
        )
        assert consumer.decay_state == "warning"
        assert consumer.is_active  # still loads, just reduced weight

    def test_warning_appends_notice(self, tmp_path):
        """Warning feedback should append decay notice."""
        long_text = "这是一段用于测试衰减提示的较长反馈内容，包含多个句子。用于验证字符截断。"
        path = str(tmp_path / "feedback.json")
        _write_feedback(path, _make_feedback(
            days_ago=100,
            agent_feedback={"analysts": long_text},
        ))
        consumer = BacktestFeedbackConsumer(
            feedback_path=path, decay_warn_days=90, decay_ignore_days=180,
        )
        result = consumer.get_analyst_feedback()
        assert "衰减中" in result

    def test_warning_halved_char_budget(self, tmp_path):
        """Warning state should use halved character budget."""
        # analysts max = 120 chars → warning budget = 60 chars
        text = "A" * 80
        path = str(tmp_path / "feedback.json")
        _write_feedback(path, _make_feedback(
            days_ago=100,
            agent_feedback={"analysts": text},
        ))
        consumer = BacktestFeedbackConsumer(
            feedback_path=path, decay_warn_days=90, decay_ignore_days=180,
        )
        result = consumer.get_analyst_feedback()
        # 60 chars budget + "（回测反馈衰减中）" (9 chars) = ~69 max
        assert len(result) <= 70

    # ── Expired tier ────────────────────────────────────────────

    def test_expired_state_past_ignore_days(self, tmp_path):
        """Feedback at 200 days should be expired (ignore=180)."""
        consumer = self._make_consumer(
            tmp_path, days_ago=200, decay_warn_days=90, decay_ignore_days=180,
        )
        assert consumer.decay_state == "expired"
        assert not consumer.is_active

    def test_expired_returns_empty(self, tmp_path):
        """Expired feedback should return empty string."""
        consumer = self._make_consumer(
            tmp_path, days_ago=200, decay_warn_days=90, decay_ignore_days=180,
        )
        assert consumer.get_analyst_feedback() == ""
        assert consumer.get_pm_feedback() == ""

    def test_exact_ignore_threshold_rejected(self, tmp_path):
        """Feedback exactly at ignore threshold should be rejected."""
        consumer = self._make_consumer(
            tmp_path, days_ago=180, decay_warn_days=90, decay_ignore_days=180,
        )
        assert consumer.decay_state == "expired"

    def test_exact_warn_threshold_in_warning(self, tmp_path):
        """Feedback exactly at warn threshold should be in warning (not rejected)."""
        consumer = self._make_consumer(
            tmp_path, days_ago=90, decay_warn_days=90, decay_ignore_days=180,
        )
        assert consumer.decay_state == "warning"
        assert consumer.is_active

    # ── Boundary: no decay params (defaults) ────────────────────

    def test_defaults_use_90_and_180(self, tmp_path):
        """Without explicit params, defaults should be warn=90, ignore=180."""
        consumer = self._make_consumer(tmp_path, days_ago=100)
        assert consumer.decay_state == "warning"

    def test_defaults_fresh_at_50_days(self, tmp_path):
        consumer = self._make_consumer(tmp_path, days_ago=50)
        assert consumer.decay_state == "fresh"

    # ── quality_info includes decay ─────────────────────────────

    def test_quality_info_includes_decay_fields(self, tmp_path):
        path = str(tmp_path / "feedback.json")
        _write_feedback(path, _make_feedback(days_ago=30))
        consumer = BacktestFeedbackConsumer(feedback_path=path)
        info = consumer.quality_info
        assert "decay_state" in info
        assert "age_days" in info
        assert info["decay_state"] == "fresh"
        assert info["age_days"] == 30
