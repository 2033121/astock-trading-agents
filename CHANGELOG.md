# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- **辩论历史被整体覆盖，导致「一场只有一个辩手的辩论」** (`graph/setup.py` + `agents/utils/agent_states.py`)：``AgentState`` 里的 ``investment_debate_state`` / ``risk_debate_state`` 是嵌套 TypedDict，子字段上标着 ``Annotated[list, _append_str_list]``，但 **LangGraph 不对嵌套结构应用 reducer** —— 已用最小 ``StateGraph`` 实测确认子字典被当作 LastValue 通道，写入即替换。辩论顺序是 ``Bull → Bear → Bull(反驳) → 研究主管``，于是轮到主管时字典里只剩最后一轮多头的写入，``bear_history`` 已被冲掉。实测一次 600519 分析，研究主管在裁决书里写下「（本次空头未提交论据——这是一个必须点破的重大不对称）」并**自己代拟了一段空方立场**，而报告里看不出任何异常。修法是新增 ``_merge_debate()``，让每个辩论节点写出**合并后的完整字典**；风控辩论（激进/保守/中性/裁判）同型修复
- **`get_indicators` 工具封装与实现签名不匹配 —— 技术面指标从首次提交起就没通过** (`agents/utils/core_stock_tools.py` + `technical_indicators_tools.py`)：封装暴露 ``(symbol, start_date, end_date)``，vendor 实现要的是 ``(symbol, indicator, curr_date, look_back_days)``，调用必抛 ``unexpected keyword argument 'start_date'``。``git log`` 确认该签名自 Initial commit 起未变 —— 技术分析师**一次都没拿到过**均线 / MACD / RSI / BOLL，却照常产出技术面结论
- **「操作」字段会被否定句读反** (`agents/utils/rating.py` + `graph/trading_graph.py`)：``_extract_action`` 原实现按刻度表顺序做子串扫描（``for action in ("买入","增持",...): if action in plan``），有两个毛病 —— 按刻度表顺序而非文中出现顺序，且不认否定。交易员写「这不是"买入信号"，而是"布局框架"」会被读成「买入」，方向正好读反并写进记忆日志与 history 摘要。新增 ``extract_action()``：按出现位置排序 → 剔除处在否定小句内的提及 → 取最靠前的一个，一个都不剩时返回 ``None``（不猜）
- **HTML 报告默认不生成** (`default_config.py`)：``report_output_dir`` 缺省是空串，只有显式设了 ``ASTOCK_REPORT_DIR`` 才会有报告，而文档把它写成「可选」—— 实际是静默失效。现在默认生成到 ``<项目根>/reports/``，``ASTOCK_REPORT_DIR`` 仍可覆盖
- **报告耗时永远显示 0.0 秒** (`graph/report_generator.py` + `trading_graph.py`)：耗时回填只替换了 JSON 里的 ``elapsed`` 字段，写死在摘要正文里的那个数字没人管。改用 ``ELAPSED_PLACEHOLDER`` 占位，``_patch_report_elapsed`` 同时回填两处
- **辩论面板与裁判面板逐字重复** (`graph/report_generator.py`)：裁判节点把同一段文本同时写进 ``judge_decision`` 和下一阶段的字段，而面板只取 ``judge_decision``，于是「多空辩论」与「研究主管」完全相同、「风控辩论」与「组合经理」完全相同 —— 辩论过程一个字都看不到。现在辩论面板渲染「双方发言 + 裁判裁决」，摘要表格也改为给出多/空各一句
- **消息清理漏网会让分析师继承上一个分析师的 system prompt** (`graph/setup.py`)：``RemoveMessage`` 列表原用 ``hasattr(m, "id")`` 过滤，``id`` 为 ``None`` 时既清不掉（残留给下一个节点）又可能直接抛错。改为要求 ``id`` 非空，并对漏网条数打 warning
- **`~/.astock_trader` 硬编码在九个模块里** → 收敛到新增的 ``paths.resolve_project_dir()``（`default_config.py`、`cli/main.py`、`trading_graph.py`、`checkpointer.py`、`utils/memory.py`、`backtest_consumer.py`、`monitor/engine.py`、`external_calibration/ledger.py`、`mcp_server.py`）。此前改一次根目录要动九处，漏一处就会出现「报告写在新盘、记忆还在旧盘」的半迁移状态
- **CLI 在收尾打印时因 GBK 编码崩溃，结果 JSON 整个丢失** (`cli/main.py`)：Windows 控制台默认 GBK 且 ``sys.stdout.errors`` 是 ``surrogateescape``，Rich 渲染 ``⚠`` 这类字符时抛 ``UnicodeEncodeError``。实测那次 600519 分析**已经跑完、HTML 报告也写好了**，只在最后写结果时被这行错误打断 —— 几分钟的分析白做。现在启动时把 stdout/stderr 的错误策略放宽为 ``replace``（**不改编码**，避免影响把 CLI 当子进程读输出的调用方）
- **MCP server 用系统区域设置编码输出，中文乱码** (`mcp_server.py`)：``json.dumps(..., ensure_ascii=False)`` 配 Windows 默认 GBK 的 stdout，中文（工具描述、股票名、评级、记忆正文）被编成 GBK 字节，而 MCP 协议规定 UTF-8，客户端解出来是乱码。现在 stdio 显式钉成 UTF-8；`tests/test_mcp_server.py` 的子进程也改为固定 ``encoding="utf-8"``，不再随机器区域设置变红
- **`set_config` 从未被调用，数据层配置全是死的** (`graph/trading_graph.py`)：``dataflows`` 是独立于图模块的全局单例，靠 ``set_config`` 注入，而全仓库**没有任何地方调用它** —— ``get_config()`` 永远返回空 dict。后果静默且严重：``data_vendor``（全局首选数据源）配置形同虚设、路由永远按硬编码顺序走；**凭证只能靠环境变量碰运气**，写在 ``user_config.json`` 里的 Tushare token 根本递不到数据源（实测报告反复写「Tushare token 失效」而 token 是好的）。现在 ``TradingAgentsGraph.__init__`` 构造时推送配置
- **旧 token 一直把新 token 顶掉** (`dataflows/tushare_data.py`)：解析顺序原为 环境变量 → 配置，而环境里留着一个**早已失效的旧 token**，于是用户新写进 ``user_config.json`` 的值永远轮不到，每轮回测都报「您的token不对」。改为 **显式配置 → 环境变量**（配置是更晚、更具体的意图），覆盖发生时记一条日志且不打印任何值；``DEFAULT_CONFIG`` 也不再于 import 时快照环境变量（那会让旧 token 伪装成「用户配置」）
- **大宗交易工具从写下起就没成功过** (`dataflows/eastmoney_news.py` + `dataflows/interface.py` + `agents/utils/news_data_tools.py`)：它调用的 ``ak.stock_dzjy_mingxi`` 与 ``ak.stock_dzjy_detail`` **在 akshare 里都不存在**（实测 ``module 'akshare' has no attribute 'stock_dzjy_mingxi'``），而且路由表把 vendor 标成 ``akshare``，实现却住在 ``eastmoney_news`` —— 双重的对不上。情绪分析师因此长期拿不到大宗数据，只在报告里写一句「数据源异常」。现改用 ``ak.stock_dzjy_mrmx``（东财大宗交易每日明细，需先取全市场再按代码筛），并补上 ``curr_date`` 时点门控（大宗交易逐日公布，分析日之后的成交当时不可知）与 ``InjectedState`` 日期注入；「这只票没有成交」与「取数失败」现在是两句不同的话
- **评级字段与否定句：实盘抓到的误读** (`agents/utils/rating.py`)：一次真实的 000155 分析里，基金经理白纸黑字写「**最终评级 持有（HOLD）**」，解析出来的评级却是「**买入**」—— 因为正文有一句「低估值**不是买入**充分条件」，而旧实现按**刻度表顺序**全文找关键词，「买入」排第一就命中。``extract_rating`` 第二轮改为与 ``extract_action`` 共用同一套判据：**按出现顺序 + 跳过否定小句**。实测同一份决策原文，修复后返回「持有」，与正文一致（此前 ``action`` 字段已修，``rating`` 字段是同型漏网）
- **MCP 旗舰工具 `analyze_stock` 一直是坏的** (`mcp_server.py` + `cli/main.py`)：三个缺陷串在一起 —— ① CLI 把 `--output -` 当成**普通文件名**，于是工作目录里被拉出一个名叫 `-` 的垃圾文件，而调用方永远解析不到 JSON；② MCP 侧用 `text=True` 让父进程按本机 GBK 解码，中文评级与决策正文会整段乱码；③ 就算解析成功，取的键名也不对（CLI 写的是 `_rating`，代码读的是 `rating`）。现约定 `--output -` = **UTF-8 JSON 写到 stdout**，MCP 侧固定按 UTF-8 解码并读 `_rating`。此前测试只覆盖工具名单与快照类工具，从未端到端跑过它
- **CLI `--quiet` 号称输出 TSV，实际不是 TSV** (`cli/main.py`)：那一行走的是 Rich 的 `console.print`，制表符被重排成空格填充，按 `\t` 切分的调用方会解析错。改为直写 `sys.stdout`，说好是 TSV 就真是 TSV
- **文档与实现不符的几处**：`.qoder-plugin/plugin.json`、`AGENTS.md`、`README.md` 都引用了一个**并不存在**的 `skills/复盘深度分析` 目录（已从「活」的清单里移除，并在 README 的 v0.4 历史条目旁标注）；`integrations/README.md` 宣称可用 `ASTOCK_PROGRESS_FILE` 覆盖进度文件路径，而**代码里没有读这个环境变量**（唯一生效的是配置键 `progress_file`）；`mkdocs.yml` 的 nav 把同一个 README.en.md 列了两遍
- **评级解析不出来时报「待复核」，不再静默降级成「持有」** (`agents/utils/rating.py` + `graph/signal_processing.py`)：新增 `extract_rating()`（无法确定返回 `None`）与 `RATING_REVIEW = "待复核"`；`parse_rating()` 保留旧的「总有返回值」语义供历史调用点使用。同时修掉两处误判：标签命中但取值不在五级刻度内（如 `评级: 观望`）不再退到全文搜索，避免从「买入/增持/持有/减持/卖出」刻度说明里捞出一个凭空造的评级；英文关键词改用词干+变形匹配（`buying` 仍识别，`buyer`/`seller` 不再误判）。CLI 评级色、HTML 报告徽章均补上「待复核」样式（上游 #1170）
- **数据源软失败不再阻断 fallback 链** (`dataflows/interface.py` + 新增 `dataflows/errors.py`)：`route_to_vendor` 此前把任何返回值都当成成功直接返回 —— 妙想配额用尽返回 `"[ERROR] ..."` 时，链上的 Tushare / 东方财富 / akshare 根本不会被尝试，Agent 拿到一句错误文本并把它当成数据。现在换源有两个触发条件：抛异常（按 `VendorError` 子类分类）或返回 `[ERROR]` 串。新增 `VendorError` / `NoMarketDataError` / `VendorRateLimitError` / `VendorNotConfiguredError` 层级（类型数量 = 路由层的不同反应数量），缺 key 降为 debug 级日志、限流保持 warning；`mx_data`（状态码 113/114、传输异常）、`tushare_data`（缺 token、积分/频次受限）已迁移为类型化抛错
- **交易员价位锚定** (`agents/trader/trader.py`)：把技术面报告喂给 Trader（此前只给研究方案，入场价/止损价只能靠编），并要求入场价/止损价填**绝对价格**（人民币元）——不填百分比、区间或「现价下方 3%」这类相对描述，换算不出来就留空（上游 #1167 / #1288）
- **裁决纪律** (`agents/managers/research_manager.py` + `portfolio_manager.py`)：明确「证据均衡、互相冲突或信息不足时选『持有』，不要为了显得果断而硬选一个方向」，研究经理另加「评估多空只看论据、不受发言先后顺序影响」。组合经理原结尾「决策应明确、果断」会把模型推向编方向，改为「明确 = 把分歧与不确定性写清楚」

