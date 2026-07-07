@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
echo Running 5-symbol portfolio (au/cu/sc/m/im) on 2022-2024...
python -u examples\chanlun_5m_portfolio.py > portfolio.log 2>&1
echo Done. Tail of log:
echo.
powershell -Command "Get-Content -Path portfolio.log -Tail 100 -Encoding UTF8"
echo.
pause
