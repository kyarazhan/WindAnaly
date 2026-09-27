"""冻结模式引导桩（S5 模块化分发）。

PyInstaller 只打包本桩 + 第三方运行时（_internal/，由 hiddenimports
显式声明）；业务代码全部位于安装目录 app/ 下的 .pyc（由 build.py
编译拷入），运行时由本桩加入 sys.path 后动态导入。

效果：日常改动只产生 app/*.pyc 的 KB 级增量包；exe 与 _internal/
仅在第三方依赖集合变化时重建。

注意：本桩必须单独放在临时目录里交给 PyInstaller 分析——若与业务
源码同目录，modulegraph 会顺着 import 把业务代码又打进 exe。
"""
import os
import sys


def main():
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(os.path.abspath(sys.executable))
        app = os.path.join(base, 'app')
        if app not in sys.path:
            sys.path.insert(0, app)
    try:
        import windanaly
        windanaly.main()
    except SystemExit:
        raise
    except BaseException:
        # 窗口化进程的异常只弹对话框不留痕迹；落盘便于定位
        import traceback
        try:
            base = os.path.dirname(os.path.abspath(sys.executable))
            err = os.path.join(base, 'data', 'boot_error.log')
            os.makedirs(os.path.dirname(err), exist_ok=True)
            with open(err, 'a', encoding='utf-8') as f:
                f.write(traceback.format_exc())
        except OSError:
            pass
        raise


if __name__ == '__main__':
    main()
