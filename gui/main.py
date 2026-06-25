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
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from typing import Dict, List, Optional, Tuple

import serial
import serial.tools.list_ports


DEFAULT_FREQ_HZ = 20000
DEFAULT_PHASE_DEG = 0
BAUD_RATE = 115200
INPUT_PINS = (5, 6, 7, 8)
OUTPUT_PINS = (9, 10, 11, 12, 13)
POLL_MS = 250
PHASE_DEBOUNCE_MS = 40
PORT_SCAN_MS = 1500

ARDUINO_PORT_HINTS = ("ch340", "arduino", "usb-serial", "ftdi", "cp210", "wch")

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
  D9–D13  數位輸出（面板點擊 HIGH / LOW 控制）

【快速操作】
  1. 啟動 GUI，程式會自動掃描 COM 埠
  2. 選擇正確埠號（含 CH340 者通常為 Nano）→ 連線
  3. 設定頻率（預設 20000 Hz）→ 按「套用頻率」
  4. 按「開始輸出」產生 D2/D3 方波
  5. 拖動相位滑桿可即時調整兩通道相位差
  6. D5–D8 輸入狀態自動更新；D9–D13 可手動切換輸出

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
  OUT:<pin>:<0|1> 設定 D9–D13 輸出
  OUT?            查詢 D9–D13 輸出狀態
"""


class AndGateTesterApp:
    """Tkinter GUI for controlling the AND gate signal generator."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Arduino Nano Simple Signal Generator")
        self.root.minsize(540, 600)

        self._serial: Optional[serial.Serial] = None
        self._poll_job: Optional[str] = None
        self._port_scan_job: Optional[str] = None
        self._phase_job: Optional[str] = None
        self._last_applied_phase: Optional[int] = None
        self._known_ports: List[str] = []
        self._output_state: Dict[int, int] = {pin: 0 for pin in OUTPUT_PINS}
        self._output_labels: Dict[int, ttk.Label] = {}
        self._input_labels: Dict[int, ttk.Label] = {}

        self._build_ui()
        self._refresh_ports()
        self._start_port_scan()

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

        ttk.Label(conn_frame, text="COM 埠").grid(row=0, column=0, sticky=tk.W)
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(
            conn_frame, textvariable=self.port_var, width=36, state="readonly"
        )
        self.port_combo.grid(row=0, column=1, padx=6, sticky=tk.EW)
        conn_frame.columnconfigure(1, weight=1)

        self.scan_status_var = tk.StringVar(value="掃描中…")
        ttk.Label(conn_frame, textvariable=self.scan_status_var, foreground="gray").grid(
            row=1, column=0, columnspan=2, sticky=tk.W, pady=(4, 0)
        )

        btn_row = ttk.Frame(conn_frame)
        btn_row.grid(row=0, column=2, rowspan=2, padx=4)
        self.connect_btn = ttk.Button(btn_row, text="連線", command=self._toggle_connection)
        self.connect_btn.pack(pady=2)

        param_frame = ttk.LabelFrame(parent, text="信號產生 (D2/D3)", padding=8)
        param_frame.pack(fill=tk.X, padx=6, pady=4)

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
            length=220,
            command=self._on_phase_drag,
        )
        self.phase_scale.grid(row=1, column=1, columnspan=2, sticky=tk.EW, padx=6)
        self.phase_label = ttk.Label(param_frame, text="0°")
        self.phase_label.grid(row=1, column=3)

        ctrl_frame = ttk.Frame(param_frame)
        ctrl_frame.grid(row=2, column=0, columnspan=4, pady=(6, 0), sticky=tk.W)
        ttk.Button(ctrl_frame, text="開始輸出", command=self._start).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl_frame, text="停止輸出", command=self._stop).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl_frame, text="查詢狀態", command=self._query_status).pack(
            side=tk.LEFT, padx=4
        )

        io_frame = ttk.Frame(parent, padding=0)
        io_frame.pack(fill=tk.X, padx=6, pady=4)

        in_frame = ttk.LabelFrame(io_frame, text="數位輸入 D5–D8（自動掃描）", padding=8)
        in_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))
        for pin in INPUT_PINS:
            row = ttk.Frame(in_frame)
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=f"D{pin}", width=4).pack(side=tk.LEFT)
            lbl = ttk.Label(row, text="—", width=8, anchor=tk.CENTER)
            lbl.pack(side=tk.LEFT, padx=4)
            self._input_labels[pin] = lbl

        out_frame = ttk.LabelFrame(io_frame, text="數位輸出 D9–D13（自動同步）", padding=8)
        out_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0))
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

        status_frame = ttk.LabelFrame(parent, text="狀態 / 日誌", padding=8)
        status_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        self.status_var = tk.StringVar(value="未連線")
        ttk.Label(status_frame, textvariable=self.status_var).pack(anchor=tk.W)

        self.log_text = tk.Text(status_frame, height=8, state=tk.DISABLED)
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

        current = self.port_var.get()
        current_device = self._device_from_display(current)

        if current_device and current_device not in devices:
            if self._serial and self._serial.is_open:
                self._log(f"COM 埠 {current_device} 已消失，自動斷線")
                self._disconnect()
            self.port_var.set("")
        elif not current and labels:
            picked = self._pick_default_port(ports)
            if picked:
                self.port_var.set(picked)

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
        self._refresh_ports()
        self._port_scan_job = self.root.after(PORT_SCAN_MS, self._port_scan_tick)

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
        except serial.SerialException as exc:
            messagebox.showerror("連線失敗", str(exc))
            self._serial = None

    def _disconnect(self) -> None:
        self._stop_io_scan()
        self._cancel_phase_apply()
        self._last_applied_phase = None
        if self._serial:
            try:
                self._send_command("STOP", log=False)
            except OSError:
                pass
            self._serial.close()
            self._serial = None
        self.connect_btn.configure(text="連線")
        self.status_var.set("未連線")
        self._log("已斷線")
        self._reset_io_display()

    def _reset_io_display(self) -> None:
        for pin in INPUT_PINS:
            self._input_labels[pin].configure(text="—", foreground="gray")
        for pin in OUTPUT_PINS:
            self._output_state[pin] = 0
            self._refresh_output_label(pin)

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
        if self._serial and self._serial.is_open:
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
        self._poll_job = self.root.after(POLL_MS, self._io_scan_tick)

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
        self._stop_port_scan()
        self._disconnect()
        self.root.destroy()


def main() -> None:
    """Launch the AND gate tester GUI."""
    root = tk.Tk()
    app = AndGateTesterApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
