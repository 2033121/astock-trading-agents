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
    "llm_provider": "deepseek",
    "deep_think_llm": "mimo-v2.5-pro",          # 深度推理层：基金经理最终决策
    "heavy_think_llm": "deepseek-v4-pro",        # 重度分析层：多空研究员辩论
    "standard_think_llm": "mimo-v2.5",            # 标准处理层：研究经理+交易员+3风控
    "quick_think_llm": "deepseek-v4-flash",      # 轻量采集层：4分析师+信号处理+报告
    "backend_url": None,  # 自定义 API 端点，默认 None 使用官方地址
    # ── LLM 容错配置 ─────────────────────────────────────────
    "llm_max_retries": 3,               # 最大重试次数
    "llm_retry_base_delay": 4,          # 指数退避基础延迟（秒）
    "llm_retry_max_delay": 60,          # 指数退避最大延迟（秒）
    "circuit_breaker_threshold": 5,     # 熔断器连续失败阈值
    "circuit_breaker_cooldown": 30,     # 熔断器冷却窗口（秒）
    # ── 上下文瘦身 ────────────────────────────────────────────
    "enable_context_slimming": True,    # 按目标节点裁剪报告，降低 token 消耗 ~25%
    # ── Headroom Token 压缩 ───────────────────────────────────
    # 注意：headroom 的 Kompress ML 模型在 Windows + ONNX Runtime 环境下不兼容
    # （int8-wo 量化模型仅支持 4-bit MatMulNBits），默认关闭。
    # 在 macOS/Linux 或 headroom 修复 Windows 支持后可手动开启。
    "enable_headroom_compression": False,  # Headroom 压缩（Windows 暂不可用，默认关闭）
    "headroom_min_tokens": 500,           # 低于此 token 数的消息不压缩
    # ── 向量记忆 ──────────────────────────────────────────────
    "enable_vector_memory": True,       # 索引历史分析案例，语义检索注入 prompt
    "vector_memory_backend": "auto",    # "auto" / "tfidf" / "chroma"
    "vector_memory_dir": None,          # 持久化目录，None 使用 project_dir/vector_memory
    # ── 回测反馈注入 ──────────────────────────────────────────
    # 由 Expert Suite Plugin 生成 backtest_feedback.json，Consumer 模块读取并注入各节点 prompt
    "enable_backtest_feedback": True,   # 总开关（文件不存在时自动降级为无操作）
    "backtest_feedback_path": "",       # 自定义路径，空则使用 project_dir/backtest_feedback.json
    "backtest_feedback_min_verified": 10,  # 最少已验证快照数（质量门禁）
    "backtest_feedback_expiry_days": 90,   # 反馈有效期（天）
    # ── 记忆轮转 ──────────────────────────────────────────────
    "enable_memory_rotation": True,     # 自动轮转旧记忆条目，防止文件无限增长
    "memory_rotation_max_same": 10,     # 同标的保留最多 N 条 resolved 条目
    "memory_rotation_max_cross": 10,    # 跨标的保留最多 N 条 resolved 条目
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
