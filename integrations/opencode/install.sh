#!/usr/bin/env bash
# 安装 learn-atlas 的 OpenCode 集成：skill + 会话插件 + 本地配置。
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
OPENCODE_DIR="$CONFIG_HOME/opencode"
SKILL_DIR="$OPENCODE_DIR/skills/learn"
PLUGIN_DIR="$OPENCODE_DIR/plugins"
CONFIG_PATH="$OPENCODE_DIR/learn-atlas.json"

log() {
  printf '%s\n' "$*"
}

fail() {
  printf '错误：%s\n' "$*" >&2
  exit 1
}

command -v python3 >/dev/null 2>&1 || fail "需要 Python 3"
command -v git >/dev/null 2>&1 || fail "需要 Git"
[ -f "$REPO_ROOT/knowledge/_labels.json" ] || fail "$REPO_ROOT 不像 learning-atlas 仓库"
git -C "$REPO_ROOT" rev-parse --git-dir >/dev/null 2>&1 || fail "$REPO_ROOT 不是 Git 仓库"

mkdir -p "$SKILL_DIR/scripts" "$PLUGIN_DIR" "$OPENCODE_DIR"

cp "$SCRIPT_DIR/skills/learn/SKILL.md" "$SKILL_DIR/SKILL.md"
cp "$SCRIPT_DIR/skills/learn/scripts/learn.py" "$SKILL_DIR/scripts/learn.py"
chmod 755 "$SKILL_DIR/scripts/learn.py"
cp "$SCRIPT_DIR/plugin/learn-atlas.ts" "$PLUGIN_DIR/learn-atlas.ts"

REPO_ROOT="$REPO_ROOT" CONFIG_PATH="$CONFIG_PATH" python3 - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["CONFIG_PATH"])
config = {}
if path.exists():
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            config = loaded
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"无法读取 {path}: {exc}")

config["repo"] = os.environ["REPO_ROOT"]
config.setdefault("autoPush", False)
path.write_text(
    json.dumps(config, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
PY

log ""
log "learn-atlas 已安装："
log "  skill   $SKILL_DIR"
log "  plugin  $PLUGIN_DIR/learn-atlas.ts"
log "  config  $CONFIG_PATH"
log "  repo    $REPO_ROOT"
log ""
log "在 OpenCode 中执行 /reload（或重启），然后："
log "  /learn 了解大模型的 logits 是什么"
log ""
log "默认只提交到本地；审核后执行 /learn publish 推送。"
log "其他命令：/learn status · /learn publish · /learn stop"
