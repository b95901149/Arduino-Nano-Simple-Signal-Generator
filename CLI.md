# Serial CLI 控制指令

透過 USB Serial 以文字指令控制 Arduino Nano。適用於：

- Arduino IDE **序列埠監控器**
- `arduino-cli monitor`
- Python `pyserial`、PuTTY、Tera Term 等終端機

---

## 連線參數

| 項目 | 值 |
|------|-----|
| 鮑率 | **115200** |
| 資料位 | 8 |
| 同位檢查 | None |
| 停止位 | 1 |
| 行結尾 | `\n` 或 `\r` |

上電或重設後，裝置會送出：

```
READY ANDGATE_TESTER
```

---

## 指令格式

- 每行一筆指令
- 大小寫須完全符合（建議全大寫）
- 成功多數回應 `OK`，查詢指令回傳資料行

---

## 指令一覽

### 波形產生（D2 / D3）

| 指令 | 說明 | 範例 |
|------|------|------|
| `FREQ:<hz>` | 設定頻率（10 ~ 80000 Hz） | `FREQ:20000` |
| `PHASE:<deg>` | 設定相位差 0 ~ 360°（B 相對 A） | `PHASE:90` |
| `START` | 開始輸出方波 | `START` |
| `STOP` | 停止輸出，D2/D3 拉低 | `STOP` |
| `STATUS?` | 查詢波形狀態 | `STATUS?` |

### 數位輸入（D5 ~ D8）

| 指令 | 說明 | 範例 |
|------|------|------|
| `IN?` | 讀取 D5、D6、D7、D8 狀態 | `IN?` |

### 數位輸出（主核心 D9 / D12 / D13）

| 指令 | 說明 | 範例 |
|------|------|------|
| `OUT:<pin>:<level>` | 設定輸出腳位 High/Low | `OUT:9:1` |
| `OUT:D<pin>:<level>` | 同上，可帶 D 前綴 | `OUT:D12:1` |
| `OUT?` | 查詢 D9 / D12 / D13 狀態 | `OUT?` |

> D10、D11 保留給 **SoftwareSerial**（9600 baud），不可作 GPIO 輸出。

### 副核心轉送（SoftwareSerial D10/D11）

| 指令 | 說明 | 範例 |
|------|------|------|
| `SS:<cmd>` | 轉送指令至副核心 Arduino | `SS:PING` |
| 回應 | 副核心回應以 `SSR:` 為前綴 | `SSR:PONG` |

副核心使用 `firmware/slave_core/slave_core.ino`，支援：`PING`、`STATUS?`、`IN?`、`OUT?`、`OUT:<pin>:<0\|1>`、`BLINK:<ms>`、`BLINK:0`（D13 閃爍週期 100~5000 ms）。

`<level>`：`0` = LOW，`1` = HIGH  
`<pin>`：僅接受 **9、10、11、12、13**

---

## 回應格式

### 成功

```
OK
```

### 查詢波形

```
STATUS:FREQ=20000,PHASE=90,RUN=1,STEPS=4
```

| 欄位 | 說明 |
|------|------|
| `FREQ` | 目前頻率（Hz） |
| `PHASE` | 目前相位（°） |
| `RUN` | `1` 輸出中 / `0` 已停止 |
| `STEPS` | 每週期離散步數（相位解析度相關） |

### 查詢輸入

```
IN:D5=0,D6=1,D7=0,D8=0
```

### 查詢輸出

```
OUT:D9=0,D10=1,D11=0,D12=0,D13=0
```

### 錯誤

```
ERR:<代碼>
```

| 代碼 | 說明 |
|------|------|
| `ERR:UNKNOWN` | 無法辨識的指令 |
| `ERR:FREQ_RANGE` | 頻率超出 10 ~ 80000 Hz |
| `ERR:PHASE_RANGE` | 相位超出 0 ~ 360 |
| `ERR:TIMER` | Timer 設定失敗 |
| `ERR:OUT_FORMAT` | `OUT:` 格式錯誤 |
| `ERR:OUT_PIN` | 腳位非 D9 / D12 / D13（主核心） |
| `ERR:SS_EMPTY` | `SS:` 後無指令 |
| `ERR:SS_TIMEOUT` | 副核心無回應（500 ms） |

