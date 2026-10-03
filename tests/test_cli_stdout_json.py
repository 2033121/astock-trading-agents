"""CLI `--output -` 契约：把结果 JSON 写到 stdout。

MCP server 的 ``analyze_stock`` 就靠这个约定取结构化结果。此前 ``-`` 被当成普通
文件名，于是有两个后果同时发生：

1. 工作目录里被拉出一个**名叫 ``-`` 的垃圾文件**；
2. 调用方永远解析不到 JSON —— quiet 模式下它从 stdout 拿到的是一行 TSV。

再加上 MCP 侧用 ``text=True``（按本机 GBK 解码）和取错了键名（CLI 写的是
``_rating``），``analyze_stock`` 这个旗舰工具实际上是坏的，而测试只覆盖了
工具名单与快照类工具，从没端到端跑过它。
"""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from astock_trader.cli.main import app

_ROOT = Path(__file__).resolve().parents[1]


def _load_server_module():
    """按**文件路径**加载 ``mcp_server.py``，不要用 ``import mcp_server``。

    仓库根不在 ``sys.path`` 上（pyproject 只声明了 ``pythonpath = ["src"]``）。
    本地跑 ``python -m pytest`` 时 CWD 恰好进了 ``sys.path`` 所以能 import，
    CI 跑 ``pytest`` 就 ``ModuleNotFoundError`` —— 本地过、CI 挂的经典陷阱。
    """
    spec = importlib.util.spec_from_file_location("astock_mcp_server", _ROOT / "mcp_server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_MINIMAL_STATE = {
    "company_of_interest": "000155",
    "trade_date": "2026-10-03",
    "final_trade_decision": "# 决策\n评级：持有（HOLD）——条件化参与",
    "market_report": "市场：收盘 10.88",
}


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def stub_graph(monkeypatch):
    """把图替换成桩，避免测试真的去调 LLM。"""

    def _install(state=None, rating="持有"):
        payload = dict(state or _MINIMAL_STATE)

        class _StubGraph:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            def propagate(self, symbol, trade_date):
                return payload, rating

        monkeypatch.setattr("astock_trader.graph.trading_graph.TradingAgentsGraph", _StubGraph)

    return _install


class TestStdoutJson:
    def test_dash_writes_parseable_json(self, runner, stub_graph, tmp_path, monkeypatch):
        stub_graph()
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["analyze", "000155", "--quiet", "--output", "-"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert data["company_of_interest"] == "000155"
        assert data["_rating"] == "持有"
        assert "_elapsed_seconds" in data

    def test_no_junk_file_named_dash(self, runner, stub_graph, tmp_path, monkeypatch):
        """回归：旧实现会在 cwd 里建一个叫 ``-`` 的文件。"""
        stub_graph()
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["analyze", "000155", "--quiet", "--output", "-"])

        assert not (tmp_path / "-").exists()

    def test_chinese_survives_the_roundtrip(self, runner, stub_graph, tmp_path, monkeypatch):
        stub_graph(rating="增持")
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["analyze", "000155", "--quiet", "--output", "-"])

        data = json.loads(result.stdout)
        assert data["_rating"] == "增持"
        assert "条件化参与" in data["final_trade_decision"]

    def test_stdout_json_is_not_polluted_by_the_tsv_line(self, runner, stub_graph, tmp_path, monkeypatch):
        stub_graph()
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["analyze", "000155", "--quiet", "--output", "-"])

        # 整段 stdout 必须就是一份 JSON，不能混进 "000155\t2026-10-03\t持有"
        json.loads(result.stdout)
        assert "\t" not in result.stdout.split("\n")[0]


class TestExistingBehaviourKept:
    def test_quiet_without_dash_still_prints_tsv(self, runner, stub_graph, tmp_path):
        stub_graph()
        out_file = tmp_path / "r.json"
        result = runner.invoke(app, ["analyze", "000155", "--quiet", "--output", str(out_file), "-d", "2026-10-03"])

        assert result.exit_code == 0, result.output
        assert "000155\t2026-10-03\t持有" in result.stdout

    def test_regular_output_writes_the_file(self, runner, stub_graph, tmp_path):
        stub_graph()
        out_file = tmp_path / "r.json"
        result = runner.invoke(app, ["analyze", "000155", "--quiet", "--output", str(out_file)])

        assert result.exit_code == 0, result.output
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert data["_rating"] == "持有"


class TestMcpParsesWhatTheCliWrites:
    def test_mcp_side_reads_rating_from_underscore_key(self, monkeypatch):
        """MCP ``analyze_stock`` 取的键必须是 CLI 真正写出来的那个。"""
        mcp_server = _load_server_module()

        captured = {}

        class _Proc:
            returncode = 0
            stdout = json.dumps(
                {"_rating": "增持", "final_trade_decision": "决策正文", "report_path": "X", "_elapsed_seconds": 12.5},
                ensure_ascii=False,
            ).encode("utf-8")
            stderr = b""

        def _fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return _Proc()

        monkeypatch.setattr(subprocess, "run", _fake_run)
        out = mcp_server.analyze_stock("000155", date="2026-10-03")

        assert out["rating"] == "增持"
        assert out["elapsed_seconds"] == 12.5
        # 必须请求 CLI 把 JSON 打到 stdout，且不能用 text=True 让父进程按 GBK 解码
        assert captured["cmd"][-2:] == ["--output", "-"]
        assert "text" not in captured["kwargs"]

    def test_mcp_decodes_utf8_bytes(self, monkeypatch):
        mcp_server = _load_server_module()

        class _Proc:
            returncode = 0
            stdout = json.dumps({"_rating": "买入"}, ensure_ascii=False).encode("utf-8")
            stderr = b""

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc())
        assert mcp_server.analyze_stock("600519")["rating"] == "买入"
