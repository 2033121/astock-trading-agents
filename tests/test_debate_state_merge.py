"""辩论历史必须在多轮之间存活。

**这是本轮最严重的一个 bug。** 实测一次 600519 分析，研究主管在裁决书里写下
「（本次空头未提交论据——这是一个必须点破的重大不对称）」，然后自己代拟了一段
空方立场。一场只有一个辩手的辩论，而报告里看不出任何异常。

根因：``AgentState.investment_debate_state`` 是嵌套 TypedDict，子字段上虽然标了
``Annotated[list, _append_str_list]``，但 **LangGraph 不对嵌套结构应用 reducer**
（下面 ``test_nested_reducers_do_not_apply`` 用最小 StateGraph 把这个前提钉死）。
于是子字典整体是 LastValue 通道 —— 写入即替换。

辩论顺序是 ``Bull → Bear → Bull(反驳) → 研究主管``，所以轮到主管时，它读到的
字典里只剩最后一轮多头的写入，``bear_history`` 已被冲掉。

修法是 ``setup._merge_debate``：每个辩论节点写出**合并后的完整字典**。
"""

from typing import Annotated, TypedDict

import pytest
from langgraph.graph import END, START, StateGraph

from astock_trader.agents.utils.agent_states import _append_str_list
from astock_trader.graph.setup import _merge_debate

# ── 前提：LangGraph 不处理嵌套 reducer ──────────────────────────


class _Inner(TypedDict, total=False):
    bull_history: Annotated[list[str], _append_str_list]
    bear_history: Annotated[list[str], _append_str_list]
    judge_decision: str
    count: int


class _Outer(TypedDict, total=False):
    debate: _Inner


def test_nested_reducers_do_not_apply():
    """固定住前提：嵌套 TypedDict 的子字段注解是**惰性**的，整体被替换。

    如果哪天 LangGraph 支持了嵌套 reducer，这个测试会失败 —— 那时
    ``_merge_debate`` 就可以退休了，不必再手动合并。
    """

    def bull(_s):
        return {"debate": {"bull_history": ["多头论据"], "count": 1}}

    def bear(_s):
        return {"debate": {"bear_history": ["空头论据"], "count": 2}}

    def judge(_s):
        return {"debate": {"judge_decision": "裁决"}}

    g = StateGraph(_Outer)
    g.add_node("bull", bull)
    g.add_node("bear", bear)
    g.add_node("judge", judge)
    g.add_edge(START, "bull")
    g.add_edge("bull", "bear")
    g.add_edge("bear", "judge")
    g.add_edge("judge", END)

    final = g.compile().invoke({})["debate"]

    # 每一次写入都整体替换了子字典：既没有追加，早期的内容也留不下来
    assert final == {"judge_decision": "裁决"}
    assert "bull_history" not in final
    assert "bear_history" not in final


# ── 修法：节点自己合并 ────────────────────────────────────────


class TestMergeDebate:
    def test_lists_append(self):
        merged = _merge_debate({"bull_history": ["第一轮"]}, bull_history=["第二轮"])
        assert merged["bull_history"] == ["第一轮", "第二轮"]

    def test_scalars_overwrite(self):
        merged = _merge_debate({"count": 1, "current_response": "旧"}, count=2, current_response="新")
        assert merged["count"] == 2
        assert merged["current_response"] == "新"

    def test_does_not_mutate_input(self):
        original = {"bull_history": ["a"]}
        _merge_debate(original, bull_history=["b"])
        assert original == {"bull_history": ["a"]}

    def test_none_previous(self):
        assert _merge_debate(None, bear_history=["x"]) == {"bear_history": ["x"]}

    def test_corrupt_non_list_history_is_replaced(self):
        # 历史字段被别处写成了 str 时不能崩，退化成新建列表
        merged = _merge_debate({"bull_history": "坏数据"}, bull_history=["新"])
        assert merged["bull_history"] == ["新"]

    def test_preserves_unrelated_keys(self):
        merged = _merge_debate({"judge_decision": "裁决"}, bull_history=["x"])
        assert merged["judge_decision"] == "裁决"


class TestDebateSurvivesFullRound:
    """走一遍真实顺序 Bull → Bear → Bull(反驳) → 主管，历史必须都在。"""

    def test_all_three_turns_survive(self):
        state: dict = {}
        for key, text in (
            ("bull_history", "多头第一轮"),
            ("bear_history", "空头第一轮"),
            ("bull_history", "多头反驳"),
        ):
            state = _merge_debate(state, **{key: [text]})
        state = _merge_debate(state, judge_decision="裁决")

        assert state["bull_history"] == ["多头第一轮", "多头反驳"]
        assert state["bear_history"] == ["空头第一轮"]
        assert state["judge_decision"] == "裁决"

    def test_research_manager_sees_both_sides(self):
        """回归：主管读到的两个历史都不能为空（原来 bear 必空）。"""
        debate_state: dict = {}
        debate_state = _merge_debate(debate_state, bull_history=["看多: 估值极低"])
        debate_state = _merge_debate(debate_state, bear_history=["看空: 价值陷阱"])
        debate_state = _merge_debate(debate_state, bull_history=["看多: 反驳空头"])

        assert debate_state.get("bull_history")
        assert debate_state.get("bear_history")
        assert debate_state["bear_history"][0] == "看空: 价值陷阱"


class TestRiskDebateSurvives:
    def test_three_risk_speakers_all_kept(self):
        state: dict = {}
        state = _merge_debate(state, aggressive_history=["激进"])
        state = _merge_debate(state, conservative_history=["保守"])
        state = _merge_debate(state, neutral_history=["中性"])
        state = _merge_debate(state, judge_decision="风控裁决")

        assert state["aggressive_history"] == ["激进"]
        assert state["conservative_history"] == ["保守"]
        assert state["neutral_history"] == ["中性"]
        assert state["judge_decision"] == "风控裁决"


def _setup_source() -> str:
    with open("src/astock_trader/graph/setup.py", encoding="utf-8") as fh:
        return fh.read()


@pytest.mark.parametrize(
    "legacy_write",
    [
        '"bull_history": [content]',
        '"bear_history": [content]',
        '"aggressive_history": [content]',
        '"conservative_history": [content]',
        '"neutral_history": [content]',
    ],
)
def test_no_bare_dict_history_write_remains(legacy_write):
    """守门测试：辩论节点不允许再回到「裸 dict 写历史字段」的旧写法。

    裸写就会重新引入覆盖 bug，而且**症状是静默的** —— 报告照样生成，只是有一方
    的论据凭空消失，裁判再自己编一段补上。
    """
    assert legacy_write not in _setup_source()


def test_merge_helper_is_used_by_every_debate_node():
    # 投资辩论 3 处（多头/空头/主管）+ 风控辩论 4 处（激进/保守/中性/裁判）
    assert _setup_source().count("_merge_debate(") >= 8
