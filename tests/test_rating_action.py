"""交易动作提取 —— 「操作」字段不该被否定句读反。

背景：``TradingAgentsGraph._extract_action`` 原来按刻度表顺序做子串扫描
（``for action in ("买入","增持",...): if action in plan``），有两个毛病：

1. **顺序偏见** —— 按刻度表顺序而不是文中出现顺序；
2. **不认否定** —— 交易员写「这不是"买入信号"，而是布局框架」，字面出现
   「买入」就返回「买入」，方向正好读反，还会写进记忆日志与 history 摘要。

这里把两类误读都钉住。
"""

from astock_trader.agents.utils.rating import extract_action, extract_rating


class TestRatingNegation:
    """评级字段也有「否定句里出现刻度词」的毛病 —— 而且是实盘抓到的。

    一次真实的 000155 分析里，基金经理白纸黑字写「**最终评级 持有（HOLD）**」，
    评级却解析成「买入」。原因：正文里有一句「**低估值不是买入充分条件**」，
    而旧实现按**刻度表顺序**全文找关键词，「买入」排在第一位就命中。
    """

    def test_real_000155_final_decision(self):
        # 照抄实盘那份决策的开头与那句致命的话
        text = (
            "# 川能动力（000155）最终交易决策\n\n"
            "## 1. 最终评级\n\n"
            "**持有（HOLD）——条件化参与，不接飞刀，不追趋势**\n\n"
            "## 3. 投资逻辑\n\n"
            "低估值不是买入充分条件，必须配合拐点确认。\n"
        )
        assert extract_rating(text) == "持有"

    def test_negated_keyword_is_not_the_rating(self):
        assert extract_rating("不是买入信号，建议持有") == "持有"

    def test_all_mentions_negated_returns_none(self):
        assert extract_rating("低估值不是买入充分条件") is None

    def test_later_unnegated_stance_wins_over_earlier_negated_one(self):
        assert extract_rating("不构成买入理由。综合判断：减持") == "减持"

    def test_position_order_not_scale_order(self):
        # 「持有」在前、「买入」在后 —— 必须取持有，而不是刻度表里排第一的买入
        assert extract_rating("建议持有，若放量突破可考虑买入") == "持有"

    def test_label_still_takes_priority(self):
        # 带冒号的标签仍然直接命中，不受全文扫描影响
        assert extract_rating("**评级**: 减持") == "减持"


class TestNegation:
    """否定语境里的刻度词不能当成表态。"""

    def test_quoted_negation_is_skipped(self):
        # 实测那条交易员计划里的原句
        plan = '这不是"买入信号"，而是"布局框架"。当前以持有为主。'
        assert extract_action(plan) == "持有"

    def test_all_mentions_negated_returns_none(self):
        # 唯一提到的方向是被否定的 —— 不能猜，交回 unknown 让调用方处理
        assert extract_action("本计划不构成买入建议。") is None

    def test_negation_does_not_leak_across_clauses(self):
        # 「不建议」只否定它自己那一句，不能牵连后一句的「减持」
        assert extract_action("不建议买入，建议减持") == "减持"

    def test_labeled_negation(self):
        assert extract_action('结论：不给予"买入"，维持减持') == "减持"

    def test_negation_window_does_not_reach_far_back(self):
        # 否定词离得太远（超出窗口）就不算否定，「买入后长期持有」是买入表态
        text = "不构成买入" + "、" * 8 + "买入并持有"
        assert extract_action(text) == "买入"


class TestOrdering:
    """取「最先表态的那个」，而不是刻度表里排最前的那个。"""

    def test_position_wins_over_scale_order(self):
        # 文中先说持有、后提买入，结论是持有
        assert extract_action("以持有为主，若回踩则考虑买入") == "持有"

    def test_scale_enumeration_is_stripped(self):
        # 五级刻度枚举描述的是量表本身，不是表态
        assert extract_action("买入/增持/持有/减持/卖出") is None

    def test_scale_enumeration_with_real_stance(self):
        assert extract_action("评级（买入/增持/持有/减持/卖出）：减持") == "减持"


class TestEdgeCases:
    def test_empty_inputs(self):
        assert extract_action(None) is None
        assert extract_action("") is None
        assert extract_action("   \n  ") is None

    def test_no_scale_word_at_all(self):
        assert extract_action("中性偏多，条件化分批建仓。") is None

    def test_real_trader_plan_fragment(self):
        plan = (
            "## 一、交易方向：**中性偏多 → 条件化分批建仓"
            '（当前以"持有 + 左侧小仓试仓"为主，不追高、不重仓）**\n\n'
            '这不是"买入信号"，而是"布局框架"。'
        )
        assert extract_action(plan) == "持有"
