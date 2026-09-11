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
