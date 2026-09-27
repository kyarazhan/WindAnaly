"""WindAnaly 独立更新器 updater.exe —— 自带界面，与主程序完全解耦。

主程序只负责「拉起」本更新器（任务 JSON 传入安装目录/当前版本/更新源），
此后查更新、提示、选版本、下载、关闭主程序、备份、替换、重启全部由
本进程独立完成 —— 主程序退出/无响应均不影响。

启动方式：
  updater.exe --task .update/task.json                # 后台伴随：无窗查询，
                                                      # 发现新版写
                                                      # .update/available.json，
                                                      # 由主程序状态栏提示
  updater.exe --task .update/task.json --foreground   # 前台：打开版本选择窗口
  updater.exe                                         # 独立运行（双击）：自行
                                                      # 定位目录/版本/更新源
  updater.exe --config .update/pending.json           # 兼容旧版：应用已下载
                                                      # 的更新包

界面流程（tkinter，纯标准库）：
  检查更新 → 版本选择（当前版本之后的都可选）→ 更新方式（最新全量包 /
  多个增量包逐级补齐）→ 下载（进度）→ 接管安装 → 重启新版。
"""
import argparse
import ctypes
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import zipfile
from tkinter import ttk

import feed
from version import compare_versions, is_newer

APP_EXE_DEFAULT = 'WindAnaly.exe'

# data/ 下更新时必须保留的用户数据
_PRESERVE = {
    'settings.json', 'windkit.db', 'turbines.json', 'updater.log',
}

LOG_PATH = ''


def log(msg):
    line = f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {msg}'
    try:
        if LOG_PATH:
            with open(LOG_PATH, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
    except OSError:
        pass


# ================================================================ 进程控制
def _pid_alive(pid) -> bool:
    try:
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x100000, False, int(pid))   # SYNCHRONIZE
        if not h:
            return False
        k32.CloseHandle(h)
        return True
    except Exception:
        return False


def _exe_running(name: str) -> bool:
    try:
        # tasklist 输出为系统 ANSI（中文系统 GBK），不能用 text=True
        out = subprocess.run(
            ['tasklist', '/FI', f'IMAGENAME eq {name}'],
            capture_output=True, timeout=15).stdout or b''
        txt = out.decode('gbk', 'replace') if isinstance(out, bytes) \
            else str(out)
        return name.lower() in txt.lower()
    except Exception:
        return False


def _close_exe(name: str, logfn=log, graceful_wait: float = 10):
    """关闭单个程序：优雅 → 等待 → 强制。"""
    if not _exe_running(name):
        return
    logfn(f'请求 {name} 退出')
    subprocess.run(['taskkill', '/IM', name],
                   capture_output=True, timeout=20)
    deadline = time.time() + graceful_wait
    while _exe_running(name) and time.time() < deadline:
        time.sleep(0.4)
    if _exe_running(name):
        logfn(f'{name} 未退出，强制结束')
        subprocess.run(['taskkill', '/F', '/IM', name],
                       capture_output=True, timeout=20)
        time.sleep(0.6)
    logfn(f'{name} 已退出')


def close_main_app(task, logfn=log):
    """关闭主程序：优雅 → 等待 → 强制（exe 不退出必然 Permission denied）。"""
    exe = task.get('app_exe') or APP_EXE_DEFAULT
    pid = task.get('pid')
    if pid and _pid_alive(pid):
        logfn(f'请求主程序关闭（pid={pid}）')
        subprocess.run(['taskkill', '/PID', str(pid)],
                       capture_output=True, timeout=20)
    deadline = time.time() + 15
    while _exe_running(exe) and time.time() < deadline:
        time.sleep(0.5)
    if _exe_running(exe):
        logfn('主程序未退出，广播关闭消息')
        subprocess.run(['taskkill', '/IM', exe],
                       capture_output=True, timeout=20)
        deadline = time.time() + 10
        while _exe_running(exe) and time.time() < deadline:
            time.sleep(0.5)
    if _exe_running(exe):
        logfn('主程序仍占用文件，强制结束')
        subprocess.run(['taskkill', '/F', '/IM', exe],
                       capture_output=True, timeout=20)
        time.sleep(1.0)
    logfn('主程序已退出')


# ================================================================ 安装
def _zip_entries(zf):
    """[(归档路径, 相对路径)]；整体包在顶层文件夹里时自动去前缀。"""
    names = [i.filename.replace('\\', '/').lstrip('/')
             for i in zf.infolist() if not i.is_dir()]
    tops = {n.split('/', 1)[0] for n in names}
    has_root_exe = any('/' not in n and n == APP_EXE_DEFAULT for n in names)
    if len(tops) == 1 and not has_root_exe:
        prefix = tops.pop() + '/'
        return [(n, n[len(prefix):]) for n in names if n.startswith(prefix)]
    return [(n, n) for n in names]


def _self_exe() -> str:
    """当前更新器自己的可执行文件路径（冻结模式）。"""
    if getattr(sys, 'frozen', False):
        return os.path.abspath(sys.executable)
    return ''


