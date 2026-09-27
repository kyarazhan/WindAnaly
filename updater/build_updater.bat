@echo off
:: 构建 updater.exe（独立更新器）
cd /d "%~dp0"
pyinstaller --onefile --name updater --console updater_main.py
echo.
echo updater.exe 构建完成
