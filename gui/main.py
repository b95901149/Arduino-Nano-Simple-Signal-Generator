"""Arduino Nano AND Gate Tester - Serial control GUI."""

from __future__ import annotations

import os
import sys


def _configure_frozen_tcl_tk() -> None:
    """Set Tcl/Tk library paths when running as PyInstaller onefile."""
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS
        os.environ["PATH"] = base + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(base)
        os.environ["TCL_LIBRARY"] = os.path.join(base, "tcl", "tcl8.6")
        os.environ["TK_LIBRARY"] = os.path.join(base, "tk", "tk8.6")


_configure_frozen_tcl_tk()

import re
import time
import atexit
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from typing import Dict, List, Optional, Tuple

import serial
import serial.tools.list_ports


DEFAULT_FREQ_HZ = 20000
DEFAULT_PHASE_DEG = 0
BAUD_RATE = 115200
INPUT_PINS = (5, 6, 7, 8)
OUTPUT_PINS = (9, 12, 13)
SLAVE_OUTPUT_PINS = (9, 12, 13)
POLL_MS = 250
PORT_SCAN_MS = 1500
SLAVE_MONITOR_MS = 50
PHASE_DEBOUNCE_MS = 40
BLINK_DEBOUNCE_MS = 80
BLINK_MIN_SEC = 0.1
BLINK_MAX_SEC = 5.0
BLINK_DEFAULT_SEC = 1.0

SLAVE_VAR_NAMES = ("A", "B", "C", "D", "E")
VAR_ACK_WAIT_MS = 1200

ARDUINO_PORT_HINTS = ("ch340", "arduino", "usb-serial", "ftdi", "cp210", "wch")
VAR_LINE_RE = re.compile(r"([ABCDE])=([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)")

DOCS_TEXT = """\
═══════════════════════════════════════
  AND Gate 測試器 — 使用說明
═══════════════════════════════════════

【硬體需求】
  • Arduino Nano（ATmega328P，Old Bootloader）
  • USB 連線至電腦（CH340 / FTDI 轉串列埠）

【腳位配置】
  D2      信號 A（方波輸出）
  D3      信號 B（方波輸出，可調相位）
  D5–D8   數位輸入（自動掃描顯示 HIGH / LOW）
  D9/D12/D13  主核心數位輸出
  D10/D11 SoftwareSerial 9600 → 副核心 Arduino

【副核心接線（Software Serial）】
  主 D11 (TX) ──► 副 D10 (RX)
  主 D10 (RX) ◄── 副 D11 (TX)
  GND 共地

【快速操作】
  1. 啟動 GUI，程式會自動掃描 COM 埠
  2. 選擇正確埠號（含 CH340 者通常為 Nano）→ 連線
  3. 設定頻率（預設 20000 Hz）→ 按「套用頻率」
  4. 按「開始輸出」產生 D2/D3 方波
  5. 拖動相位滑桿可即時調整兩通道相位差
  6. D5–D8 輸入狀態自動更新；D9/D12/D13 可手動切換輸出
  7. 「副核心」區塊透過 D10/D11 控制另一片 Arduino

【AND 閘測試接線】
  Nano D2 ──► AND 輸入 A
  Nano D3 ──► AND 輸入 B
  Nano GND ─┴─ AND GND
  AND 輸出 Y ──► 示波器

【技術規格】
  • 頻率範圍：約 10 Hz ~ 80 kHz
  • 預設頻率：20 kHz
  • 相位：0° ~ 360°（拖曳即時更新）
  • 20 kHz 時相位解析度約 90°（0°/90°/180°/270°）
  • 占空比：固定 50%

【燒錄韌體】
  Arduino IDE → 開發板：Arduino Nano
  Processor：ATmega328P (Old Bootloader)
  或使用 arduino-cli 上傳至 COM 埠

═══════════════════════════════════════
  開發流程紀錄
═══════════════════════════════════════

階段 1 — 需求規劃
  • 以 Arduino Nano 產生 20 kHz 雙通道方波
  • D2/D3 輸出，頻率與相位可調
  • Serial 指令控制 + Python GUI

階段 2 — 韌體開發
  • Timer1 CTC 模式驅動 ISR 產生方波
  • 直接操作 PORTD 暫存器（D2/D3）以達高速切換
  • 自適應每週期步數，平衡頻率與相位解析度
  • Serial 協定：FREQ / PHASE / START / STOP / STATUS?

階段 3 — 硬體相容修正
  • 確認使用 Arduino Nano（非 Mega），腳位改為 PORTD
  • Bootloader 選 Old Bootloader
  • 關閉 Timer2 對 D3 的硬體 PWM 干擾
  • 修正 ISR 內除法導致 CPU 飽和、Serial 無回應問題
  • 修正 STOP 無法真正停止輸出

階段 4 — GPIO 擴充
  • D5–D8 設為 INPUT，指令 IN? 查詢
  • D9–D13 設為 OUTPUT，指令 OUT:<pin>:<0|1>
  • GUI 面板顯示輸入、控制輸出

階段 5 — GUI 強化
  • 相位滑桿拖曳即時更新波形（不中斷輸出）
  • COM 埠與 I/O 狀態自動掃描
  • 新增說明分頁（本頁）

階段 6 — 待辦（可選）
  □ 自動測試序列（掃頻 / 掃相位）
  □ 示波器自動量測整合
  □ 提升高頻相位解析度

【Serial 指令參考】
  FREQ:<hz>       設定頻率
  PHASE:<deg>     設定相位（0~360）
  START / STOP    開始 / 停止方波輸出
  STATUS?         查詢波形狀態
  IN?             讀取 D5–D8 輸入
  OUT:<pin>:<0|1> 設定 D9/D12/D13 輸出
  OUT?            查詢 D9/D12/D13 輸出狀態
  SS:<cmd>        轉送指令至副核心（回應 SSR:...）
  SVAR? / SVAR:ALL:a,b,c,d,e  讀寫副核心 EEPROM 變數 A~E (float)
  副核心變更後會從 COM6 (USB) 送出 VARACK:...

【組合型診斷】
  同時連線主核心 USB + 副核心 USB，監看副核心 SSRXC/SSRX 行
  以確認 D10/D11 交叉接線與 9600 baud 通訊是否正常
"""


