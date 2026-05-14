@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
echo Testing API auth directly...
python examples\test_api_auth.py > api_test.log 2>&1
echo.
type api_test.log
echo.
echo ====
echo Full log: D:\repo\ssquant\api_test.log
pause
