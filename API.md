# 主副核心連線架構 — API 應用說明

本文件描述 **Arduino Nano 雙核心**（主核心 + 副核心）的硬體接線、通訊協定與完整指令 API，供 GUI、Python、序列監控器或上位機程式整合使用。

> 簡要指令表請見 [CLI.md](CLI.md)  
> 燒錄與開發流程請見 [DEVELOPMENT.md](DEVELOPMENT.md)

---

## 1. 系統架構概覽

```
┌──────────────────┐  USB 115200   ┌─────────────────────────────┐
│  PC / GUI        │◄─────────────►│  主核心 (andgate_tester)      │
│  pyserial        │               │  • D2/D3 方波產生              │
└──────────────────┘               │  • D9/D13 GPIO                 │
                                   │  • D10/D11 SoftwareSerial TX/RX│
                                   │  • D12 通訊觸發 OUTPUT         │
                                   └───────────┬─────────────────┘
                                               │
                     ┌─────────────────────────┼─────────────────────────┐
                     │  D11(TX)→D10(RX)  資料 │  D12(TRIG)→D12(IN) 觸發 │
                     │  D10(RX)←D11(TX)  資料 │  GND 共地                │
                     └─────────────────────────┼─────────────────────────┘
                                               ▼
                                   ┌─────────────────────────────┐
                                   │  副核心 (slave_core)          │
                                   │  • D10/D11 SoftwareSerial   │
                                   │  • D12 觸發閘門 (中斷/輪詢)   │
                                   │  • D9/D13 GPIO、D13 LED 閃爍  │
                                   │  • EEPROM 變數 A~E            │
                                   └───────────┬─────────────────┘
                                               │ USB 115200 (COM6)
                                               ▼
                                   ┌──────────────────┐
                                   │  PC 監聽 (可選)   │
                                   │  VARACK / 診斷    │
                                   └──────────────────┘
```

### 1.1 三層通訊路徑

| 層級 | 介面 | 鮑率 | 用途 |
|------|------|------|------|
| **L1 — 主控** | 主核心 USB Serial | 115200 | PC 控制方波、GPIO、轉送副核心指令 |
| **L2 — 主副通訊** | SoftwareSerial D10/D11 | 9600 | 主核心轉送指令至副核心 |
| **L3 — 副核心本機** | 副核心 USB Serial | 115200 | 直連除錯、`VARACK` 確認、組合型診斷 |

### 1.2 D12 觸發閘門（核心機制）

為避免 SoftwareSerial 干擾副核心的即時任務（如 LED 閃爍），採用 **D12 硬體觸發閘門**：

| D12 狀態 | 主核心行為 | 副核心行為 |
|----------|------------|------------|
| **LOW** | 不主動進行 SS 交易（`forwardToSlave` 仍由 PC 觸發時執行完整脈衝） | **忽略** SS 資料，執行本機任務（`updateBlink()` 等） |
| **HIGH** | 拉高 D12 → 送 SS 指令 → 等回應 → 拉低 D12 | **開啟閘門**，解析並執行 SS 指令 |

**主核心 `forwardToSlave` 時序（韌體自動完成）：**

1. 若方波輸出中，**暫停 Timer1**（避免干擾 SS 接收）
2. `D12 = HIGH`，等待 **5 ms** 穩定
3. 經 D11 送出指令（9600 baud）+ `flush()`
4. 經 D10 等待副核心回應（逾時 **800 ms**）
5. `D12 = LOW`
6. 若先前有輸出方波，**恢復 Timer1**

---

## 2. 硬體接線

### 2.1 必要接線（主副核心之間）

| 主核心腳位 | 方向 | 副核心腳位 | 說明 |
|------------|------|------------|------|
| **D11** | → | **D10** | SS 資料：主 TX → 副 RX |
| **D10** | ← | **D11** | SS 資料：副 TX → 主 RX |
| **D12** | → | **D12** | **觸發閘門（必接）** |
| **GND** | — | **GND** | 共地 |

### 2.2 主核心腳位功能

| 腳位 | 功能 | API 相關 |
|------|------|----------|
| D2 | 方波 A | `FREQ` / `PHASE` / `START` / `STOP` |
| D3 | 方波 B | 同上 |
| D5–D8 | 數位輸入 | `IN?` |
| D9, D13 | 數位輸出 | `OUT:<pin>:<0\|1>` / `OUT?` |
| D10 | SS RX | 內部，連副 D11 |
| D11 | SS TX | 內部，連副 D10 |
| D12 | SS 觸發輸出 | 內部，連副 D12 |

### 2.3 副核心腳位功能

