@echo off
rem 本地检查脚本：语法编译 + pytest 回归 + GUI 离屏冒烟（发布前必须全绿）
cd /d "%~dp0"

python -m compileall -q windanaly.py app.py build.py core ui updater tests
if errorlevel 1 goto :fail

python -X utf8 -m pytest tests -q
if errorlevel 1 goto :fail

python -X utf8 tools\i18n_audit.py
if errorlevel 1 goto :fail

set QT_QPA_PLATFORM=offscreen
python -X utf8 tools\smoke_ui.py
if errorlevel 1 goto :fail

echo.
echo ===== ALL CHECKS PASSED =====
exit /b 0

:fail
echo.
echo ===== CHECKS FAILED =====
exit /b 1
