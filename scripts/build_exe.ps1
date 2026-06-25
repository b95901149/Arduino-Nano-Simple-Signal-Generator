# 編譯 Windows 執行檔
# 需先：C:\ProgramData\anaconda3\python.exe -m pip install pyinstaller

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = "C:\ProgramData\anaconda3\python.exe"
$condaLib = "C:\ProgramData\anaconda3\Library"

& $python -m PyInstaller `
    --onefile `
    --windowed `
    --name "Arduino-Nano-Signal-Generator" `
    --distpath release `
    --workpath build `
    --specpath build `
    --paths "$condaLib\bin" `
    --add-binary "$condaLib\bin\tcl86t.dll;." `
    --add-binary "$condaLib\bin\tk86t.dll;." `
    --add-binary "$condaLib\bin\ffi.dll;." `
    --add-data "$condaLib\lib\tcl8.6;tcl/tcl8.6" `
    --add-data "$condaLib\lib\tk8.6;tk/tk8.6" `
    --clean `
    gui\main.py

Write-Host "Done: release\Arduino-Nano-Signal-Generator.exe"
