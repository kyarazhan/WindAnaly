"""路径解析：安装目录 / 用户数据 / 只读资源（打包冻结模式感知）。

三.get 类路径必须全软件统一走这里，禁止各模块自行用 __file__ 推导——
冻结（PyInstaller onedir）模式下模块位于 _internal/，用户数据必须落在
exe 旁的 data/，只读资源在 _internal/，混用会导致「改了配置不生效」。
"""


def app_dir() -> str:
    """安装根目录：冻结 = exe 所在目录；开发 = 项目根（core 的上一级）。"""
    import os
    import sys
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_base() -> str:
    """只读资源根：冻结 = PyInstaller 运行时目录（onedir 为 _internal）；
    开发 = 项目根。"""
    import sys
    meipass = getattr(sys, '_MEIPASS', None)
    return meipass if meipass else app_dir()


def resource_path(*parts: str) -> str:
    """拼只读资源路径（随包分发的文件，如 turbines.json / theme.qss / 图标）。"""
    import os
    return os.path.join(resource_base(), *parts)


def user_data_dir() -> str:
    """用户数据目录（settings.json / windkit.db / backups，更新时保留）。"""
    import os
    return os.path.join(app_dir(), 'data')
