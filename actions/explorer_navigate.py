"""
Visual File Explorer / Finder navigator — open/close folders by screen reading.
Reuses computer_control._screen_find for one vision-click per call.
"""

from __future__ import annotations

import io
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False

_OS = platform.system()


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _get_api_key() -> str:
    path = _base_dir() / "config" / "api_keys.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("gemini_api_key", "")
    except Exception:
        return ""


def _focus_explorer() -> str:
    from actions.computer_control import _focus_window
    if _OS == "Windows":
        return _focus_window("File Explorer") or _focus_window("Explorer")
    if _OS == "Darwin":
        return _focus_window("Finder")
    return _focus_window("Files") or _focus_window("Nautilus") or _focus_window("Dolphin")


def _open_explorer(path: str = "") -> str:
    """Open Explorer without CREATE_NO_WINDOW (Popen hides the window on Windows)."""
    target = (path or "").strip()
    try:
        if target:
            from actions.file_controller import open_path
            msg = open_path(target)
            if str(msg).startswith("Opened:"):
                time.sleep(1.0)
                _focus_explorer()
            return msg

        if _OS == "Windows":
            import ctypes
            ctypes.windll.shell32.ShellExecuteW(None, "open", "explorer.exe", None, None, 1)
        elif _OS == "Darwin":
            subprocess.Popen(["open", str(Path.home())])
        else:
            opened = False
            for cmd in (["nautilus"], ["dolphin"], ["thunar"], ["nemo"], ["xdg-open", str(Path.home())]):
                try:
                    subprocess.Popen(cmd)
                    opened = True
                    break
                except Exception:
                    continue
            if not opened:
                return "Could not find a file manager to open."
        time.sleep(1.0)
        _focus_explorer()
        return "Opened File Explorer."
    except Exception as e:
        return f"Could not open Explorer: {e}"


def _look() -> str:
    """Screenshot + Gemini: list visible folder/file names."""
    api_key = _get_api_key()
    if not api_key:
        return "No API key for screen look."
    if not _PYAUTOGUI:
        return "pyautogui not installed."

    try:
        from google import genai
        from google.genai import types as gtypes

        _focus_explorer()
        time.sleep(0.3)
        img = pyautogui.screenshot()
        buf = io.BytesIO()
        img.save(buf, format="PNG")

        from core.gemini_models import get_flash_lite_model

        client = genai.Client(api_key=api_key)
        prompt = (
            "This is a screenshot of a file manager (File Explorer / Finder). "
            "List the visible folder and file names in the main pane only. "
            "Reply with one name per line. No commentary. Max 40 lines."
        )
        response = client.models.generate_content(
            model=get_flash_lite_model(),
            contents=[
                gtypes.Part.from_bytes(data=buf.getvalue(), mime_type="image/png"),
                prompt,
            ],
        )
        text = (response.text or "").strip()
        return text or "(nothing visible)"
    except Exception as e:
        return f"Look failed: {e}"


def _open_folder(name: str) -> str:
    if not name:
        return "No folder name provided."
    from actions.computer_control import _screen_find, _click, _scroll

    _focus_explorer()
    time.sleep(0.3)
    desc = f"the folder or file named '{name}' in the file list"
    coords = _screen_find(desc)
    if not coords:
        _scroll("down", 3)
        time.sleep(0.4)
        coords = _screen_find(desc)
    if not coords:
        return f"Could not find '{name}' on screen."
    _click(coords[0], coords[1], "left", 2)
    time.sleep(0.5)
    return f"Opened '{name}'."


def _go_up() -> str:
    if not _PYAUTOGUI:
        return "pyautogui not installed."
    _focus_explorer()
    time.sleep(0.2)
    if _OS == "Darwin":
        pyautogui.hotkey("command", "up")
    else:
        pyautogui.hotkey("alt", "up")
    return "Went up one folder level."


def _close_window() -> str:
    if not _PYAUTOGUI:
        return "pyautogui not installed."
    _focus_explorer()
    time.sleep(0.2)
    if _OS == "Darwin":
        pyautogui.hotkey("command", "w")
    else:
        pyautogui.hotkey("alt", "f4")
    return "Closed File Explorer window."


def _tree_toggle(name: str, expand: bool) -> str:
    from actions.computer_control import _screen_find, _click

    if not name:
        return "No folder name provided."
    _focus_explorer()
    time.sleep(0.3)
    verb = "expand" if expand else "collapse"
    desc = (
        f"the small arrow/chevron next to the folder '{name}' "
        f"in the left navigation tree (to {verb} it)"
    )
    coords = _screen_find(desc)
    if not coords:
        return f"Could not find tree control for '{name}'."
    _click(coords[0], coords[1], "left", 1)
    return f"{'Expanded' if expand else 'Collapsed'} '{name}'."


def explorer_navigate(
    parameters: dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    action = str(params.get("action", "")).lower().strip()
    name = str(params.get("name", "") or params.get("folder", "")).strip()
    path = str(params.get("path", "")).strip()

    if player:
        player.write_log(f"[explorer] {action} {name or path}")

    if not action:
        return "No action specified. Use: open_explorer | look | open_folder | go_up | close_folder | close_window | expand | collapse"

    try:
        if action in ("open_explorer", "open"):
            return _open_explorer(path)

        if action == "look":
            return _look()

        if action in ("open_folder", "enter"):
            return _open_folder(name)

        if action in ("go_up", "close_folder", "back", "up"):
            return _go_up()

        if action in ("close_window", "close"):
            return _close_window()

        if action == "expand":
            return _tree_toggle(name, True)

        if action == "collapse":
            return _tree_toggle(name, False)

        if action == "focus":
            return _focus_explorer()

        return f"Unknown explorer action: '{action}'"
    except Exception as e:
        return f"explorer_navigate failed: {e}"
