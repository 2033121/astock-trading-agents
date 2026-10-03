"""配置必须真的推送到数据层。

``dataflows`` 是独立于图模块的**全局单例**，靠 ``set_config`` 注入。此前没有任何
地方调用它，于是 ``get_config()`` 永远返回空 dict —— 后果是静默的：

* ``data_vendor``（全局首选数据源）配置形同虚设，路由永远按硬编码顺序走；
* 凭证只能靠环境变量碰运气 —— 写在 ``user_config.json`` 里的 Tushare token
  **完全走不到数据源**，实测表现为报告里写「Tushare token 失效」，而 token 其实
  是好的、只是没人把它递下去。

这个文件把「图构造时推送配置」这件事钉住。
"""

import pytest

from astock_trader.dataflows.config import get_config, set_config


@pytest.fixture(autouse=True)
def _restore_global_config():
    """``get_config()`` 是全局单例，用例之间必须隔离。"""
    import copy

    before = copy.deepcopy(get_config())
    yield
    set_config(before)


def _build_graph(**overrides):
    from astock_trader.graph.trading_graph import TradingAgentsGraph

    config = {
        "project_dir": overrides.pop("project_dir", ""),
        "enable_vector_memory": False,
        "enable_backtest_feedback": False,
        "checkpoint_enabled": False,
        "output_language": "Chinese",
    }
    config.update(overrides)
    return TradingAgentsGraph(config=config)


class TestConfigIsWired:
    def test_graph_push_populates_the_singleton(self, tmp_path):
        _build_graph(project_dir=str(tmp_path), tushare_token="tok-from-config")

        cfg = get_config()
        assert cfg, "get_config() 仍是空 dict —— 配置没有被推送到数据层"
        assert cfg.get("tushare_token") == "tok-from-config"

    def test_unknown_vendor_preference_survives(self, tmp_path):
        _build_graph(project_dir=str(tmp_path), data_vendor="tushare")
        assert get_config().get("data_vendor") == "tushare"

    def test_token_reaches_tushare_resolver(self, tmp_path, monkeypatch):
        """端到端：配置里的 token 必须能被 tushare_data 取到。"""
        monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
        from astock_trader.dataflows import tushare_data

        _build_graph(project_dir=str(tmp_path), tushare_token="tok-from-config")
        assert tushare_data._get_token() == "tok-from-config"

    def test_explicit_config_token_beats_stale_env(self, tmp_path, monkeypatch):
        """显式配置必须赢过环境变量 —— 环境里常留着已失效的旧 token。

        实测事故：环境里是个过期的 token，用户把新 token 写进了 user_config.json，
        但 env 优先，于是**每一轮分析都报「token 失效」**，而新 token 其实是好的。
        """
        monkeypatch.setenv("TUSHARE_TOKEN", "stale-from-env")
        from astock_trader.dataflows import tushare_data

        _build_graph(project_dir=str(tmp_path), tushare_token="fresh-from-config")
        assert tushare_data._get_token() == "fresh-from-config"

    def test_env_used_when_nothing_configured(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TUSHARE_TOKEN", "tok-from-env")
        from astock_trader.dataflows import tushare_data

        _build_graph(project_dir=str(tmp_path))
        assert tushare_data._get_token() == "tok-from-env"

    def test_missing_token_is_a_typed_error(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
        from astock_trader.dataflows import tushare_data
        from astock_trader.dataflows.errors import VendorNotConfiguredError

        _build_graph(project_dir=str(tmp_path))
        with pytest.raises(VendorNotConfiguredError):
            tushare_data._get_token()

    def test_default_config_does_not_snapshot_env(self, monkeypatch):
        """DEFAULT_CONFIG 不该在 import 时把环境变量烤进去。

        烤进去的后果：旧 token 会伪装成「用户显式配置」，永远盖过用户在
        user_config.json 里新写的值。
        """
        from astock_trader.default_config import DEFAULT_CONFIG

        assert DEFAULT_CONFIG["tushare_token"] == ""