- **前视偏差防护（对齐上游 TradingAgents v0.4.x）**：`--date <历史日期>` 运行时，任何「分析日之后才可知」的信息都不再进入 prompt。判据收敛在新增的 `point_in_time.py`，专题说明见 `docs/前视偏差防护.md`
  - **交易记忆**：resolved 条目新增 `resolved_date`（结局落地的那个交易日），`get_past_context(ticker, as_of=...)` 只放行 `resolved_date <= as_of`；没有该字段的**老条目在 as_of 查询下保守排除**，实时运行（`as_of=None`）行为不变。此前 `get_past_context` 完全不看运行日期，2025 年的分析会读到 2026 年才落地的反思教训（上游 #1251）
  - **向量记忆**：`MarketMemory.search/search_by_ticker` 新增 `as_of`。TF-IDF 后端在**排序前**过滤候选（`top_k` 仍由历史记录填满）；chroma 后端下发 `where={"date": {"$lte": as_of}}` 并在返回后兜底再过滤一次（后端忽略该条件时宁可少返回也不放行未来记录）；「直接扫元数据」的兜底路径同样受门控
  - **反思闭环持有窗口改为按交易日判定**：结算要求已出现 `days + 1` 根**已收盘** K 线，不足则条目保持 pending。原实现用 `timedelta(days=5)` 自然日判定 + `target_idx = min(days, len(df)-1)` 取平仓价，长假期间会把 **1 日收益写成「5日收益」** 并作为教训存入记忆；平仓价一律取严格早于今天的 K 线（当日 K 线可能还在变）；基准拉不到时 `alpha_return` 记为 `None`、文案写「超额未获取」，不再假装超额为 0（上游同类修复）
  - **新闻窗口**：`eastmoney_news` 的两处泄漏修掉 —— `get_news` 日期解析失败时原先 `pass` 返回**全部**新闻，`get_global_news` 原先只在筛选结果非空时才采用过滤、窗口筛空即退回全量。现在统一用 `in_window`，比较**北京时间的日历天**（naive 发布时间按 CST 解释，避免 UTC 偏移 8 小时把「次日凌晨」的稿件漏进窗口）；无发布时间的条目只在实时窗口保留（上游 #1126 / #1220）
  - **基本面当期快照泄漏（A9，上游 #1300）**：`get_fundamentals` / `get_balance_sheet` / `get_cashflow` / `get_income_statement` 四个工具此前**完全不接收分析日**（`curr_date` 标注为 *unused*），历史运行一律拿到「最新财报 + 运行当天市值快照」。难点是**报告期结束 ≠ 可知**：一季报报告期 3-31、最晚 4-30 才披露，直接比报告期最多能放进一个月后的信息。现在按 `report_is_known(period_end, as_of, ann_date=...)` 门控 —— 有公告日期按公告日期精确判定（Tushare `ann_date` / 东财 `NOTICE_DATE`），没有就退回**法定披露截止日**（一季报/年报 4-30、半年报 8-31、三季报 10-31，年报跨次年），认不出报告期列则**整帧剔除**
    - **Tushare**：结构化财报按 `ann_date` 过滤，`daily_basic` 按 `trade_date` 过滤
    - **akshare**：财报/报表按报告期 + 公告日期过滤，滤空时明确写「No report was public as of <日期>；the latest snapshot is withheld」而不是给最新值；「总市值/流通市值/总股本/流通股」这类**运行当天的快照字段**在历史运行下隐去并留下说明（需要价位改用 `get_stock_data` / `get_indicators` 取该日行情）
    - **妙想（MX）**：自然语言查询返回的是渲染好的表格，**没有可判定的报告期字段**，证明不了就不放行 —— 历史运行直接抛 `VendorError`，由路由换到能按报告期过滤的数据源（这也顺带验证了 A8 的换源契约）
    - **运行日期由服务端注入，不交给模型**：四个工具的 `trade_date` 参数改用 `InjectedState("trade_date")` 从图状态注入，**模型看不到也改不了** —— 模型漏填一次，历史运行就退回最新快照，门控必须由运行侧保证而非靠 prompt 提醒
    - **实时运行不门控**：`run_as_of(trade_date)` 仅在分析日**严格早于今天**时返回该日期，否则返回 `None`。实时运行若也按法定截止日卡，会误伤「刚披露但还没到截止日」的报告（9-30 三季报 10-02 披露、截止日却是 10-31）

