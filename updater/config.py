"""更新源配置加载。

发版前若需调整更新源顺序，直接改 updater/sources.json 即可（无需动代码）。
每个源至少包含：
  - name:         展示名（仅日志/调试用）
  - manifest_url: manifest.json 的地址
                  * 以 http:// 或 https:// 开头 → 走 HTTP 拉取
                  * 否则视为本地/UNC 文件路径（如 \\\\server\\share\\windanaly\\manifest.json）
"""
from __future__ import annotations

import json
import os
import sys

# 兜底默认源（当 sources.json 缺失或损坏时使用）。
# GitHub Releases 为真实可用通道（网页解析，不耗 API 配额）；内网/
# NAS 源在部署时写入 sources.json，不放占位地址——避免兜底链路
# 全部失效（1.3.1 审计修复：此前兜底为 CHANGE_ME 占位，等于没有兜底）。
_DEFAULT_SOURCES = [
    {"name": "GitHub Releases", "type": "github-releases",
     "repo": "kyarazhan/WindAnaly"},
]


def load_sources() -> list:
    """按序返回更新源定义列表。

    查找顺序：本模块所在目录（开发/onefile 独立打包）→ 安装根
    `_internal/updater/`（onedir 随包分发）→ 安装根 `updater/`。
    1.0.4 起业务代码层可能位于 app/，模块 __file__ 随之变化，
    因此必须同时探测安装根的固定位置。"""
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [os.path.join(here, 'sources.json')]
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(os.path.abspath(sys.executable))
        cands += [os.path.join(base, '_internal', 'updater', 'sources.json'),
                  os.path.join(base, 'updater', 'sources.json')]
    for path in cands:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, list) and data:
                return data
        except Exception:
            continue
    return list(_DEFAULT_SOURCES)


def manifest_is_http(url: str) -> bool:
    return str(url).startswith('http://') or str(url).startswith('https://')


def app_dir() -> str:
    """返回安装根目录（冻结模式 = exe 所在目录；开发 = 项目根）。

    不用 sys.argv[0] 推导：快捷方式/相对路径启动时会得到错误目录，
    导致更新解压位置错乱（表现为“下载后重启不生效”）。"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    # 开发环境：updater/config.py 的上一级即项目根
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
