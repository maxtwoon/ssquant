# SSQuant K 线数据库自动更新脚本 (PowerShell)
# 可被 Windows 任务计划程序调用
# 用法: powershell.exe -ExecutionPolicy Bypass -File "D:\repo\ssquant\auto_update.ps1"

$ProjectDir = "D:\repo\ssquant"
$DbPath = "D:\BaiduNetdiskDownload\新数据库\ssquant数据库_20260425\kline_data.db"
$LogDir = "D:\BaiduNetdiskDownload\新数据库\ssquant数据库_20260425\auto_update_logs"
$Python = "python"

# 创建日志目录
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$Timestamp = (Get-Date -Format "yyyyMMdd_HHmmss")
$LogFile = Join-Path $LogDir "auto_update_$Timestamp.log"

# 构建命令
$ArgumentList = @(
    "update_kline_db.py",
    "--db-path", $DbPath
    # 如需指定截止日期，取消下行注释
    # "--end-date", (Get-Date -Format "yyyy-MM-dd")
)

# 写入开始信息
"[START] SSQuant K-line auto update at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Out-File -FilePath $LogFile -Encoding utf8
"DB: $DbPath" | Out-File -FilePath $LogFile -Encoding utf8 -Append
"" | Out-File -FilePath $LogFile -Encoding utf8 -Append

# 执行更新
Push-Location $ProjectDir
try {
    & $Python @ArgumentList 2>&1 | Tee-Object -FilePath $LogFile -Append
    $ExitCode = $LASTEXITCODE
    if ($null -eq $ExitCode) { $ExitCode = 0 }
} finally {
    Pop-Location
}

# 写入退出信息
"" | Out-File -FilePath $LogFile -Encoding utf8 -Append
"[EXIT] code=$ExitCode at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Out-File -FilePath $LogFile -Encoding utf8 -Append

# 清理 30 天前的日志
Get-ChildItem -Path $LogDir -Filter "auto_update_*.log" -File |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
    Remove-Item -Force

exit $ExitCode
