"""Tests for rating extraction and signal processing."""

import pytest

from astock_trader.agents.utils.rating import RATING_REVIEW, RATINGS, extract_rating, parse_rating
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

    def test_process_signal_empty_returns_review(self, processor):
        """空信号 -> 待复核（不再静默降级成「持有」）。"""
        assert processor.process_signal("") == RATING_REVIEW

    def test_process_signal_none_returns_review(self, processor):
        """None 信号 -> 待复核（不再静默降级成「持有」）。"""
        assert processor.process_signal(None) == RATING_REVIEW

    def test_process_signal_unparseable_returns_review(self, processor):
        """无法解析的决策 -> 待复核，而不是伪造一个中性评级。"""
        signal = "本报告综合了各方观点，具体结论请参见上文分析。"
        assert processor.process_signal(signal) == RATING_REVIEW

    def test_process_signal_wraps_parse_rating(self, processor):
        """process_signal 应使用 extract_rating 内部逻辑。"""
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


# ────────────────────────────────────────────────────────────────
#  extract_rating — 不猜、不兜底
# ────────────────────────────────────────────────────────────────


class TestExtractRatingStrictness:
    """``extract_rating`` 在无法确定时返回 ``None``，而不是编一个评级。"""

    def test_returns_none_when_nothing_matches(self):
        assert extract_rating("今天天气不错，适合出门") is None

    @pytest.mark.parametrize("text", ["", "   ", "\n\n", None])
    def test_empty_input_returns_none(self, text):
        assert extract_rating(text) is None

    def test_label_with_off_scale_value_returns_none(self):
        """「评级: 观望」不在五级刻度内 —— 不该退到全文搜索里捞一个关键词。"""
        assert extract_rating("**评级**: 观望\n\n后续视成交量决定。") is None

    def test_off_scale_label_does_not_fall_back_to_boilerplate(self):
        """刻度说明里全是关键词，旧实现在这里会返回「买入」。"""
        text = "**评级**: 待定\n\n评级取值：买入/增持/持有/减持/卖出。\n"
        assert extract_rating(text) is None

    def test_scale_boilerplate_alone_returns_none(self):
        """整篇只有刻度说明、没有表态 —— 不能把刻度里第一个词当成结论。"""
        text = "本次分析的评级体系为：买入/增持/持有/减持/卖出，共五档。\n"
        assert extract_rating(text) is None

    def test_scale_boilerplate_does_not_shadow_real_verdict(self):
        """刻度说明 + 明确表态：表态要赢。"""
        text = "评级取值：买入/增持/持有/减持/卖出。\n\n综合判断，建议减持。\n"
        assert extract_rating(text) == "减持"

    def test_scale_run_inside_a_sentence_is_stripped(self):
        text = "结论：增持（刻度：买入/增持/持有/减持/卖出）\n"
        assert extract_rating(text) == "增持"

    def test_short_enumeration_is_not_a_scale_listing(self):
        """只列两个档位不构成「刻度说明」，正常表态仍要识别。"""
        assert extract_rating("既可能买入也可能持有") == "买入"

    def test_buyer_is_not_a_rating(self):
        """同根词不该被当成评级。"""
        assert extract_rating("The buyer showed strong interest in the asset.") is None

    def test_buying_is_a_rating(self):
        assert extract_rating("We recommend buying this stock") == "买入"

    def test_seller_is_not_a_rating(self):
        assert extract_rating("The seller dominated the order book.") is None

    def test_selling_is_a_rating(self):
        assert extract_rating("Selling into strength is prudent here") == "卖出"


class TestRatingReviewContract:
    """``RATING_REVIEW`` 的对外契约。"""

    def test_review_is_not_a_tradeable_tier(self):
        """待复核不是仓位档位，不能混进 RATINGS 里。"""
        assert RATING_REVIEW not in RATINGS

    def test_ratings_tuple_is_the_five_tier_scale(self):
        assert RATINGS == ("买入", "增持", "持有", "减持", "卖出")

    def test_parse_rating_still_defaults_for_legacy_callers(self):
        """兼容包装保持「总有返回值」的旧语义。"""
        assert parse_rating("今天天气不错") == "持有"
        assert parse_rating("今天天气不错", default="卖出") == "卖出"

    def test_parse_rating_delegates_to_extract_rating(self):
        assert parse_rating("**评级**: 减持") == "减持"
