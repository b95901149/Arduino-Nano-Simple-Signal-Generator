# 開發指令與流程

本文件記錄 AND Gate 測試器專案截至目前為止的開發環境設定、建置燒錄、測試指令與開發歷程。

> Serial 控制指令完整說明請見 [CLI.md](CLI.md)

---

## 專案路徑

```powershell
cd "d:\python\arduino ANDgate tester"
```

---

## 環境與依賴

```powershell
# 安裝 Python 依賴
C:\ProgramData\anaconda3\python.exe -m pip install -r requirements.txt

# 檢查 GUI 語法
C:\ProgramData\anaconda3\python.exe -m py_compile gui\main.py
```

---

## Arduino CLI 安裝（首次）

```powershell
$cliDir = "d:\python\arduino ANDgate tester\tools\arduino-cli"
New-Item -ItemType Directory -Force -Path $cliDir
Invoke-WebRequest -Uri "https://downloads.arduino.cc/arduino-cli/arduino-cli_latest_Windows_64bit.zip" -OutFile "$cliDir\arduino-cli.zip"
Expand-Archive -Path "$cliDir\arduino-cli.zip" -DestinationPath $cliDir -Force

& "$cliDir\arduino-cli.exe" version
& "$cliDir\arduino-cli.exe" core update-index
& "$cliDir\arduino-cli.exe" core install arduino:avr
```

---

## 韌體編譯與燒錄

| 項目 | 設定 |
|------|------|
| 開發板 | Arduino Nano |
| Processor | **ATmega328P (Old Bootloader)** |
| FQBN | `arduino:avr:nano:cpu=atmega328old` |
| 通訊速率 | 115200 baud（執行時 Serial） |

```powershell
$cli    = "d:\python\arduino ANDgate tester\tools\arduino-cli\arduino-cli.exe"
$sketch = "d:\python\arduino ANDgate tester\firmware\andgate_tester"
$fqbn   = "arduino:avr:nano:cpu=atmega328old"
$port   = "COM5"   # 依實際埠號修改

# 僅編譯
& $cli compile --fqbn $fqbn $sketch

# 僅燒錄
& $cli upload -p $port --fqbn $fqbn $sketch

# 編譯 + 燒錄
& $cli compile --fqbn $fqbn $sketch; & $cli upload -p $port --fqbn $fqbn $sketch
```

### Arduino IDE 燒錄

1. 開啟 `firmware\andgate_tester\andgate_tester.ino`
2. 工具 → 開發板 → **Arduino Nano**
3. 工具 → Processor → **ATmega328P (Old Bootloader)**
4. 選擇 COM 埠 → 上傳

上傳失敗（`stk500_recv()`）時，請確認 Bootloader 是否選 **Old Bootloader**。

---

## 啟動 GUI

```powershell
C:\ProgramData\anaconda3\python.exe "d:\python\arduino ANDgate tester\gui\main.py"
```

---

## 編譯 Windows 執行檔

```powershell
C:\ProgramData\anaconda3\python.exe -m pip install pyinstaller
cd "d:\python\arduino ANDgate tester"
.\scripts\build_exe.ps1
```

產出：`release\Arduino-Nano-Signal-Generator.exe`（約 7 MB，免安裝 Python）

---

## 偵測 COM 埠

```powershell
Get-WmiObject Win32_PnPEntity | Where-Object { $_.Caption -match 'COM\d+' } | Select-Object Caption
```

Nano 常見為 **USB-SERIAL CH340 (COMx)**。

---

## Serial 連線測試（Python）

```powershell
# 開機訊息
C:\ProgramData\anaconda3\python.exe -c "
import serial, time
s = serial.Serial('COM5', 115200, timeout=2)
time.sleep(2)
print(s.readline().decode())
s.close()
"
```

```powershell
# 批次指令測試
C:\ProgramData\anaconda3\python.exe -c "
import serial, time
s = serial.Serial('COM5', 115200, timeout=3)
time.sleep(2)
s.readline()
cmds = [
    'STOP', 'FREQ:1000', 'START', 'STATUS?',
    'PHASE:90', 'PHASE:180', 'STOP',
    'IN?', 'OUT:10:1', 'OUT?', 'OUT:10:0', 'OUT?'
]
for cmd in cmds:
    s.write((cmd + chr(10)).encode())
    s.flush()
    print(cmd, '->', s.readline().decode().strip())
s.close()
"
```

---

## 腳位配置

| 腳位 | 方向 | 功能 |
|------|------|------|
| D2 | OUTPUT | 信號 A（方波） |
| D3 | OUTPUT | 信號 B（方波，可調相位） |
| D5 | INPUT | 數位輸入 |
| D6 | INPUT | 數位輸入 |
| D7 | INPUT | 數位輸入 |
| D8 | INPUT | 數位輸入 |
| D9 | OUTPUT | 使用者可控輸出 |
| D10 | OUTPUT | 使用者可控輸出 |
| D11 | OUTPUT | 使用者可控輸出 |
| D12 | OUTPUT | 使用者可控輸出 |
| D13 | OUTPUT | 使用者可控輸出 |

---

## 專案結構

```
arduino ANDgate tester/
├── README.md
├── DEVELOPMENT.md          # 本文件
├── CLI.md                  # Serial 控制指令
├── requirements.txt
├── firmware/
│   └── andgate_tester/
│       └── andgate_tester.ino
├── gui/
│   └── main.py
└── tools/
    └── arduino-cli/        # 本機 arduino-cli
```

---

## 開發歷程

### 階段 1 — 需求規劃

- Arduino 產生 20 kHz 雙通道方波（D2/D3）
- 頻率與相位可調，Serial 指令 + Python GUI

### 階段 2 — 韌體初版

- Timer1 CTC + ISR 產生 50% 方波
- 直接操作 `PORTD` 切換 D2/D3
- Serial 協定：`FREQ` / `PHASE` / `START` / `STOP` / `STATUS?`

### 階段 3 — 硬體相容

- 開發板由 Mega 改為 **Arduino Nano**（`PORTD` PD2/PD3）
- Bootloader：**Old Bootloader**
- 關閉 Timer2 對 D3 的硬體 PWM
- 修正 ISR 內 `%` 取模導致 CPU 飽和、Serial 無回應
- 修正 `STOP` 無法真正停止輸出

### 階段 4 — GPIO 擴充

- D5–D8：`INPUT`，`IN?` 查詢
- D9–D13：`OUTPUT`，`OUT:<pin>:<0|1>` / `OUT?`

### 階段 5 — GUI 強化

- 相位滑桿拖曳即時更新（不中斷波形）
- COM 埠與 I/O 自動掃描
- 分頁介面：控制面板 + 說明

### 階段 6 — 待辦

- [ ] 自動測試序列（掃頻 / 掃相位）
- [ ] 示波器自動量測
- [ ] 高頻相位解析度提升

---

## 技術備註

1. **D3 / Timer2**：Arduino 開機預設啟用 D3 PWM，韌體須關閉 Timer2 OC2B。
2. **ISR 效能**：不可在 80 kHz ISR 內做除法／取模。
3. **相位更新**：`PHASE` 僅更新 `g_phase_offset`，輸出進行中不 STOP/START。
4. **頻率更新**：`FREQ` 執行中會短暫停止後重啟波形。
5. **燒錄 vs 執行**：Old Bootloader 影響上傳速率；執行時 Serial 固定 **115200 baud**。
