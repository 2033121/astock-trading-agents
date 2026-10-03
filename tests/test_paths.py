"""落盘路径解析 —— 所有输出目录必须从同一个根派生。

改动前 ``~/.astock_trader`` 硬编码在九个模块里，改根要动九处，漏一处就是
「报告写在新盘、记忆还在旧盘」的半迁移状态。这里锁住解析顺序与派生关系。
"""

import os
from pathlib import Path

import pytest

from astock_trader.default_config import DEFAULT_CONFIG, derive_paths
from astock_trader.paths import ENV_HOME, project_dir, project_path, resolve_project_dir


class TestResolveProjectDir:
    def test_env_override_wins(self, monkeypatch, tmp_path):
        monkeypatch.setenv(ENV_HOME, str(tmp_path / "custom"))
        assert resolve_project_dir() == os.path.abspath(str(tmp_path / "custom"))

    def test_env_override_expands_user(self, monkeypatch):
        monkeypatch.setenv(ENV_HOME, "~/astock-home")
        assert resolve_project_dir() == os.path.abspath(os.path.join(os.path.expanduser("~"), "astock-home"))

    def test_blank_env_is_ignored(self, monkeypatch):
        # 空串（设置了但没值）不能当成有效覆盖
        monkeypatch.delenv(ENV_HOME, raising=False)
        baseline = resolve_project_dir()
        monkeypatch.setenv(ENV_HOME, "   ")
        assert resolve_project_dir() == baseline

    def test_default_is_absolute_and_stable(self, monkeypatch):
        monkeypatch.delenv(ENV_HOME, raising=False)
        resolved = resolve_project_dir()
        assert os.path.isabs(resolved)
        assert resolve_project_dir() == resolved  # 纯函数，无副作用

    def test_prefers_d_drive_when_present(self, monkeypatch):
        monkeypatch.delenv(ENV_HOME, raising=False)
        expected_d = os.path.abspath("D:\\astock_trader")
        if os.path.isdir(os.path.dirname(expected_d)):
            assert resolve_project_dir() == expected_d
        else:
            # 没有 D 盘（Linux/macOS/CI）时必须退回主目录，不能凭空造 D:\ 路径
            assert resolve_project_dir() == os.path.join(os.path.expanduser("~"), ".astock_trader")


class TestProjectPath:
    def test_joins_under_root(self, monkeypatch, tmp_path):
        monkeypatch.setenv(ENV_HOME, str(tmp_path))
        assert project_path("reports") == str(tmp_path / "reports")

    def test_multi_part(self, monkeypatch, tmp_path):
        monkeypatch.setenv(ENV_HOME, str(tmp_path))
        assert project_path("memory", "trading_memory.md") == str(tmp_path / "memory" / "trading_memory.md")

    def test_project_dir_alias(self, monkeypatch, tmp_path):
        monkeypatch.setenv(ENV_HOME, str(tmp_path))
        assert project_dir() == resolve_project_dir()


_REPORT_ENV_SET = pytest.mark.skipif(
    bool(os.environ.get("ASTOCK_REPORT_DIR")),
    reason="本机设置了 ASTOCK_REPORT_DIR，默认报告目录会被它覆盖",
)


class TestDerivedConfig:
    @_REPORT_ENV_SET
    def test_defaults_derive_from_project_dir(self):
        root = DEFAULT_CONFIG["project_dir"]
        assert DEFAULT_CONFIG["results_dir"] == os.path.join(root, "logs")
        assert DEFAULT_CONFIG["report_output_dir"] == os.path.join(root, "reports")

    @_REPORT_ENV_SET
    def test_report_dir_defaults_to_project_subdir(self):
        # 旧默认是空串 —— 于是**默认根本不生成报告**。现在默认就写。
        assert DEFAULT_CONFIG["report_output_dir"]
        assert Path(DEFAULT_CONFIG["report_output_dir"]).name == "reports"

    def test_custom_project_dir_pulls_derived_paths(self, tmp_path):
        cfg = derive_paths({"project_dir": str(tmp_path)})
        assert cfg["results_dir"] == str(tmp_path / "logs")
        assert cfg["report_output_dir"] == str(tmp_path / "reports")
        assert cfg["memory_log_path"] == str(tmp_path / "memory" / "trading_memory.md")

    def test_explicit_derived_key_is_respected(self, tmp_path):
        # 显式把报告放到另一个盘时，不能被 project_dir 覆盖回去
        cfg = derive_paths({"project_dir": str(tmp_path), "report_output_dir": "E:\\somewhere\\reports"})
        assert cfg["report_output_dir"] == "E:\\somewhere\\reports"
        assert cfg["results_dir"] == str(tmp_path / "logs")

    def test_empty_values_are_filled(self, tmp_path):
        cfg = derive_paths({"project_dir": str(tmp_path), "results_dir": ""})
        assert cfg["results_dir"] == str(tmp_path / "logs")

    def test_report_env_override_beats_derivation(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ASTOCK_REPORT_DIR", str(tmp_path / "elsewhere"))
        cfg = derive_paths({"project_dir": str(tmp_path / "root")})
        assert "report_output_dir" not in cfg  # 交给 DEFAULT_CONFIG 里的环境变量分支


@pytest.mark.parametrize("key", ["project_dir", "results_dir", "report_output_dir", "memory_log_path"])
def test_config_paths_are_absolute(key):
    assert os.path.isabs(DEFAULT_CONFIG[key])