| 腳位 | 功能 | API 相關 |
|------|------|----------|
| D5–D8 | 數位輸入 | `SS:IN?` 或 USB 直送 `IN?` |
| D9, D13 | 數位輸出 | `SS:OUT:...`；D13 亦為板載 LED |
| D10 | SS RX | 內部 |
| D11 | SS TX | 內部 |
| D12 | 觸發輸入（中斷） | 僅硬體閘門，不作 GPIO 輸出 |

---

## 3. 通訊協定通用規則

### 3.1 封包格式

- **一行一指令**，以 `\n` 或 `\r` 結尾
- 建議使用 **大寫** 指令
- 字元編碼：ASCII
- 查詢指令以 `?` 結尾

### 3.2 回應類型

| 類型 | 格式 | 說明 |
|------|------|------|
| 成功 | `OK` | 寫入/執行成功 |
| 資料 | `KEY=VAL,...` | 查詢回傳 |
| 副核心轉送 | `SSR:<副核心回應>` | 主核心轉發 SS 結果 |
| 錯誤 | `ERR:<代碼>` | 見第 7 節 |

### 3.3 上電訊息

| 裝置 | 訊息 |
|------|------|
| 主核心 | `READY ANDGATE_TESTER` |
| 副核心（USB） | 無固定 READY（SS 啟動時送 `READY SLAVE` 至 SS 匯流排） |

---

## 4. 主核心 API（USB 115200 → COM 主埠）

連線參數：`115200, 8N1`，行結尾 `\n`。

### 4.1 方波產生（D2 / D3）

| 指令 | 說明 | 回應 |
|------|------|------|
| `FREQ:<hz>` | 頻率 10 ~ 80000 Hz | `OK` / `ERR:FREQ_RANGE` |
| `PHASE:<deg>` | 相位 0 ~ 360°（輸出中可即時更新） | `OK` / `ERR:PHASE_RANGE` |
| `START` | 開始輸出方波 | `OK` / `ERR:TIMER` |
| `STOP` | 停止輸出，D2/D3 拉低 | `OK` |
| `STATUS?` | 查詢波形狀態 | `STATUS:FREQ=...,PHASE=...,RUN=...,STEPS=...` |

**範例：**

```
FREQ:20000
PHASE:90
START
STATUS?
```

### 4.2 主核心 GPIO

| 指令 | 說明 | 有效腳位 |
|------|------|----------|
| `IN?` | 讀取輸入 | D5, D6, D7, D8 |
| `OUT:<pin>:<level>` | 設定輸出 | **D9, D13** |
| `OUT:D<pin>:<level>` | 同上（可帶 D 前綴） | 同上 |
| `OUT?` | 查詢輸出狀態 | D9, D13 |

`<level>`：`0` = LOW，`1` = HIGH

### 4.3 副核心轉送（SS 閘門）

所有 `SS:` / `SVAR` 指令皆經 **D12 觸發 + SoftwareSerial** 轉送至副核心。

| 指令 | 說明 | 回應 |
|------|------|------|
| `SS:<副核心指令>` | 轉送任意副核心指令 | `SSR:<回應>` / `ERR:SS_TIMEOUT` |
| `SVAR?` | 讀取副核心 EEPROM 變數 | `SSR:VAR:A=...,E=...` |
| `SVAR:<子指令>` | 寫入副核心變數（等同 `SS:VAR:...`） | `SSR:OK` 等 |
| `SSDIAG?` | 查詢主核心 SS 埠狀態 | `SSDIAG:RX=D10,TX=D11,TRIG=D12,...` |

**`SVAR` 子指令對照：**

| 主核心指令 | 實際轉送 |
|------------|----------|
| `SVAR?` | `VAR?` |
| `SVAR:A:1.5` | `VAR:A:1.5` |
| `SVAR:ALL:0,0,0,0,2.0` | `VAR:ALL:0,0,0,0,2.0` |

**範例：**

```
SS:PING
SS:STATUS?
SS:BLINK:1000
SVAR:E:2.5
SSDIAG?
```

---

## 5. 副核心 API

副核心指令可透過兩種路徑送達：

| 路徑 | 前綴 | 觸發 D12 | 適用場景 |
|------|------|----------|----------|
| **經主核心** | PC → `SS:...` → 主核心 | 是（自動） | 正式操作、GUI |
| **USB 直連** | PC → COM6 直接送 | 否 | 除錯、組合型診斷 |

### 5.1 連線測試與狀態

| 指令 | 說明 | 回應 |
|------|------|------|
| `PING` | 連線測試 | `PONG` |
| `STATUS?` | 狀態查詢 | `SLAVE:OK,GATE=0\|1,BLINK=<ms>,VAR:A=<float>` |
| `SSRX?` | SS 接收統計（除錯） | `SSRX:LAST=...,CHARS=...,AVAIL=...` |