def _sha_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def extract_preserve_data(zip_path, app_dir):
    """解压到 app_dir；data/ 下用户数据一律保留不覆盖。

    特殊：zip 里的 updater.exe 与正在运行的更新器自身是同一个文件
    （Windows 锁定运行中的 exe，直接覆盖必报 Permission denied），
    因此先跳过，解压完再"改名腾位 → 写入新版"自替换。"""
    # 防呆：完整包必须有根级 WindAnaly.exe；纯差量补丁至少要有
    # _internal/ 下的变更文件（源码存档 zip 两者皆无，拒绝安装）。
    # 校验必须用 _zip_entries 归一化后的路径——完整包带顶层文件夹
    # （WindAnaly/…），用原始条目名会把有效包误判为无效（1.0.5 修复）
    with zipfile.ZipFile(zip_path, 'r') as zf:
        rels = [rel for _, rel in _zip_entries(zf)]
        has_exe = any(r == APP_EXE_DEFAULT for r in rels)
        has_internal = any(r.startswith('_internal/') for r in rels)
        has_app = any(r.startswith('app/') for r in rels)
        if not has_exe and not has_internal and not has_app:
            raise ValueError(
                '所选包不是有效的更新包（既无主程序、无运行时、'
                '也无业务代码 app/），已取消安装')
    self_exe = _self_exe()
    pending_self = None      # (目标路径, 新版字节)
    with zipfile.ZipFile(zip_path, 'r') as zf:
        for arcname, rel in _zip_entries(zf):
            parts = [p for p in rel.split('/') if p and p not in ('.', '..')]
            if not parts:
                continue
            if 'data' in parts and parts[-1] in _PRESERVE:
                continue
            target = os.path.join(app_dir, *parts)
            if not os.path.abspath(target).startswith(
                    os.path.abspath(app_dir)):
                continue
            if self_exe and os.path.abspath(target) == self_exe:
                pending_self = (target, zf.open(arcname).read())
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(arcname) as src, open(target, 'wb') as dst:
                shutil.copyfileobj(src, dst)

    if pending_self:
        target, blob = pending_self
        try:
            if _sha_file(target) != hashlib.sha256(blob).hexdigest():
                old = target + '.old'
                try:
                    if os.path.exists(old):
                        os.remove(old)
                except OSError:
                    pass
                try:
                    os.replace(target, old)  # 运行中的 exe 允许改名
                    with open(target, 'wb') as f:
                        f.write(blob)
                except PermissionError:
                    # 改名/覆盖仍被占用：写 .new 并用延迟脚本在退出后替换
                    new = target + '.new'
                    with open(new, 'wb') as f:
                        f.write(blob)
                    bat = target + '_replace.bat'
                    with open(bat, 'w', encoding='utf-8') as f:
                        f.write('@echo off\n')
                        f.write('ping -n 3 127.0.0.1 >nul\n')
                        f.write(f'move /y "{new}" "{target}"\n')
                        f.write(f'del "%~f0"\n')
                    subprocess.Popen(
                        ['cmd', '/c', bat],
                        cwd=os.path.dirname(target) or '.',
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                        | subprocess.DETACHED_PROCESS,
                        close_fds=True)
                    log('updater.exe 退出后由脚本替换（延迟 2 秒）')
                else:
                    log('updater.exe 已自替换（旧版暂存为 updater.exe.old）')
        except OSError as e:
            # 自替换失败不影响本次更新的其余文件
            log(f'updater.exe 自替换失败: {e}')


def cleanup_stale(app_dir):
    """清理上次自替换留下的 updater.exe.old 等遗留文件。"""
    self_exe = _self_exe()
    if not self_exe:
        return
    old = self_exe + '.old'
    try:
        if os.path.exists(old):
            os.remove(old)
            log('清理 updater.exe.old')
    except OSError:
        pass


def _backup_keep_count(app_dir) -> int:
    """备份保留份数：读 data/settings.json 的 backup_keep（stdlib 直读，
    不依赖主程序）；缺省 10，范围 1~50。"""
    p = os.path.join(app_dir, 'data', 'settings.json')
    try:
        import json
        data = json.load(open(p, encoding='utf-8'))
        keep = int(data.get('backup_keep', 10) or 10)
    except Exception:
        keep = 10
    return max(1, min(keep, 50))


def backup_data(app_dir, backup_root, logfn=log):
    """备份 data/ 用户数据 → backup_root/pre_update_<时间戳>.zip（压缩
    单文件，1.6.4 起不再展开为目录），并按 settings.backup_keep 只保留
    最近 N 份更新前备份（此前无限累积的问题）。

    打包跳过 backups/ 子目录与 updater.log —— 备份目的地就在
    data/backups 里，避免自我包含。"""
    from datetime import datetime
    src = os.path.join(app_dir, 'data')
    if not os.path.isdir(src):
        return ''
    os.makedirs(backup_root, exist_ok=True)
    dst = os.path.join(backup_root, 'pre_update_'
                       + datetime.now().strftime('%Y%m%d_%H%M%S') + '.zip')
    skip = {'backups', 'updater.log'}
    n = 0
    try:
        with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED,
                             compresslevel=6) as zf:
            for root, dirs, files in os.walk(src):
                dirs[:] = [d for d in dirs if d not in skip]
                rel = os.path.relpath(root, src)
                for fn in sorted(files):
                    if fn in skip:
                        continue
                    full = os.path.join(root, fn)
                    arc = fn if rel == '.' else \
                        os.path.join(rel, fn).replace('\\', '/')
                    zf.write(full, arc)
                    n += 1
    except Exception:
        try:
            os.remove(dst)
        except OSError:
            pass
        raise
    keep = _backup_keep_count(app_dir)
    try:
        olds = sorted(f for f in os.listdir(backup_root)
                      if f.startswith('pre_update_') and f.endswith('.zip'))
        for f in olds[:-keep]:
            try:
                os.remove(os.path.join(backup_root, f))
            except OSError:
                pass
    except OSError:
        pass
    logfn(f'data backup -> {dst} ({n} 个文件，保留最近 {keep} 份)')
    return dst