### Added

- **`docs/Agent接入指南.md`**：把本框架接进各种 AI Agent 宿主的完整说明 —— 三条接入面（CLI 直用 / Skills / MCP）的分工与选型、通用准备（安装、LLM 与数据源凭证的**配置优先**优先级、落盘根、自检）、Claude Code（CLAUDE.md + 技能软链 + `claude mcp add`）、OpenAI Codex CLI（AGENTS.md + `~/.codex/prompts/astock-*.md` slash 命令）、其他 AGENTS.md 宿主（zCode/Cursor/Windsurf/Cline/Amp）、Trae IDE（按路径挂载的 `.trae/rules/`）、Qoder/QoderWork、任意 MCP 宿主（5 工具表 + 配置 JSON + 环境变量 + 依赖边界）、进度面板，附**数据闭环与文件落点**图和已知限制表。`CLAUDE.md` / `AGENTS.md` / `README.md` / `docs/index.md` 同步更新并互相链接
- **`tests/test_cli_stdout_json.py`**（8 项）：把 `--quiet --output -` 的 stdout 契约钉死 —— 整段 stdout 必须是一份可解析的 UTF-8 JSON、不能混进 TSV、不能在 cwd 里留下名叫 `-` 的文件；另含 MCP 侧取键与解码参数的断言
- **`README.md` 新增「AI Agent 接入」章节**与 `docs/Agent接入指南.md` 导航；核心特性补上监控层与 Agent 原生接入两条；测试清单加入 8 个「静默失效」回归护栏文件
- **日线行情三源 fallback + 单位归一化** (`dataflows/akshare_data.py`)：东方财富 ``push2his`` 会按**出口 IP** 在服务端 WAF 层拦截，表现为 TLS 握手成功后连接被重置，实测 UA / Referer / TLS 指纹（curl_cffi impersonate、真 Chrome）**全部无效**（akshare issue #6100 / #6198 / #6561 / #7098）。此前只有一个源，它一挂整条技术面分析就没有输入，而下游照样产出一份措辞确定的报告。现在按 东方财富 → 新浪 → 腾讯 依次尝试，**表头写明实际出数的源**。三个源的列名与单位都不一样，统一归一化为 ``volume(手) / turnover(元)``：新浪 volume 是「股」需 ÷100；腾讯在 akshare 1.18.x 只返回 6 列且 ``amount`` 实为成交量（手）、无成交额，≥1.19 才改为 ``volume(股) + amount(元)`` —— 同一列名跨版本含义不同，按**列名结构**而非版本号判别。三家前复权基准略有差异，故同一序列固定由同一源提供，不做跨源拼接
- **`get_technical_indicators` 真正落地** (`dataflows/akshare_data.py` + 路由表)：此前这个工具与 ``get_indicators`` 重复且签名同样是坏的，docstring 承诺的「均线系统 MA5/10/20、成交量趋势」从未兑现。现在一次返回 MA5/MA10/MA20/MA60 + 成交量及其 5 日均量，附均线排列、价格与 MA20 相对位置、量能放缩的信号解读；区间外历史仅用于均线预热（120 自然日缓冲，覆盖春节等连续休市）
- **Tushare token 可从用户级配置读取** (`dataflows/tushare_data.py`)：解析顺序改为 环境变量 ``TUSHARE_TOKEN`` → 配置 ``tushare_token``，可用 ``astock-trader config --set tushare_token --value <token>`` 写入 ``user_config.json``（仓库之外）。凭证纪律不变：绝不写进仓库
- **统一路径解析** (`paths.py`)：``ASTOCK_HOME`` → ``D:\astock_trader``（Windows 且 D 盘存在）→ ``~/.astock_trader``；``derive_paths()`` 让 user_config.json 里只写 ``project_dir`` 一处，``logs`` / ``reports`` / ``memory`` 等自动跟随，显式写过某个派生键的则以显式值为准
- 新增 9 个测试文件共 164 项：``test_tool_signatures.py``（**结构性**比对每个工具封装与 vendor 的参数名，并正确排除 LangGraph 注入参数 —— 这正是那 600 多项测试漏掉 ``get_indicators`` 的原因）、``test_debate_state_merge.py``（含用最小 StateGraph 钉死「嵌套 reducer 不生效」这一前提）、``test_dataflows_config_wiring.py``（配置必须真的推到数据层、token 优先级）、``test_block_trades.py``、``test_ohlcv_fallback.py``、``test_rating_action.py``（含实盘那条「最终评级持有却解析成买入」的原文）、``test_report_stages.py``、``test_paths.py``。全套 **799 项通过**（原 635 项）、15 项按环境跳过
- **监控层：常驻盯盘 + 规则告警 + 多通道推送** (`monitor/` + `dataflows/realtime_data.py` + `astock-trader watch`)：项目此前完全没有告警能力，"实时"只是 JSONL 进度文件 + 2 秒 meta-refresh 的静态 HTML。现在补上不依赖 LLM、可长时间常驻的一层
  - **实时行情源** (`dataflows/realtime_data.py`)：腾讯 `qt.gtimg.cn` 主源 + 新浪 `hq.sinajs.cn` 兜底，**均免 Key**；解析现价/涨跌幅/换手率/**量比**/振幅/PB/总市值/涨停跌停价。**历史日期硬拒绝** —— 调用方给的 `curr_date` 不等于运行当天即抛 `VendorError`。实时快照无法证明分析日当时可知，喂进 `--date` 回测就是前视偏差，所以这一层直接不给机会。已注册进 `VENDOR_METHODS["get_realtime_quote"]`
  - **规则 DSL** (`monitor/rules.py`)：`change_pct` / `price` / `limit_move` / `near_limit` / `turnover` / `amount` / `volume_ratio` / `amplitude` 八类，声明式配置、支持按标的覆盖；求值器是纯函数（只读行情 dict），可脱离网络单测。没有引入 `durable_rules` 之类的重量级规则引擎——为六个操作符背上 Rete/状态机不划算
  - **轮询引擎** (`monitor/engine.py`)：交易时段门控（周一至周五 9:30-11:30 / 13:00-15:00）、`(标的, 规则)` 冷却去重、取数失败跳过本轮而不退出进程、`on_event` 钩子留给上层触发深度分析。**落盘先于推送**：事件先写 JSONL 台账再发通知，通知超时不会丢告警（这一条来自对 PanWatch 的调研）
  - **通知分发** (`monitor/notify.py`)：console / 通用 webhook / 企业微信 / 钉钉 / 飞书 / Server酱 / PushPlus / Bark，全部走已有的 `requests`，**零新增依赖**；单通道失败只记 warning，不影响其它通道与监控循环
  - **台账** (`monitor/store.py`)：追加式 JSONL + 冷却状态原子落盘（重启不重复喊同一异动）
  - **CLI** `astock-trader watch`：`--once` 核对规则、`--interval` 调间隔、`--cooldown` 调静默窗口、`--all-hours` 关时段门控、`--test-notify` 验通道；配置集中在 `~/.astock_trader/monitor.json`
  - 新增 `tests/test_monitor.py` + `tests/test_realtime_data.py` 共 81 项（规则边界、冷却与重启去重、通道失败隔离、交易时段边界、取数/回调失败下的引擎行为、历史日期门控）
