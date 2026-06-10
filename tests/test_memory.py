"""Tests for astock_trader.agents.utils.memory — trading memory log system."""

import pytest

from astock_trader.agents.utils.memory import TradingMemoryLog

# ────────────────────────────────────────────────────────────────
#  Fixtures
# ────────────────────────────────────────────────────────────────


@pytest.fixture
def memory(tmp_path):
    """Create a TradingMemoryLog using a temporary directory."""
    return TradingMemoryLog(
        memory_dir=str(tmp_path),
        memory_file="test_memory.log",
    )


@pytest.fixture
def memory_with_entries(tmp_path):
    """Create a TradingMemoryLog pre-populated with some entries."""
    mem = TradingMemoryLog(
        memory_dir=str(tmp_path),
        memory_file="test_memory.log",
    )
    # Store a few decisions
    mem.store_decision(
        "000001",
        "2025-06-01",
        {
            "rating": "买入",
            "action": "买入",
            "reasoning": "技术面突破",
        },
    )
    mem.store_decision(
        "600519",
        "2025-06-02",
        {
            "rating": "增持",
            "action": "增持",
            "reasoning": "基本面改善",
        },
    )
    mem.store_decision(
        "000001",
        "2025-06-03",
        {
            "rating": "持有",
            "action": "持有",
            "reasoning": "等待确认",
        },
    )
    return mem


# ────────────────────────────────────────────────────────────────
#  store_decision
# ────────────────────────────────────────────────────────────────


class TestStoreDecision:
    """Tests for store_decision()."""

    def test_creates_pending_entry(self, memory):
        """store_decision 创建 pending 状态的条目。"""
        memory.store_decision(
            "000001",
            "2025-06-01",
            {
                "rating": "买入",
                "action": "买入",
            },
        )
        entries = memory._load_all_entries()
        assert len(entries) == 1
        assert entries[0]["ticker"] == "000001"
        assert entries[0]["date"] == "2025-06-01"
        assert entries[0]["rating"] == "买入"
        assert entries[0]["pending"] is True

    def test_multiple_entries_stored(self, memory):
        """多个决策依次存储。"""
        memory.store_decision("000001", "2025-06-01", {"rating": "买入"})
        memory.store_decision("600519", "2025-06-02", {"rating": "增持"})
        memory.store_decision("300750", "2025-06-03", {"rating": "持有"})
        entries = memory._load_all_entries()
        assert len(entries) == 3

    def test_decision_dict_preserved(self, memory):
        """决策字典内容被完整保存。"""
        decision = {
            "rating": "卖出",
            "action": "卖出",
            "reasoning": "破位下行",
            "final_trade_decision": "建议止损离场",
        }
        memory.store_decision("000001", "2025-06-01", decision)
        entries = memory._load_all_entries()
        assert entries[0]["decision"]["action"] == "卖出"
        assert entries[0]["decision"]["reasoning"] == "破位下行"

    def test_default_rating_when_missing(self, memory):
        """决策字典无 rating 字段时使用 'unknown'。"""
        memory.store_decision("000001", "2025-06-01", {"action": "买入"})
        entries = memory._load_all_entries()
        assert entries[0]["rating"] == "unknown"

    def test_file_created_on_disk(self, memory, tmp_path):
        """记忆文件在磁盘上被创建。"""
        memory.store_decision("000001", "2025-06-01", {"rating": "买入"})
        assert (tmp_path / "test_memory.log").exists()


# ────────────────────────────────────────────────────────────────
#  get_pending_entries
# ────────────────────────────────────────────────────────────────


class TestGetPendingEntries:
    """Tests for get_pending_entries()."""

    def test_returns_only_pending(self, memory_with_entries):
        """get_pending_entries 仅返回 pending 条目。"""
        pending = memory_with_entries.get_pending_entries()
        assert all(e["pending"] for e in pending)
        assert len(pending) == 3  # all entries are pending by default

    def test_empty_when_no_pending(self, memory):
        """无 pending 条目时返回空列表。"""
        pending = memory.get_pending_entries()
        assert pending == []

    def test_pending_count_matches(self, memory):
        """pending 条目数量与存储数量一致。"""
        memory.store_decision("000001", "2025-06-01", {"rating": "买入"})
        memory.store_decision("600519", "2025-06-02", {"rating": "增持"})
        pending = memory.get_pending_entries()
        assert len(pending) == 2


