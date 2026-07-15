"""
Frozen entry point for the bundled Localy backend (PyInstaller).

The Tauri desktop app spawns this as a sidecar with the argument "serve", so it
behaves exactly like `localy serve` but as a self-contained executable that
needs no Python install on the target machine.
"""

from __future__ import annotations

import multiprocessing
import sys

# The frozen exe's stdio defaults to the Windows ANSI code page (cp1252), which
# crashes on emoji/Unicode in log banners. Force UTF-8 before anything prints.
for _stream in (sys.stdout, sys.stderr):
    try:
        if _stream is not None:
            _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

from localy.cli.main import app

if __name__ == "__main__":
    multiprocessing.freeze_support()
    # Default to `serve` if launched with no args (e.g. double-clicked).
    if len(sys.argv) == 1:
        sys.argv.append("serve")
    app()