- **GDELT 全球新闻源** (`dataflows/gdelt_data.py`)：免 Key 直连 GDELT 2.0 DOC API，补上"全球事件面"（地缘/灾害/政策/供应链）的空白，作为 `get_global_news` 第三顺位（mx → eastmoney → gdelt）接入路由表。**查询区间上界钉死在分析日 23:59:59**（时点门控）；因 GDELT 对出口 IP 限流"每 5 秒一次"，加客户端节流避免并发自伤。已知限制：DOC API 只索引最近约 3 个月，更早的历史抛 `NoMarketDataError` 换源。新增 `tests/test_gdelt_data.py` 20 项（全 mock，不打外网）
- **`docs/监控层与数据源扩展.md`**：参考产品（TradingVane）的实时链路与数据源拆解、GitHub 生态选型调研（含 PanWatch 架构对照与**许可证风险登记表**：明确不复制 GPL 的 freqtrade/TrendRadar/gdeltPyR，不使用无许可证的 Ashare/Sequoia-X/pytdx）、监控层落地说明与未做清单
- **时间点门控模块** (`point_in_time.py`)：`normalize_date` / `within_as_of` / `in_window` / `window_reaches_present` / `to_local` / `report_is_known` / `statutory_disclosure_deadline` / `run_as_of` + `CST` 常量。保守方向统一为「证明不了它在分析日之前可知，就不放行」；`CST` 用固定 UTC+8 而非 `zoneinfo`（Windows 缺 IANA 数据库时 `ZoneInfo("Asia/Shanghai")` 会直接抛异常）
- **`docs/前视偏差防护.md`**：五道门的判据、数据源错误层级与换源契约、新增数据源检查清单（含财报类「报告期结束 ≠ 可知」一问）、**已知缺口**与上游提交对照表
- 新增 8 个专项测试文件 `tests/test_point_in_time.py`、`test_memory_pointintime.py`、`test_market_memory_pointintime.py`、`test_reflection_holding_window.py`、`test_news_lookahead.py`、`test_fundamentals_pointintime.py`、`test_dataflows_vendor_errors.py`、`test_agent_prompt_grounding.py`，并为评级严格性追加用例；全套 **534 项通过**（原 327 项），`ruff check` + `ruff format --check` 双绿
- **外部校准接入（Headline Arena 试点支撑）** (`external_calibration/` + `scripts/external_calibration.py` + `docs/外部校准接入.md`)：给反思闭环补一份**不由自己运营**的机械结算参照（issue #1）
  - `arena_client.py`：只读 REST 客户端，对接官方公开端点（`/eval/agents/{id}/predictions|calibration|scorecard`，无需登录）；凭据只从环境变量读取、绝不落盘，无凭据时全链路优雅降级为 `None` 且绝不抛异常（网络/HTTP 4xx-5xx/非 JSON/结构异常全部覆盖）；实机验证发现平台前置网关对缺少 `User-Agent` 的请求返回 403，客户端已统一发送
  - `ledger.py`：追加式 JSONL 台账，与内部交易记忆**物理隔离**——构造时即拒绝 `trading_memory.{log,md}` 路径；每条记录带 `source: external_headline_arena` 并整包保留平台原始返回；重复结算幂等，本地判断默认写一次即冻结（须 `--overwrite` 才能修正），保证「提交前的内部判断」事后无法被结算结果反向污染
  - `reconciliation.py`：把「第三方机械结算线」与「提交前冻结的本地镜像线」配对成比对报告（命中率/平均置信度/Brier/方向一致率 + 平台公开校准曲线的分箱偏差），自动标注小样本与低配对覆盖率
  - 题域边界固化为 `ASSET_DOMAIN_BOUNDARY` 并强制出现在每份报告（含 JSON）中：外部结算测的是宏观期货，**不能**作为 A 股个股判断力的裁决
  - 新增 `tests/test_external_calibration.py` 80 项，全套 323 项通过；`ruff check` + `ruff format --check` 双绿
  - 未做（按 issue #1 约定）：自动提交预测（试点期人工提交）、接入反思闭环主流程
