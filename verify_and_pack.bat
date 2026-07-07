@echo off
chcp 65001 > nul
cd /d D:\repo\ssquant
set PYTHONIOENCODING=utf-8
echo run-at: %DATE% %TIME% > D:\repo\ssquant\verify_marker.txt
(
echo Run started at: %DATE% %TIME%
echo === [1/4] Cleanup temp files ===
del /q resolve_conflicts.py 2^>nul
del /q resolve_conflicts.ps1 2^>nul
del /q resolve_log.txt 2^>nul
del /q run_resolve.bat 2^>nul
del /q pack_log.txt 2^>nul
del /q hello.txt 2^>nul
echo Cleanup done.

echo.
echo === [2/4] Syntax check (python on PATH) ===
where py
where python
python -c "import sys; sys.path.insert(0, '.'); import ssquant; from ssquant.api.strategy_api import StrategyAPI; from ssquant.data.data_source import DataSource; from ssquant.backtest.backtest_results import BacktestResultCalculator; print('IMPORT OK, version:', ssquant.__version__)"

echo.
echo === [3/4] Skip pytest (large test suite, will run separately) ===

echo.
echo === [4/4] Repack ===
powershell -NoProfile -ExecutionPolicy Bypass -File D:\repo\ssquant\pack_strategy.ps1
echo.
echo End: %DATE% %TIME%
) > D:\repo\ssquant\verify_log.txt 2>&1
echo done-at: %DATE% %TIME% >> D:\repo\ssquant\verify_marker.txt