def restore_backup(app_dir, zip_path, logfn=log) -> int:
    """从更新前备份 zip 恢复 data/ 用户数据（解压覆盖，跳过日志）。

    返回恢复的文件数；zip 无效抛 ValueError。"""
    src = os.path.join(app_dir, 'data')
    with zipfile.ZipFile(zip_path) as zf:
        names = [i.filename.replace('\\', '/') for i in zf.infolist()
                 if not i.is_dir()]
    if not names:
        raise ValueError('备份包为空')
    os.makedirs(src, exist_ok=True)
    n = 0
    with zipfile.ZipFile(zip_path) as zf:
        for arc in names:
            if arc == 'updater.log' or arc.startswith('backups/'):
                continue
            target = os.path.join(src, *arc.split('/'))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(arc) as fsrc, open(target, 'wb') as fdst:
                shutil.copyfileobj(fsrc, fdst)
            n += 1
    logfn(f'backup restore <- {zip_path} ({n} 个文件)')
    return n


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


class DownloadCancelled(Exception):
    """用户在下载中途选择终止。"""


def download_package(url, dest, sha, progress_cb, cancel_event=None,
                     logfn=log):
    """下载单个包（http/https 或本地/UNC 路径），带 sha256 校验。

    cancel_event 置位时抛出 DownloadCancelled（保留半成品，重试时覆盖）。"""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    low = str(url).lower()
    if low.startswith(('http://', 'https://')):
        import urllib.request
        req = urllib.request.Request(url, headers={'User-Agent':
                                                   'WindAnaly-Updater'})
        with urllib.request.urlopen(req, timeout=60) as r, \
                open(dest, 'wb') as f:
            total = int(r.headers.get('Content-Length', 0) or 0)
            done = 0
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise DownloadCancelled('下载已终止')
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                progress_cb(done, total)
    else:
        total = os.path.getsize(url)
        done = 0
        with open(url, 'rb') as fin, open(dest, 'wb') as f:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise DownloadCancelled('下载已终止')
                chunk = fin.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                progress_cb(done, total)
    if cancel_event is not None and cancel_event.is_set():
        raise DownloadCancelled('下载已终止')
    if sha:
        actual = _sha256(dest)
        if actual.lower() != str(sha).lower():
            try:
                os.remove(dest)
            except OSError:
                pass
            raise ValueError(f'{os.path.basename(dest)} 校验失败'
                             f'（sha256 与索引不符），已放弃该包')


# ================================================================ 旧版兼容
def run_pending_apply(args):
    """--config pending.json：应用主程序此前已下载好的更新包。"""
    global LOG_PATH
    with open(args.config, encoding='utf-8') as f:
        cfg = json.load(f)
    app_dir = cfg['app_dir']
    package = cfg['package']
    bdir = cfg.get('backup_dir') or os.path.join(app_dir, 'data', 'backups')
    os.makedirs(bdir, exist_ok=True)
    LOG_PATH = os.path.join(bdir, 'updater.log')
    log(f'legacy apply: package={package}')

    pid = cfg.get('pid')
    if pid and _pid_alive(pid):
        wait = getattr(ctypes.windll.kernel32, 'WaitForSingleObject')
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x100000, False, int(pid))
        if h:
            k32.WaitForSingleObject(h, 30000)
            k32.CloseHandle(h)
        time.sleep(0.5)
    # 文件替换前必须停掉主程序
    close_main_app({'app_dir': app_dir,
                    'app_exe': cfg.get('app_exe') or APP_EXE_DEFAULT,
                    'pid': pid})
    backup_data(app_dir, bdir)
    extract_preserve_data(package, app_dir)
    try:
        os.remove(args.config)
    except OSError:
        pass
    exe = os.path.join(app_dir, cfg.get('app_exe') or APP_EXE_DEFAULT)
    if os.path.exists(exe):
        subprocess.Popen([exe], cwd=app_dir)
    log('legacy apply done')