- **智能体进度侧边栏面板** (`graph/progress_recorder.py` + `scripts/agent_panel.py`)：
  - `NodeProgressRecorder`（LangChain callback）把每个节点 运行中/完成/失败 事件写入 `<symbol>_<date>_progress.jsonl`（`enable_progress_recorder` 默认开，`progress_file`/结果目录可覆盖），`agent_progress` 也通过 `_emit` 供 CLI 回调转发
  - 适配全部 12 位核心智能体的中文标牌与流水线阶段（AGENT_LABELS），未列出的 ReAct 工具子轮不污染面板
  - `scripts/agent_panel.py`：零依赖生成自刷新 HTML 面板（2s meta refresh），状态色/耗时/焦点高亮/最终评级；DSH 会话可通过 sidebar 打开实时观察，其他宿主浏览器打开即可
  - 新增 `tests/test_progress_panel.py` 6 项（含空运行/未知节点过滤/完整时序），全套 247 项通过
- **多宿主插件集成** (`integrations/install.sh` + `docs/README.md`→`integrations/README.md`)：幂等安装器把 `skills/` 注册到 DSH（软链）、Claude Code（软链）、zCode（软链，未装则跳过）、Codex CLI（SKILL.md → `~/.codex/prompts/astock-<slug>.md` slash 命令，中文技能名映射 ascii slug）；AGENTS.md 增补 Skills 触发词表——AGENTS.md 系宿主零安装即可用；支持 `--dry-run/--force`；沙箱实测四宿主注册成功
## [0.5.0] - 2026-09-10

