# 編譯 Windows 執行檔
# 需先：C:\ProgramData\anaconda3\python.exe -m pip install pyinstaller

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

C:\ProgramData\anaconda3\python.exe -m PyInstaller `
    --onefile `
    --windowed `
    --name "Arduino-Nano-Signal-Generator" `
    --distpath release `
    --workpath build `
    --specpath build `
    --clean `
    gui\main.py

Write-Host "Done: release\Arduino-Nano-Signal-Generator.exe"
