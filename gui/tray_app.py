"""
Compatibility entrypoint — prefer `python -m ui.tray` or `python app.py`.

Works when launched as:
  python gui/tray_app.py
  python d:/Projects/Jarvis/gui/tray_app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ui.tray import AthenaTray, main

__all__ = ["AthenaTray", "main"]

if __name__ == "__main__":
    main()
