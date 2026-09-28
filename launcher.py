"""
launcher.py — 应急智航 启动器
==========================

跨平台菜单驱动启动器；避免记忆 pip / streamlit / unittest 命令。

用法：
    python launcher.py

菜单：
    1  安装依赖 (pip install -r requirements.txt)
    2  启动主应用 (streamlit run app.py)
    4  运行单元测试 (python -m unittest discover -s tests -v)
    5  运行全部测试 + 启动主应用（推荐新机器一键）
    0  退出

设计原则：
- 仅做命令行包装，不修改任何业务代码
- 所有子命令的当前工作目录固定为项目根目录（避免路径漂移）
- 退出码透传；Ctrl+C 安全退出
- 跨平台：Windows / macOS / Linux 均可

可被下列包裹脚本调用：
- run.bat    (Windows 资源管理器双击)
- run.sh     (Unix / Git Bash / WSL)
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Optional, Tuple


# ===================== 终端编码 =====================
# Windows 默认 GBK 终端无法输出项目名里的非中断连字符 U+2011；
# 优先尝试 utf-8，失败则降级为系统默认并使用 errors="replace" 输出。

def _configure_stdio_encoding() -> None:
    """将 stdout/stderr 重编为 UTF-8；Windows 旧终端无法切换时回退。"""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            # 老版本 Python 或已被替换；保持现状
            pass


_configure_stdio_encoding()


# ===================== 模块常量 =====================

ROOT: Path = Path(__file__).resolve().parent
REQUIREMENTS: Path = ROOT / "requirements.txt"
APP_ENTRY: str = "app.py"
TESTS_DIR: str = "tests"
PYTHON: str = sys.executable or "python"

# 启动 streamlit 时附加的参数：跳过"邮箱登记 onboarding wizard"，
# 避免首次启动被卡在 Email: 提示符。
STREAMLIT_EXTRA_ARGS: Tuple[str, ...] = (
    "--server.headless", "true",                # 不自动打开浏览器（用户自行访问 http://localhost:8501）
    "--server.showEmailPrompt", "false",        # 跳过首次启动的邮箱询问
    "--browser.gatherUsageStats", "false",      # 不上报匿名统计
)


# ===================== 终端辅助 =====================

def _clear_screen() -> None:
    """跨平台清屏。"""
    cmd = "cls" if platform.system() == "Windows" else "clear"
    os.system(cmd)


def _pause(message: str = "按 Enter 继续...") -> None:
    """跨平台暂停；EOF / Ctrl+C 直接返回。"""
    try:
        input(f"\n{message}")
    except (EOFError, KeyboardInterrupt):
        print()


def _run(cmd: List[str], *, stdin: Optional[int] = None) -> int:
    """在项目根目录执行命令；透传 stdout/stderr 与退出码。

    Args:
        cmd:    命令及参数列表。
        stdin:  subprocess.DEVNULL / subprocess.PIPE / None。
                默认 None（继承父进程）。启动 streamlit 时必须显式传 DEVNULL，
                否则 streamlit 会把父进程 stdin 当作 TTY，第一次启动进入
                "邮箱登记 onboarding wizard"，阻塞在 Email: 提示符。
    """
    try:
        return subprocess.run(cmd, cwd=str(ROOT), stdin=stdin).returncode
    except KeyboardInterrupt:
        print("\n[中断] 子进程被 Ctrl+C 终止")
        return 130
    except FileNotFoundError as exc:
        print(f"[错误] 找不到可执行文件: {exc}")
        return 127


# ===================== 菜单动作 =====================

def action_install_deps() -> None:
    """1: 安装依赖。"""
    print(f"\n>>> 正在安装依赖 ({REQUIREMENTS.name})")
    if not REQUIREMENTS.is_file():
        print(f"[警告] 未找到 {REQUIREMENTS}，直接安装 streamlit 默认版本")
        rc = _run([PYTHON, "-m", "pip", "install", "streamlit"])
    else:
        rc = _run([PYTHON, "-m", "pip", "install", "-r", str(REQUIREMENTS)])
    print(f"\n>>> 退出码: {rc}", "✓ 依赖已就绪" if rc == 0 else "✗ 安装失败")
    _pause()


def action_run_app() -> None:
    """2: 启动主应用 streamlit run app.py。"""
    target = ROOT / APP_ENTRY
    if not target.is_file():
        print(f"[错误] 未找到 {APP_ENTRY}")
        _pause()
        return
    print(f"\n>>> 启动主应用: streamlit run {APP_ENTRY}")
    print(">>> (Ctrl+C 退出 Streamlit 后回到菜单)")
    print(">>> 浏览器请手动访问 http://localhost:8501")
    # 关掉 stdin + 跳过 onboarding wizard：streamlit 检测不到 TTY 也拿到 headless/showEmailPrompt 参数，
    # 直接启动 app，否则会卡在 Email: 提示符。
    _run(
        [PYTHON, "-m", "streamlit", "run", APP_ENTRY, *STREAMLIT_EXTRA_ARGS],
        stdin=subprocess.DEVNULL,
    )
    _pause()


def action_run_tests() -> None:
    """4: 运行单元测试。"""
    tests_path = ROOT / TESTS_DIR
    if not tests_path.is_dir():
        print(f"[错误] 未找到测试目录 {TESTS_DIR}/")
        _pause()
        return
    print(f"\n>>> 运行测试: python -m unittest discover -s {TESTS_DIR} -v")
    rc = _run([PYTHON, "-m", "unittest", "discover", "-s", TESTS_DIR, "-v"])
    print(f"\n>>> 退出码: {rc}", "✓ 全部通过" if rc == 0 else "✗ 存在失败用例")
    _pause()


def action_full_check() -> None:
    """5: 一键体检：装依赖 → 跑测试 → 启动主应用。"""
    action_install_deps()
    action_run_tests()
    action_run_app()


def action_exit() -> None:
    """0: 退出。"""
    print("\n再见。")
    sys.exit(0)


# ===================== 菜单定义 =====================

MENU: List[Tuple[str, str, Callable[[], None]]] = [
    ("1", "安装依赖 (pip install -r requirements.txt)", action_install_deps),
    ("2", "启动主应用 (streamlit run app.py)",            action_run_app),
    ("4", "运行单元测试 (unittest discover -s tests)",   action_run_tests),
    ("5", "一键体检 (装依赖 + 跑测试 + 启应用)",          action_full_check),
    ("0", "退出",                                          action_exit),
]


# ===================== 主循环 =====================

def _print_menu() -> None:
    print("=" * 64)
    print("  应急智航 — 无人机物资调度仿真系统  启动器")
    print(f"  Python : {sys.version.split()[0]}")
    print(f"  平台   : {platform.system()} {platform.release()}")
    print(f"  工作目录: {ROOT}")
    print("=" * 64)
    for key, label, _ in MENU:
        print(f"  [{key}] {label}")
    print("-" * 64)


def main() -> None:
    """启动器主循环。"""
    while True:
        _clear_screen()
        _print_menu()
        try:
            choice = input("选择 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            action_exit()

        matched = False
        for key, _, fn in MENU:
            if key == choice:
                fn()
                matched = True
                break

        if not matched and choice:
            print(f"\n[!] 未知选项: {choice!r}")
            _pause()


if __name__ == "__main__":
    main()