# ================================================================ 界面
class UpdaterApp:
    """更新器界面：更新方式（在线/本地）→ 检查或选包 → 下载/安装。

    打开时不自动联网检查——在线更新需手动点「检查更新」；
    本地更新点「选择更新包…」选 zip，校验无误后安装。"""

    def __init__(self, task: dict):
        global LOG_PATH
        self.task = task
        self.app_dir = task['app_dir']
        self.cur = str(task.get('current_version', '0'))
        self.entries = []
        self.notes = []
        self.downloads = []
        self.local_pkg = None
        self.installing = False
        self._cancel = None
        self.q: queue = queue.Queue()

        bdir = os.path.join(self.app_dir, 'data', 'backups')
        try:
            os.makedirs(bdir, exist_ok=True)
        except OSError:
            pass
        LOG_PATH = os.path.join(bdir, 'updater.log')
        log(f'updater start: mode=foreground current=v{self.cur}')
        cleanup_stale(self.app_dir)

        # 注意：Tk 实例必须先于 BooleanVar 等控件变量创建
        self.root = tk.Tk()
        self.restart_after = tk.BooleanVar(value=True)
        ver = self._app_version() or self.cur
        self.root.title(f'WindAnaly 更新器 v{ver}')
        self.root.geometry('620x460')
        self.root.minsize(560, 400)
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)

        # 顶栏：更新方式 + 动作按钮（始终可见）
        top = ttk.Frame(self.root, padding=(12, 10))
        top.pack(fill='x')
        self.lb_cur = ttk.Label(top, text=f'当前版本 v{self.cur}')
        self.lb_cur.pack(side='left')
        ttk.Label(top, text='    更新方式：').pack(side='left')
        self.mode_var = tk.StringVar(value='online')
        self.rb_online = ttk.Radiobutton(top, text='在线更新',
                                         value='online',
                                         variable=self.mode_var,
                                         command=self._on_mode)
        self.rb_online.pack(side='left')
        self.rb_local = ttk.Radiobutton(top, text='本地更新',
                                        value='local',
                                        variable=self.mode_var,
                                        command=self._on_mode)
        self.rb_local.pack(side='left')
        self.btn_check = ttk.Button(top, text='检查更新',
                                    command=self._start_check)
        self.btn_check.pack(side='left', padx=(18, 0))
        self.btn_pick = ttk.Button(top, text='选择更新包…',
                                   command=self._pick_local_pkg,
                                   state='disabled')
        self.btn_pick.pack(side='left', padx=(8, 0))
        self.btn_restore = ttk.Button(top, text='从备份恢复…',
                                      command=self._open_restore)
        self.btn_restore.pack(side='right')

        # 内容区（检查结果 / 版本选择 / 本地包信息 / 下载进度）
        self.body = ttk.Frame(self.root, padding=(12, 4, 12, 12))
        self.body.pack(fill='both', expand=True)
        self._show_idle()
        self.root.after(120, self._poll)

    # ---- 框架 ----
    def _app_version(self) -> str:
        try:
            with open(os.path.join(self.app_dir, 'data',
                                   'app_version.txt'),
                      encoding='utf-8') as f:
                return f.read().strip()
        except OSError:
            return ''

    def _clear(self):
        for w in self.body.winfo_children():
            w.destroy()

    def _label(self, parent, text, **kw):
        return ttk.Label(parent, text=text, wraplength=560, **kw)

    def _run_thread(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    def _show_idle(self):
        """初始/切换方式时的内容区提示。"""
        self._clear()
        online = self.mode_var.get() == 'online'
        self.btn_check.configure(state='normal' if online else 'disabled')
        self.btn_pick.configure(state='normal' if not online else 'disabled')
        tip = ('点击上方「检查更新」联网查询新版本。' if online else
               '点击上方「选择更新包…」，选择已下载好的更新包 zip'
               '（完整包或差量补丁均可），校验无误后安装。')
        self._label(self.body, tip, foreground='#6a737d').pack(
            anchor='w', pady=(10, 0))

    def _on_mode(self):
        self.local_pkg = None
        self._show_idle()

    # ---- 在线更新：检查 ----
    def _start_check(self):
        if self.mode_var.get() != 'online':
            return
        self._clear()
        self.lb_status = self._label(self.body, '正在检查更新…')
        self.lb_status.pack(anchor='w', pady=(4, 6))
        self.txt_notes = tk.Text(self.body, height=6, state='disabled',
                                 font=('Microsoft YaHei UI', 9))
        self.txt_notes.pack(fill='both', expand=True)
        self._start_fetch()

    def _start_fetch(self):
        self.txt_notes.configure(state='normal')
        self.txt_notes.delete('1.0', 'end')
        self.txt_notes.configure(state='disabled')
        self.lb_status.configure(text='正在检查更新…')
        self._run_thread(self._fetch_worker)

    def _fetch_worker(self):
        try:
            ents, notes = feed.fetch_index(self.task)
            self.q.put(('fetch', ents, notes))
        except Exception as e:                     # noqa: BLE001
            self.q.put(('fetch', [], [f'获取更新信息失败：{e}']))

    def _on_fetched(self, ents, notes):
        self.entries = ents
        self.notes = notes
        newer = feed.newer_versions(ents, self.cur)
        notes_txt = '\n'.join(notes) or '（无）'
        if not newer:
            latest = ents[0]['version'] if ents else ''
            self._clear()
            self._label(self.body,
                        f'已是最新版本 v{self.cur}'
                        + (f'（更新源最新：v{latest}）' if latest else '')
                        ).pack(anchor='w', pady=(4, 8))
            self._label(self.body, '各更新源状态：\n' + notes_txt,
                        foreground='#6a737d').pack(anchor='w')
            row = ttk.Frame(self.body)
            row.pack(fill='x', side='bottom')
            ttk.Button(row, text='重新检查',
                       command=self._start_check).pack(side='right')
            return
        self._show_chooser()

    # ---- 版本选择（在线更新）----
    def _show_chooser(self):
        self._clear()
        self.lb_head = self._label(
            self.body,
            f'当前版本 v{self.cur}　→　选择要更新的目标版本：')
        self.lb_head.pack(anchor='w', pady=(0, 6))

        newer = feed.newer_versions(self.entries, self.cur)
        mid = ttk.Frame(self.body)
        mid.pack(fill='both', expand=True)

        left = ttk.Frame(mid)
        left.pack(side='left', fill='both', expand=True)
        self.lb_versions = tk.Listbox(left, exportselection=False,
                                      height=9, activestyle='dotbox')
        self.lb_versions.pack(side='left', fill='both', expand=True)
        sb = ttk.Scrollbar(left, command=self.lb_versions.yview)
        sb.pack(side='left', fill='y')
        self.lb_versions.configure(yscrollcommand=sb.set)
        self._ver_meta = []
        for e in newer:
            tags = ['全量包' if e.get('full') else '无全量']
            if e.get('patch'):
                tags.append(f"增量(自v{e['patch']['base']})")
            line = (f'v{e["version"]}   {e.get("date", "")}   '
                    + '  '.join(tags))
            self._ver_meta.append(e)
            self.lb_versions.insert('end', line)
        self.lb_versions.selection_set(0)
        self.lb_versions.bind('<<ListboxSelect>>',
                              lambda _e: self._refresh_plan())

        right = ttk.Frame(mid)
        right.pack(side='left', fill='both', expand=True, padx=(12, 0))
        self.mode_pkg = tk.StringVar(value='full')
        ttk.Radiobutton(right, text='完整包（推荐，一步到位）',
                        value='full', variable=self.mode_pkg,
                        command=self._refresh_plan).pack(anchor='w')
        ttk.Radiobutton(right, text='增量包逐级补齐（体积小）',
                        value='patch', variable=self.mode_pkg,
                        command=self._refresh_plan).pack(anchor='w')
        self.lb_plan = self._label(right, '', foreground='#2a7')
        self.lb_plan.pack(anchor='w', pady=(6, 0))
        ttk.Checkbutton(right, text='安装完成后自动重启软件',
                        variable=self.restart_after).pack(anchor='w',
                                                          pady=(10, 0))

        self._label(self.body, '更新说明：').pack(anchor='w', pady=(8, 2))
        self.txt_chg = tk.Text(self.body, height=7, state='disabled',
                               font=('Microsoft YaHei UI', 9))
        self.txt_chg.pack(fill='both', expand=True)

        row = ttk.Frame(self.body)
        row.pack(side='bottom', fill='x', pady=(8, 0))
        ttk.Button(row, text='返回', command=self._show_idle
                   ).pack(side='right')
        self.btn_go = ttk.Button(row, text='下载并安装',
                                 command=self._start_install)
        self.btn_go.pack(side='right', padx=(0, 8))
        self._refresh_plan()

    def _selected_entry(self):
        sel = self.lb_versions.curselection()
        if not sel:
            return None
        return self._ver_meta[sel[0]]

    def _refresh_plan(self):
        e = self._selected_entry()
        if not e:
            self.lb_plan.configure(text='请选择版本')
            return
        self.txt_chg.configure(state='normal')
        self.txt_chg.delete('1.0', 'end')
        chg = (e.get('changelog') or '').strip() or '（暂无更新说明）'
        self.txt_chg.insert('1.0',
                            f'v{e["version"]}  {e.get("date", "")}\n{chg}')
        self.txt_chg.configure(state='disabled')

        mode = self.mode_pkg.get()
        pkgs, err = feed.plan_packages(self.entries, self.cur,
                                       e['version'], mode)
        if err:
            self.lb_plan.configure(text='✗ ' + err, foreground='#c33')
            self.btn_go.configure(state='disabled')
            other = 'patch' if mode == 'full' else 'full'
            _p2, err2 = feed.plan_packages(self.entries, self.cur,
                                           e['version'], other)
            if not err2:
                self.mode_pkg.set(other)
                self.lb_plan.configure(
                    text=f'（{"完整包" if other == "full" else "增量包"}可用，'
                         f'已自动切换）', foreground='#2a7')
                self.btn_go.configure(state='normal')
            return
        lines, total = [], 0
        for p in pkgs:
            sz = feed.probe_size(p['url'])
            line = p['label']
            if sz:
                line += f' · {sz / 1048576:.1f} MB'
                total += sz
            lines.append(line)
        detail = '\n'.join(lines)
        if total:
            detail += f'\n共 {len(pkgs)} 个包，合计 {total / 1048576:.1f} MB'
        self.lb_plan.configure(text='✓ ' + detail, foreground='#2a7')
        self.btn_go.configure(state='normal')

    # ---- 本地更新：选择包 ----
    def _open_restore(self):
        """从备份恢复：列出 data/backups/pre_update_*.zip（新→旧），
        选定后关闭主程序并解压覆盖 data/ 用户数据。"""
        import glob
        from tkinter import messagebox, Toplevel, ttk as _ttk

        bdir = os.path.join(self.app_dir, 'data', 'backups')
        zips = sorted(
            glob.glob(os.path.join(bdir, 'pre_update_*.zip')),
            key=os.path.getmtime, reverse=True)
        if not zips:
            messagebox.showinfo(
                'WindAnaly 更新器',
                '还没有可恢复的更新前备份（pre_update_*.zip）。\n'
                '每次安装更新前会自动在这里生成一份。')
            return

        win = Toplevel(self.root)
        win.title('从备份恢复用户数据')
        win.geometry('560x300')
        win.transient(self.root)
        _ttk.Label(win, text='选择要恢复的备份（覆盖当前 data/ 用户数据）：'
                   ).pack(anchor='w', padx=12, pady=(12, 4))
        lb = _ttk.Listbox(win, height=10)
        lb.pack(fill='both', expand=True, padx=12)
        for z in zips:
            stamp = os.path.basename(z)[len('pre_update_'):-len('.zip')]
            size_mb = os.path.getsize(z) / 1048576
            lb.insert('end', f'{stamp}    {size_mb:.1f} MB')
        lb.selection_set(0)

        def _do():
            sel = lb.curselection()
            if not sel:
                return
            z = zips[sel[0]]
            if not messagebox.askyesno(
                    '确认恢复',
                    '恢复将把备份中的用户数据（台账库、设置、通道规则'
                    '等）覆盖回 data/ 目录，且 data/backups 之后的自动'
                    '备份不受影响。\n\n'
                    '恢复前会关闭正在运行的主程序。确定继续？'):
                return
            self.btn_restore.config(state='disabled')
            close_main_app({'app_dir': self.app_dir,
                            'app_exe': self.task.get('app_exe')
                            or APP_EXE_DEFAULT,
                            'pid': self.task.get('pid')},
                           logfn=log)
            try:
                n = restore_backup(self.app_dir, z, logfn=log)
            except Exception as e:
                messagebox.showerror('WindAnaly 更新器',
                                     f'恢复失败：{e}')
                self.btn_restore.config(state='normal')
                return
            win.destroy()
            messagebox.showinfo(
                'WindAnaly 更新器',
                f'已恢复 {n} 个文件。\n\n'
                '台账库若来自旧版本，下次启动主程序时会自动无损升级。')

        btns = _ttk.Frame(win)
        btns.pack(fill='x', padx=12, pady=10)
        _ttk.Button(btns, text='取消', command=win.destroy).pack(side='right')
        _ttk.Button(btns, text='恢复所选备份', command=_do).pack(
            side='right', padx=(0, 8))

    def _pick_local_pkg(self):
        if self.mode_var.get() != 'local':
            return
        from tkinter import filedialog, messagebox
        path = filedialog.askopenfilename(
            title='选择本地更新包',
            filetypes=[('WindAnaly 更新包', '*.zip'), ('所有文件', '*.*')])
        if not path:
            return
        try:
            with zipfile.ZipFile(path) as zf:
                # 复用安装时的归一化逻辑：整体包带顶层文件夹时自动去前缀，
                # 否则带目录的完整包会被误判为无效（1.0.4 修复）
                rels = [rel for _, rel in _zip_entries(zf)]
            has_exe = any(r == APP_EXE_DEFAULT for r in rels)
            has_internal = any(r.startswith('_internal/') for r in rels)
            has_app = any(r.startswith('app/') for r in rels)
        except zipfile.BadZipFile:
            messagebox.showerror('WindAnaly 更新器',
                                 '所选文件不是有效的 zip')
            return
        if not has_exe and not has_internal and not has_app:
            messagebox.showerror(
                'WindAnaly 更新器',
                '所选 zip 缺少主程序、运行时与业务代码（app/），'
                '不是有效的更新包。')
            return
        self.local_pkg = path
        self._show_local_card(path, has_exe)

    def _show_local_card(self, path: str, has_exe: bool):
        """本地包检查结果：信息确认 + 开始安装。"""
        self._clear()
        name = os.path.basename(path)
        size_mb = os.path.getsize(path) / 1048576
        m = __import__('re').search(
            r'(\d+(?:\.\d+)+)-(\d+(?:\.\d+)+)-patch', name)
        if m:
            kind, ver = f'差量补丁（v{m.group(1)} → v{m.group(2)}）', \
                m.group(2)
        else:
            m2 = __import__('re').search(r'(\d+(?:\.\d+)+)', name)
            ver = m2.group(1) if m2 else '未知'
            kind = '完整包' if has_exe else '程序文件补丁'
        self._label(self.body, '文件检查无误', foreground='#2a7',
                    font=('Microsoft YaHei UI', 11, 'bold')
                    ).pack(anchor='w', pady=(4, 8))
        txt = tk.Text(self.body, height=5, font=('Microsoft YaHei UI', 10),
                      relief='flat', background='#f6f9fc')
        txt.insert('1.0', f'文件：{name}\n类型：{kind}\n'
                          f'大小：{size_mb:.1f} MB\n识别版本：v{ver}')
        txt.configure(state='disabled')
        txt.pack(fill='x', pady=(0, 10))
        self.target = ver
        row = ttk.Frame(self.body)
        row.pack(side='bottom', fill='x')
        ttk.Button(row, text='重新选择',
                   command=self._pick_local_pkg).pack(side='right')
        ttk.Button(row, text='开始安装',
                   command=self._begin_local_install).pack(side='right',
                                                           padx=(0, 8))

    def _begin_local_install(self):
        if not self.local_pkg:
            return
        self.downloads = [{'url': self.local_pkg, 'sha256': '',
                           'label': os.path.basename(self.local_pkg),
                           'local': True}]
        self.installing = True
        self._cancel = threading.Event()
        self._show_progress()
        self._run_thread(self._install_worker)

    # ---- 下载与安装（在线/本地共用）----
    def _start_install(self):
        e = self._selected_entry()
        if e is None:
            return
        pkgs, err = feed.plan_packages(self.entries, self.cur,
                                       e['version'],
                                       self.mode_pkg.get())
        if err:
            from tkinter import messagebox
            messagebox.showerror('WindAnaly 更新器', err)
            return
        self.downloads = pkgs
        self.target = e['version']
        self._begin_install()

    def _begin_install(self):
        self.installing = True
        self._cancel = threading.Event()
        self._show_progress()
        self._run_thread(self._install_worker)

    def _cancel_download(self):
        """下载中途终止。"""
        if getattr(self, '_cancel', None) is not None:
            self._cancel.set()
            self.lb_phase.configure(text='正在终止下载…')

    def _retry_install(self):
        """重试：重新下载并安装（未完成的半成品会被覆盖）。"""
        self._begin_install()

    def _show_progress(self):
        self._clear()
        self.lb_phase = self._label(self.body, '准备下载…',
                                    font=('Microsoft YaHei UI', 11, 'bold'))
        self.lb_phase.pack(anchor='w', pady=(6, 8))
        self.bar = ttk.Progressbar(self.body, maximum=100)
        self.bar.pack(fill='x')
        self.lb_pkg = self._label(self.body, '')
        self.lb_pkg.pack(anchor='w', pady=(6, 2))
        self.txt_log = tk.Text(self.body, height=10, state='disabled',
                               font=('Consolas', 9))
        self.txt_log.pack(fill='both', expand=True, pady=(6, 0))
        btn_row = ttk.Frame(self.body)
        btn_row.pack(side='bottom', fill='x', pady=(8, 0))
        self.btn_cancel = ttk.Button(btn_row, text='终止下载',
                                     command=self._cancel_download)
        self.btn_cancel.pack(side='right')
        self.btn_retry = ttk.Button(btn_row, text='重试下载',
                                    command=self._retry_install,
                                    state='disabled')
        self.btn_retry.pack(side='right', padx=(0, 8))
        self.btn_done = ttk.Button(btn_row, text='完成',
                                   command=self._on_close,
                                   state='disabled')
        self.btn_done.pack(side='right', padx=(0, 8))

    def _log_line(self, line):
        self.txt_log.configure(state='normal')
        self.txt_log.insert('end', line + '\n')
        self.txt_log.see('end')
        self.txt_log.configure(state='disabled')

    def _install_worker(self):
        staging = os.path.join(self.app_dir, '.update')
        # 纯本地包没有下载阶段，「终止下载」无意义
        self.q.put(('cancel_btn',
                    any(not p.get('local') for p in self.downloads)))
        try:
            os.makedirs(staging, exist_ok=True)
            files, cleanup = [], []
            for i, pkg in enumerate(self.downloads, 1):
                if pkg.get('local'):
                    # 本地更新包：免下载，直接安装（不删除用户文件）
                    files.append(pkg['url'])
                    self.q.put(('log', f'使用本地包 {pkg["label"]}'))
                    continue
                name = os.path.basename(str(pkg['url']).replace('\\', '/')) \
                    or f'package{i}.zip'
                if not name.lower().endswith('.zip'):
                    name = f'package{i}.zip'
                dest = os.path.join(staging, name)
                self.q.put(('phase', f'下载中（{i}/{len(self.downloads)}）'))
                self.q.put(('pkg', pkg['label']))
                t0 = time.time()
                download_package(
                    pkg['url'], dest, pkg.get('sha256', ''),
                    lambda d, t: self.q.put(('dl', d, t)),
                    cancel_event=getattr(self, '_cancel', None))
                files.append(dest)
                cleanup.append(dest)
                self.q.put(('log', f'完成 {name} '
                            f'({os.path.getsize(dest) / 1048576:.1f} MB，'
                            f'{time.time() - t0:.0f}s)'))
            self.q.put(('cancel_btn', False))   # 进入安装阶段，不可中断

            self.q.put(('phase', '正在关闭主程序…'))
            self.q.put(('bar', None))
            close_main_app(self.task, logfn=lambda m: self.q.put(('log', m)))

            self.q.put(('phase', '备份用户数据…'))
            backup_data(self.app_dir,
                        os.path.join(self.app_dir, 'data', 'backups'),
                        logfn=lambda m: self.q.put(('log', m)))

            self.q.put(('phase', '安装更新…'))
            for f in files:
                extract_preserve_data(f, self.app_dir)
                self.q.put(('log', f'已应用 {os.path.basename(f)}'))

            # 清理任务、旧 pending 与"有新版"提示文件，防重复触发/误提示
            for p in (self.task.get('_task_path'),
                      os.path.join(self.app_dir, '.update', 'pending.json'),
                      os.path.join(self.app_dir, '.update',
                                   'available.json')):
                try:
                    if p and os.path.exists(p):
                        os.remove(p)
                except OSError:
                    pass
            for f in cleanup:                     # 只清理下载的临时包
                try:
                    os.remove(f)
                except OSError:
                    pass

            if self.restart_after.get():
                self.q.put(('phase', '重启软件…'))
                exe = os.path.join(self.app_dir,
                                   self.task.get('app_exe')
                                   or APP_EXE_DEFAULT)
                if os.path.exists(exe):
                    subprocess.Popen([exe], cwd=self.app_dir)
                    self.q.put(('log', '已启动新版'))
                else:
                    self.q.put(('log', f'未找到 {exe}，请手动启动'))
            self.q.put(('phase', f'更新完成：当前 v{self.cur} → '
                                 f'v{self.target}'))
            log(f'update applied: v{self.cur} -> v{self.target} '
                f'({len(files)} packages)')
            self.q.put(('done',))
        except DownloadCancelled:
            log('download cancelled by user')
            self.q.put(('cancelled',))
        except Exception as e:                     # noqa: BLE001
            import traceback as _tb
            tb_txt = _tb.format_exc()
            log(f'install error: {type(e).__name__}: {e}')
            log(tb_txt)                             # 完整堆栈进日志定位
            self.q.put(('fail', str(e)))

    # ---- 事件循环与关闭 ----
    def _poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == 'fetch':
                    self._on_fetched(item[1], item[2])
                elif kind == 'phase':
                    self.lb_phase.configure(text=item[1])
                elif kind == 'pkg':
                    self.lb_pkg.configure(text=item[1])
                elif kind == 'dl':
                    d, t = item[1], item[2]
                    pct = (d / t * 100) if t else 0
                    self.bar.configure(
                        maximum=100,
                        value=pct if t else 0,
                        mode='determinate' if t else 'indeterminate')
                    if t:
                        self.lb_pkg.configure(
                            text=f'{self.lb_pkg.cget("text").split("（")[0]}'
                                 f'（{d / 1048576:.1f} / '
                                 f'{t / 1048576:.1f} MB，{pct:.0f}%）')
                elif kind == 'bar':
                    self.bar.configure(mode='indeterminate')
                    if item[1] is None:
                        self.bar.start(12)
                elif kind == 'cancel_btn':
                    # 下载阶段可终止；进入安装阶段后不可中断
                    self.btn_cancel.configure(
                        state='normal' if item[1] else 'disabled')
                elif kind == 'cancelled':
                    self.installing = False
                    self.bar.stop()
                    self.lb_phase.configure(text='已终止下载')
                    self._log_line('已终止（可点击「重试下载」重新开始）')
                    self.btn_cancel.configure(state='disabled')
                    self.btn_retry.configure(state='normal')
                    self.btn_done.configure(state='normal')
                elif kind == 'log':
                    self._log_line(item[1])
                elif kind == 'done':
                    self.installing = False
                    self.bar.stop()
                    self.btn_cancel.configure(state='disabled')
                    self.btn_done.configure(state='normal')
                    self.btn_done.focus_set()
                elif kind == 'fail':
                    self.installing = False
                    self.bar.stop()
                    self.lb_phase.configure(text='更新失败')
                    self._log_line('错误：' + item[1])
                    from tkinter import messagebox
                    messagebox.showerror(
                        'WindAnaly 更新器',
                        '更新失败：' + item[1]
                        + '\n\n可点击「重试下载」重新开始；也可改用'
                          '「本地更新」选择手动下载的包安装。'
                                          '数据备份位于 data/backups/')
                    self.btn_cancel.configure(state='disabled')
                    self.btn_retry.configure(state='normal')
                    self.btn_done.configure(state='normal')
        except queue.Empty:
            pass
        self.root.after(120, self._poll)

    def _on_close(self):
        # 下载/安装进行中不允许关闭（防半成品状态）
        if getattr(self, 'installing', False):
            from tkinter import messagebox
            messagebox.showwarning(
                'WindAnaly 更新器',
                '正在下载/安装更新，请等待完成后再关闭。')
            return
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# ================================================================ 后台伴随
def run_background(task):
    """后台伴随模式：完全不弹窗。

    查询更新源 → 发现新版本则写 .update/available.json（由主程序轮询后
    在状态栏左下角提示）；无新版本/查询失败则清理旧提示并静默退出。
    """
    global LOG_PATH
    app_dir = task['app_dir']
    bdir = os.path.join(app_dir, 'data', 'backups')
    try:
        os.makedirs(bdir, exist_ok=True)
    except OSError:
        pass
    LOG_PATH = os.path.join(bdir, 'updater.log')
    cur = str(task.get('current_version', '0'))
    log(f'updater start: mode=background current=v{cur}')
    cleanup_stale(app_dir)
    try:
        ents, notes = feed.fetch_index(task)
    except Exception as e:                          # noqa: BLE001
        ents, notes = [], [f'获取更新信息失败：{e}']
        log(f'fetch error: {e}')
    for n in notes:
        log(f'source: {n}')

    avail = os.path.join(app_dir, '.update', 'available.json')
    newer = feed.newer_versions(ents, cur)
    if newer:
        latest = newer[0]
        payload = {'version': latest['version'],
                   'date': latest.get('date', ''),
                   'changelog': latest.get('changelog', ''),
                   'newer_count': len(newer),
                   'found_at': time.strftime('%Y-%m-%d %H:%M:%S')}
        try:
            os.makedirs(os.path.dirname(avail), exist_ok=True)
            with open(avail, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except OSError:
            pass
        log(f'update available: v{latest["version"]} '
            f'({len(newer)} newer) -> available.json')
    else:
        try:
            if os.path.exists(avail):
                os.remove(avail)
        except OSError:
            pass
        log(f'no update (latest='
            f'v{ents[0]["version"] if ents else "?"}), exit silently')


# ================================================================ 独立运行
def build_standalone_task() -> dict:
    """双击 updater.exe（无参数）：独立运行模式。

    自行定位安装目录、当前版本与更新源，不依赖主程序可用——
    主程序损坏无法打开时，本更新器仍可下载全量包修复/升级。
    """
    if getattr(sys, 'frozen', False):
        ad = os.path.dirname(os.path.abspath(sys.executable))
    else:
        ad = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    cur = ''
    try:
        with open(os.path.join(ad, 'data', 'app_version.txt'),
                  encoding='utf-8') as f:
            cur = f.read().strip()
    except OSError:
        pass
    if not re.fullmatch(r'\d+(\.\d+)*', cur or ''):
        cur = '0.0.0'        # 读不到版本 → 视为最旧，列出全部可用版本

    sources = None
    for cand in (os.path.join(ad, '_internal', 'updater', 'sources.json'),
                 os.path.join(ad, 'updater', 'sources.json')):
        try:
            with open(cand, encoding='utf-8') as f:
                d = json.load(f)
            if isinstance(d, list) and d:
                sources = d
                break
        except Exception:
            continue
    if not sources:
        sources = [{'name': 'GitHub Releases', 'type': 'github-releases',
                    'repo': 'kyarazhan/WindAnaly'}]

    return {'app_dir': ad,
            'app_exe': APP_EXE_DEFAULT,
            'current_version': cur,
            'sources': sources,
            'include_prerelease': True,
            'pid': 0}


# ================================================================ 入口
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--task', help='任务 JSON（主程序生成）')
    ap.add_argument('--foreground', action='store_true',
                    help='前台模式：打开版本选择窗口（缺省为后台无窗查询）')
    ap.add_argument('--config', help='兼容旧版：应用已下载更新包（pending.json）')
    args = ap.parse_args()

    if args.config:
        run_pending_apply(args)
        return

    if args.task:
        with open(args.task, encoding='utf-8') as f:
            task = json.load(f)
        task['_task_path'] = args.task
        if not task.get('sources'):
            print('task 缺少 sources', file=sys.stderr)
            sys.exit(2)
        if args.foreground:
            app = UpdaterApp(task)
            app.run()
        else:
            run_background(task)
        return

    # 无参数 = 双击独立运行：前台窗口（不依赖主程序）
    app = UpdaterApp(build_standalone_task())
    app.run()


if __name__ == '__main__':
    main()