class AndGateTesterApp:
    """Tkinter GUI for controlling the AND gate signal generator."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Arduino Nano Simple Signal Generator")
        self.root.minsize(880, 720)

        self._serial: Optional[serial.Serial] = None
        self._slave_serial: Optional[serial.Serial] = None
        self._poll_job: Optional[str] = None
        self._port_scan_job: Optional[str] = None
        self._slave_monitor_job: Optional[str] = None
        self._phase_job: Optional[str] = None
        self._last_applied_phase: Optional[int] = None
        self._known_ports: List[str] = []
        self._output_state: Dict[int, int] = {pin: 0 for pin in OUTPUT_PINS}
        self._output_labels: Dict[int, ttk.Label] = {}
        self._input_labels: Dict[int, ttk.Label] = {}
        self._slave_output_labels: Dict[int, ttk.Label] = {}
        self._slave_status_var = tk.StringVar(value="未連線副核心")
        self._blink_job: Optional[str] = None
        self._last_blink_ms: Optional[int] = None
        self._blink_running = False
        self._slave_var_vars: Dict[str, tk.StringVar] = {
            name: tk.StringVar(value="1.0" if name == "E" else "0.0")
            for name in SLAVE_VAR_NAMES
        }
        self._var_ack_var = tk.StringVar(value="尚未更新 EEPROM 變數")
        self._closing = False

        self._build_ui()
        self._refresh_ports()
        self._start_port_scan()
        atexit.register(self._atexit_release_ports)

    def _build_ui(self) -> None:
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        control_tab = ttk.Frame(notebook, padding=4)
        docs_tab = ttk.Frame(notebook, padding=4)
        notebook.add(control_tab, text="控制面板")
        notebook.add(docs_tab, text="說明")

        self._build_control_tab(control_tab)
        self._build_docs_tab(docs_tab)

    def _build_control_tab(self, parent: ttk.Frame) -> None:
        conn_frame = ttk.LabelFrame(parent, text="連線（COM 埠自動掃描）", padding=8)
        conn_frame.pack(fill=tk.X, padx=6, pady=6)

        mode_row = ttk.Frame(conn_frame)
        mode_row.grid(row=0, column=0, columnspan=3, sticky=tk.W, pady=(0, 6))
        ttk.Label(mode_row, text="連線模式").pack(side=tk.LEFT)
        self.conn_mode_var = tk.StringVar(value="single")
        ttk.Radiobutton(
            mode_row,
            text="僅主核心",
            variable=self.conn_mode_var,
            value="single",
            command=self._on_conn_mode_change,
        ).pack(side=tk.LEFT, padx=(8, 4))
        ttk.Radiobutton(
            mode_row,
            text="組合型（主 + 副 USB）",
            variable=self.conn_mode_var,
            value="combo",
            command=self._on_conn_mode_change,
        ).pack(side=tk.LEFT, padx=4)

        ttk.Label(conn_frame, text="主核心 COM").grid(row=1, column=0, sticky=tk.W)
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(
            conn_frame, textvariable=self.port_var, width=28, state="readonly"
        )
        self.port_combo.grid(row=1, column=1, padx=6, sticky=tk.EW)
        conn_frame.columnconfigure(1, weight=1)

        ttk.Label(conn_frame, text="副核心 COM").grid(row=2, column=0, sticky=tk.W, pady=(6, 0))
        self.slave_port_var = tk.StringVar()
        self.slave_port_combo = ttk.Combobox(
            conn_frame, textvariable=self.slave_port_var, width=28, state="readonly"
        )
        self.slave_port_combo.grid(row=2, column=1, padx=6, sticky=tk.EW, pady=(6, 0))

        self.scan_status_var = tk.StringVar(value="掃描中…")
        ttk.Label(conn_frame, textvariable=self.scan_status_var, foreground="gray").grid(
            row=3, column=0, columnspan=2, sticky=tk.W, pady=(4, 0)
        )

        btn_row = ttk.Frame(conn_frame)
        btn_row.grid(row=1, column=2, rowspan=3, padx=4)
        self.connect_btn = ttk.Button(btn_row, text="連線", command=self._toggle_connection)
        self.connect_btn.pack(pady=2)
        self.slave_monitor_btn = ttk.Button(
            btn_row, text="監聽副核心", command=self._toggle_slave_monitor, state=tk.DISABLED
        )
        self.slave_monitor_btn.pack(pady=2)

        self._on_conn_mode_change()

        body_frame = ttk.Frame(parent)
        body_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        left_col = ttk.Frame(body_frame)
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 3), pady=4)

        right_col = ttk.Frame(body_frame)
        right_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(3, 6), pady=4)

        param_frame = ttk.LabelFrame(left_col, text="信號產生 (D2/D3)", padding=8)
        param_frame.pack(fill=tk.X, pady=(0, 4))

        ttk.Label(param_frame, text="頻率 (Hz)").grid(row=0, column=0, sticky=tk.W)
        self.freq_var = tk.StringVar(value=str(DEFAULT_FREQ_HZ))
        ttk.Entry(param_frame, textvariable=self.freq_var, width=12).grid(
            row=0, column=1, padx=6, sticky=tk.W
        )
        ttk.Button(param_frame, text="套用頻率", command=self._apply_freq).grid(
            row=0, column=2, padx=4
        )

        ttk.Label(param_frame, text="相位差 (°)").grid(row=1, column=0, sticky=tk.W, pady=6)
        self.phase_var = tk.IntVar(value=DEFAULT_PHASE_DEG)
        self.phase_scale = ttk.Scale(
            param_frame,
            from_=0,
            to=360,
            variable=self.phase_var,
            orient=tk.HORIZONTAL,
            length=200,
            command=self._on_phase_drag,
        )
        self.phase_scale.grid(row=1, column=1, columnspan=2, sticky=tk.EW, padx=6)
        param_frame.columnconfigure(1, weight=1)
        self.phase_label = ttk.Label(param_frame, text="0°")
        self.phase_label.grid(row=1, column=3)

        ctrl_frame = ttk.Frame(param_frame)
        ctrl_frame.grid(row=2, column=0, columnspan=4, pady=(6, 0), sticky=tk.W)
        ttk.Button(ctrl_frame, text="開始輸出", command=self._start).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl_frame, text="停止輸出", command=self._stop).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl_frame, text="查詢狀態", command=self._query_status).pack(
            side=tk.LEFT, padx=4
        )

        io_frame = ttk.Frame(left_col, padding=0)
        io_frame.pack(fill=tk.BOTH, expand=True)

        in_frame = ttk.LabelFrame(io_frame, text="數位輸入 D5–D8（自動掃描）", padding=8)
        in_frame.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))
        for pin in INPUT_PINS:
            row = ttk.Frame(in_frame)
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=f"D{pin}", width=4).pack(side=tk.LEFT)
            lbl = ttk.Label(row, text="—", width=8, anchor=tk.CENTER)
            lbl.pack(side=tk.LEFT, padx=4)
            self._input_labels[pin] = lbl

        out_frame = ttk.LabelFrame(io_frame, text="主核心輸出 D9/D12/D13", padding=8)
        out_frame.pack(side=tk.TOP, fill=tk.X)
        for pin in OUTPUT_PINS:
            row = ttk.Frame(out_frame)
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=f"D{pin}", width=4).pack(side=tk.LEFT)
            hi_btn = ttk.Button(
                row, text="HIGH", width=6, command=lambda p=pin: self._set_output(p, 1)
            )
            lo_btn = ttk.Button(
                row, text="LOW", width=6, command=lambda p=pin: self._set_output(p, 0)
            )
            hi_btn.pack(side=tk.LEFT, padx=2)
            lo_btn.pack(side=tk.LEFT, padx=2)
            st = ttk.Label(row, text="—", width=6, anchor=tk.CENTER)
            st.pack(side=tk.LEFT, padx=4)
            self._output_labels[pin] = st

        slave_frame = ttk.LabelFrame(
            right_col, text="副核心 (Software Serial D10/D11 @ 9600)", padding=8
        )
        slave_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(slave_frame, textvariable=self._slave_status_var, foreground="gray").pack(
            anchor=tk.W
        )

        ss_btn_row = ttk.Frame(slave_frame)
        ss_btn_row.pack(fill=tk.X, pady=4)
        ttk.Button(ss_btn_row, text="PING", command=lambda: self._ss_ping()).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(ss_btn_row, text="狀態", command=lambda: self._ss_command("STATUS?")).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(ss_btn_row, text="IN?", command=lambda: self._ss_command("IN?")).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(ss_btn_row, text="OUT?", command=lambda: self._ss_command("OUT?")).pack(
            side=tk.LEFT, padx=2
        )

        ss_io = ttk.LabelFrame(slave_frame, text="副核心輸出 D9/D12/D13", padding=6)
        ss_io.pack(fill=tk.X, pady=4)
        for pin in SLAVE_OUTPUT_PINS:
            row = ttk.Frame(ss_io)
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=f"D{pin}", width=4).pack(side=tk.LEFT)
            ttk.Button(
                row, text="HIGH", width=6, command=lambda p=pin: self._ss_set_output(p, 1)
            ).pack(side=tk.LEFT, padx=2)
            ttk.Button(
                row, text="LOW", width=6, command=lambda p=pin: self._ss_set_output(p, 0)
            ).pack(side=tk.LEFT, padx=2)
            lbl = ttk.Label(row, text="—", width=6, anchor=tk.CENTER)
            lbl.pack(side=tk.LEFT, padx=4)
            self._slave_output_labels[pin] = lbl

        var_frame = ttk.LabelFrame(slave_frame, text="EEPROM 變數 (float A~E)", padding=6)
        var_frame.pack(fill=tk.X, pady=(4, 0))

        for row_idx, name in enumerate(SLAVE_VAR_NAMES):
            label = "E (閃爍秒)" if name == "E" else name
            ttk.Label(var_frame, text=label, width=8 if name == "E" else 2).grid(
                row=row_idx, column=0, sticky=tk.W, padx=(0, 4), pady=2
            )
            ttk.Entry(var_frame, textvariable=self._slave_var_vars[name], width=12).grid(
                row=row_idx, column=1, sticky=tk.EW, pady=2
            )
        var_frame.columnconfigure(1, weight=1)

        var_btn_row = ttk.Frame(var_frame)
        var_btn_row.grid(row=len(SLAVE_VAR_NAMES), column=0, columnspan=2, sticky=tk.W, pady=(6, 0))
        ttk.Button(var_btn_row, text="更新變數", command=self._update_slave_vars).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(var_btn_row, text="讀取變數", command=self._query_slave_vars).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Label(var_frame, textvariable=self._var_ack_var, foreground="gray", wraplength=280).grid(
            row=len(SLAVE_VAR_NAMES) + 1, column=0, columnspan=2, sticky=tk.W, pady=(4, 0)
        )

        blink_frame = ttk.LabelFrame(slave_frame, text="D13 LED 閃爍", padding=6)
        blink_frame.pack(fill=tk.X, pady=(8, 0))

        ttk.Label(blink_frame, text="週期 (秒)").grid(row=0, column=0, sticky=tk.W)
        self.blink_period_var = tk.DoubleVar(value=BLINK_DEFAULT_SEC)
        self.blink_scale = ttk.Scale(
            blink_frame,
            from_=BLINK_MIN_SEC,
            to=BLINK_MAX_SEC,
            variable=self.blink_period_var,
            orient=tk.HORIZONTAL,
            length=160,
            command=self._on_blink_drag,
        )
        self.blink_scale.grid(row=0, column=1, padx=6, sticky=tk.EW)
        blink_frame.columnconfigure(1, weight=1)
        self.blink_period_label = ttk.Label(blink_frame, text="1.0 s")
        self.blink_period_label.grid(row=0, column=2, padx=4)

        blink_btn_row = ttk.Frame(blink_frame)
        blink_btn_row.grid(row=1, column=0, columnspan=3, pady=(6, 0), sticky=tk.W)
        ttk.Button(blink_btn_row, text="開始閃爍", command=self._start_blink).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(blink_btn_row, text="停止閃爍", command=self._stop_blink).pack(
            side=tk.LEFT, padx=2
        )
        self.blink_state_label = ttk.Label(blink_btn_row, text="未閃爍", foreground="gray")
        self.blink_state_label.pack(side=tk.LEFT, padx=8)

        ss_cmd_row = ttk.Frame(slave_frame)
        ss_cmd_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(ss_cmd_row, text="自訂 SS").pack(side=tk.LEFT)
        self.ss_cmd_var = tk.StringVar()
        ttk.Entry(ss_cmd_row, textvariable=self.ss_cmd_var, width=16).pack(
            side=tk.LEFT, padx=6, fill=tk.X, expand=True
        )
        ttk.Button(ss_cmd_row, text="送出", command=self._ss_send_custom).pack(side=tk.LEFT)

        diag_frame = ttk.LabelFrame(slave_frame, text="SS 接收字元檢查 (D10 RX)", padding=6)
        diag_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        diag_hint = ttk.Label(
            diag_frame,
            text="組合型監聽 COM6：SSRXC / SSRX / VARACK",
            foreground="gray",
            wraplength=300,
        )
        diag_hint.pack(anchor=tk.W, pady=(0, 4))

        self.ss_rx_text = tk.Text(diag_frame, height=6, state=tk.DISABLED, font=("Consolas", 9))
        self.ss_rx_text.pack(fill=tk.BOTH, expand=True, pady=4)

        diag_btn_row = ttk.Frame(diag_frame)
        diag_btn_row.pack(fill=tk.X)
        ttk.Button(diag_btn_row, text="組合診斷", command=self._run_combined_diag).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(diag_btn_row, text="直連 PING", command=self._slave_direct_ping).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(diag_btn_row, text="SSRX?", command=self._query_ssrx).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(diag_btn_row, text="SSDIAG?", command=self._query_ssdiag).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(diag_btn_row, text="清除", command=self._clear_ss_rx_log).pack(
            side=tk.LEFT, padx=2
        )
        self.ss_diag_summary_var = tk.StringVar(value="尚未執行診斷")
        ttk.Label(
            diag_frame, textvariable=self.ss_diag_summary_var, foreground="gray", wraplength=300
        ).pack(anchor=tk.W, pady=(4, 0))

        status_frame = ttk.LabelFrame(parent, text="狀態 / 日誌", padding=8)
        status_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        self.status_var = tk.StringVar(value="未連線")
        ttk.Label(status_frame, textvariable=self.status_var).pack(anchor=tk.W)

        self.log_text = tk.Text(status_frame, height=6, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True, pady=4)

    def _build_docs_tab(self, parent: ttk.Frame) -> None:
        text = scrolledtext.ScrolledText(
            parent, wrap=tk.WORD, font=("Consolas", 10), state=tk.DISABLED
        )
        text.pack(fill=tk.BOTH, expand=True)
        text.configure(state=tk.NORMAL)
        text.insert(tk.END, DOCS_TEXT)
        text.configure(state=tk.DISABLED)

    def _log(self, message: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _append_ss_rx_log(self, message: str) -> None:
        self.ss_rx_text.configure(state=tk.NORMAL)
        self.ss_rx_text.insert(tk.END, message + "\n")
        self.ss_rx_text.see(tk.END)
        self.ss_rx_text.configure(state=tk.DISABLED)
        if message.startswith("< "):
            line = message[2:].strip()
        else:
            line = message
        if line.startswith("VARACK:"):
            self._apply_var_payload(line[7:])

    def _apply_var_payload(self, payload: str) -> None:
        values = self._parse_var_payload(payload)
        if not values:
            return
        for name, val in values.items():
            self._slave_var_vars[name].set(f"{val:g}")
        if "E" in values:
            self._set_blink_ui_from_e(values["E"])
        self._var_ack_var.set(f"COM6 確認：{payload}")

    @staticmethod
    def _parse_var_payload(payload: str) -> Dict[str, float]:
        values: Dict[str, float] = {}
        for name, raw in VAR_LINE_RE.findall(payload):
            try:
                values[name] = float(raw)
            except ValueError:
                continue
        return values

    def _read_slave_var_fields(self) -> Optional[str]:
        parts: List[str] = []
        for name in SLAVE_VAR_NAMES:
            raw = self._slave_var_vars[name].get().strip()
            if not raw:
                messagebox.showwarning("EEPROM 變數", f"變數 {name} 不可為空")
                return None
            try:
                parts.append(f"{float(raw):g}")
            except ValueError:
                messagebox.showwarning("EEPROM 變數", f"變數 {name} 請輸入有效數字")
                return None
        return ",".join(parts)

    def _send_svar(self, subcmd: str, log: bool = True) -> str:
        if subcmd == "?":
            resp = self._send_command("SVAR?", log=log)
        else:
            resp = self._send_command(f"SVAR:{subcmd}", log=log)
        if resp.startswith("SSR:"):
            slave_resp = resp[4:]
            self._slave_status_var.set(f"副核心：{slave_resp}")
            if slave_resp.startswith("VAR:"):
                self._apply_var_payload(slave_resp[4:])
            return slave_resp
        if resp.startswith("ERR"):
            self._slave_status_var.set(resp)
        return resp

    def _wait_var_ack_on_com6(self) -> Optional[str]:
        if not self._slave_serial or not self._slave_serial.is_open:
            return None
        deadline = time.time() + (VAR_ACK_WAIT_MS / 1000.0)
        while time.time() < deadline:
            for line in self._drain_slave_serial():
                if line.startswith("VARACK:"):
                    return line
            time.sleep(0.05)
        return None

    def _update_slave_vars(self) -> None:
        payload = self._read_slave_var_fields()
        if payload is None:
            return
        try:
            if self.conn_mode_var.get() == "combo" and (
                not self._slave_serial or not self._slave_serial.is_open
            ):
                self._start_slave_monitor(auto=True)

            resp = self._send_svar(f"ALL:{payload}")
            if resp != "OK":
                messagebox.showwarning("EEPROM 變數", resp or "更新失敗")
                return

            try:
                e_sec = float(self._slave_var_vars["E"].get())
                if e_sec > 0:
                    self._set_blink_ui_from_e(e_sec)
                    self._blink_running = True
                    self._last_blink_ms = self._period_sec_to_ms(e_sec)
                    self.blink_state_label.configure(
                        text=f"閃爍中 {e_sec:.1f}s", foreground="green"
                    )
                    lbl = self._slave_output_labels[13]
                    lbl.configure(text="BLINK", foreground="green")
            except ValueError:
                pass

            ack = self._wait_var_ack_on_com6()
            if ack:
                self._var_ack_var.set(f"COM6 確認：{ack[7:]}")
                self._log(f"< {ack}")
            elif self.conn_mode_var.get() == "combo":
                self._var_ack_var.set("主核心 OK，但未收到 COM6 VARACK")
            else:
                self._var_ack_var.set("主核心已更新（組合型可監聽 COM6 VARACK）")
        except RuntimeError as exc:
            messagebox.showwarning("連線", str(exc))

    def _query_slave_vars(self) -> None:
        try:
            resp = self._send_svar("?")
            if resp.startswith("VAR:"):
                self._apply_var_payload(resp[4:])
            elif resp.startswith("ERR"):
                messagebox.showwarning("EEPROM 變數", resp)
        except RuntimeError as exc:
            messagebox.showwarning("連線", str(exc))

    def _clear_ss_rx_log(self) -> None:
        self.ss_rx_text.configure(state=tk.NORMAL)
        self.ss_rx_text.delete("1.0", tk.END)
        self.ss_rx_text.configure(state=tk.DISABLED)

    def _on_conn_mode_change(self) -> None:
        combo = self.conn_mode_var.get() == "combo"
        state = "readonly" if combo else tk.DISABLED
        self.slave_port_combo.configure(state=state)
        if combo:
            self.slave_monitor_btn.configure(state=tk.NORMAL)
        else:
            self.slave_monitor_btn.configure(state=tk.DISABLED)
            self._stop_slave_monitor()

    @staticmethod
    def _pick_slave_port(
        ports: List[Tuple[str, str]], main_label: Optional[str]
    ) -> Optional[str]:
        main_device = ""
        if main_label:
            main_device = main_label.split()[0]
        candidates = [
            label for device, label in ports if device != main_device
        ]
        for label in candidates:
            if AndGateTesterApp._is_arduino_like(label):
                return label
        return candidates[0] if candidates else None

    @staticmethod
    def _enumerate_ports() -> List[Tuple[str, str]]:
        ports: List[Tuple[str, str]] = []
        for info in serial.tools.list_ports.comports():
            desc = info.description or "Unknown"
            ports.append((info.device, f"{info.device}  ({desc})"))
        return ports

    @staticmethod
    def _device_from_display(display: str) -> str:
        if not display:
            return ""
        return display.split()[0]

    @staticmethod
    def _is_arduino_like(label: str) -> bool:
        lower = label.lower()
        return any(hint in lower for hint in ARDUINO_PORT_HINTS)

    def _pick_default_port(self, ports: List[Tuple[str, str]]) -> Optional[str]:
        for _device, label in ports:
            if self._is_arduino_like(label):
                return label
        return ports[0][1] if ports else None

    def _refresh_ports(self) -> bool:
        ports = self._enumerate_ports()
        labels = [label for _device, label in ports]
        devices = [device for device, _label in ports]

        changed = labels != self._known_ports
        self._known_ports = labels
        self.port_combo["values"] = labels
        self.slave_port_combo["values"] = labels

        current = self.port_var.get()
        current_device = self._device_from_display(current)
        slave_current = self.slave_port_var.get()
        slave_device = self._device_from_display(slave_current)

        if current_device and current_device not in devices:
            if self._serial and self._serial.is_open:
                self._log(f"COM 埠 {current_device} 已消失，自動斷線")
                self._disconnect()
            self.port_var.set("")
        elif not current and labels:
            picked = self._pick_default_port(ports)
            if picked:
                self.port_var.set(picked)

        if slave_device and slave_device not in devices:
            if self._slave_serial and self._slave_serial.is_open:
                self._append_ss_rx_log(f"[系統] 副核心 COM {slave_device} 已消失，停止監聽")
                self._stop_slave_monitor()
            self.slave_port_var.set("")
        elif not slave_current and labels and self.conn_mode_var.get() == "combo":
            picked_slave = self._pick_slave_port(ports, self.port_var.get())
            if picked_slave:
                self.slave_port_var.set(picked_slave)

        count = len(labels)
        arduino_count = sum(1 for label in labels if self._is_arduino_like(label))
        if count == 0:
            self.scan_status_var.set("未偵測到 COM 埠")
        else:
            self.scan_status_var.set(
                f"已掃描 {count} 個埠" + (f"，{arduino_count} 個疑似 Arduino" if arduino_count else "")
            )
        return changed

    def _start_port_scan(self) -> None:
        self._stop_port_scan()
        self._port_scan_tick()

    def _stop_port_scan(self) -> None:
        if self._port_scan_job is not None:
            self.root.after_cancel(self._port_scan_job)
            self._port_scan_job = None

    def _port_scan_tick(self) -> None:
        if not self._closing:
            self._refresh_ports()
            self._port_scan_job = self.root.after(PORT_SCAN_MS, self._port_scan_tick)
        else:
            self._port_scan_job = None

    def _toggle_connection(self) -> None:
        if self._serial and self._serial.is_open:
            self._disconnect()
        else:
            self._connect()

    def _connect(self) -> None:
        port = self._device_from_display(self.port_var.get())
        if not port:
            messagebox.showwarning("連線", "請選擇 COM 埠（或等待自動掃描）")
            return
        try:
            self._serial = serial.Serial(port, BAUD_RATE, timeout=1.0)
            self.connect_btn.configure(text="斷線")
            self.status_var.set(f"已連線：{port}")
            self._log(f"已連線 {port}")
            greeting = self._serial.readline().decode(errors="ignore").strip()
            if greeting:
                self._log(f"< {greeting}")
                if "ANDGATE" not in greeting:
                    self._log("提示：未收到 READY，請確認韌體已燒錄")
            else:
                self._log("提示：未收到 READY，請確認韌體已燒錄")
            self._sync_io_state()
            self._last_applied_phase = int(self.phase_var.get())
            self._start_io_scan()
            if self.conn_mode_var.get() == "combo":
                self._start_slave_monitor(auto=True)
        except serial.SerialException as exc:
            messagebox.showerror("連線失敗", str(exc))
            self._serial = None

    def _disconnect(self) -> None:
        if self._closing:
            return
        self._stop_io_scan()
        self._stop_slave_monitor()
        self._cancel_phase_apply()
        self._cancel_blink_apply()
        self._last_applied_phase = None
        self._last_blink_ms = None
        self._blink_running = False
        self._close_main_serial(send_stop=True)
        self.connect_btn.configure(text="連線")
        self.status_var.set("未連線")
        self._log("已斷線")
        self._reset_io_display()

    def _close_main_serial(self, send_stop: bool = False) -> None:
        ser = self._serial
        if ser is None:
            return
        self._serial = None
        try:
            if send_stop and ser.is_open:
                ser.write(b"STOP\n")
                ser.flush()
        except OSError:
            pass
        try:
            if ser.is_open:
                ser.close()
        except OSError:
            pass

    def _close_slave_serial(self) -> None:
        if self._slave_monitor_job is not None:
            try:
                self.root.after_cancel(self._slave_monitor_job)
            except tk.TclError:
                pass
            self._slave_monitor_job = None
        ser = self._slave_serial
        if ser is None:
            return
        self._slave_serial = None
        try:
            if ser.is_open:
                ser.close()
        except OSError:
            pass

    def _release_all_ports(self) -> None:
        self._stop_port_scan()
        self._stop_io_scan()
        self._cancel_phase_apply()
        self._cancel_blink_apply()
        self._close_slave_serial()
        self._close_main_serial(send_stop=False)

    def _atexit_release_ports(self) -> None:
        self._closing = True
        try:
            self._release_all_ports()
        except Exception:
            pass

    def _reset_io_display(self) -> None:
        for pin in INPUT_PINS:
            self._input_labels[pin].configure(text="—", foreground="gray")
        for pin in OUTPUT_PINS:
            self._output_state[pin] = 0
            self._refresh_output_label(pin)
        self._slave_status_var.set("未連線副核心")
        for pin in SLAVE_OUTPUT_PINS:
            self._slave_output_labels[pin].configure(text="—", foreground="gray")
        self.blink_state_label.configure(text="未閃爍", foreground="gray")
        self.ss_diag_summary_var.set("尚未執行診斷")
        self._var_ack_var.set("尚未更新 EEPROM 變數")

    def _toggle_slave_monitor(self) -> None:
        if self._slave_serial and self._slave_serial.is_open:
            self._stop_slave_monitor()
        else:
            self._start_slave_monitor(auto=False)

    def _start_slave_monitor(self, auto: bool = False) -> None:
        if self.conn_mode_var.get() != "combo":
            return
        port = self._device_from_display(self.slave_port_var.get())
        main_port = self._device_from_display(self.port_var.get())
        if not port:
            if not auto:
                messagebox.showwarning("副核心監聽", "請選擇副核心 COM 埠")
            return
        if port == main_port:
            if not auto:
                messagebox.showwarning("副核心監聽", "副核心 COM 不可與主核心相同")
            return
        try:
            self._slave_serial = serial.Serial(port, BAUD_RATE, timeout=0.05)
            self.slave_monitor_btn.configure(text="停止監聽")
            self._append_ss_rx_log(f"[系統] 開始監聽 {port} @ {BAUD_RATE}")
            time.sleep(0.15)
            self._drain_slave_serial()
            self._start_slave_monitor_tick()
        except serial.SerialException as exc:
            self._slave_serial = None
            if not auto:
                messagebox.showerror("副核心監聽失敗", str(exc))

    def _stop_slave_monitor(self) -> None:
        self._close_slave_serial()
        if not self._closing:
            self.slave_monitor_btn.configure(text="監聽副核心")

    def _start_slave_monitor_tick(self) -> None:
        self._slave_monitor_tick()

    def _slave_monitor_tick(self) -> None:
        if not self._closing and self._slave_serial and self._slave_serial.is_open:
            try:
                self._drain_slave_serial()
            except OSError:
                pass
        if not self._closing:
            self._slave_monitor_job = self.root.after(SLAVE_MONITOR_MS, self._slave_monitor_tick)
        else:
            self._slave_monitor_job = None

    def _drain_slave_serial(self) -> List[str]:
        lines: List[str] = []
        if not self._slave_serial or not self._slave_serial.is_open:
            return lines
        while self._slave_serial.in_waiting:
            raw = self._slave_serial.readline()
            if not raw:
                break
            line = raw.decode(errors="replace").strip()
            if line:
                lines.append(line)
                self._append_ss_rx_log(f"< {line}")
        return lines

    def _send_slave_direct(self, command: str, log: bool = True) -> str:
        if not self._slave_serial or not self._slave_serial.is_open:
            raise RuntimeError("尚未監聽副核心 USB")
        self._slave_serial.write((command + "\n").encode())
        self._slave_serial.flush()
        if log:
            self._append_ss_rx_log(f"> USB {command}")
        deadline = time.time() + 1.0
        while time.time() < deadline:
            lines = self._drain_slave_serial()
            for line in lines:
                if line.startswith(("PONG", "OK", "ERR", "SSRX:", "SLAVE:", "OUT:", "IN:", "VAR:", "VARACK:")):
                    return line
            time.sleep(0.05)
        return ""

    def _query_ssdiag(self) -> None:
        try:
            resp = self._send_command("SSDIAG?")
            self.ss_diag_summary_var.set(f"主核心 SS：{resp}")
        except RuntimeError as exc:
            messagebox.showwarning("連線", str(exc))

    def _query_ssrx(self) -> None:
        try:
            if self._slave_serial and self._slave_serial.is_open:
                resp = self._send_slave_direct("SSRX?")
                self.ss_diag_summary_var.set(f"副核心 SSRX?：{resp or '(無回應)'}")
            else:
                resp = self._send_ss_command("SSRX?")
                self.ss_diag_summary_var.set(f"經主核心 SS: SSRX? → {resp}")
        except RuntimeError as exc:
            messagebox.showwarning("連線", str(exc))

    def _slave_direct_ping(self) -> None:
        try:
            if not self._slave_serial or not self._slave_serial.is_open:
                messagebox.showwarning("副核心", "請先選擇組合型並按「監聽副核心」")
                return
            resp = self._send_slave_direct("PING")
            if resp == "PONG":
                messagebox.showinfo("副核心直連", "USB 直連正常 (PONG)")
            else:
                messagebox.showwarning("副核心直連", resp or "無回應")
        except RuntimeError as exc:
            messagebox.showwarning("連線", str(exc))

    def _run_combined_diag(self) -> None:
        if not self._serial or not self._serial.is_open:
            messagebox.showwarning("組合診斷", "請先連線主核心")
            return
        if self.conn_mode_var.get() != "combo":
            messagebox.showwarning("組合診斷", "請切換至「組合型（主 + 副 USB）」")
            return
        if not self._slave_serial or not self._slave_serial.is_open:
            self._start_slave_monitor(auto=False)
            if not self._slave_serial or not self._slave_serial.is_open:
                return

        self._clear_ss_rx_log()
        self._log("=== 組合診斷開始 ===")
        results: List[str] = []

        ssdiag = self._send_command("SSDIAG?")
        self._log(f"1. 主核心 SSDIAG? → {ssdiag}")
        results.append(f"SSDIAG={ssdiag}")

        self._append_ss_rx_log("--- 2. 副核心 USB 直送 PING ---")
        direct = self._send_slave_direct("PING")
        self._log(f"2. 副核心 USB PING → {direct or '(無回應)'}")
        results.append(f"USB_PING={direct or 'NONE'}")

        self._append_ss_rx_log("--- 3. 主核心 SS:PING → 副核心 D10 ---")
        time.sleep(0.1)
        ss_resp = self._send_ss_command("PING")
        time.sleep(0.6)
        ss_lines = self._drain_slave_serial()
        ss_chars = [ln for ln in ss_lines if ln.startswith("SSRXC:")]
        ss_cmds = [ln for ln in ss_lines if ln.startswith("SSRX:")]
        self._log(f"3. 主核心 SS:PING → {ss_resp}")
        self._log(f"   副核心 SS 字元數：{len(ss_chars)}，完整指令：{len(ss_cmds)}")
        results.append(f"SS_PING={ss_resp}")
        results.append(f"SSRXC={len(ss_chars)}")
        results.append(f"SSRX={len(ss_cmds)}")

        if direct != "PONG":
            summary = "副核心 USB 無回應 — 請確認副核心韌體與 COM 埠"
            level = "warn"
        elif ss_resp != "PONG":
            if len(ss_chars) == 0:
                summary = (
                    "副核心 USB 正常，但 SS 未收到字元 — 檢查接線："
                    "主 D11→副 D10、主 D10←副 D11、GND"
                )
            else:
                summary = f"SS 有收到字元但主核心回應 {ss_resp} — 可能接線或 baud 不符"
            level = "warn"
        else:
            summary = "組合診斷通過：主→副 Software Serial 正常"
            level = "ok"

        self.ss_diag_summary_var.set(summary)
        self._log(f"=== 診斷結果：{summary} ===")
        if level == "ok":
            messagebox.showinfo("組合診斷", summary)
        else:
            messagebox.showwarning("組合診斷", summary)

    def _require_serial(self) -> serial.Serial:
        if not self._serial or not self._serial.is_open:
            raise RuntimeError("尚未連線")
        return self._serial

    def _send_command(self, command: str, log: bool = True) -> str:
        ser = self._require_serial()
        ser.write((command + "\n").encode())
        ser.flush()
        response = ser.readline().decode(errors="ignore").strip()
        if log:
            self._log(f"> {command}")
            if response:
                self._log(f"< {response}")
        return response

    @staticmethod
    def _parse_pin_values(response: str) -> Dict[int, int]:
        values: Dict[int, int] = {}
        for pin_str, val_str in re.findall(r"D(\d+)=(\d)", response):
            values[int(pin_str)] = int(val_str)
        return values

    def _sync_io_state(self) -> None:
        try:
            in_resp = self._send_command("IN?", log=False)
            for pin, val in self._parse_pin_values(in_resp).items():
                if pin in self._input_labels:
                    self._update_input_label(pin, val)

            out_resp = self._send_command("OUT?", log=False)
            for pin, val in self._parse_pin_values(out_resp).items():
                if pin in self._output_state:
                    self._output_state[pin] = val
                    self._refresh_output_label(pin)
        except (RuntimeError, OSError):
            pass

    def _start_io_scan(self) -> None:
        self._stop_io_scan()
        self._io_scan_tick()

    def _stop_io_scan(self) -> None:
        if self._poll_job is not None:
            self.root.after_cancel(self._poll_job)
            self._poll_job = None

    def _io_scan_tick(self) -> None:
        if not self._closing and self._serial and self._serial.is_open:
            try:
                in_resp = self._send_command("IN?", log=False)
                for pin, val in self._parse_pin_values(in_resp).items():
                    if pin in self._input_labels:
                        self._update_input_label(pin, val)

                out_resp = self._send_command("OUT?", log=False)
                for pin, val in self._parse_pin_values(out_resp).items():
                    if pin in self._output_state and self._output_state[pin] != val:
                        self._output_state[pin] = val
                        self._refresh_output_label(pin)
            except (RuntimeError, OSError):
                pass
        if not self._closing:
            self._poll_job = self.root.after(POLL_MS, self._io_scan_tick)
        else:
            self._poll_job = None

    def _update_input_label(self, pin: int, value: int) -> None:
        lbl = self._input_labels[pin]
        if value:
            lbl.configure(text="HIGH", foreground="green")
        else:
            lbl.configure(text="LOW", foreground="gray")

    def _refresh_output_label(self, pin: int) -> None:
        state = self._output_state[pin]
        lbl = self._output_labels[pin]
        if state:
            lbl.configure(text="HIGH", foreground="green")
        else:
            lbl.configure(text="LOW", foreground="gray")

    def _set_output(self, pin: int, level: int) -> None:
        try:
            resp = self._send_command(f"OUT:{pin}:{level}")
            if resp.startswith("ERR"):
                messagebox.showwarning("輸出", resp)
                return
            self._output_state[pin] = level
            self._refresh_output_label(pin)
        except RuntimeError as exc:
            messagebox.showwarning("連線", str(exc))

    def _send_ss_command(self, cmd: str, log: bool = True) -> str:
        resp = self._send_command(f"SS:{cmd}", log=log)
        if resp.startswith("SSR:"):
            slave_resp = resp[4:]
            self._slave_status_var.set(f"副核心：{slave_resp}")
            self._update_slave_outputs_from_response(slave_resp)
            return slave_resp
        if resp.startswith("ERR"):
            self._slave_status_var.set(resp)
        return resp

    def _update_slave_outputs_from_response(self, resp: str) -> None:
        if not resp.startswith("OUT:"):
            return
        for pin, val in self._parse_pin_values(resp).items():
            if pin in self._slave_output_labels:
                lbl = self._slave_output_labels[pin]
                if val:
                    lbl.configure(text="HIGH", foreground="green")
                else:
                    lbl.configure(text="LOW", foreground="gray")

    def _ss_ping(self) -> None:
        try:
            resp = self._send_ss_command("PING")
            if resp == "PONG":
                messagebox.showinfo("副核心", "連線正常 (PONG)")
            elif resp.startswith("ERR"):
                messagebox.showwarning("副核心", resp)
        except RuntimeError as exc:
            messagebox.showwarning("連線", str(exc))

    def _ss_command(self, cmd: str) -> None:
        try:
            self._send_ss_command(cmd)
        except RuntimeError as exc:
            messagebox.showwarning("連線", str(exc))

    def _ss_set_output(self, pin: int, level: int) -> None:
        try:
            resp = self._send_ss_command(f"OUT:{pin}:{level}")
            if resp == "OK":
                lbl = self._slave_output_labels[pin]
                if level:
                    lbl.configure(text="HIGH", foreground="green")
                else:
                    lbl.configure(text="LOW", foreground="gray")
            elif resp.startswith("ERR"):
                messagebox.showwarning("副核心輸出", resp)
        except RuntimeError as exc:
            messagebox.showwarning("連線", str(exc))

    def _ss_send_custom(self) -> None:
        cmd = self.ss_cmd_var.get().strip()
        if not cmd:
            return
        try:
            self._send_ss_command(cmd)
        except RuntimeError as exc:
            messagebox.showwarning("連線", str(exc))

    @staticmethod
    def _period_sec_to_ms(sec: float) -> int:
        clamped = max(BLINK_MIN_SEC, min(BLINK_MAX_SEC, sec))
        return int(round(clamped * 1000))

    def _set_blink_ui_from_e(self, sec: float) -> None:
        sec = max(BLINK_MIN_SEC, min(BLINK_MAX_SEC, sec))
        self.blink_period_var.set(sec)
        self.blink_period_label.configure(text=f"{sec:.1f} s")

    def _set_e_from_blink_sec(self, sec: float) -> None:
        sec = max(BLINK_MIN_SEC, min(BLINK_MAX_SEC, sec))
        self._slave_var_vars["E"].set(f"{sec:g}")

    def _on_blink_drag(self, _value: str) -> None:
        sec = float(self.blink_period_var.get())
        sec = max(BLINK_MIN_SEC, min(BLINK_MAX_SEC, sec))
        self.blink_period_label.configure(text=f"{sec:.1f} s")
        self._set_e_from_blink_sec(sec)
        if self._blink_running and self._serial and self._serial.is_open:
            self._schedule_blink_apply(sec)

    def _cancel_blink_apply(self) -> None:
        if self._blink_job is not None:
            self.root.after_cancel(self._blink_job)
            self._blink_job = None

    def _schedule_blink_apply(self, sec: float) -> None:
        self._cancel_blink_apply()
        self._blink_job = self.root.after(
            BLINK_DEBOUNCE_MS, lambda s=sec: self._apply_blink_live(s)
        )

    def _apply_blink_live(self, sec: float) -> None:
        self._blink_job = None
        period_ms = self._period_sec_to_ms(sec)
        if period_ms == self._last_blink_ms:
            return
        try:
            resp = self._send_ss_command(f"BLINK:{period_ms}", log=False)
            if resp == "OK":
                self._last_blink_ms = period_ms
                self._set_e_from_blink_sec(sec)
                self.blink_state_label.configure(text=f"閃爍中 {sec:.1f}s", foreground="green")
        except (RuntimeError, OSError):
            pass

    def _start_blink(self) -> None:
        sec = float(self.blink_period_var.get())
        sec = max(BLINK_MIN_SEC, min(BLINK_MAX_SEC, sec))
        self._set_e_from_blink_sec(sec)
        period_ms = self._period_sec_to_ms(sec)
        try:
            resp = self._send_ss_command(f"BLINK:{period_ms}")
            if resp == "OK":
                self._blink_running = True
                self._last_blink_ms = period_ms
                self.blink_state_label.configure(text=f"閃爍中 {sec:.1f}s", foreground="green")
                lbl = self._slave_output_labels[13]
                lbl.configure(text="BLINK", foreground="green")
            elif resp.startswith("ERR"):
                messagebox.showwarning("LED 閃爍", resp)
        except RuntimeError as exc:
            messagebox.showwarning("連線", str(exc))

    def _stop_blink(self) -> None:
        try:
            self._cancel_blink_apply()
            resp = self._send_ss_command("BLINK:0")
            self._blink_running = False
            self._last_blink_ms = None
            self.blink_state_label.configure(text="已停止", foreground="gray")
            if resp == "OK":
                lbl = self._slave_output_labels[13]
                lbl.configure(text="LOW", foreground="gray")
            elif resp.startswith("ERR"):
                messagebox.showwarning("LED 閃爍", resp)
        except RuntimeError as exc:
            messagebox.showwarning("連線", str(exc))

    def _apply_freq(self) -> None:
        try:
            freq = int(self.freq_var.get())
        except ValueError:
            messagebox.showwarning("頻率", "請輸入整數 Hz")
            return
        try:
            resp = self._send_command(f"FREQ:{freq}")
            if resp.startswith("ERR"):
                messagebox.showwarning("頻率", resp)
        except RuntimeError as exc:
            messagebox.showwarning("連線", str(exc))

    def _on_phase_drag(self, _value: str) -> None:
        deg = int(float(self.phase_var.get()))
        self.phase_label.configure(text=f"{deg}°")
        if self._serial and self._serial.is_open:
            self._schedule_phase_apply(deg)

    def _cancel_phase_apply(self) -> None:
        if self._phase_job is not None:
            self.root.after_cancel(self._phase_job)
            self._phase_job = None

    def _schedule_phase_apply(self, deg: int) -> None:
        self._cancel_phase_apply()
        self._phase_job = self.root.after(
            PHASE_DEBOUNCE_MS, lambda d=deg: self._apply_phase_live(d)
        )

    def _apply_phase_live(self, deg: int) -> None:
        self._phase_job = None
        if deg == self._last_applied_phase:
            return
        try:
            resp = self._send_command(f"PHASE:{deg}", log=False)
            if resp == "OK":
                self._last_applied_phase = deg
            elif resp.startswith("ERR"):
                self._log(f"< {resp}")
        except (RuntimeError, OSError):
            pass

    def _apply_phase(self) -> None:
        deg = int(self.phase_var.get())
        self._cancel_phase_apply()
        resp = self._send_command(f"PHASE:{deg}")
        if resp.startswith("ERR"):
            messagebox.showwarning("相位", resp)
        elif resp == "OK":
            self._last_applied_phase = deg

    def _start(self) -> None:
        try:
            self._apply_freq()
            self._apply_phase()
            self._send_command("START")
            self.status_var.set("輸出中")
        except RuntimeError as exc:
            messagebox.showwarning("連線", str(exc))

    def _stop(self) -> None:
        try:
            resp = self._send_command("STOP")
            if resp.startswith("ERR"):
                messagebox.showwarning("停止", resp)
            self.status_var.set("已停止")
        except RuntimeError as exc:
            messagebox.showwarning("連線", str(exc))

    def _query_status(self) -> None:
        try:
            resp = self._send_command("STATUS?")
            self.status_var.set(resp)
        except RuntimeError as exc:
            messagebox.showwarning("連線", str(exc))

    def on_close(self) -> None:
        self._closing = True
        self._release_all_ports()
        self.root.destroy()


def main() -> None:
    """Launch the AND gate tester GUI."""
    root = tk.Tk()
    app = AndGateTesterApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