### Fixed

- **CI lint 与最新版 ruff 对齐**：ruff-action@v3 使用最新 ruff（0.16.x），23 个未格式化文件已统一 `ruff format`，根目录两个遗留 phase-e2e 脚本加入 ruff `exclude`（脚本式导入顺序不适用库 lint）；本地 `ruff check .` + `ruff format --check .` 双绿，241 测试通过

### Changed

- **文档站（GitHub Pages）** (`mkdocs.yml` + `docs/index.md` + `.github/workflows/docs.yml`)：mkdocs-material 主题，导航含中英 README/Token 方案/路线图；推送 master 涉及 README/docs 时自动构建并部署 Pages，`mkdocs build --strict` 本地验证通过；构建产物与同步副本已加入 .gitignore
- **行业对比解读 Skill** (`skills/行业对比解读/SKILL.md`)：基于仓库自带 get_industry_peers/get_industry_chain/get_fundamentals 工具链的相对估值横截面——行业中位 PE/PB、目标分位数定位（含剔除负 PE 的显式规则）、多业务板块分别对标、块效应提示，及"分位数≠估值结论需与竞争格局互证"的解读纪律
- **龙虎榜解读 Skill** (`skills/龙虎榜解读/SKILL.md`)：基于 akshare 实测接口（`stock_lhb_detail_em` / `stock_lhb_stock_detail_em` / `stock_lhb_jgstatistic_em`，列名经 2026-09 实机验证）的龙虎榜→资金信号解读技能：个股榜日席位归因（机构/游资/量化通道）、全市场热力扫描、信号注入 news/sentiment 分析师上下文，含事后披露与"疑似"归因的解读纪律
- **英文精简版 README** (`README.en.md`)：面向国际读者的 condensed guide（架构/评级术语对照表/快速开始/MCP/Token 优化摘要/测试 CI），中文 README 顶部增加语言切换链接；评级体系中文↔英文对照表收录

### Changed

- **辩论不满轮反转保护** (`graph/conditional_logic.py`):
  - 多空辩论结算阈值从 `2 * max_debate_rounds` 调整为 `2 * max_debate_rounds + 1`
  - 新增一条 Bull Researcher 最终反驳轮：`max_debate_rounds=1` 时序为 Bull → Bear → Bull(反驳) → Research Manager，确保裁决前双方论点均获得最后一次回应
  - 同步更新 `tests/test_conditional_logic.py`（186 项测试全部通过）

### Added

- **基金经理决策矩阵（Token 方案策略 2A 收尾）** (`agents/managers/portfolio_manager.py`)：
  - 新增 `_build_decision_matrix()`：在完整上下文前注入确定性 0-token 结构化矩阵——各信息源（研究员/交易员/三派风控/历史记忆）的看多·中性·看空方向分布、分歧点定位与含目标价/止损/仓位的关键数值行
  - `_rating_direction()` 五档评级方向粗分类 + 关键词退化；完整原文仍保留供 deep 模型深推理
  - 新增 `tests/test_pm_matrix.py` 5 项，全套 241 项通过
- **零依赖 MCP stdio 服务器** (`mcp_server.py`)：暴露 `analyze_stock` / `list_snapshots` / `get_snapshot` / `read_recent_memories` / `review_backtest` 五个工具（新增回测复盘：评级-实际行情对照、T+1/5/10/20 追踪与准确率，可选 Markdown 报告）（完整管线触发 + 快照查询 + 反思记忆读取），实现 MCP 握手子集（initialize/tools/list/tools/call/ping），`tests/test_mcp_server.py` 7 项含 stdio 端到端往返；`save_snapshot.py` 的日志路径支持 `ASTOCK_SNAPSHOT_LOG_PATH` 环境变量覆盖
- **节点级语义缓存（Token 方案策略 3）** (`llm_clients/semantic_cache.py`)：
  - `SemanticCache`：TTL（默认 60 分钟）+ LRU（256 条）+ 归一化 key（折叠空白/中英标点）精确命中，可选 difflib 相似度惩罚式近邻命中（阈值 0.92）
  - 挂载于 `GraphSetup._safe_invoke`（研究员/经理/交易员节点收口），默认关闭（`enable_semantic_cache`），覆盖"同股同日重复分析"场景
  - 新增 `tests/test_semantic_cache.py` 8 项测试；仓库全量 ruff check/format 清零（含历史遗留 F541/UP015/I001 等 18 处自动修复），全套 224 项通过
