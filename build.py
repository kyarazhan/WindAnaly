"""PyInstaller 打包脚本：主程序 WindAnaly.exe（onedir）+ 独立更新器 updater.exe。

用法（在 venv 中）：
    pip install pyinstaller
    python build.py            # 打包主程序 + 更新器
    python build.py --updater  # 只重建更新器

发布物：
    dist/WindAnaly/WindAnaly.exe        主程序（onedir 文件夹）
    dist/WindAnaly/updater.exe          独立更新器（随主程序放同一目录）
  发布时把 dist/WindAnaly 整目录压缩为 WindAnaly-<版本>.zip 放到更新源，
  并在源目录放 versions.json（多版本索引：全量/增量包 + sha256 + 更新说明）。
"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))


def _data(src: str, dst: str) -> str:
    """构造 --add-data 参数：源路径;目标目录（跨平台用 os.pathsep）。"""
    return f"{os.path.join(ROOT, src)}{os.pathsep}{dst}"


def build_app() -> None:
    # 排除 pandas 的可选依赖与开发工具（本软件未使用，
    # 环境里装了也会被 PyInstaller hooks 捎带进来导致包体虚胖）
    excludes = [
        "--exclude-module", "matplotlib", "--exclude-module", "numba",
        "--exclude-module", "llvmlite", "--exclude-module", "sqlalchemy",
        "--exclude-module", "lxml", "--exclude-module", "PIL",
        "--exclude-module", "psycopg2", "--exclude-module", "psycopg_binary",
        "--exclude-module", "pytest", "--exclude-module", "tkinter",
    ]
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
        *excludes,
        "--clean", "--noconfirm",
        os.path.join(ROOT, "windanaly.py"),
    ]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)
    print("\n主程序打包完成 → dist/WindAnaly/WindAnaly.exe")


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
    print("\n全部完成。发布：将 dist/WindAnaly 整目录压缩为 "
          "WindAnaly-<版本>.zip 上传更新源。")


if __name__ == "__main__":
    main()
