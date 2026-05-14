@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo ========================================================
echo 缠论 5 分钟策略 - 回测 (2024-01-01 ~ 2024-12-31)
echo ========================================================
echo.
python examples\B_缠论5分钟策略.py
echo.
echo ========================================================
echo 运行完成。结果在 backtest_results\ 目录下：
echo   - chanlun_5m_au888_5m_*.png  (缠论分析图)
echo   - chanlun_signals_au888_5m_*.csv  (信号清单)
echo   - chanlun_signals_au888_5m_*.json  (信号 JSON)
echo ========================================================
pause
