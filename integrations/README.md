# 多宿主插件集成

把 `skills/` 与分析入口同时注册到多种 Agent 宿主，按情况二选一或全装：

| 宿主 | 注册方式 | 目标目录 |
|------|----------|----------|
| DSH | 软链 `skills/<名>`（按 SKILL.md frontmatter 识别） | `~/.dsh/skills/`（`DSH_SKILLS_DIR` 可覆盖） |
| Claude Code | 软链 `skills/<名>` | `~/.claude/skills/` |
| Codex CLI | 每个 SKILL.md 复制为 `~/.codex/prompts/astock-<slug>.md`（slash-command 调用，中文技能名自动映射 ascii slug） | `~/.codex/prompts/` |
| zCode | 同 DSH 软链至 `~/.zcode/skills/`；未安装则跳过 | `~/.zcode/skills/` |
| Qoder | 原生 `.qoder-plugin/plugin.json`（保留不动） | 仓库内 |

## 使用

```bash
./integrations/install.sh             # 探测已装宿主并注册（幂等）
./integrations/install.sh dsh codex   # 只装指定宿主
./integrations/install.sh --dry-run   # 预览动作
./integrations/install.sh --force     # 覆盖已复制的 codex prompts
```

## AGENTS.md 通用入口

根目录 `AGENTS.md`（Codex / zCode 自动读取）包含 Commands / Structure /
**Skills 触发词表**——任何以 AGENTS.md 为约定的宿主无需安装即可使用技能说明；
DSH 与 Claude Code 则通过上面的软链获得技能加载。

## 注意

- DSH 侧：技能在 DSH Web 启动时加载，安装后需重启 DSH 生效。
- zCode 的技能机制以 `~/.zcode/skills` 在宿主中的实际约定为准；如你的 zCode
  版本使用其他目录，用 `ZCODE_SKILLS_DIR=...` 覆盖即可，无需改脚本。


## 智能体进度侧边栏面板 (v0.5 面板增强)

运行 `astock-trader analyze` 时默认在 results 目录生成
`<symbol>_<date>_progress.jsonl`（可 `progress_file` / `ASTOCK_PROGRESS_FILE` 覆盖），
记录 12 个智能体的 运行中/完成/失败 事件（主持人匹配各智能体的中文标牌）。

任何宿主实时观察：

```bash
python3 scripts/agent_panel.py <results_dir>/600519_20260911_progress.jsonl
# -> 同目录 agent_panel.html，2 秒自刷新
```

- **DSH**：分析会话里 `sidebar_open` 该 `agent_panel.html`（或直接拖进侧边栏），流水线跑的每一步都能在侧边栏看到哪个智能体在运行、谁失败、最终评级。
- **Codex / zCode / Claude**：运行分析后把 HTML 打开浏览器；或在 AGENTS.md 会话里让智能体"监控 <progress>.jsonl"。
- 适配规则：面板按 `progress_recorder.AGENT_LABELS` 映射显示；未列出的节点（如 tools 子轮）不渲染，保证卡片与真实分析师一一对应。