`GATE=1` 表示 D12 觸發閘門目前開啟。

### 5.2 數位 I/O

| 指令 | 說明 | 有效腳位 |
|------|------|----------|
| `IN?` | 讀取輸入 | D5 ~ D8 |
| `OUT:<pin>:<level>` | 設定輸出 | **D9, D13** |
| `OUT?` | 查詢輸出 | D9, D13 |

### 5.3 D13 LED 閃爍

| 指令 | 說明 | 回應 |
|------|------|------|
| `BLINK:<ms>` | 週期閃爍（100 ~ 5000 ms） | `OK` / `ERR:BLINK_RANGE` |
| `BLINK:0` / `BLINK:STOP` | 停止閃爍 | `OK` |

變更閃爍週期會同步更新 EEPROM 變數 **E**（秒），並從 USB 送出 `VARACK`。

### 5.4 EEPROM 浮點變數（A ~ E）

| 變數 | 說明 | 預設 |
|------|------|------|
| A ~ D | 通用浮點參數 | 0.0 |
| **E** | **LED 閃爍週期（秒）**，範圍 0.1 ~ 5.0 | 1.0 |

| 指令 | 說明 | 回應 |
|------|------|------|
| `VAR?` | 讀取全部變數 | `VAR:A=0.000,B=0.000,C=0.000,D=0.000,E=1.000` |
| `VAR:<名稱>:<值>` | 設定單一變數 | `OK` |
| `VAR:<名稱>=<值>` | 同上 | `OK` |
| `VAR:ALL:a,b,c,d,e` | 一次設定五個 | `OK` |

**變更確認（USB COM6）：**

變數寫入 EEPROM 後，副核心自動從 USB 送出：

```
VARACK:A=0.000,B=0.000,C=0.000,D=0.000,E=2.500
```

**變數 E 與閃爍連動：**

- 修改 `E` → 自動依秒數更新 D13 閃爍週期並啟動
- 修改 `BLINK:<ms>` → 自動回寫 `E` 並送 `VARACK`

---

## 6. 應用整合模式

### 6.1 單埠模式（僅主核心 COM5）

```
PC ──USB──► 主核心
              └── SS + D12 ──► 副核心（無 USB 監聽）
```

- 所有副核心操作：`SS:<cmd>` 或 `SVAR...`
- 變更確認僅能從 `SSR:OK` 得知，**不會**收到 `VARACK`

### 6.2 組合型模式（主 COM5 + 副 COM6）

```
PC ──USB──► 主核心 ── SS/D12 ──► 副核心
PC ──USB──► 副核心（監聽 VARACK / 診斷）
```

- GUI「組合型」同時開啟兩個 Serial
- 適合驗證 D12 觸發、觀察 `VARACK`、執行組合診斷
- 副核心 USB 直送 `PING` 可驗證副核心韌體獨立運作

### 6.3 典型應用流程

#### A. 方波 + 副核心 LED 閃爍

```
# 主核心
FREQ:20000
PHASE:0
START

# 副核心（經 SS）
SS:BLINK:1000
```

#### B. 透過 EEPROM 變數 E 設定閃爍（2.5 秒）

```
SVAR:E:2.5
# 或
SS:VAR:ALL:0,0,0,0,2.5
```

組合型下 COM6 應收到：`VARACK:...E=2.500`

#### C. 讀寫副核心 GPIO

```
SS:OUT:9:1
SS:OUT?
SS:IN?
```

#### D. 完整診斷序列

```
SSDIAG?
SS:PING
SS:STATUS?
SS:VAR?
```

---

## 7. 錯誤代碼

### 7.1 主核心

| 代碼 | 說明 |
|------|------|
| `ERR:UNKNOWN` | 無法辨識的指令 |
| `ERR:FREQ_RANGE` | 頻率超出 10 ~ 80000 Hz |
| `ERR:PHASE_RANGE` | 相位超出 0 ~ 360 |
| `ERR:TIMER` | Timer 設定失敗 |
| `ERR:OUT_FORMAT` | `OUT:` 格式錯誤 |
| `ERR:OUT_PIN` | 腳位非 D9 / D13 |
| `ERR:SS_EMPTY` | `SS:` 後無指令 |
| `ERR:SS_TIMEOUT` | 副核心 SS 逾時（800 ms）；檢查 D12/D10/D11 接線 |

### 7.2 副核心

