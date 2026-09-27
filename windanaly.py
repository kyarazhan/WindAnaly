"""WindAnaly：测风塔数据风资源分析软件。

本文件是软件唯一入口（python windanaly.py）：
  python windanaly.py     桌面 GUI

主窗口定义在 app.py（AnalysisApp）；PySide6 仅在 GUI 路径导入。
更新由独立的 updater.exe 完成（见 updater/ 包）。
"""

import json
import os
import subprocess
import sys

# 安装目录的唯一判定：冻结（打包）模式 = exe 所在目录；开发 = 项目根。
# 全软件（含 updater 包）必须统一用它——避免各处推导不一致导致
# 「下载了更新、重启不生效」。
if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))


def _handle_update_pending() -> bool:
    """发现 .update/pending.json 时交接给独立更新器（或 bat 兜底）。

    返回 True 表示本进程应退出（更新交接完成）。"""
    pending = os.path.join(APP_DIR, '.update', 'pending.json')
    if not os.path.exists(pending):
        return False
    updater_exe = os.path.join(APP_DIR, 'updater.exe')
    if os.path.exists(updater_exe):
        try:
            cfg = json.loads(open(pending, encoding='utf-8').read())
        except Exception:
            cfg = {}
        cfg['app_dir'] = APP_DIR
        cfg['pid'] = os.getpid()    # 更新器等本进程退出后再替换文件
        with open(pending, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        subprocess.Popen(
            [updater_exe, '--config', pending],
            cwd=APP_DIR,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS,
            close_fds=True)
        return True
    # 兜底：bat 脚本接管更新（cmd.exe 不加载主程序 DLL，无锁冲突）
    package_name = ''
    try:
        pdata = json.loads(open(pending, encoding='utf-8').read())
        package_name = os.path.basename(pdata.get('package', ''))
    except Exception:
        package_name = ''
    bat = os.path.join(APP_DIR, '_do_update.bat')
    with open(bat, 'w', encoding='utf-8') as f:
        f.write('@echo off\n')
        f.write('chcp 65001 >NUL\n')
        f.write('title WindAnaly Updater\n')
        f.write(':wait\n')
        f.write('tasklist /FI "IMAGENAME eq WindAnaly.exe" 2>NUL')
        f.write(' | find /I "WindAnaly.exe" >NUL\n')
        f.write('if not errorlevel 1 (\n')
        f.write('    timeout /t 2 /nobreak >NUL\n')
        f.write('    goto wait\n')
        f.write(')\n')
        f.write('if not exist "data\\backups" mkdir "data\\backups"\n')
        f.write('if exist "data\\windkit.db" copy /Y "data\\windkit.db" '
                '"data\\backups\\windkit_pre_update.db" >NUL\n')
        f.write(f'tar -xf ".update\\{package_name}"\n')
        f.write('start "" "WindAnaly.exe"\n')
        f.write('del ".update\\pending.json" 2>NUL\n')
        f.write(f'del ".update\\{package_name}" 2>NUL\n')
        f.write('del "%~f0"\n')
    subprocess.Popen(
        ['cmd', '/c', bat],
        cwd=APP_DIR,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
        | subprocess.DETACHED_PROCESS,
        close_fds=True)
    return True


def main() -> None:
    # 更新交接：有 pending 都让位给更新器（旧版更新器遗留的
    # pending.json 由 updater.exe --config 兼容路径应用）
    if _handle_update_pending():
        sys.exit(0)

    _run_gui()


def _run_gui() -> None:
    """桌面 GUI：异常落日志 → QApplication → 主窗口 → 主循环。"""
    # 未捕获异常写入运行日志，便于定位「闪退」
    def _except_hook(t, v, tb):
        try:
            import traceback
            log = os.path.join(APP_DIR, 'data', 'boot_error.log')
            os.makedirs(os.path.dirname(log), exist_ok=True)
            with open(log, 'a', encoding='utf-8') as f:
                f.write('未捕获异常 '
                        + ''.join(traceback.format_exception(t, v, tb))
                        [-2000:] + '\n')
        except Exception:
            pass
        sys.__excepthook__(t, v, tb)

    sys.excepthook = _except_hook

    from PySide6.QtWidgets import QApplication
    qapp = QApplication(sys.argv)
    qapp.setStyle('Fusion')

    from PySide6.QtGui import QIcon
    from core.paths import resource_path
    icon = resource_path('icon.png')
    if os.path.exists(icon):
        qapp.setWindowIcon(QIcon(icon.replace('\\', '/')))  # 任务栏图标

    from core.paths import resource_path
    qss = resource_path('ui', 'theme.qss')
    if os.path.exists(qss):
        with open(qss, 'r', encoding='utf-8') as f:
            qapp.setStyleSheet(f.read())

    from core import settings
    settings.apply_font_size(qapp)

    from app import AnalysisApp
    win = AnalysisApp()
    win.show()
    sys.exit(qapp.exec())


if __name__ == '__main__':
    main()
