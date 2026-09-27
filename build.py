"""PyInstaller 打包脚本（S5 模块化分发）：
  WindAnaly.exe（引导桩，稳定）+ _internal/（第三方运行时，少变）
  + app/（业务代码 .pyc，常变）+ updater.exe（独立更新器）

日常发版增量包只含 app/*.pyc 与 data/app_version.txt，KB~MB 级；
exe/_internal 仅在依赖集合变化时进补丁。

用法（在 venv 中）：
    pip install pyinstaller
    python build.py            # 打包主程序 + 更新器
    python build.py --updater  # 只重建更新器

发布物：
    dist/WindAnaly/WindAnaly.exe        主程序（onedir 文件夹）
    dist/WindAnaly/updater.exe          独立更新器（随主程序放同一目录）
  发布时用 tools/release.py 出完整包/增量包/索引。
"""
from __future__ import annotations

import ast
import os
import py_compile
import shutil
import subprocess
import sys

from core.version import VERSION

ROOT = os.path.dirname(os.path.abspath(__file__))

# 打包进运行时的业务代码（编译为 app/ 下 .pyc）
APP_MODULES = ['app.py', 'windanaly.py']
APP_PKGS = ['core', 'ui', 'updater']

# 运行时必须排除的 pandas 可选依赖与开发工具
EXCLUDES = [
    'matplotlib', 'numba', 'llvmlite', 'sqlalchemy', 'lxml', 'PIL',
    'psycopg2', 'psycopg_binary', 'pytest', 'tkinter',
]
# 本地业务包（这些进 app/ 层，绝不打进运行时）
LOCAL_PKGS = {'app', 'windanaly', 'core', 'ui', 'updater', 'tools', 'tests'}


def _data(src: str, dst: str) -> str:
    """构造 --add-data 参数：源路径;目标目录。"""
    return f"{os.path.join(ROOT, src)}{os.pathsep}{dst}"


def _scan_hidden_imports() -> list[str]:
    """静态扫描业务源码的全部 import（含函数级），返回第三方/标准库
    顶层模块名——模块化打包下运行时分析不到业务码，依赖必须显式声明。"""
    tops: set[str] = set()
    files = [os.path.join(ROOT, m) for m in APP_MODULES]
    for pkg in APP_PKGS:
        for r, d, fs in os.walk(os.path.join(ROOT, pkg)):
            d[:] = [x for x in d if x != '__pycache__']
            files += [os.path.join(r, f) for f in fs if f.endswith('.py')]
    for p in files:
        tree = ast.parse(open(p, encoding='utf-8').read())
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                for a in n.names:
                    tops.add(a.name.split('.')[0])
            elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                tops.add(n.module.split('.')[0])
    return sorted(t for t in tops
                  if t not in LOCAL_PKGS and t not in EXCLUDES)


def _compile_app_layer(dist_dir: str) -> None:
    """业务源码 → dist/WindAnaly/app/ 下的无源码 .pyc（保持包结构）。"""
    app_dir = os.path.join(dist_dir, 'app')
    shutil.rmtree(app_dir, ignore_errors=True)
    count = 0

    def compile_to(src: str, dst: str) -> None:
        nonlocal count
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        py_compile.compile(src, cfile=dst, doraise=True)
        count += 1

    for m in APP_MODULES:
        compile_to(os.path.join(ROOT, m),
                   os.path.join(app_dir, m[:-3] + '.pyc'))
    for pkg in APP_PKGS:
        for r, d, fs in os.walk(os.path.join(ROOT, pkg)):
            d[:] = [x for x in d if x != '__pycache__']
            for f in fs:
                if f.endswith('.py'):
                    rel = os.path.relpath(os.path.join(r, f), ROOT)
                    compile_to(os.path.join(ROOT, rel),
                               os.path.join(app_dir, rel[:-3] + '.pyc'))
    print(f"业务代码层：app/ 下 {count} 个 .pyc")


def build_app() -> None:
    # ---- 1) 桩目录：只放引导桩，防止 modulegraph 把业务码打进 exe ----
    stage = os.path.join(ROOT, 'build', 'stage')
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage, exist_ok=True)
    shutil.copy(os.path.join(ROOT, 'tools', 'boot_frozen.py'),
                os.path.join(stage, 'boot_frozen.py'))

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "WindAnaly",
        "--onedir",
        "--windowed",
        "--icon", os.path.join(ROOT, "icon.ico"),
        "--add-data", _data("ui/theme.qss", "ui"),
        "--add-data", _data("updater/sources.json", "updater"),
        "--add-data", _data("data/turbines.json", "data"),
        "--add-data", _data("icon.png", "."),
        "--distpath", os.path.join(ROOT, "dist"),
        "--workpath", os.path.join(ROOT, "build", "WindAnaly"),
        "--specpath", stage,
        "--clean", "--noconfirm",
    ]
    for h in _scan_hidden_imports():
        cmd += ["--hidden-import", h]
    for e in EXCLUDES:
        cmd += ["--exclude-module", e]
    cmd.append(os.path.join(stage, "boot_frozen.py"))
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=stage)

    dist_dir = os.path.join(ROOT, "dist", "WindAnaly")

    # ---- 2) 业务代码层 ----
    _compile_app_layer(dist_dir)

    # ---- 3) 版本溯源文件（独立更新器据此识别已装版本）----
    data_dir = os.path.join(dist_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, "app_version.txt"), "w",
              encoding="utf-8") as f:
        f.write(VERSION + "\n")

    print("\n主程序打包完成 → dist/WindAnaly/WindAnaly.exe (v" + VERSION + ")")


def build_updater() -> None:
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "updater.spec",
        "--clean", "--noconfirm",
    ]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=os.path.join(ROOT, "updater"))
    # spec 产物在 updater/dist/updater.exe → 挪到主程序目录旁
    src = os.path.join(ROOT, "updater", "dist", "updater.exe")
    dst = os.path.join(ROOT, "dist", "WindAnaly", "updater.exe")
    if os.path.exists(src):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.replace(src, dst)
        print("更新器打包完成 →", dst)
    else:
        print("!! 未找到 updater/dist/updater.exe，请检查打包输出")


def main() -> None:
    if "--updater" in sys.argv:
        build_updater()
        return
    build_app()
    build_updater()
    print("\n全部完成。发布：python tools/release.py <版本> --notes \"说明\"")


if __name__ == "__main__":
    main()
