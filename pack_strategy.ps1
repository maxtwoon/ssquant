# ============================================================================
# 缠论 5 分钟策略 — 打包脚本 (v0.4.7)
# 输出: D:\repo\ssquant\chanlun_5m_strategy_pack.zip
# 包含: 策略代码 + 文档 + 完整 ssquant 框架 (含 5 处修改 + Review 4 项修复)
# 排除: __pycache__ / .git / .venv / data_cache / backtest_results / 等
# ============================================================================

$ErrorActionPreference = 'Stop'

$src = 'D:\repo\ssquant'
$dst = 'D:\repo\ssquant\chanlun_5m_strategy_pack.zip'
$tmp = Join-Path $env:TEMP "ssquant_pack_$(Get-Random)"

Write-Host "[1/4] 准备临时目录: $tmp"
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

Write-Host "[2/4] 复制源代码 (robocopy, 显式列出排除项)..."
# 显式列出 /XD /XF,避免 PowerShell 数组 splat 在不同版本下行为不一致
& robocopy $src $tmp /E `
    /XD __pycache__ .git .venv .pytest_cache data_cache backtest_results `
        ssquant.egg-info build dist node_modules .idea .vscode `
    /XF *.pyc *.pyo *.log *.tmp .DS_Store *.conflict_bak `
        pack_strategy.ps1 verify_and_pack.bat verify_log.txt `
        resolve_conflicts.py resolve_conflicts.ps1 resolve_log.txt `
        run_resolve.bat pack_log.txt hello.txt chanlun_5m_strategy_pack.zip `
    /NP /NFL /NDL /NJH /NJS /R:1 /W:1 | Out-Null
# robocopy 退出码 < 8 都算成功
if ($LASTEXITCODE -ge 8) {
    Write-Error "robocopy 失败,退出码: $LASTEXITCODE"
    exit 1
}

# 验证 backtest_results 不在 tmp 里
$leak = Get-ChildItem $tmp -Recurse -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq 'backtest_results' -or $_.Name -eq '.git' -or $_.Name -eq '.venv' }
if ($leak) {
    Write-Warning "排除目录未生效:"
    $leak | ForEach-Object { Write-Warning "  - $($_.FullName)" }
}

Write-Host "[3/4] 压缩为 zip..."
if (Test-Path $dst) { Remove-Item $dst -Force }
Compress-Archive -Path (Join-Path $tmp '*') -DestinationPath $dst -CompressionLevel Optimal

Write-Host "[4/4] 清理临时目录"
Remove-Item $tmp -Recurse -Force

$size = (Get-Item $dst).Length
$sizeMB = [math]::Round($size / 1MB, 2)
Write-Host ""
Write-Host "================================================================"
Write-Host " 打包完成"
Write-Host "================================================================"
Write-Host " 输出文件 : $dst"
Write-Host " 文件大小 : $sizeMB MB ($size 字节)"
Write-Host "================================================================"
