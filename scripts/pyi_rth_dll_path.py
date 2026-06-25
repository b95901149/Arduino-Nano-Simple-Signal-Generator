"""PyInstaller runtime hook: add _MEIPASS to DLL search path before imports."""

import os
import sys

if getattr(sys, "frozen", False):
    base = sys._MEIPASS
    os.environ["PATH"] = base + os.pathsep + os.environ.get("PATH", "")
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(base)
