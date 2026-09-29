"""决策类 Agent 的 prompt 契约（价位锚定 + 模糊时不硬选方向）。

两处借鉴自上游 TradingAgents：

* **Trader 价位锚定**（#1167 / #1288）：研究方案只给方向，真实价位结构在技术面
  报告里。不把报告给交易员，入场价/止损价就只能是编的；而只要「具体价位」而不
  限定单位，模型会写「现价下方 3%」这类**不是价格**的值，结构化解析直接失败。
* **裁决纪律**：证据均衡、互相冲突或信息不足时应当选「持有」，不要为了显得果断
  而硬选一个方向（上游 v0.4.1 ``stop the debate managers forcing a direction
  under ambiguity``）。
"""

import pytest

from astock_trader.agents.managers import portfolio_manager, research_manager
from astock_trader.agents.trader import trader as trader_module


class _PromptSpy:
    """替换 ``invoke_structured_or_freetext``：只记录 prompt，不真的调 LLM。"""

    def __init__(self, result: str = "渲染后的 agent 输出"):
        self.result = result
        self.prompts: list[str] = []

    def __call__(self, structured_llm, plain_llm, prompt, render, agent_name):
        self.prompts.append(_flatten(prompt))
        return self.result

    @property
    def last(self) -> str:
        return self.prompts[-1]


def _flatten(prompt) -> str:
    """把 ``str`` 或 LangChain 消息列表统一成一段文本。"""
    if isinstance(prompt, str):
        return prompt
    return "\n".join(str(part) for part in prompt)


@pytest.fixture
def trader_spy(monkeypatch):
    spy = _PromptSpy()
    monkeypatch.setattr(trader_module, "bind_structured", lambda *a, **k: None)
    monkeypatch.setattr(trader_module, "invoke_structured_or_freetext", spy)
    return spy


@pytest.fixture
def research_manager_spy(monkeypatch):
    spy = _PromptSpy()
    monkeypatch.setattr(research_manager, "bind_structured", lambda *a, **k: None)
    monkeypatch.setattr(research_manager, "invoke_structured_or_freetext", spy)
    return spy


@pytest.fixture
def portfolio_manager_spy(monkeypatch):
    spy = _PromptSpy()
    monkeypatch.setattr(portfolio_manager, "bind_structured", lambda *a, **k: None)
    monkeypatch.setattr(portfolio_manager, "invoke_structured_or_freetext", spy)
    return spy


# ────────────────────────────────────────────────────────────────
#  Trader
# ────────────────────────────────────────────────────────────────


class TestTraderPriceGrounding:
    """交易员必须拿到技术面报告，并被要求给绝对价位。"""

    def _run(self, trader_spy, state):
        node = trader_module.create_trader(object())
        node(state, company_name="贵州茅台")
        return trader_spy.last

    def test_market_report_is_included_when_present(self, trader_spy):
        prompt = self._run(
            trader_spy,
            {
                "investment_plan": "评级: 增持",
                "market_report": "当前价 1523.5 元，支撑位 1480，压力位 1600，ATR 32。",
            },
        )
        assert "### 技术面报告（价位锚定的依据）" in prompt
        assert "当前价 1523.5 元" in prompt

    def test_grounding_instruction_requires_anchoring(self, trader_spy):
        prompt = self._run(
            trader_spy,
            {"investment_plan": "评级: 增持", "market_report": "支撑位 1480"},
        )
        assert "必须锚定" in prompt

    def test_absolute_price_rule_always_present(self, trader_spy):
        """没有技术面报告时也要拦住「百分比」这种非价格写法。"""
        prompt = self._run(trader_spy, {"investment_plan": "评级: 增持", "market_report": ""})
        assert "绝对价格" in prompt
        assert "不要填百分比" in prompt
        assert "留空" in prompt

    def test_report_section_omitted_when_missing(self, trader_spy):
        """报告为空时不留一个空气章节。"""
        prompt = self._run(trader_spy, {"investment_plan": "评级: 增持", "market_report": "   "})
        assert "### 技术面报告" not in prompt
        assert "必须锚定" not in prompt

    def test_investment_plan_still_primary(self, trader_spy):
        prompt = self._run(trader_spy, {"investment_plan": "评级: 减持", "market_report": "支撑位 10"})
        assert "### 研究员投资方案" in prompt
        assert "评级: 减持" in prompt


# ────────────────────────────────────────────────────────────────
#  裁决纪律
# ────────────────────────────────────────────────────────────────


class TestResearchManagerAmbiguity:
    """研究经理在证据不足时应被允许选「持有」。"""

    def _prompt(self, research_manager_spy, state):
        node = research_manager.create_research_manager(object())
        node(state)
        return research_manager_spy.last

    def test_allows_hold_under_ambiguity(self, research_manager_spy):
        prompt = self._prompt(
            research_manager_spy,
            {
                "company_of_interest": "贵州茅台",
                "investment_debate_state": {
                    "history": "多头说估值低，空头说需求弱。",
                    "bull_history": "",
                    "bear_history": "",
                    "judge_decision": "",
                },
            },
        )
        assert "【裁决纪律】" in prompt
        assert "证据均衡" in prompt
        assert "不要为了显得果断而硬选一个方向" in prompt

    def test_ignores_speaking_order(self, research_manager_spy):
        prompt = self._prompt(
            research_manager_spy,
            {"company_of_interest": "X", "investment_debate_state": {"history": "h"}},
        )
        assert "不受发言先后顺序影响" in prompt


class TestPortfolioManagerAmbiguity:
    """组合经理同样不能在冲突证据下假装确定。"""

    def _prompt(self, portfolio_manager_spy, state):
        node = portfolio_manager.create_portfolio_manager(object())
        node(state)
        return portfolio_manager_spy.last

    def test_conflicting_evidence_may_choose_hold(self, portfolio_manager_spy):
        prompt = self._prompt(
            portfolio_manager_spy,
            {"company_of_interest": "贵州茅台", "investment_plan": "评级: 增持"},
        )
        assert "【裁决纪律】" in prompt
        assert "请选「持有」并写明分歧" in prompt

    def test_no_longer_demands_blind_decisiveness(self, portfolio_manager_spy):
        """旧 prompt 结尾是「决策应明确、果断」，直接把模型推向编方向。"""
        prompt = self._prompt(portfolio_manager_spy, {"company_of_interest": "X"})
        assert "决策应明确、果断" not in prompt
        assert "不是在证据不足时假装确定" in prompt