---

## 指令詳解

### `FREQ:<hz>`

設定 D2/D3 方波頻率。

```
FREQ:20000
```

- 範圍：10 ~ 80000
- 若波形正在輸出，會短暫停止後以新頻率重啟

### `PHASE:<deg>`

設定 B 通道（D3）相對 A 通道（D2）的相位延遲。

```
PHASE:90
```

- 範圍：0 ~ 360
- **輸出進行中可即時更新**，不會中斷波形
- 實際解析度受頻率影響（見 README 相位解析度表）

### `START`

開始產生方波。

```
START
```

- 成功：`OK`
- Timer 設定失敗：`ERR:TIMER`

### `STOP`

停止方波，D2、D3 設為 LOW。

```
STOP
```

### `STATUS?`

```
STATUS?
```

回應範例：

```
STATUS:FREQ=20000,PHASE=0,RUN=0,STEPS=4
```

### `IN?`

讀取 D5 ~ D8 邏輯位準（浮接腳位可能不穩定）。

```
IN?
```

### `OUT:<pin>:<level>`

設定 D9 ~ D13 輸出。

```
OUT:9:1
OUT:10:0
OUT:D13:1
```

### `OUT?`

```
OUT?
```

---

## 常用操作範例

### 基本方波測試（20 kHz，同相）

```
STOP
FREQ:20000
PHASE:0
START
STATUS?
```

### 掃描相位（20 kHz）

```
FREQ:20000
START
PHASE:0
PHASE:90
PHASE:180
PHASE:270
STOP
```

### 低頻測試（較細相位）

```
FREQ:1000
PHASE:45
START
STATUS?
```

### 讀寫 GPIO

```
IN?
OUT:9:1
OUT:10:1
OUT?
OUT:9:0
OUT:10:0
```

### 副核心測試

```
SS:PING
SS:STATUS?
SS:IN?
SS:OUT:12:1
SS:OUT?
SS:BLINK:1000
SS:BLINK:0
```

`SS:BLINK:<ms>` 控制副核心 D13 LED 閃爍週期（100 ~ 5000 ms）；`SS:BLINK:0` 停止。

### 完整測試流程

```
STOP
FREQ:20000
PHASE:0
START
STATUS?
IN?
OUT:12:1
OUT?
STOP
STATUS?
```

---

## arduino-cli 序列監控

```powershell
$cli  = "d:\python\arduino ANDgate tester\tools\arduino-cli\arduino-cli.exe"
$port = "COM5"

& $cli monitor -p $port -c baudrate=115200
```

監控器中直接輸入指令，例如 `STATUS?` 後按 Enter。

結束監控：`Ctrl+C`

---

## Python 單行送指令

```powershell
C:\ProgramData\anaconda3\python.exe -c "import serial; s=serial.Serial('COM5',115200,timeout=2); s.write(b'STATUS?\n'); print(s.readline().decode()); s.close()"
```

---

## 腳位與指令對照

| 腳位 | CLI 相關指令 |
|------|----------------|
| D2 | `START` / `STOP` / `FREQ` / `PHASE` |
| D3 | 同上 |
| D5 | `IN?` |
| D6 | `IN?` |
| D7 | `IN?` |
| D8 | `IN?` |
| D9 | `OUT:9:0` / `OUT:9:1` / `OUT?` |
| D10 | SoftwareSerial RX（連副核心 TX） |
| D11 | SoftwareSerial TX（連副核心 RX） |
| D12 | `OUT:12:0` / `OUT:12:1` / `OUT?` |
| D13 | `OUT:13:0` / `OUT:13:1` / `OUT?` |