- **研究员报告确定性摘要（Token 方案策略 2A）** (`graph/context_slimmer.py`)：
  - 新增 `_compress_prose()` / `_is_structured_line()`：对超大报告做 0-token 结构化摘要——保留标题、列表行与含数值证据行（`%`/`亿`/`ROE`/`EPS` 等），长段落仅保留首句
  - 接入 `slim_for_researchers` 的 light 压缩路径（当初步压缩后仍占原文 >60% 时启用），峰值压缩目标从 ~20-30% 提升到 ~30-50%
  - 新增 `tests/test_context_digest.py` 5 项测试，全套 216 项通过
- **Token 控制改进方案** (`docs/Token控制改进方案.md`)：基于 12 个开源项目 + 15 篇论文调研的 Token 消耗诊断与分层降耗路线图（P0 分层模型路由 / 极简任务规则引擎等六大策略）
- **统一系统提示词前缀** (`agents/utils/prompt_prefix.py`)：新增 `SYSTEM_PREFIX` 共享常量（A股交易制度 + 分析纪律），全部 11 个 LLM 节点（4 分析师 / 多空研究员 / 3 风控 / 研究经理 / 交易员 / 基金经理）统一前置（Token 方案策略二 B）：
  - 所有节点调用共享同一段固定前缀文本，命中 provider 端 prompt 前缀缓存（DeepSeek 磁盘 KV Cache 折扣约 90%+、OpenAI 50%）
  - 新增 `tests/test_prompt_prefix.py` 防退化护栏（节点接线与顺序断言），测试总数 186 → 211

## [0.4.0] - 2026-06-16

### Added

- **Backtest Feedback Consumer** (`agents/utils/backtest_consumer.py`, 258 lines):
  - `BacktestFeedbackConsumer` class: reads `backtest_feedback.json`, validates schema/expiry/quality gates
  - Per-agent getters with character-budget truncation at sentence boundaries: analysts (120), debaters (100), manager (100), risk (80), PM (150)
  - Three-tier feedback decay: fresh (<90d, 1.0x weight) → warning (90–180d, 0.5x + "衰减中" notice) → expired (>180d, auto-ignore)
  - `decay_state` / `age_days` / `quality_info` properties for logging and debugging
  - Quality gates: `min_total_verified=10`, `schema_version=1`, configurable `decay_warn_days` / `decay_ignore_days`

- **复盘深度分析 Expert Suite Skill** (`skills/复盘深度分析/SKILL.md`):
  - 7-step flow: read snapshots → statistics → quality gate → LLM deep analysis → JSON output → verify → report
  - Outputs `backtest_feedback.json` matching consumer contract (schema_version=1)
  - Integrated into weekly Friday 17:00 cron job alongside `review_backtest.py`

### Fixed

- **past_context Injection Asymmetry** (`graph/setup.py`):
  - Added missing `past_context` to Bear Researcher, Research Manager, Portfolio Manager
  - Added missing `trade_date` to 3 risk analysts (Aggressive/Conservative/Neutral)
  - Root cause: only Bull Researcher and 4 analysts had injection; debate opponent and judge were blind

- **Tracking Interval Calculation** (plugin `scripts/review_backtest.py`):
  - T+N now counts **trading days** instead of calendar days via sorted trading-day index
  - Price data window expanded from 30 to 45 calendar days to cover T+20 trading days
  - Previously T+5/T+10/T+20 collapsed onto adjacent dates due to weekend/holiday gaps

- **Memory Rotation Never Called** (`graph/trading_graph.py`):
  - Added `_apply_rotation()` call after `_store_decision()` to prevent unbounded memory growth
  - Configurable via `enable_memory_rotation`, `memory_rotation_max_same`, `memory_rotation_max_cross`

### Changed

- **Snapshot Confidence Field** (plugin `scripts/save_snapshot.py`):
  - New `confidence: float` field derived from debate consensus (高=0.9, 中=0.6, 低=0.3, absent=0.5)
  - Available for future weighted feedback injection (high-confidence snapshots carry more weight)

- **Prompt Injection Pipeline** (`graph/setup.py`, `graph/trading_graph.py`):
  - All 10 pipeline nodes now receive conditional backtest feedback via `_bt_feedback()` helper
  - `GraphSetup.__init__()` accepts `backtest_consumer` parameter
  - Consumer auto-initialises from config; gracefully degrades to no-op when file missing

- **Default Config** (`default_config.py`):
  - New keys: `enable_backtest_feedback`, `backtest_feedback_path`, `backtest_feedback_min_verified` (10), `backtest_feedback_expiry_days` (90), `backtest_feedback_decay_warn_days` (90), `backtest_feedback_decay_ignore_days` (180), `enable_memory_rotation`, `memory_rotation_max_same` (10), `memory_rotation_max_cross` (10)

### Testing

- 185 total tests (151 original + 34 backtest consumer tests)
- `test_backtest_consumer.py`: 34 tests across 8 classes (loading, quality gate, schema, expiry, getters, truncation, quality info, decay tiers)

## [0.3.0] - 2026-06-13

### Added

