"""Global default configuration for AStock Trader."""

import os

DEFAULT_CONFIG = {
    # ── 项目目录 ──────────────────────────────────────────────
    "project_dir": os.path.expanduser("~/.astock_trader"),
    "results_dir": os.path.expanduser("~/.astock_trader/logs"),
    "data_cache_dir": os.path.expanduser("~/.astock_trader/cache"),
    "memory_log_path": os.path.expanduser("~/.astock_trader/memory/trading_memory.md"),
    "memory_log_max_entries": None,
    # ── LLM 配置 ─────────────────────────────────────────────
    "llm_provider": "openai",
    "deep_think_llm": "deepseek-chat",
    "quick_think_llm": "deepseek-chat",
    "backend_url": None,  # 自定义 API 端点，默认 None 使用官方地址
    # ── 运行控制 ──────────────────────────────────────────────
    "checkpoint_enabled": False,
    "output_language": "Chinese",
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    # ── 数据源配置 ────────────────────────────────────────────
    # Tushare 为财务首选（结构化数据），MX 为新闻首选，akshare 提供行情
    "data_vendors": {
        "core_stock_apis": "akshare",  # 行情数据仅 akshare 支持
        "technical_indicators": "akshare",  # 技术指标仅 akshare 支持
        "fundamental_data": "tushare",  # 财务数据首选 Tushare（结构化精准）
        "news_data": "mx",  # 新闻资讯首选妙想（东方财富权威源）
    },
    "data_vendor": None,  # 全局首选供应商（优先级最高），None 则按各分类配置
    "tool_vendors": {},
    # ── 报告产出 ────────────────────────────────────────────
    "report_output_dir": os.environ.get("ASTOCK_REPORT_DIR", ""),  # HTML 报告保存目录（空则不生成）
}
