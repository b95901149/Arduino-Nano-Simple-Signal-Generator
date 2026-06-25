"""Capture the main GUI window for README documentation."""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

from PIL import ImageGrab

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gui.main import AndGateTesterApp  # noqa: E402

OUTPUT = ROOT / "docs" / "images" / "gui-main.png"


def capture(root: tk.Tk) -> None:
    """Grab the root window and save as PNG."""
    root.update_idletasks()
    root.update()
    x = root.winfo_rootx()
    y = root.winfo_rooty()
    w = root.winfo_width()
    h = root.winfo_height()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(OUTPUT)
    print(f"Saved: {OUTPUT}")
    root.destroy()


def main() -> None:
    """Launch GUI briefly and capture screenshot."""
    root = tk.Tk()
    app = AndGateTesterApp(root)
    try:
        root.state("zoomed")
    except tk.TclError:
        root.geometry("560x640")
    root.update_idletasks()
    root.after(1200, lambda: capture(root))
    root.mainloop()


if __name__ == "__main__":
    main()