| 代碼 | 說明 |
|------|------|
| `ERR:UNKNOWN` | 無法辨識的指令 |
| `ERR:OUT_FORMAT` | `OUT:` 格式錯誤 |
| `ERR:OUT_PIN` | 腳位非 D9 / D13 |
| `ERR:BLINK_RANGE` | 閃爍週期超出 100 ~ 5000 ms |
| `ERR:VAR_FORMAT` | 變數格式錯誤 |
| `ERR:VAR_NAME` | 變數名非 A ~ E |

---

## 8. Python 整合範例

### 8.1 基本連線（僅主核心）

```python
import serial
import time

PORT = "COM5"
BAUD = 115200

def send(ser, cmd: str) -> str:
    ser.write((cmd + "\n").encode())
    ser.flush()
    return ser.readline().decode(errors="ignore").strip()

with serial.Serial(PORT, BAUD, timeout=2) as ser:
    time.sleep(0.3)
    print(ser.readline().decode(errors="ignore").strip())  # READY

    print(send(ser, "SS:PING"))           # SSR:PONG
    print(send(ser, "SS:BLINK:1000"))     # SSR:OK
    print(send(ser, "SVAR?"))             # SSR:VAR:A=...
    print(send(ser, "FREQ:20000"))
    print(send(ser, "START"))
```

### 8.2 組合型 — 監聽 VARACK

```python
import serial
import threading
import time

def monitor_slave(port: str):
    with serial.Serial(port, 115200, timeout=0.1) as s:
        while True:
            line = s.readline().decode(errors="ignore").strip()
            if line.startswith("VARACK:"):
                print(f"[COM6] {line}")

threading.Thread(target=monitor_slave, args=("COM6",), daemon=True).start()

with serial.Serial("COM5", 115200, timeout=2) as master:
    time.sleep(0.5)
    master.readline()
    master.write(b"SVAR:E:1.5\n")
    master.flush()
    print(master.readline().decode().strip())  # SSR:OK
    time.sleep(0.5)  # 等待 VARACK 出現在 COM6
```

### 8.3 錯誤處理建議

```python
def send_ss(ser, cmd: str) -> str:
    resp = send(ser, f"SS:{cmd}")
    if resp == "ERR:SS_TIMEOUT":
        raise RuntimeError(
            "副核心 SS 逾時 — 請確認主 D12→副 D12、D11→D10、D10←D11、GND"
        )
    if resp.startswith("SSR:"):
        return resp[4:]
    return resp
```

---

## 9. 即時性與設計注意事項

1. **D12 必接**：未接觸發線時，副核心永遠忽略 SS → `ERR:SS_TIMEOUT`。
2. **方波與 SS 互斥**：主核心在 SS 交易期間會短暫停止方波，交易完成後自動恢復。
3. **副核心本機任務**：D12 為 LOW 時，副核心專注 `updateBlink()` 等本機邏輯，不被 SS 打斷。
4. **D13 共用**：板載 LED 與 `OUT:13` / `BLINK` 共用 D13；手動 `OUT:13` 會停止閃爍模式。
5. **變數 E**：建議以秒為單位操作閃爍；與 `BLINK:<ms>` 會雙向同步。
6. **逾時設定**：SS 回應逾時 800 ms；觸發穩定時間 5 ms（韌體常數，見 `andgate_tester.ino`）。

---

## 10. 韌體對照

| 角色 | 檔案 | FQBN |
|------|------|------|
| 主核心 | `firmware/andgate_tester/andgate_tester.ino` | `arduino:avr:nano:cpu=atmega328old` |
| 副核心 | `firmware/slave_core/slave_core.ino` | 同上 |

---

## 11. 指令速查表

### 主核心（USB）

```
FREQ:<hz>          PHASE:<deg>         START / STOP
STATUS?            IN?                 OUT? / OUT:<pin>:<0|1>
SS:<slave_cmd>     SVAR? / SVAR:...    SSDIAG?
```

### 副核心（SS 或 USB 直送）

```
PING               STATUS?             SSRX?
IN?                OUT? / OUT:<pin>:<0|1>
BLINK:<ms>         BLINK:0
VAR?               VAR:<X>:<val>       VAR:ALL:a,b,c,d,e
```

### 常用組合

```
SS:PING                              → SSR:PONG
SS:BLINK:1000                        → SSR:OK
SVAR:E:2.0                           → SSR:OK (+ VARACK on COM6)
SS:VAR:ALL:1,2,3,4,5                 → SSR:OK
SSDIAG?                              → SSDIAG:RX=D10,TX=D11,TRIG=D12,...
```

---

*文件版本對應韌體：主/副核心含 D12 觸發閘門、EEPROM 變數 A~E、E 連動 LED 閃爍。*
