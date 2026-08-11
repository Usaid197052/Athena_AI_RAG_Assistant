"""
Resolve Athena's project root for both source and frozen (PyInstaller) runs.
"""

from __future__ import annotations

import sys
from pathlib import Path


def project_root() -> Path:
    """
    Writable Athena root.

    - Source checkout: repository root
    - Frozen build: folder containing Athena.exe (onedir layout)
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def bundle_root() -> Path:
    """
    Read-only bundled resources (PyInstaller extract dir), else project root.
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return project_root()


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))