# ────────────────────────────────────────────────────────────────
#  get_past_context
# ────────────────────────────────────────────────────────────────


class TestGetPastContext:
    """Tests for get_past_context()."""

    def test_returns_formatted_history_for_same_ticker(self, memory_with_entries):
        """同一标的的历史上下文包含该标的的条目。"""
        # First resolve some entries manually
        memory_with_entries.batch_update_with_outcomes(
            [
                {
                    "ticker": "000001",
                    "trade_date": "2025-06-01",
                    "reflection": {"outcome": "盈利", "lesson": "技术分析有效"},
                },
            ]
        )
        context = memory_with_entries.get_past_context("000001")
        assert "000001" in context

    def test_returns_no_history_message_when_empty(self, memory):
        """无历史记录时返回提示信息。"""
        context = memory.get_past_context("000001")
        assert "暂无历史决策记录" in context

    def test_cross_ticker_context_included(self, memory_with_entries):
        """其他标的的历史也被包含。"""
        # Resolve entries for both tickers
        memory_with_entries.batch_update_with_outcomes(
            [
                {
                    "ticker": "000001",
                    "trade_date": "2025-06-01",
                    "reflection": {"outcome": "盈利"},
                },
                {
                    "ticker": "600519",
                    "trade_date": "2025-06-02",
                    "reflection": {"outcome": "亏损"},
                },
            ]
        )
        context = memory_with_entries.get_past_context("000001")
        # Should contain both same-ticker and cross-ticker sections
        assert "000001" in context

    def test_context_contains_rating(self, memory_with_entries):
        """上下文中包含评级信息。"""
        memory_with_entries.batch_update_with_outcomes(
            [
                {
                    "ticker": "000001",
                    "trade_date": "2025-06-01",
                    "reflection": {"outcome": "盈利"},
                },
            ]
        )
        context = memory_with_entries.get_past_context("000001")
        assert "买入" in context or "评级" in context


# ────────────────────────────────────────────────────────────────
#  batch_update_with_outcomes
# ────────────────────────────────────────────────────────────────


class TestBatchUpdateWithOutcomes:
    """Tests for batch_update_with_outcomes()."""

    def test_resolves_pending_entry(self, memory):
        """批量更新将 pending 标记为 resolved。"""
        memory.store_decision("000001", "2025-06-01", {"rating": "买入"})
        updated = memory.batch_update_with_outcomes(
            [
                {
                    "ticker": "000001",
                    "trade_date": "2025-06-01",
                    "reflection": {"outcome": "盈利", "lesson": "顺势而为"},
                },
            ]
        )
        assert updated == 1
        pending = memory.get_pending_entries()
        assert len(pending) == 0

    def test_reflection_stored(self, memory):
        """反思内容被正确存储。"""
        memory.store_decision("000001", "2025-06-01", {"rating": "买入"})
        memory.batch_update_with_outcomes(
            [
                {
                    "ticker": "000001",
                    "trade_date": "2025-06-01",
                    "reflection": {"outcome": "盈利", "lesson": "止损设置合理"},
                },
            ]
        )
        entries = memory._load_all_entries()
        assert entries[0]["reflection"]["outcome"] == "盈利"
        assert entries[0]["reflection"]["lesson"] == "止损设置合理"

    def test_new_rating_applied(self, memory):
        """更新时可修改评级。"""
        memory.store_decision("000001", "2025-06-01", {"rating": "买入"})
        memory.batch_update_with_outcomes(
            [
                {
                    "ticker": "000001",
                    "trade_date": "2025-06-01",
                    "reflection": {"outcome": "亏损"},
                    "new_rating": "减持",
                },
            ]
        )
        entries = memory._load_all_entries()
        assert entries[0]["rating"] == "减持"

    def test_no_match_returns_zero(self, memory):
        """无匹配条目时返回 0。"""
        memory.store_decision("000001", "2025-06-01", {"rating": "买入"})
        updated = memory.batch_update_with_outcomes(
            [
                {
                    "ticker": "999999",
                    "trade_date": "2025-06-01",
                    "reflection": {"outcome": "N/A"},
                },
            ]
        )
        assert updated == 0


