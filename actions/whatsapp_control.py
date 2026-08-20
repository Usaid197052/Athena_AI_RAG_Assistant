"""
WhatsApp control for Athena — Baileys bridge (no Desktop GUI).

Compose → confirm → send. Auto-reply via whatsapp_watch + bridge.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from actions import whatsapp_bridge_client as bridge


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


def with_signature(text: str) -> str:
    body = (text or "").rstrip()
    name = _assistant_name()
    body = re.sub(
        rf"(?:\r?\n)*[—\-–]+\s*\r?\n\s*Composed by\s+{re.escape(name)}\s*$",
        "",
        body,
        flags=re.I,
    ).rstrip()
    body = re.sub(
        rf"(?:\r?\n)*Composed by\s+{re.escape(name)}\s*$",
        "",
        body,
        flags=re.I,
    ).rstrip()
    if f"Composed by {name}" not in body:
        body = f"{body}\n\n—\nComposed by {name}"
    return body


def auto_reply_text() -> str:
    name = _assistant_name()
    user = _user_name()
    first = user.split()[0] if user else "Usaid"
    return (
        f"This is an automated message from {name}. "
        f"{first} will respond to you shortly — meanwhile I'll remind Sir to contact you back."
    )


_pending: dict[str, Any] | None = None
_pending_lock = threading.Lock()
_state = "idle"
_state_lock = threading.Lock()


def get_pending() -> dict[str, Any] | None:
    with _pending_lock:
        return dict(_pending) if _pending else None


def clear_pending() -> None:
    global _pending
    with _pending_lock:
        _pending = None
    _set_state("idle")


def has_pending_compose() -> bool:
    return bool(get_pending())


def get_actor_state() -> str:
    with _state_lock:
        return _state


def _set_state(new: str) -> None:
    global _state
    with _state_lock:
        _state = new


def _try_show_setup_ui(player=None) -> None:
    try:
        if player is not None and hasattr(player, "show_whatsapp_setup"):
            player.show_whatsapp_setup()
    except Exception:
        pass


def _qr_hint() -> str:
    st = bridge.status()
    if st.get("state") == "qr" or bridge.qr_path().exists():
        return (
            " Scan the QR in Settings ⚙ → WhatsApp Setup "
            "(phone: WhatsApp → Linked Devices → Link a device)."
        )
    return ""


def _ensure_ready(player=None) -> str | None:
    ok, msg = bridge.ensure_bridge()
    if not ok:
        _try_show_setup_ui(player)
        return msg
    st = bridge.status().get("state")
    if st == "connected":
        return None
    _try_show_setup_ui(player)
    if st == "qr":
        return f"WhatsApp not linked yet.{_qr_hint()}"
    return f"WhatsApp bridge is {st}.{_qr_hint()}"


_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm"}
_AUDIO_EXT = {".mp3", ".m4a", ".ogg", ".opus", ".wav"}
_MEDIA_MAX = 64 * 1024 * 1024


def _as_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def _pretty_phone(digits: str) -> str:
    d = re.sub(r"\D", "", digits or "")
    if not d:
        return ""
    if d.startswith("92") and len(d) >= 12:
        rest = d[2:]
        if len(rest) == 10:
            return f"+92 {rest[:3]} {rest[3:]}"
        return f"+92 {rest}"
    if len(d) >= 10:
        return f"+{d}"
    return d


def _digits_for_jid(jid: str, is_group: bool) -> str:
    if is_group or str(jid).endswith("@g.us"):
        return ""
    try:
        from actions import whatsapp_contacts_book as book
        d = book.jid_to_digits(jid)
        if d:
            return d
        return book.phone_for_lid(jid) or ""
    except Exception:
        user = str(jid).split("@")[0].split(":")[0]
        d = re.sub(r"\D", "", user)
        return d if 8 <= len(d) <= 15 else ""


def _book_display(jid: str, fallback: str, is_group: bool = False) -> str:
    fb = (fallback or "").strip()
    if is_group or str(jid).endswith("@g.us"):
        return fb
    try:
        from actions import whatsapp_contacts_book as book
        return book.display_for_jid(jid, fb) or fb
    except Exception:
        return fb


def _kind_from_path(path: Path, *, voice: bool = False) -> str:
    if voice:
        return "voice"
    ext = path.suffix.lower()
    if ext in _IMAGE_EXT:
        return "image"
    if ext in _VIDEO_EXT:
        return "video"
    if ext in _AUDIO_EXT:
        return "audio"
    return "document"


def _resolve_media_path(raw: str) -> Path | None:
    s = (raw or "").strip().strip('"').strip("'")
    if not s:
        return None
    p = Path(s).expanduser()
    if p.is_file():
        return p
    home = Path.home()
    name = Path(s).name
    for folder in (home / "Downloads", home / "Desktop", home / "Documents", Path.cwd()):
        cand = folder / name
        if cand.is_file():
            return cand
    return None


def _capture_screenshot_file() -> Path:
    from actions.screen_processor import _capture_screen
    data, _fmt = _capture_screen()
    dest = Path(tempfile.gettempdir()) / f"athena_wa_shot_{int(time.time())}.png"
    dest.write_bytes(data)
    return dest


def _app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _find_ffmpeg() -> str | None:
    root = _app_root()
    for p in (
        root / "tools" / "ffmpeg" / "ffmpeg.exe",
        root / "tools" / "ffmpeg" / "ffmpeg",
    ):
        if p.is_file():
            return str(p)
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).is_file():
            return exe
    except Exception:
        pass
    return None


def _synth_voice_file(text: str) -> tuple[Path, bool]:
    from core.tts import synthesize_to_file

    src = Path(synthesize_to_file(text))
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return src, src.suffix.lower() in (".ogg", ".opus")
    dest = Path(tempfile.gettempdir()) / f"athena_wa_voice_{int(time.time() * 1000)}.ogg"
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    try:
        r = subprocess.run(
            [
                ffmpeg, "-y", "-i", str(src),
                "-vn", "-map_metadata", "-1",
                "-ac", "1", "-ar", "48000",
                "-c:a", "libopus", "-b:a", "24k",
                "-vbr", "on", "-application", "voip",
                "-f", "ogg", str(dest),
            ],
            capture_output=True,
            timeout=60,
            creationflags=flags,
        )
    except Exception:
        return src, False
    if r.returncode == 0 and dest.exists() and dest.stat().st_size > 64:
        return dest, True
    return src, False


def _looks_like_group_request(contact: str) -> bool:
    c = (contact or "").lower()
    return bool(re.search(r"\bgroup\b", c)) or c.strip().endswith(" group")


def _resolve_contact(contact: str) -> tuple[str | None, str, str, bool]:
    """Returns (error, jid, display_name, is_group)."""
    contact = (contact or "").strip()
    if not contact or contact.lower() in (
        "this", "this chat", "current", "current chat", "open chat", "here",
    ):
        return (
            "Specify a contact or group name (or phone number with country code).",
            "",
            "",
            False,
        )
    if "@" in contact and (
        contact.endswith("@s.whatsapp.net")
        or contact.endswith("@g.us")
        or contact.endswith("@lid")
    ):
        is_group = contact.endswith("@g.us")
        label = _book_display(contact, contact.split("@")[0], is_group)
        return None, contact, label, is_group

    kind = "group" if _looks_like_group_request(contact) else "any"
    resolved = bridge.resolve(contact, kind=kind)
    if not resolved.get("ok") and kind == "group":
        resolved = bridge.resolve(contact, kind="any")
    if not resolved.get("ok"):
        return str(resolved.get("error") or "Contact or group not found."), "", "", False
    jid = str(resolved["jid"])
    is_group = bool(resolved.get("isGroup")) or jid.endswith("@g.us")
    label = _book_display(jid, str(resolved.get("name") or contact), is_group)
    return None, jid, label, is_group


def compose(
    contact: str,
    message: str,
    *,
    send_now: bool = False,
    jid: str = "",
    player=None,
    path: str = "",
    media: str = "",
    voice: bool = False,
    caption: str = "",
) -> str:
    global _pending
    message = (message or "").strip()
    caption = (caption or "").strip() or message
    media = (media or "").strip().lower()
    voice = bool(voice)

    err = _ensure_ready(player)
    if err:
        return err

    is_group = False
    if jid and "@" in jid:
        resolved_jid = jid
        is_group = jid.endswith("@g.us")
        label = _book_display(jid, (contact or jid.split("@")[0]).strip() or jid, is_group)
    else:
        resolve_err, resolved_jid, label, is_group = _resolve_contact(contact)
        if resolve_err:
            return resolve_err

    kind = "text"
    media_path = ""
    ptt = False
    body = message

    if voice:
        if not message:
            return "Please specify the text to speak in the voice note."
        try:
            dest, is_opus = _synth_voice_file(message)
        except Exception as e:
            return f"Could not create a voice note: {e}"
        kind = "voice"
        media_path = str(dest)
        ptt = True
        body = message
    elif media in ("screenshot", "screen", "screenshot_png"):
        try:
            dest = _capture_screenshot_file()
        except Exception as e:
            return f"Could not capture a screenshot: {e}"
        kind = "image"
        media_path = str(dest)
        body = caption
    elif path:
        resolved = _resolve_media_path(path)
        if not resolved:
            return f"I could not find that file: {path}"
        size = resolved.stat().st_size
        if size > _MEDIA_MAX:
            mb = round(size / 1048576)
            return f"That file is too large ({mb} MB). WhatsApp limit here is 64 MB."
        kind = _kind_from_path(resolved)
        media_path = str(resolved)
        body = caption
    else:
        if not message:
            return "Please specify the message text."
        body = message if send_now else with_signature(message)

    target = f"group '{label}'" if is_group else label
    if send_now:
        _set_state("auto_replying")
        result = bridge.send(
            resolved_jid,
            body,
            media_path=media_path,
            caption=caption if kind != "text" else "",
            media_type="voice" if kind == "voice" else (kind if kind != "text" else ""),
            ptt=ptt,
        )
        _set_state("idle")
        if not result.get("ok"):
            return f"WhatsApp send failed: {result.get('error')}"
        sent_jid = str(result.get("jid") or resolved_jid)
        try:
            from actions import whatsapp_contacts_book as book
            book.remember_lid_mapping(lid=resolved_jid, phone_jid=sent_jid)
        except Exception:
            pass
        bridge.cache_set(contact or label, resolved_jid, label)
        return f"Sent WhatsApp message to {target}."

    digits = _digits_for_jid(resolved_jid, is_group)
    pretty = _pretty_phone(digits)
    with _pending_lock:
        _pending = {
            "contact": label,
            "jid": resolved_jid,
            "text": body,
            "caption": caption if kind != "text" else "",
            "is_group": is_group,
            "kind": kind,
            "path": media_path,
            "ptt": ptt,
            "digits": digits,
            "ts": time.time(),
        }
    _set_state("composing")
    num_bit = f" — {pretty}" if pretty else ""
    ask = (
        "Ask if this number is correct, then action=send."
        if pretty
        else "Ask to confirm send, then action=send."
    )
    if kind == "voice":
        return f"Composed WhatsApp voice note to {target}{num_bit}. {ask}"
    if kind != "text":
        fname = Path(media_path).name if media_path else "file"
        noun = {"image": "photo", "video": "video", "audio": "audio", "document": "file"}.get(
            kind, "file"
        )
        return f"Composed a WhatsApp {noun} to {target}{num_bit} ({fname}). {ask}"
    return (
        f"Composed WhatsApp to {target}{num_bit}. {ask}"
    )


def send_pending(player=None) -> str:
    global _pending
    with _pending_lock:
        draft = dict(_pending) if _pending else None
    if not draft:
        return "No pending WhatsApp draft. Compose a message first."

    err = _ensure_ready(player)
    if err:
        return err

    jid = str(draft.get("jid") or "")
    text = str(draft.get("text") or "")
    label = str(draft.get("contact") or "contact")
    is_group = bool(draft.get("is_group")) or jid.endswith("@g.us")
    kind = str(draft.get("kind") or "text")
    media_path = str(draft.get("path") or "")
    if not jid or (kind == "text" and not text) or (kind != "text" and not media_path):
        clear_pending()
        return "Pending draft was incomplete. Compose again."

    media_type = "voice" if kind == "voice" else (kind if kind != "text" else "")
    result = bridge.send(
        jid,
        text,
        media_path=media_path,
        caption=str(draft.get("caption") or ""),
        media_type=media_type,
        ptt=bool(draft.get("ptt")),
    )
    if not result.get("ok"):
        return f"WhatsApp send failed: {result.get('error')}"
    clear_pending()
    target = f"group '{label}'" if is_group else label
    if kind == "voice":
        return f"Sent WhatsApp voice note to {target}."
    if kind != "text":
        noun = {"image": "photo", "video": "video", "audio": "audio", "document": "file"}.get(
            kind, "file"
        )
        return f"Sent WhatsApp {noun} to {target}."
    return f"Sent WhatsApp message to {target}."


def send_auto_reply(contact: str, *, jid: str = "") -> str:
    if has_pending_compose():
        return "DEFER: pending user compose"
    if (jid or "").endswith("@g.us"):
        return "SKIP: group chat (auto-reply disabled for groups)"
    return compose(contact, auto_reply_text(), send_now=True, jid=jid)


def read_chat(contact: str, limit: int = 15, player=None) -> str:
    err = _ensure_ready(player)
    if err:
        return err
    resolve_err, jid, label, is_group = _resolve_contact(contact)
    if resolve_err:
        return resolve_err
    data = bridge.chat_messages(jid, limit)
    if not data.get("ok") and not data.get("messages"):
        return str(data.get("error") or "Could not read that chat.")
    rows = data.get("messages") or []
    if not rows:
        return (
            f"I don't have recent WhatsApp messages with {label} yet. "
            "I only see messages since this session or last sync."
        )
    lines = []
    for m in rows[-limit:]:
        who = "You" if m.get("fromMe") else str(m.get("name") or label)
        text = str(m.get("text") or "[media]").replace("\n", " ")
        lines.append(f"{who}: {text}")
    header = f"Last {len(lines)} WhatsApp message(s) with {label}"
    if is_group:
        header += " (group)"
    return header + ":\n" + "\n".join(lines)


def unread_briefing(player=None) -> str:
    err = _ensure_ready(player)
    if err:
        return err
    data = bridge.unread_chats()
    if not data.get("ok"):
        return str(data.get("error") or "Could not list unread chats.")
    chats = data.get("chats") or []
    if not chats:
        return "No unread WhatsApp chats that I can see right now."
    parts = []
    for c in chats[:10]:
        name = str(c.get("name") or "someone")
        n = int(c.get("unreadCount") or 1)
        preview = str(c.get("preview") or "").replace("\n", " ").strip()
        extra = f" Last: {preview[:80]}" if preview else ""
        kind = " group" if c.get("isGroup") else ""
        parts.append(f"{name}{kind} ({n} unread).{extra}")
    return "Unread WhatsApp: " + " ".join(parts)


def whatsapp_control(
    parameters: dict | None = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    action = str(params.get("action", "compose") or "compose").lower().strip().replace("-", "_")
    contact = str(
        params.get("contact")
        or params.get("receiver")
        or params.get("name")
        or ""
    ).strip()
    message = str(
        params.get("message")
        or params.get("message_text")
        or params.get("text")
        or ""
    ).strip()
    path = str(params.get("path") or params.get("file") or params.get("media_path") or "").strip()
    caption = str(params.get("caption") or "").strip()
    media = str(params.get("media") or "").strip().lower()
    voice = _as_bool(params.get("voice")) or action in ("voice", "voice_note")
    try:
        limit = int(params.get("limit") or 15)
    except Exception:
        limit = 15
    limit = max(1, min(40, limit))

    if player:
        try:
            player.write_log(f"[whatsapp] {action} → {contact or '-'}")
        except Exception:
            pass

    try:
        # Lazy bridge start on any WhatsApp tool use
        bridge.ensure_bridge()

        if action in ("link", "setup", "connect", "qr"):
            _try_show_setup_ui(player)
            ok, msg = bridge.ensure_bridge()
            st = bridge.status().get("state", "unknown")
            if st == "connected":
                result = "WhatsApp is already linked."
            elif not ok:
                result = msg
            else:
                result = (
                    "WhatsApp Setup is open. Scan the QR with your phone: "
                    "WhatsApp → Linked Devices → Link a device. "
                    "Drop a Contacts.vcf (or Google CSV) into the Contacts folder "
                    "so spoken names resolve to numbers."
                )
        elif action in ("auto_reply_on", "enable_auto_reply"):
            from actions.whatsapp_watch import set_auto_reply_enabled
            result = set_auto_reply_enabled(True)
        elif action in ("auto_reply_off", "disable_auto_reply"):
            from actions.whatsapp_watch import set_auto_reply_enabled
            result = set_auto_reply_enabled(False)
        elif action in ("auto_reply_status", "status"):
            from actions.whatsapp_watch import is_auto_reply_enabled
            st = bridge.status().get("state", "unknown")
            ar = "ON" if is_auto_reply_enabled() else "OFF"
            result = f"WhatsApp auto-reply is {ar}. Bridge state={st}.{_qr_hint()}"
        elif action in (
            "auto_reply_clear_cooldown",
            "clear_auto_reply_cooldown",
            "reset_auto_reply",
        ):
            from actions.whatsapp_watch import clear_auto_reply_state, is_auto_reply_enabled
            clear_auto_reply_state()
            ar = "ON" if is_auto_reply_enabled() else "OFF"
            result = (
                f"WhatsApp auto-reply cooldowns cleared. Auto-reply is {ar}. "
                "The next incoming DM will get a fresh automated reply."
            )
        elif action in ("abort", "cancel"):
            clear_pending()
            result = "WhatsApp draft cleared. Nothing was sent."
        elif action in ("read", "history", "messages", "summarize"):
            if not contact:
                result = "read needs a contact or group name."
            else:
                result = read_chat(contact, limit=limit, player=player)
        elif action in ("unread", "unread_briefing", "who_messaged"):
            result = unread_briefing(player=player)
        elif action == "auto_reply":
            if not contact:
                return "auto_reply needs a contact name."
            result = send_auto_reply(contact)
        elif action == "send":
            if get_pending():
                result = send_pending(player=player)
            elif contact and (message or path or media or voice):
                composed = compose(
                    contact,
                    message,
                    send_now=False,
                    player=player,
                    path=path,
                    media=media,
                    voice=voice,
                    caption=caption,
                )
                if "Waiting for you to confirm" not in composed:
                    result = composed
                else:
                    result = send_pending(player=player)
            else:
                result = "No pending WhatsApp draft. Compose with contact and message first."
        else:
            result = compose(
                contact,
                message,
                send_now=False,
                player=player,
                path=path,
                media=media,
                voice=voice,
                caption=caption,
            )

        if player:
            try:
                player.write_log(f"[whatsapp] {result}")
            except Exception:
                pass
        return result
    except Exception as e:
        msg = f"WhatsApp error: {e}"
        print(f"[WhatsApp] {msg}")
        return msg


# Compatibility aliases
def has_pending_whatsapp_compose() -> bool:
    return has_pending_compose()


def send_whatsapp_auto_reply(receiver: str) -> str:
    return send_auto_reply(receiver)


def clear_pending_draft() -> None:
    clear_pending()


def list_unread_chat_names() -> list[str]:
    data = bridge.unread_chats()
    names = []
    for c in data.get("chats") or []:
        n = str(c.get("name") or "").strip()
        if n:
            names.append(n)
    return names
