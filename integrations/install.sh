#!/usr/bin/env bash
# 多宿主插件安装器 — 把 skills/ 注册到 DSH / Codex / zCode / Claude Code。
#
# 用法:
#   ./integrations/install.sh              # 自动探测所有已安装的宿主
#   ./integrations/install.sh dsh codex    # 仅指定宿主
#   ./integrations/install.sh --dry-run    # 只打印将执行的动作
#   DSH_SKILLS_DIR=/path ./integrations/install.sh dsh   # 自定义目标目录
#
# 各宿主的注册方式:
#   - dsh   : 软链 skills/<名>/ 到 "$DSH_SKILLS_DIR"（默认 ~/.dsh/skills），DSH 按 SKILL.md frontmatter 识别
#   - codex : 把每个 SKILL.md 复制为 ~/.codex/prompts/astock-<slug>.md（slash-command 形式调用）
#   - zcode : 软链 skills/<名>/ 到 "$ZCODE_SKILLS_DIR"（默认 ~/.zcode/skills）；无该目录时降级为提示块写入 ~/.zcode/AGENTS.md
#   - claude: 软链 skills/<名>/ 到 "$CLAUDE_SKILLS_DIR"（默认 ~/.claude/skills）
#
# 幂等：重复执行安全；使用 --force 重新覆盖（仅对复制的宿主有效）。

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS_SRC="$REPO_ROOT/skills"
AGENTS_SRC="$REPO_ROOT/AGENTS.md"

FORCE=0
DRY_RUN=0
TARGETS=()
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    --dry-run|--dry-run=|--dryrun) DRY_RUN=1 ;;  # be lenient on typos
    --dry-run*) DRY_RUN=1 ;;
    *) TARGETS+=( "$arg" ) ;;
  esac
done
TARGETS=( "${TARGETS[@]:-}" )

log()  { printf '[install] %s\n' "$*"; }
run()  { if [ "$DRY_RUN" = 1 ]; then log "DRY-RUN: $*"; else "$@"; fi; }

dsh_dir()   { echo "${DSH_SKILLS_DIR:-$HOME/.dsh/skills}"; }
claude_dir(){ echo "${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"; }
zcode_dir() { echo "${ZCODE_SKILLS_DIR:-$HOME/.zcode/skills}"; }
codex_dir() { echo "${CODEX_PROMPTS_DIR:-$HOME/.codex/prompts}"; }

slug() { # 中文目录名 -> ascii slug（无法可靠转写时用 pinyin 缺省表）
  case "$1" in
    智能分析) echo "analysis" ;;
    分析历史) echo "history" ;;
    决策记忆) echo "memory" ;;
    交易配置) echo "config" ;;
    快照跟踪对比) echo "snapshot-tracking" ;;
    复盘深度分析) echo "postmortem" ;;
    龙虎榜解读) echo "lhb-interpretation" ;;
    行业对比解读) echo "industry-comparison" ;;
    *) echo "$1" | tr -c 'a-zA-Z0-9_' '-' ;;
  esac
}

install_dsh() {
  local dir; dir="$(dsh_dir)"
  log "[dsh] -> $dir"
  mkdir -p "$dir"
  for skill_dir in "$SKILLS_SRC"/*/; do
    [ -f "$skill_dir/SKILL.md" ] || continue
    name="$(basename "$skill_dir")"
    link="$dir/astock-$name"
    run ln -sfn "$skill_dir" "$link"
    log "[dsh]   linked astock-$name"
  done
  log "[dsh] 完成。提示：DSH 启动时加载技能，需重启 DSH Web 生效。"
}

install_claude() {
  local dir; dir="$(claude_dir)"
  log "[claude] -> $dir"
  mkdir -p "$dir"
  for skill_dir in "$SKILLS_SRC"/*/; do
    [ -f "$skill_dir/SKILL.md" ] || continue
    name="$(basename "$skill_dir")"
    run ln -sfn "$skill_dir" "$dir/astock-$name"
    log "[claude]   linked astock-$name"
  done
}

install_zcode() {
  local dir; dir="$(zcode_dir)"
  log "[zcode] -> $dir"
  if [ ! -d "$(dirname "$dir")" ] && [ -z "${ZCODE_SKILLS_DIR:-}" ]; then
    # 未安装 zcode：降级只输出说明
    log "[zcode] 未检测到 ~/.zcode，跳过（如需强制安装请设置 ZCODE_SKILLS_DIR）"
    return 0
  fi
  mkdir -p "$dir"
  for skill_dir in "$SKILLS_SRC"/*/; do
    [ -f "$skill_dir/SKILL.md" ] || continue
    name="$(basename "$skill_dir")"
    run ln -sfn "$skill_dir" "$dir/astock-$name"
    log "[zcode]   linked astock-$name"
  done
  # zcode 若无 skills 机制，则把入口提示附加到 ~/.zcode/AGENTS.md
  local agents_zc="$HOME/.zcode/AGENTS.md"
  if [ -f "$agents_zc" ] && ! grep -q "AStock Trading Agents skills" "$agents_zc" 2>/dev/null; then
    run sh -c "printf '\\n## AStock Trading Agents skills\\nskills 目录: $SKILLS_SRC\\n触发词见各 SKILL.md frontmatter description。\\n' >> '$agents_zc'"
  fi
}

install_codex() {
  local dir; dir="$(codex_dir)"
  log "[codex] -> $dir"
  mkdir -p "$dir"
  for skill_dir in "$SKILLS_SRC"/*/; do
    [ -f "$skill_dir/SKILL.md" ] || continue
    name="$(basename "$skill_dir")"
    slug="$(slug "$name")"
    dest="$dir/astock-$slug.md"
    if [ -e "$dest" ] && [ "$FORCE" != 1 ]; then
      log "[codex]   $dest 已存在，跳过（--force 覆盖）"
      continue
    fi
    run cp -f "$skill_dir/SKILL.md" "$dest"
    log "[codex]   prompt astock-$slug.md"
  done
  # AGENTS.md 由 codex 自动读取（本仓库根已含），仅校验其存在
  if [ ! -f "$AGENTS_SRC" ]; then
    log "[codex] 警告: 根目录缺少 AGENTS.md"
  fi
}

# 解析目标
if [ "${#TARGETS[@]}" -eq 0 ] || [ -z "${TARGETS[0]}" ]; then
  TARGETS=( dsh claude codex zcode )
fi

for t in "${TARGETS[@]}"; do
  case "$t" in
    dsh)    install_dsh ;;
    claude) install_claude ;;
    zcode|zcode-cli|zcode_cli) install_zcode ;;
    codex|codex-cli|codex_cli) install_codex ;;
    all) TARGETS=(dsh claude codex zcode); install_dsh; install_claude; install_codex; install_zcode ;;
    *) log "未知宿主: $t（可用: dsh claude codex zcode all）"; exit 1 ;;
  esac
done

log "全部完成。"
