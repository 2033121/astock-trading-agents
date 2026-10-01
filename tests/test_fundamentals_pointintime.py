"""基本面数据的时点门控（roadmap A9）。

历史运行里「最新财报 + 当期估值快照」是典型的前视偏差来源：报告期结束 ≠ 可知
（一季报 3-31 结束、最晚 4-30 才披露），市值/股本更是运行当天的值。这里覆盖四层：

* ``akshare_data``：认得出报告期/公告日期的帧按披露日过滤，认不出就整帧剔除；
* ``tushare_data``：结构化财报按 ``ann_date`` 过滤，每日指标按交易日过滤；
* ``mx_data``：自然语言查询给不出可判定的报告期，历史运行下**拒绝出数**，
  让路由换到能过滤的数据源；
* 工具层：运行日期由 ``InjectedState`` 注入，模型看不到也改不了。
"""

from typing import Annotated, TypedDict

import pandas as pd
import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from astock_trader.agents.utils import fundamental_data_tools as tools_module
from astock_trader.dataflows import akshare_data, mx_data, tushare_data
from astock_trader.dataflows.errors import VendorError, VendorNotConfiguredError
from astock_trader.dataflows.interface import route_to_vendor

# 同花顺财务摘要：只有报告期，没有公告日期 —— 只能靠法定披露截止日判定。
THS_SUMMARY = pd.DataFrame(
    {
        "报告期": ["2025-09-30", "2025-06-30", "2025-03-31", "2024-12-31"],
        "净利润": [30.0, 20.0, 10.0, 40.0],
    }
)

# 东财报表：带公告日期，可以精确判定。
EM_BALANCE = pd.DataFrame(
    {
        "REPORT_DATE": ["2025-09-30", "2025-06-30", "2025-03-31"],
        "NOTICE_DATE": ["2025-10-28", "2025-08-20", "2025-04-25"],
        "总资产": [100.0, 90.0, 80.0],
    }
)

COMPANY_INFO = pd.DataFrame(
    {
        "item": ["股票简称", "行业", "上市时间", "总市值", "流通市值", "总股本"],
        "value": ["贵州茅台", "白酒", "2001-08-27", "2100000000", "2100000000", "1256000000"],
    }
)


@pytest.fixture
def akshare_em_frames(monkeypatch):
    """把东财两个接口换成固定帧。"""
    monkeypatch.setattr(akshare_data.ak, "stock_individual_info_em", lambda **kw: COMPANY_INFO)
    monkeypatch.setattr(akshare_data.ak, "stock_financial_abstract_ths", lambda **kw: THS_SUMMARY)


# ────────────────────────────────────────────────────────────────
#  akshare：report period gating
# ────────────────────────────────────────────────────────────────


class TestAkshareFundamentalsGating:
    """``get_fundamentals``：财报行按披露日过滤，当期快照字段隐去。"""

    def test_live_run_is_unchanged(self, akshare_em_frames):
        """实时运行（curr_date=None）行为与修复前一致。"""
        out = akshare_data.get_fundamentals("600519")
        assert "2025-09-30" in out
        assert "2025-06-30" in out
        assert "总市值" in out
        assert "withheld" not in out

    def test_historical_run_drops_undisclosed_periods(self, akshare_em_frames):
        """2025-06-10：一季报已过截止日（4-30）放行，半年报（截止 8-31）不放行。"""
        out = akshare_data.get_fundamentals("600519", curr_date="2025-06-10")
        assert "2025-03-31" in out
        assert "2025-06-30" not in out
        assert "2025-09-30" not in out

    def test_historical_run_withholds_snapshot_fields(self, akshare_em_frames):
        out = akshare_data.get_fundamentals("600519", curr_date="2025-06-10")
        # 字段不再作为数据行出现（通知里会点名说明隐去了哪些字段）
        assert "- **总市值**" not in out
        assert "- **总股本**" not in out
        assert "withheld" in out
        # 静态属性保留
        assert "贵州茅台" in out
        assert "白酒" in out

    def test_no_disclosed_period_says_so(self, akshare_em_frames):
        """分析日之前什么都没披露：明确说明，而不是给最新值。"""
        out = akshare_data.get_fundamentals("600519", curr_date="2025-01-15")
        assert "No reporting period was public as of 2025-01-15" in out
        assert "2024-12-31" not in out


