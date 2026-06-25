# 啟動 GUI（無命令列視窗）
$root = Split-Path -Parent $PSScriptRoot
$pythonw = "C:\ProgramData\anaconda3\pythonw.exe"
$script = Join-Path $root "gui\main.py"

if (-not (Test-Path $pythonw)) {
    Write-Error "找不到 pythonw.exe：$pythonw"
    exit 1
}

Start-Process -FilePath $pythonw -ArgumentList "`"$script`""