- **LLM Resilience Layer** (`llm_clients/resilience.py`):
  - `ResilientInvoker` wrapping 8 non-ReAct `llm.invoke()` calls with Tenacity retry (3x exponential backoff 4s→60s) + 3-state circuit breaker (5 failures → OPEN → 30s cooldown)
  - `_safe_invoke()` graceful degradation to raw invoke when circuit breaker is open
  - Headroom v0.25.0 Library mode integration: `_compress_messages()` compresses messages before LLM calls, saving 60-95% tokens on long prompts
  - Configurable via `llm_max_retries`, `circuit_breaker_threshold`, `circuit_breaker_cooldown`, `enable_headroom_compression`, `headroom_min_tokens`

- **Analyst Structured Output** (`agents/schemas.py`):
  - 5 Pydantic v2 models: `MarketSignal`, `SentimentSignal`, `NewsSignal`, `FundamentalSignal`, `AnalystConsensus`
  - 4 robust parsers: JSON → markdown block → brace matching + CJK/EN aliases → free-text regex fallback

- **Four-Tier Model Allocation** (`graph/setup.py`):
  - New `heavy_think_llm` config key; 4 tiers: Deep (PM only) → Heavy (bull/bear debate) → Standard (research mgr + trader + 3 risk) → Quick (4 analysts + auxiliary)
  - Each tier independently auto-routes to the correct LLM provider via `_MODEL_PREFIX_MAP`

- **Reflection Loop** (`graph/trading_graph.py`):
  - `_resolve_pending_memory()`: filters ≥5-day pending entries → `_fetch_actual_returns()` via akshare → `_fetch_benchmark_return()` (CSI300) → Reflector generates LLM reflection → `batch_update_with_outcomes()` writes back to memory

- **Smart Backtesting** (`scripts/review_backtest.py`):
  - Multi-dimensional scoring: direction (40%) + magnitude (25%) + timing (15%) + assumption validation (20%)
  - `recognize_patterns()`: detects rating bias, magnitude bias, direction bias
  - `generate_strategy_feedback()`: actionable feedback for prompt injection

- **Context Slimming** (`graph/context_slimmer.py`):
  - Per-node report trimming: PM keeps conclusions (~60-70% compression), risk keeps risk paragraphs (~40-50%), researchers keep evidence (~20-30%), trader no trimming
  - `_gather_reports_for(state, target_node)` replaces all 8 `_gather_reports()` calls
  - Configurable via `enable_context_slimming` (default: True)

- **Vector Memory** (`memory/market_memory.py`):
  - Pure Python TF-IDF bigram engine (ChromaDB optional)
  - `AnalysisRecord` dataclass + `_TfIdfIndex` backend + `MarketMemory` public API
  - Pre-analysis: semantic search top-3 injected into prompt; Post-analysis: auto-indexed with pickle+JSON persistence
  - Configurable via `enable_vector_memory`, `vector_memory_backend`, `vector_memory_dir`

### Changed

- `GraphSetup.__init__()` now accepts `context_slimming` parameter
- `_create_llms()` returns 4-tuple (deep, heavy, standard, quick) instead of 3-tuple
- `default_config.py`: added `heavy_think_llm`, resilience config keys, headroom config, context slimming, vector memory config

### Testing

- 276 total tests (151 original + 125 new phase tests)
- `test_phase1.py`: 16 tests (resilience, schemas, parsers, config)
- `test_phase2.py`: 60 tests (4-tier models, reflection, snapshots, backtesting)
- `test_phase3.py`: 49 tests (context slimming, vector memory, pipeline integration)

## [0.1.0] - 2026-06-10

### Added

- **Core Pipeline**: LangGraph-based multi-agent analysis framework with 15 AI roles
  - 4 parallel analysts (market, news, social media, fundamentals) with ReAct tool loops
  - Bull/Bear investment debate with configurable rounds
  - Research Manager synthesizing debate into structured investment plan
  - Trader converting plans into executable trading strategies
  - 3-way risk debate (aggressive/conservative/neutral) with configurable rounds
  - Portfolio Manager producing final investment decision
  - Report Generator creating interactive HTML reports
- **Multi-Source Data Layer**: 3-level vendor fallback system
  - akshare for market data and technical indicators
  - Tushare Pro for financial statements and capital flow
  - EastMoney MX for news and real-time quotes
- **5-Level Rating System**: 买入/增持/持有/减持/卖出 with structured extraction
- **Decision Memory**: Trading memory log with pending/resolved lifecycle and delayed reflection
- **LLM Flexibility**: OpenAI-compatible client supporting 9 providers (OpenAI, DeepSeek, Qwen, GLM, Ollama, OpenRouter, SiliconFlow, Together, Groq)
- **CLI**: Typer-based CLI with analyze, history, memory, and config commands
- **QoderWork Plugin**: 4 integrated skills (智能分析, 分析历史, 决策记忆, 交易配置)
- **AI Editor Integration**: Project instructions for Claude Code (`CLAUDE.md`), OpenAI Codex (`AGENTS.md`), and Trae IDE (`.trae/rules/`)
- **Testing**: 151 unit tests covering schemas, conditional logic, signal processing, memory, data routing, and agent factories

[0.5.0]: https://github.com/2033121/astock-trading-agents/releases/tag/v0.5.0
[0.4.0]: https://github.com/2033121/astock-trading-agents/releases/tag/v0.4.0
[0.3.0]: https://github.com/2033121/astock-trading-agents/releases/tag/v0.3.0
[0.1.0]: https://github.com/2033121/astock-trading-agents/releases/tag/v0.1.0