class TestAkshareStatementsGating:
    """三大报表同样按公告日期过滤。"""

    @pytest.fixture(autouse=True)
    def _patch(self, monkeypatch):
        monkeypatch.setattr(akshare_data.ak, "stock_balance_sheet_by_report_em", lambda **kw: EM_BALANCE)

    def test_live_run_keeps_latest(self):
        out = akshare_data.get_balance_sheet("600519")
        assert "2025-09-30" in out

    def test_historical_run_uses_last_disclosed(self):
        """2025-06-01：一季报（公告 4-25）已知，半年报（公告 8-20）未知。"""
        out = akshare_data.get_balance_sheet("600519", curr_date="2025-06-01")
        assert "2025-03-31" in out
        assert "2025-06-30" not in out

    def test_announcement_date_beats_statutory_deadline(self):
        """2025-04-27：按截止日（4-30）还不算可知，但公告日期（4-25）已过 —— 放行。"""
        out = akshare_data.get_balance_sheet("600519", curr_date="2025-04-27")
        assert "2025-03-31" in out

    def test_nothing_disclosed_says_so(self):
        out = akshare_data.get_balance_sheet("600519", curr_date="2025-02-01")
        assert "No report was public as of 2025-02-01" in out
        assert "总资产" not in out


class TestAkshareUnknownPeriodColumn:
    """认不出报告期列时宁可整帧剔除 —— 无法证明任何一行当时可知。"""

    def test_frame_without_period_column_is_dropped(self, monkeypatch):
        frame = pd.DataFrame({"项目": ["营业收入"], "金额": [100.0]})
        monkeypatch.setattr(akshare_data.ak, "stock_balance_sheet_by_report_em", lambda **kw: frame)
        out = akshare_data.get_balance_sheet("600519", curr_date="2025-06-01")
        assert "No report was public as of 2025-06-01" in out
        assert "营业收入" not in out

    def test_frame_without_period_column_is_kept_live(self, monkeypatch):
        frame = pd.DataFrame({"项目": ["营业收入"], "金额": [100.0]})
        monkeypatch.setattr(akshare_data.ak, "stock_balance_sheet_by_report_em", lambda **kw: frame)
        out = akshare_data.get_balance_sheet("600519")
        assert "营业收入" in out


# ────────────────────────────────────────────────────────────────
#  tushare：ann_date gating
# ────────────────────────────────────────────────────────────────


def _tushare_data(rows: list[list], fields: list[str]) -> dict:
    return {"fields": fields, "items": rows}


class TestTushareGating:
    """Tushare 结构化的 ``{fields, items}`` 按公告日 / 交易日过滤。"""

    def test_report_rows_filtered_by_announcement_date(self):
        data = _tushare_data(
            [
                ["2025-06-30", "2025-08-20", 200.0],
                ["2025-03-31", "2025-04-25", 100.0],
            ],
            ["end_date", "ann_date", "revenue"],
        )
        kept, dropped = tushare_data._gate_report_rows(data, "2025-06-01")
        assert dropped == 1
        assert [row[0] for row in kept["items"]] == ["2025-03-31"]

    def test_live_run_keeps_all_rows(self):
        data = _tushare_data([["2025-06-30", "2025-08-20", 200.0]], ["end_date", "ann_date", "revenue"])
        kept, dropped = tushare_data._gate_report_rows(data, None)
        assert dropped == 0
        assert len(kept["items"]) == 1

    def test_report_without_period_field_is_dropped(self):
        """认不出报告期字段 → 整批剔除。"""
        data = _tushare_data([["2025-06-30", 200.0]], ["period", "revenue"])
        kept, dropped = tushare_data._gate_report_rows(data, "2025-06-01")
        assert dropped == 1
        assert kept["items"] == []

    def test_daily_rows_filtered_by_trade_date(self):
        data = _tushare_data(
            [["20250610", 15.0], ["20250401", 14.0]],
            ["trade_date", "pe"],
        )
        kept, dropped = tushare_data._gate_daily_rows(data, "2025-05-01")
        assert dropped == 1
        assert [row[0] for row in kept["items"]] == ["20250401"]

    def test_get_balance_sheet_filters_by_announcement(self, monkeypatch):
        monkeypatch.setattr(
            tushare_data,
            "_call_api",
            lambda *a, **kw: _tushare_data(
                [["2025-06-30", "2025-08-20", 200.0], ["2025-03-31", "2025-04-25", 100.0]],
                ["end_date", "ann_date", "total_assets"],
            ),
        )
        out = tushare_data.get_balance_sheet("600519", curr_date="2025-06-01")
        assert "2025-03-31" in out
        assert "2025-06-30" not in out

    def test_get_fundamentals_gates_daily_and_financial_rows(self, monkeypatch):
        def fake_call(api_name, params=None, fields=None):
            if api_name == "daily_basic":
                return _tushare_data([["20250610", 15.0], ["20250401", 14.0]], ["trade_date", "pe"])
            return _tushare_data(
                [["2025-06-30", "2025-08-20", 12.0], ["2025-03-31", "2025-04-25", 11.0]],
                ["end_date", "ann_date", "roe"],
            )

        monkeypatch.setattr(tushare_data, "_call_api", fake_call)
        out = tushare_data.get_fundamentals("600519", curr_date="2025-05-01")
        assert "20250401" in out
        assert "20250610" not in out
        assert "2025-03-31" in out
        assert "2025-06-30" not in out


