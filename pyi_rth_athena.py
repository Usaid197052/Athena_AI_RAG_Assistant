"""PyInstaller runtime hook — runs before Athena's main.py."""
from __future__ import annotations

import os
import sys
from pathlib import Path

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8", errors="replace")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8", errors="replace")

if getattr(sys, "frozen", False):
    root = Path(sys.executable).parent
    node_dir = root / "tools" / "node"
    if node_dir.is_dir():
        os.environ["PATH"] = str(node_dir) + os.pathsep + os.environ.get("PATH", "")
    try:
        os.chdir(root)
    except Exception:
        pass
