@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: SSQuant K 线数据库自动更新脚本
:: 可被 Windows 任务计划程序调用

set "PROJECT_DIR=D:\repo\ssquant"
set "DB_PATH=D:\BaiduNetdiskDownload\新数据库\ssquant数据库_20260425\kline_data.db"
set "LOG_DIR=D:\BaiduNetdiskDownload\新数据库\ssquant数据库_20260425\auto_update_logs"
set "PYTHON=python"

:: 生成带时间戳的日志文件名
set "TIMESTAMP=%date:~0,4%%date:~5,2%%date:~8,2%_%time:~0,2%%time:~3,2%%time:~6,2%"
set "TIMESTAMP=!TIMESTAMP: =0!"
set "LOG_FILE=%LOG_DIR%\auto_update_!TIMESTAMP!.log"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

cd /d "%PROJECT_DIR%"

echo [START] SSQuant K-line auto update at %date% %time% >> "%LOG_FILE%"
echo DB: %DB_PATH% >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"

:: 执行更新（end_date 不传则默认更新到今天）
%PYTHON% update_kline_db.py --db-path "%DB_PATH%" >> "%LOG_FILE%" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"

echo. >> "%LOG_FILE%"
echo [EXIT] code=%EXIT_CODE% at %date% %time% >> "%LOG_FILE%"

:: 保留最近 30 天的日志，删除更旧的日志
forfiles /P "%LOG_DIR%" /M "auto_update_*.log" /D -30 /C "cmd /c del @path" 2>nul

exit /b %EXIT_CODE%