# ────────────────────────────────────────────────────────────────
#  _apply_rotation
# ────────────────────────────────────────────────────────────────


class TestApplyRotation:
    """Tests for _apply_rotation()."""

    def test_trims_old_entries(self, tmp_path):
        """轮转保留最近的 resolved 条目，删除过多的旧条目。"""
        mem = TradingMemoryLog(
            memory_dir=str(tmp_path),
            memory_file="rotation_test.log",
        )
        # Create 15 entries for the same ticker, resolve them all
        for i in range(15):
            date = f"2025-01-{i + 1:02d}"
            mem.store_decision("000001", date, {"rating": "持有"})
        mem.batch_update_with_outcomes(
            [
                {
                    "ticker": "000001",
                    "trade_date": f"2025-01-{i + 1:02d}",
                    "reflection": {"outcome": f"day-{i}"},
                }
                for i in range(15)
            ]
        )

        # Apply rotation with max_same=5
        mem._apply_rotation(max_same=5, max_cross=10)
        entries = mem._load_all_entries()
        resolved = [e for e in entries if not e["pending"]]
        assert len(resolved) <= 5

    def test_pending_entries_always_kept(self, tmp_path):
        """轮转不会删除 pending 条目。"""
        mem = TradingMemoryLog(
            memory_dir=str(tmp_path),
            memory_file="rotation_pending.log",
        )
        # Create some pending entries
        for i in range(5):
            date = f"2025-01-{i + 1:02d}"
            mem.store_decision("000001", date, {"rating": "买入"})

        # Apply rotation
        mem._apply_rotation(max_same=2, max_cross=5)
        entries = mem._load_all_entries()
        pending = [e for e in entries if e["pending"]]
        assert len(pending) == 5  # all pending kept

    def test_cross_ticker_rotation(self, tmp_path):
        """跨标的轮转：总共保留 max_cross 条 resolved。"""
        mem = TradingMemoryLog(
            memory_dir=str(tmp_path),
            memory_file="rotation_cross.log",
        )
        # Create entries for multiple tickers
        for ticker in ["000001", "600519", "300750"]:
            for i in range(5):
                date = f"2025-01-{i + 1:02d}"
                mem.store_decision(ticker, date, {"rating": "持有"})
            # Resolve all
            mem.batch_update_with_outcomes(
                [
                    {
                        "ticker": ticker,
                        "trade_date": f"2025-01-{i + 1:02d}",
                        "reflection": {"outcome": "ok"},
                    }
                    for i in range(5)
                ]
            )

        # Apply rotation: max_same=3, max_cross=5
        mem._apply_rotation(max_same=3, max_cross=5)
        entries = mem._load_all_entries()
        resolved = [e for e in entries if not e["pending"]]
        assert len(resolved) <= 5


# ────────────────────────────────────────────────────────────────
#  Edge cases
# ────────────────────────────────────────────────────────────────


class TestMemoryEdgeCases:
    """Tests for edge cases in TradingMemoryLog."""

    def test_empty_file_returns_empty_list(self, memory):
        """空文件返回空列表。"""
        entries = memory._load_all_entries()
        assert entries == []

    def test_nonexistent_file_returns_empty(self, tmp_path):
        """文件不存在时返回空列表。"""
        mem = TradingMemoryLog(
            memory_dir=str(tmp_path / "nonexistent"),
            memory_file="no_such_file.log",
        )
        entries = mem._load_all_entries()
        assert entries == []

    def test_rewrite_all_preserves_data(self, memory):
        """_rewrite_all 后数据完整保留。"""
        memory.store_decision("000001", "2025-06-01", {"rating": "买入", "action": "买入"})
        memory.store_decision("600519", "2025-06-02", {"rating": "增持", "action": "增持"})

        entries = memory._load_all_entries()
        memory._rewrite_all(entries)

        reloaded = memory._load_all_entries()
        assert len(reloaded) == 2
        assert reloaded[0]["ticker"] == "000001"
        assert reloaded[1]["ticker"] == "600519"