# ────────────────────────────────────────────────────────────────
#  mx：无法给出时点快照 → 拒绝出数
# ────────────────────────────────────────────────────────────────


class TestMxRefusesPointInTime:
    """妙想是自然语言查询，给不出可判定的报告期，历史运行下必须拒绝。"""

    def test_historical_run_raises(self):
        with pytest.raises(VendorError):
            mx_data.get_fundamentals("600519", curr_date="2025-06-10")

    @pytest.mark.parametrize(
        "func",
        [
            mx_data.get_balance_sheet,
            mx_data.get_cashflow,
            mx_data.get_income_statement,
        ],
    )
    def test_statements_also_refuse(self, func):
        with pytest.raises(VendorError):
            func("600519", curr_date="2025-06-10")

    def test_live_run_does_not_refuse_for_point_in_time(self, monkeypatch):
        """实时运行放行（这里让它止步于「缺 key」，而不是时点拒绝）。"""
        monkeypatch.delenv("MX_APIKEY", raising=False)
        with pytest.raises(VendorNotConfiguredError):
            mx_data.get_fundamentals("600519")

    def test_router_falls_back_past_mx(self, monkeypatch):
        """mx 拒绝时路由继续换源，而不是把拒绝当成结果。"""
        monkeypatch.setattr(
            tushare_data,
            "get_fundamentals",
            lambda *a, **kw: (_ for _ in ()).throw(VendorNotConfiguredError("no token")),
        )
        monkeypatch.setattr(
            akshare_data,
            "get_fundamentals",
            lambda *a, **kw: "AKSHARE 的时点基本面",
        )
        out = route_to_vendor("get_fundamentals", symbol="600519", curr_date="2025-06-10")
        assert out == "AKSHARE 的时点基本面"


# ────────────────────────────────────────────────────────────────
#  工具层：运行日期由 graph state 注入
# ────────────────────────────────────────────────────────────────


class _MiniState(TypedDict):
    messages: Annotated[list, add_messages]
    trade_date: str


class TestTradeDateInjection:
    """工具不该让模型自己填日期：由 InjectedState 从 state 注入。"""

    def test_trade_date_hidden_from_model_schema(self):
        for func in (
            tools_module.get_fundamentals,
            tools_module.get_balance_sheet,
            tools_module.get_cashflow,
            tools_module.get_income_statement,
        ):
            assert "trade_date" not in func.args
            assert "symbol" in func.args

    def _run_tool_node(self, monkeypatch, trade_date: str) -> list[tuple]:
        seen: list[tuple] = []
        monkeypatch.setattr(
            tools_module,
            "route_to_vendor",
            lambda method, **kw: (seen.append((method, kw)), "OK")[1],
        )

        def call_tools(state):
            return {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "get_fundamentals",
                                "args": {"symbol": "600519"},
                                "id": "c1",
                                "type": "tool_call",
                            }
                        ],
                    )
                ]
            }

        graph = StateGraph(_MiniState)
        graph.add_node("call", call_tools)
        graph.add_node("tools", ToolNode([tools_module.get_fundamentals]))
        graph.add_edge(START, "call")
        graph.add_edge("call", "tools")
        graph.add_edge("tools", END)
        graph.compile().invoke({"messages": [], "trade_date": trade_date})
        return seen

    def test_historical_run_injects_as_of_date(self, monkeypatch):
        seen = self._run_tool_node(monkeypatch, "2025-06-10")
        assert seen == [("get_fundamentals", {"symbol": "600519", "curr_date": "2025-06-10"})]

    def test_live_run_injects_none(self, monkeypatch):
        """运行日就是今天 → 不门控（curr_date=None），避免误伤刚披露的报告。"""
        from datetime import datetime

        from astock_trader.point_in_time import CST

        today = datetime.now(CST).date().isoformat()
        seen = self._run_tool_node(monkeypatch, today)
        assert seen == [("get_fundamentals", {"symbol": "600519", "curr_date": None})]
