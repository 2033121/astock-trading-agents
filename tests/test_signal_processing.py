"""Tests for rating extraction and signal processing."""

import pytest

from astock_trader.agents.utils.rating import parse_rating
from astock_trader.graph.signal_processing import SignalProcessor


# ────────────────────────────────────────────────────────────────
#  parse_rating — label pattern matching
# ────────────────────────────────────────────────────────────────

class TestParseRatingLabelPattern:
    """Tests for parse_rating() with label patterns (评级: X / **评级**: X)."""

    def test_bold_rating_label_buy(self):
        """**评级**: 买入 -> 买入。"""
        assert parse_rating("**评级**: 买入") == "买入"

    def test_plain_rating_label_hold(self):
        """评级: 持有 -> 持有。"""
        assert parse_rating("评级: 持有") == "持有"

    def test_rating_label_overweight(self):
        """评级：增持 -> 增持。"""
        assert parse_rating("**评级**：增持") == "增持"

    def test_rating_label_underweight(self):
        """评级: 减持 -> 减持。"""
        assert parse_rating("评级: 减持") == "减持"

    def test_rating_label_sell(self):
        """评级: 卖出 -> 卖出。"""
        assert parse_rating("**评级**: 卖出") == "卖出"


# ────────────────────────────────────────────────────────────────
#  parse_rating — English compatibility
# ────────────────────────────────────────────────────────────────

class TestParseRatingEnglish:
    """Tests for parse_rating() English label patterns (Rating: Buy)."""

    def test_english_rating_buy(self):
        """**Rating**: Buy -> 买入。"""
        assert parse_rating("**Rating**: Buy") == "买入"

    def test_english_rating_hold(self):
        """Rating: Hold -> 持有。"""
        assert parse_rating("Rating: Hold") == "持有"

    def test_english_rating_sell(self):
        """Rating: Sell -> 卖出。"""
        assert parse_rating("**Rating**: Sell") == "卖出"

    def test_english_rating_overweight(self):
        """Rating: Overweight -> 增持。"""
        assert parse_rating("Rating: Overweight") == "增持"

    def test_english_rating_underweight(self):
        """Rating: Underweight -> 减持。"""
        assert parse_rating("Rating: Underweight") == "减持"

    def test_english_rating_case_insensitive(self):
        """Rating: buy (lowercase) -> 买入。"""
        assert parse_rating("Rating: buy") == "买入"


# ────────────────────────────────────────────────────────────────
#  parse_rating — full-text keyword search
# ────────────────────────────────────────────────────────────────

class TestParseRatingFullText:
    """Tests for parse_rating() full-text keyword fallback."""

    def test_text_contains_buy_keyword(self):
        """文本包含 建议增持 -> 增持。"""
        assert parse_rating("综合来看，建议增持该标的") == "增持"

    def test_text_contains_sell_keyword(self):
        """文本包含 建议卖出 -> 卖出。"""
        assert parse_rating("风险过高，建议卖出止损") == "卖出"

    def test_text_contains_hold_keyword(self):
        """文本包含 继续持有 -> 持有。"""
        assert parse_rating("建议继续持有等待催化") == "持有"

    def test_text_contains_buy_cn_keyword(self):
        """文本包含 买入 关键词。"""
        assert parse_rating("当前价格适合买入") == "买入"

    def test_english_keyword_in_text(self):
        """文本包含英文关键词。"""
        assert parse_rating("We recommend buying this stock") == "买入"

    def test_priority_order_in_full_text(self):
        """多个关键词同时出现时，按优先级顺序（买入 > 增持 > ...）返回。"""
        # "买入" has higher priority than "持有"
        assert parse_rating("既可能买入也可能持有") == "买入"


# ────────────────────────────────────────────────────────────────
#  parse_rating — default / edge cases
# ────────────────────────────────────────────────────────────────

class TestParseRatingEdgeCases:
    """Tests for parse_rating() edge cases and defaults."""

    def test_empty_text_returns_default(self):
        """空文本 -> 默认 持有。"""
        assert parse_rating("") == "持有"

    def test_none_text_returns_default(self):
        """None 文本 -> 默认 持有。"""
        assert parse_rating(None) == "持有"

    def test_unrecognized_text_returns_default(self):
        """无法识别的文本 -> 默认 持有。"""
        assert parse_rating("今天天气不错") == "持有"

    def test_custom_default(self):
        """自定义默认值。"""
        assert parse_rating("无法识别的内容", default="卖出") == "卖出"

    def test_long_text_with_rating_embedded(self):
        """长文本中嵌入评级标签。"""
        text = (
            "## 综合分析\n\n"
            "经过全面分析，我们得出以下结论：\n\n"
            "**评级**: 增持\n\n"
            "理由：基本面持续改善，技术面确认突破。"
        )
        assert parse_rating(text) == "增持"


# ────────────────────────────────────────────────────────────────
#  SignalProcessor
# ────────────────────────────────────────────────────────────────

class TestSignalProcessor:
    """Tests for SignalProcessor.process_signal()."""

    @pytest.fixture
    def processor(self):
        """创建 SignalProcessor 实例（不需要 LLM）。"""
        return SignalProcessor(quick_thinking_llm=None)

    def test_process_signal_extracts_rating(self, processor):
        """正常提取评级。"""
        signal = "**评级**: 买入\n\n执行摘要：强烈看多"
        assert processor.process_signal(signal) == "买入"

    def test_process_signal_empty_returns_default(self, processor):
        """空信号 -> 默认 持有。"""
        assert processor.process_signal("") == "持有"

    def test_process_signal_none_returns_default(self, processor):
        """None 信号 -> 默认 持有。"""
        assert processor.process_signal(None) == "持有"

    def test_process_signal_wraps_parse_rating(self, processor):
        """process_signal 应使用 parse_rating 内部逻辑。"""
        signal = "综合来看，建议增持"
        assert processor.process_signal(signal) == "增持"

    def test_process_signal_english_compat(self, processor):
        """英文评级兼容。"""
        signal = "**Rating**: Sell"
        assert processor.process_signal(signal) == "卖出"

    def test_processor_with_llm_param(self):
        """构造函数接受 LLM 参数（虽然当前未使用）。"""
        mock_llm = object()
        proc = SignalProcessor(quick_thinking_llm=mock_llm)
        assert proc.quick_thinking_llm is mock_llm
        # process_signal still works regardless
        assert proc.process_signal("**评级**: 卖出") == "卖出"
