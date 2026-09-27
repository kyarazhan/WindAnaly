"""PyInstaller 打包脚本（S5 模块化分发 + B1 构建缓存）：
  WindAnaly.exe（引导桩，稳定）+ _internal/（第三方运行时，少变）
  + app/（业务代码 .pyc，常变）+ updater.exe（独立更新器）

运行时与更新器按「输入指纹」缓存复用（build/cache/）：输入不变不重建，
增量包回落到 app/*.pyc 的真实体积。业务层每次现编译。

用法（在 venv 中）：
    pip install -r requirements.txt -r requirements-build.txt
    python build.py            # 打包主程序 + 更新器
    python build.py --updater  # 只重建更新器

发布物：
    dist/WindAnaly/WindAnaly.exe        主程序（onedir 文件夹）
    dist/WindAnaly/updater.exe          独立更新器（随主程序放同一目录）
  发布时用 tools/release.py 出完整包/增量包/索引。
"""
from __future__ import annotations

import ast
import hashlib
import importlib.metadata
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
    # updater 包的兄弟模块（feed/version）只被独立 updater.exe 使用，
    # 运行时不需要也不是可安装的顶层包——过滤掉，消除 hidden-import 警告
    tops -= {'feed', 'version'}
    return sorted(t for t in tops
                  if t not in LOCAL_PKGS and t not in EXCLUDES)


# ---------------------------------------------------------------------------
# 构建缓存（B1）：运行时与 updater 的产物按「输入指纹」复用。
# PyInstaller 产物内嵌构建时间戳、每次字节全变，文件级 diff 会把
# 没有任何变化的 10MB+ exe 打进补丁；输入不变时直接复用上一版产物，
# 增量包即回落到 app/*.pyc 的真实体积。
# ---------------------------------------------------------------------------
CACHE = os.path.join(ROOT, 'build', 'cache')


def _sha256_file(p: str) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


def _toolchain_tag() -> str:
    py = '%d.%d.%d' % sys.version_info[:3]
    try:
        pi = importlib.metadata.version('pyinstaller')
    except Exception:
        pi = 'unknown'
    return f'py{py}-pyi{pi}'


def _runtime_fingerprint(hidden: list[str]) -> str:
    parts = [
        open(os.path.join(ROOT, 'tools', 'boot_frozen.py'),
             'rb').read(),
        '|'.join(hidden),
        '|'.join(EXCLUDES),
    ]
    for rel in ('ui/theme.qss', 'updater/sources.json',
                'data/turbines.json', 'icon.png', 'icon.ico'):
        parts.append(_sha256_file(os.path.join(ROOT, rel)))
    parts.append(_toolchain_tag())
    h = hashlib.sha256()
    for p in parts:
        h.update(p if isinstance(p, bytes) else p.encode('utf-8'))
    return h.hexdigest()[:12]


def _updater_fingerprint() -> str:
    h = hashlib.sha256()
    pkg = os.path.join(ROOT, 'updater')
    for f in sorted(os.listdir(pkg)):
        if f.endswith(('.py', '.spec', '.ico', '.json')):
            h.update(f.encode('utf-8'))
            h.update(_sha256_file(os.path.join(pkg, f)).encode('ascii'))
    h.update(_toolchain_tag().encode('utf-8'))
    return h.hexdigest()[:12]


def _cache_fetch(cache_dir: str, dest_dir: str, label: str) -> bool:
    """命中则把缓存内容复制到 dest_dir 并返回 True。"""
    if not os.path.isdir(cache_dir):
        return False
    for root, dirs, files in os.walk(cache_dir):
        rel = os.path.relpath(root, cache_dir)
        target = os.path.join(dest_dir, rel) if rel != '.' else dest_dir
        os.makedirs(target, exist_ok=True)
        for f in files:
            shutil.copy2(os.path.join(root, f), os.path.join(target, f))
    print(f'{label}: 缓存命中 <- {os.path.basename(cache_dir)}')
    return True


def _cache_store(cache_dir: str, src_items: list[tuple[str, str]],
                 keep: int = 2) -> None:
    """把产物条目 [(源路径, 相对名)] 存入缓存并清理旧指纹目录。"""
    if os.path.isdir(cache_dir):
        shutil.rmtree(cache_dir)
    os.makedirs(cache_dir, exist_ok=True)
    for src, rel in src_items:
        dst = os.path.join(cache_dir, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    parent = os.path.dirname(cache_dir)
    prefix = os.path.basename(cache_dir).rsplit('-', 1)[0]
    if os.path.isdir(parent):
        entries = sorted(
            (os.path.join(parent, d) for d in os.listdir(parent)
             if d.startswith(prefix + '-')
             and os.path.isdir(os.path.join(parent, d))),
            key=os.path.getmtime, reverse=True)
        for old in entries[keep:]:
            shutil.rmtree(old, ignore_errors=True)


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
    dist_dir = os.path.join(ROOT, "dist", "WindAnaly")
    hidden = _scan_hidden_imports()
    fp = _runtime_fingerprint(hidden)
    cache_dir = os.path.join(CACHE, f"runtime-{fp}")

    # ---- 1) 运行时（exe + _internal）：输入不变即复用缓存 ----
    if _cache_fetch(cache_dir, dist_dir, "运行时"):
        pass
    else:
        # 桩目录：只放引导桩，防止 modulegraph 把业务码打进 exe
        stage = os.path.join(ROOT, "build", "stage")
        shutil.rmtree(stage, ignore_errors=True)
        os.makedirs(stage, exist_ok=True)
        shutil.copy(os.path.join(ROOT, "tools", "boot_frozen.py"),
                    os.path.join(stage, "boot_frozen.py"))

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
        for h in hidden:
            cmd += ["--hidden-import", h]
        for e in EXCLUDES:
            cmd += ["--exclude-module", e]
        cmd.append(os.path.join(stage, "boot_frozen.py"))
        print("Running:", " ".join(cmd))
        subprocess.run(cmd, check=True, cwd=stage)
        _cache_store(cache_dir,
                     [(os.path.join(dist_dir, "WindAnaly.exe"),
                       "WindAnaly.exe"),
                      (os.path.join(dist_dir, "_internal"), "_internal")])
        print("运行时: 已重建并入缓存")

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
    fp = _updater_fingerprint()
    cache_dir = os.path.join(CACHE, f"updater-{fp}")
    dist_dir = os.path.join(ROOT, "dist", "WindAnaly")
    dst = os.path.join(dist_dir, "updater.exe")

    if _cache_fetch(cache_dir, dist_dir, "更新器") and os.path.isfile(dst):
        return

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "updater.spec",
        "--clean", "--noconfirm",
    ]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=os.path.join(ROOT, "updater"))
    # spec 产物在 updater/dist/updater.exe → 挪到主程序目录旁
    src = os.path.join(ROOT, "updater", "dist", "updater.exe")
    if os.path.exists(src):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.replace(src, dst)
        _cache_store(cache_dir, [(dst, "updater.exe")])
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
