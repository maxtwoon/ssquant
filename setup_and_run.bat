@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
echo Running portfolio backtest (4 symbols), output -> portfolio.log
python examples\chanlun_5m_portfolio.py > portfolio.log 2>&1
echo Done. Tail of log:
echo.
powershell -Command "Get-Content -Path portfolio.log -Tail 80 -Encoding UTF8"
echo.
echo Full log: D:\repo\ssquant\portfolio.log
pause
