"""WindAnaly 自动更新子包（独立更新器 updater.exe 的源码）。

注意：updater_main.py / feed.py 以顶层兄弟模块方式互相 import，
这是为了 PyInstaller onefile 独立打包与脱离主程序运行；
主程序仅允许 import updater.config / updater.version。
"""
