#!/usr/bin/env bash
# ============================================================
#  run.sh — Unix / macOS / WSL / Git Bash 启动器
#  转发到 launcher.py 菜单
# ============================================================

set -e

# 切到脚本所在目录（项目根）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 优先 python3，回退 python
if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON=python
else
    echo "[错误] 未检测到 Python，请先安装 Python 3.10+ 并加入 PATH"
    exit 127
fi

exec "$PYTHON" launcher.py