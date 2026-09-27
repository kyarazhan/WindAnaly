"""更新器混入：主程序只负责「唤醒」独立更新器，更新全由更新器接管。

架构（与 WindVault_QT 同机制）：
  - 主程序启动 → 后台拉起 updater.exe（无窗）查询更新源；
    发现新版本时更新器写 .update/available.json，本混入轮询到后
    在状态栏左下角提示「发现新版本 vX.Y.Z」，不打扰用户；
  - 帮助 → 检查更新 → 前台拉起 updater.exe 窗口：版本选择（当前版本
    之后的都可以选）、下载最新完整包或多个增量包逐级补齐、关闭主程序、
    备份、替换、重启 —— 全部在更新器独立进程里完成；
  - updater.exe 还可脱离主程序独立双击运行（主程序损坏时自救）。
"""
import json
import os
import subprocess
import sys

from updater.config import app_dir, load_sources
from core.version import VERSION as __version__


def _task_path() -> str:
    return os.path.join(app_dir(), '.update', 'task.json')


def _write_task() -> str:
    """把更新所需上下文写给更新器（它不读主程序任何内部状态）。"""
    from core import settings
    p = _task_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump({
            'app_dir': app_dir(),
            'app_exe': 'WindAnaly.exe',
            'current_version': __version__,
            'sources': load_sources(),
            'include_prerelease': bool(
                settings.get('update_include_prerelease', True)),
            'pid': os.getpid(),
        }, f, ensure_ascii=False, indent=2)
    return p


def _launch_updater(foreground: bool) -> bool:
    """拉起独立更新器进程。返回是否成功启动。"""
    exe = os.path.join(app_dir(), 'updater.exe')
    if not os.path.exists(exe):
        return False
    task = _write_task()
    cmd = [exe, '--task', task]
    if foreground:
        cmd.append('--foreground')
    flags = 0
    if os.name == 'nt':
        flags = (subprocess.CREATE_NEW_PROCESS_GROUP
                 | subprocess.DETACHED_PROCESS)
    subprocess.Popen(cmd, cwd=app_dir(), creationflags=flags,
                     close_fds=True)
    return True


class UpdateMixin:
    """窗口混入：只提供「拉起更新器」入口与状态栏提示。"""

    def _setup_update(self):
        """启动时伴随拉起更新器（后台无窗查询），并轮询其检查结果。"""
        try:
            if self._auto_update_enabled():
                _launch_updater(foreground=False)
        except Exception:
            pass
        # 后台更新器发现新版本 → 写 available.json → 状态栏左下角提示
        from PySide6.QtCore import QTimer
        self._hinted_update = None
        self._t_hint = QTimer(self)
        self._t_hint.timeout.connect(self._poll_update_hint)
        self._t_hint.start(30000)
        QTimer.singleShot(10000, self._poll_update_hint)

    def _auto_update_enabled(self) -> bool:
        """后台静默检查开关（设置 auto_update_check，默认开）。"""
        try:
            from core import settings
            return bool(settings.get('auto_update_check', True))
        except Exception:
            return True

    def _poll_update_hint(self):
        """后台更新器发现新版本时，状态栏提示（不弹窗、不打扰）。"""
        try:
            p = os.path.join(app_dir(), '.update', 'available.json')
            if not os.path.exists(p):
                return
            with open(p, encoding='utf-8') as f:
                data = json.load(f)
            ver = str(data.get('version', '')).strip()
            if not ver or ver == getattr(self, '_hinted_update', None):
                return
            from updater.version import is_newer
            if not is_newer(ver, __version__):
                return
            self._hinted_update = ver
            self.statusBar().showMessage(
                f'发现新版本 v{ver}，可在「帮助 → 检查更新」中安装'
                + (f'（共 {data["newer_count"]} 个新版本）'
                   if data.get('newer_count') else ''))
        except Exception:
            pass

    def _open_update(self):
        """帮助 → 检查更新：前台打开更新器（版本列表/下载/安装）。"""
        if not _launch_updater(foreground=True):
            try:
                self.statusBar().showMessage(
                    '未找到独立更新器 updater.exe（安装目录缺失），'
                    '请重新安装或手动下载全量包')
            except Exception:
                pass

    def _stop_update(self):
        """窗口关闭：停掉提示轮询（更新器是独立进程，无需清理）。"""
        t = getattr(self, '_t_hint', None)
        if t is not None:
            t.stop()
