"""
Compose / send messages via Gmail API and other non-WhatsApp apps.

WhatsApp is handled exclusively by actions.whatsapp_control.
Gmail uses actions.gmail_bridge_client (OAuth API) — no browser GUI.
Compose fills a signed draft and waits for confirm; send delivers the draft.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.06
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False

try:
    import pyperclip
    _PYPERCLIP = True
except ImportError:
    _PYPERCLIP = False

VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x0002
SW_RESTORE = 9
ASFW_ANY = -1

# In-memory pending draft after compose (cleared on send / abort / replace)
_pending_draft: dict[str, Any] | None = None


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _get_os() -> str:
    try:
        cfg = json.loads(
            (_base_dir() / "config" / "api_keys.json").read_text(encoding="utf-8")
        )
        return cfg.get("os_system", "windows").lower()
    except Exception:
        return "windows"


def _assistant_name() -> str:
    try:
        from memory.config_manager import get_assistant_name
        return get_assistant_name() or "Athena"
    except Exception:
        return "Athena"


def _user_name() -> str:
    try:
        from memory.config_manager import get_user_name
        return (get_user_name() or "").strip() or "Usaid"
    except Exception:
        return "Usaid"


def with_athena_signature(text: str) -> str:
    """Append 'Composed by {assistant}' footer to user-initiated messages."""
    body = (text or "").rstrip()
    name = _assistant_name()
    # Strip a signature the model already baked into message_text
    body = re.sub(
        rf"(?:\r?\n)*[—\-–]+\s*\r?\n\s*Composed by\s+{re.escape(name)}\s*$",
        "",
        body,
        flags=re.IGNORECASE,
    ).rstrip()
    body = re.sub(
        rf"(?:\r?\n)*Composed by\s+{re.escape(name)}\s*$",
        "",
        body,
        flags=re.IGNORECASE,
    ).rstrip()
    footer = f"\n\n—\nComposed by {name}"
    if f"Composed by {name}" in body:
        return body
    return body + footer


def auto_reply_template() -> str:
    name = _assistant_name()
    user = _user_name()
    first = user.split()[0] if user else "Usaid"
    return (
        f"This is an automated message from {name}. "
        f"{first} will respond to you shortly — meanwhile I'll remind Sir to contact you back."
    )


def get_pending_draft() -> dict[str, Any] | None:
    return dict(_pending_draft) if _pending_draft else None


def clear_pending_draft() -> None:
    global _pending_draft
    _pending_draft = None


def has_pending_whatsapp_compose() -> bool:
    try:
        from actions.whatsapp_control import has_pending_compose
        return has_pending_compose()
    except Exception:
        return False


def _require_pyautogui():
    if not _PYAUTOGUI:
        raise RuntimeError("PyAutoGUI not installed. Run: pip install pyautogui")


def _paste_text(text: str) -> None:
    _require_pyautogui()
    os_name = _get_os()
    paste_hotkey = ("command", "v") if os_name == "mac" else ("ctrl", "v")
    if _PYPERCLIP:
        pyperclip.copy(text)
        time.sleep(0.15)
        pyautogui.hotkey(*paste_hotkey)
        time.sleep(0.1)
    else:
        pyautogui.write(text, interval=0.03)


def _clear_and_paste(text: str) -> None:
    _require_pyautogui()
    os_name = _get_os()
    select_all = ("command", "a") if os_name == "mac" else ("ctrl", "a")
    pyautogui.hotkey(*select_all)
    time.sleep(0.1)
    pyautogui.press("delete")
    time.sleep(0.1)
    _paste_text(text)


def _mod() -> str:
    return "command" if _get_os() == "mac" else "ctrl"


# ── Window helpers (Windows) ───────────────────────────────────────────────────

def _window_title(hwnd) -> str:
    if sys.platform != "win32":
        return ""
    import ctypes
    user32 = ctypes.windll.user32
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value or ""


def _window_rect_area(hwnd) -> int:
    if sys.platform != "win32":
        return 0
    import ctypes
    from ctypes import wintypes
    rect = wintypes.RECT()
    if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return 0
    return max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top)


def _enum_windows_matching(predicate) -> list[int]:
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    found: list[tuple[int, int]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd, _lp):
        if not user32.IsWindowVisible(hwnd):
            return True
        title = _window_title(hwnd)
        if not title:
            return True
        if predicate(title, hwnd):
            found.append((_window_rect_area(hwnd), int(hwnd)))
        return True

    user32.EnumWindows(enum_proc, 0)
    found.sort(reverse=True)
    return [h for _a, h in found]


def _focus_hwnd(hwnd: int) -> bool:
    if sys.platform != "win32" or not hwnd:
        return False
    import ctypes
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.ShowWindow(hwnd, SW_RESTORE)
    try:
        user32.AllowSetForegroundWindow(ASFW_ANY)
    except Exception:
        pass
    foreground = user32.GetForegroundWindow()
    current_thread = kernel32.GetCurrentThreadId()
    pid_buf = ctypes.c_ulong(0)
    foreground_thread = user32.GetWindowThreadProcessId(foreground, ctypes.byref(pid_buf))
    target_thread = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_buf))
    attached_fg = attached_tg = False
    try:
        if foreground_thread and foreground_thread != current_thread:
            attached_fg = bool(user32.AttachThreadInput(current_thread, foreground_thread, True))
        if target_thread and target_thread != current_thread:
            attached_tg = bool(user32.AttachThreadInput(current_thread, target_thread, True))
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached_tg:
            user32.AttachThreadInput(current_thread, target_thread, False)
        if attached_fg:
            user32.AttachThreadInput(current_thread, foreground_thread, False)
    time.sleep(0.3)
    try:
        return int(user32.GetForegroundWindow()) == int(hwnd)
    except Exception:
        return False


# ── WhatsApp → dedicated tool ─────────────────────────────────────────────────

def send_whatsapp_auto_reply(receiver: str) -> str:
    from actions.whatsapp_control import send_auto_reply
    return send_auto_reply(receiver)


# ── Gmail (API bridge — no browser GUI) ───────────────────────────────────────

def _compose_gmail(receiver: str, message: str, subject: str = "") -> str:
    global _pending_draft
    from actions.gmail_bridge_client import ensure_linked

    ok, msg = ensure_linked(interactive=True)
    if not ok:
        return msg

    body = with_athena_signature(message)
    _pending_draft = {
        "platform": "gmail",
        "receiver": receiver,
        "subject": subject or "",
        "body": body,
        "ts": time.time(),
    }
    name = _assistant_name()
    subj_bit = f" subject '{subject}'" if subject else ""
    return (
        f"Composed a Gmail draft to {receiver}{subj_bit} (signed by {name}). "
        f"Waiting for you to confirm send."
    )


def _send_pending_gmail() -> str:
    from actions.gmail_bridge_client import send_email

    draft = _pending_draft
    if not draft or str(draft.get("platform", "")).lower() != "gmail":
        return "No pending Gmail draft to send."

    receiver = str(draft.get("receiver") or "")
    subject = str(draft.get("subject") or "")
    body = str(draft.get("body") or "")
    if not receiver or not body:
        clear_pending_draft()
        return "Pending Gmail draft was incomplete. Compose again."

    result = send_email(to=receiver, subject=subject, body=body)
    if not result.get("ok"):
        return f"Gmail send failed: {result.get('error')}"
    clear_pending_draft()
    return f"Sent Gmail message to {receiver}."


# ── Other platforms (legacy desktop, still compose-then-send when possible) ────

def _desktop_compose(app_name: str, receiver: str, message: str) -> str:
    global _pending_draft
    _require_pyautogui()
    try:
        from actions.open_app import open_app
        open_app(parameters={"app_name": app_name})
    except Exception:
        if not _open_app_legacy(app_name):
            return f"Could not open {app_name}."
    time.sleep(1.5)
    mod = _mod()
    pyautogui.hotkey(mod, "f")
    time.sleep(0.5)
    _clear_and_paste(receiver)
    time.sleep(1.0)
    pyautogui.press("enter")
    time.sleep(0.8)
    body = with_athena_signature(message)
    _paste_text(body)
    _pending_draft = {"platform": app_name.lower(), "receiver": receiver, "ts": time.time()}
    name = _assistant_name()
    return (
        f"Composed a message to {receiver} via {app_name} (signed by {name}). "
        f"Waiting for you to confirm send."
    )


def _open_app_legacy(app_name: str) -> bool:
    _require_pyautogui()
    os_name = _get_os()
    try:
        if os_name == "windows":
            pyautogui.press("win")
            time.sleep(0.5)
            _paste_text(app_name)
            time.sleep(0.6)
            pyautogui.press("enter")
            time.sleep(2.5)
            return True
        if os_name == "mac":
            r = subprocess.run(["open", "-a", app_name], capture_output=True, timeout=10)
            time.sleep(2.0)
            return r.returncode == 0
        subprocess.Popen([app_name.lower()], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2.0)
        return True
    except Exception as e:
        print(f"[SendMessage] Could not open {app_name}: {e}")
        return False


def _send_pending_generic() -> str:
    draft = _pending_draft
    if not draft:
        return "No pending draft to send."
    platform = str(draft.get("platform", ""))
    receiver = draft.get("receiver", "contact")
    _require_pyautogui()
    try:
        from actions.computer_control import _focus_window
        _focus_window(platform.title() if platform else "WhatsApp")
        time.sleep(0.4)
    except Exception:
        pass
    pyautogui.press("enter")
    time.sleep(0.3)
    clear_pending_draft()
    return f"Sent message to {receiver} via {platform}."


def _normalize_platform(platform: str) -> str:
    key = (platform or "whatsapp").lower().strip()
    if any(k in key for k in ("whatsapp", "wp", "wapp")):
        return "whatsapp"
    if any(k in key for k in ("gmail", "email", "mail", "google mail")):
        return "gmail"
    if any(k in key for k in ("telegram", "tg")):
        return "telegram"
    if any(k in key for k in ("instagram", "ig", "insta")):
        return "instagram"
    if "signal" in key:
        return "signal"
    if "discord" in key:
        return "discord"
    if any(k in key for k in ("messenger", "facebook", "fb")):
        return "messenger"
    return key or "whatsapp"


def _compose_instagram(receiver: str, message: str) -> str:
    global _pending_draft
    _require_pyautogui()
    webbrowser.open("https://www.instagram.com/direct/new/")
    time.sleep(4.0)
    _paste_text(receiver)
    time.sleep(1.5)
    pyautogui.press("down")
    time.sleep(0.3)
    pyautogui.press("enter")
    time.sleep(0.4)
    for _ in range(4):
        pyautogui.press("tab")
        time.sleep(0.15)
    pyautogui.press("enter")
    time.sleep(2.0)
    _paste_text(with_athena_signature(message))
    _pending_draft = {"platform": "instagram", "receiver": receiver, "ts": time.time()}
    return (
        f"Composed an Instagram DM to {receiver} (signed by {_assistant_name()}). "
        f"Waiting for you to confirm send."
    )


def send_message(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    action = str(params.get("action", "compose") or "compose").lower().strip().replace("-", "_")
    receiver = str(params.get("receiver", "") or "").strip()
    message_text = str(params.get("message_text", "") or params.get("message", "") or "").strip()
    platform_raw = str(params.get("platform", "gmail") or "gmail")
    platform = _normalize_platform(platform_raw)
    subject = str(params.get("subject", "") or "").strip()

    # Toggle WhatsApp auto-reply: platform=whatsapp_auto_reply, message_text=on|off
    plat_key = platform_raw.lower().strip().replace(" ", "_").replace("-", "_")
    if plat_key in ("whatsapp_auto_reply", "whatsapp_autoreply", "auto_reply", "wa_auto_reply"):
        flag = (message_text or receiver or action or "").lower().strip()
        on = flag in ("on", "enable", "enabled", "true", "1", "start")
        off = flag in ("off", "disable", "disabled", "false", "0", "stop")
        try:
            from actions.whatsapp_watch import set_auto_reply_enabled
            if on:
                return set_auto_reply_enabled(True)
            if off:
                return set_auto_reply_enabled(False)
            from actions.whatsapp_watch import is_auto_reply_enabled
            state = "ON" if is_auto_reply_enabled() else "OFF"
            return f"WhatsApp auto-reply is currently {state}. Say on or off to change it."
        except Exception as e:
            return f"Could not change WhatsApp auto-reply: {e}"

    # WhatsApp has its own tool — thin delegate only
    if platform == "whatsapp" or plat_key in ("whatsapp", "wp", "wapp"):
        try:
            from actions.whatsapp_control import whatsapp_control
            return whatsapp_control(
                parameters={
                    "action": action if action not in ("",) else "compose",
                    "contact": receiver,
                    "message": message_text,
                },
                player=player,
            )
        except Exception as e:
            return f"WhatsApp tool error: {e}"

    if action in ("abort", "cancel"):
        clear_pending_draft()
        return "Pending message draft cleared. Nothing was sent."

    if action == "auto_reply":
        if not receiver:
            return "Auto-reply needs a sender/contact name."
        try:
            result = send_whatsapp_auto_reply(receiver)
        except Exception as e:
            result = f"Could not send auto-reply: {e}"
        if player:
            player.write_log(f"[msg] auto_reply → {receiver}: {result}")
        return result

    if action == "send":
        draft = get_pending_draft()
        if not draft:
            if receiver and message_text:
                print(f"[SendMessage] send without draft → compose+send {platform} → {receiver}")
                if player:
                    player.write_log(f"[msg] compose+send {platform} → {receiver}")
                try:
                    if platform == "gmail":
                        composed = _compose_gmail(receiver, message_text, subject=subject)
                        if "Waiting for you to confirm" not in composed:
                            return composed
                        result = _send_pending_gmail()
                    else:
                        if not _PYAUTOGUI:
                            return "PyAutoGUI is not installed — cannot control the desktop."
                        composed = _desktop_compose(platform.title(), receiver, message_text)
                        if "Waiting for you to confirm" not in composed:
                            return composed
                        result = _send_pending_generic()
                except Exception as e:
                    result = f"Could not compose/send message: {e}"
                print(f"[SendMessage] {result}")
                if player:
                    player.write_log(f"[msg] {result}")
                return result
            return (
                "No pending composed message to send. "
                "Call action=compose with receiver and message_text first."
            )
        plat = str(draft.get("platform", "")).lower()
        try:
            if plat == "whatsapp":
                from actions.whatsapp_control import send_pending
                result = send_pending()
            elif plat == "gmail":
                result = _send_pending_gmail()
            else:
                if not _PYAUTOGUI:
                    return "PyAutoGUI is not installed — cannot control the desktop."
                result = _send_pending_generic()
        except Exception as e:
            result = f"Could not send message: {e}"
        print(f"[SendMessage] {result}")
        if player:
            player.write_log(f"[msg] {result}")
        return result

    # compose (default)
    if not receiver:
        return "Please specify a recipient."
    if not message_text:
        return "Please specify the message content."
    if platform != "gmail" and not _PYAUTOGUI:
        return "PyAutoGUI is not installed — cannot control the desktop."

    preview = message_text[:50] + ("…" if len(message_text) > 50 else "")
    print(f"[SendMessage] compose {platform} → {receiver}: {preview}")
    if player:
        player.write_log(f"[msg] compose {platform} → {receiver}")

    try:
        if platform == "gmail":
            result = _compose_gmail(receiver, message_text, subject=subject)
        elif platform == "telegram":
            result = _desktop_compose("Telegram", receiver, message_text)
        elif platform == "signal":
            result = _desktop_compose("Signal", receiver, message_text)
        elif platform == "discord":
            result = _desktop_compose("Discord", receiver, message_text)
        elif platform == "instagram":
            result = _compose_instagram(receiver, message_text)
        elif platform == "messenger":
            webbrowser.open("https://www.messenger.com/")
            time.sleep(4.0)
            mod = _mod()
            pyautogui.hotkey(mod, "f")
            time.sleep(0.5)
            _clear_and_paste(receiver)
            time.sleep(0.5)
            pyautogui.press("down")
            time.sleep(0.3)
            pyautogui.press("enter")
            time.sleep(1.0)
            _paste_text(with_athena_signature(message_text))
            global _pending_draft
            _pending_draft = {"platform": "messenger", "receiver": receiver, "ts": time.time()}
            result = (
                f"Composed a Messenger message to {receiver} (signed by {_assistant_name()}). "
                f"Waiting for you to confirm send."
            )
        else:
            result = _desktop_compose(platform.title(), receiver, message_text)
    except Exception as e:
        result = f"Could not compose message: {e}"

    print(f"[SendMessage] {result}")
    if player:
        player.write_log(f"[msg] {result}")
    return result
