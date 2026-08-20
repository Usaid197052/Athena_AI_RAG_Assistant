"""
WhatsApp inbound watcher for Athena.

Primary: poll Baileys bridge /events while connected.
Fallback: WinRT toast listener only when bridge is disconnected.
"""

from __future__ import annotations

import hashlib
import json
import queue
import re
import sys
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from actions import whatsapp_bridge_client as bridge

_COOLDOWN_SECS = 20 * 60  # per-chat cooldown only (keyed by jid / contact)
_DEDUP_SECS = 90
_POLL_SECS = 1.5
_REMIND_MINUTES = 20
_SEEN_MAX = 256
_SEEN_TTL_SECS = 10 * 60
_DEFER_SECS = 8.0

_lock = threading.Lock()
_cooldowns: dict[str, float] = {}
_dedup: dict[str, float] = {}
_cooldown_alerted: dict[str, float] = {}  # one spoken notice per cooldown window
_enabled_cache: bool | None = None
_alert_callback: Callable[[str], None] | None = None
_access_warned = False
_notif_access_ok: bool | None = None

_stop_event = threading.Event()
_event_queue: queue.Queue[dict[str, Any]] = queue.Queue()
_seen_ids: OrderedDict[str, float] = OrderedDict()

_policy_thread: threading.Thread | None = None
_poll_thread: threading.Thread | None = None
_toast_thread: threading.Thread | None = None
_toast_stop = threading.Event()
_event_cursor = 0
_bridge_boot: str = ""
_JUNK_SENDERS = {".", "-", "_", "~", "*", ",", "you", "me"}


def _log(msg: str) -> None:
    print(f"[WhatsAppWatch] {msg}")
    try:
        from core.logger import log as athena_log
        athena_log(f"[WhatsAppWatch] {msg}", level="info")
    except Exception:
        pass


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _config_path() -> Path:
    return _base_dir() / "config" / "api_keys.json"


def _user_name() -> str:
    try:
        data = json.loads(_config_path().read_text(encoding="utf-8"))
        return str(data.get("user_name") or "").strip()
    except Exception:
        return ""


def _compact_person(text: str) -> str:
    return re.sub(r"[^\w]+", "", (text or "").lower(), flags=re.UNICODE)


def _is_junk_or_self_name(sender: str) -> bool:
    s = (sender or "").strip()
    if not s or s.lower() in _JUNK_SENDERS:
        return True
    low = s.lower()
    if "@" in low and (
        low.endswith("@lid")
        or low.endswith("@s.whatsapp.net")
        or low.endswith("@g.us")
    ):
        return True
    compact = _compact_person(s)
    if len(compact) < 2:
        return True
    mine = _compact_person(_user_name())
    return bool(mine) and compact == mine


def _announce_sender(sender: str) -> str:
    s = (sender or "").strip()
    if _is_junk_or_self_name(s):
        return "A WhatsApp contact"
    return s


def is_auto_reply_enabled() -> bool:
    global _enabled_cache
    with _lock:
        if _enabled_cache is not None:
            return _enabled_cache
    try:
        data = json.loads(_config_path().read_text(encoding="utf-8"))
        val = data.get("whatsapp_auto_reply", False)
        enabled = bool(val) if not isinstance(val, str) else val.lower() in (
            "1", "true", "yes", "on"
        )
    except Exception:
        enabled = False
    with _lock:
        _enabled_cache = enabled
    return enabled


def request_notification_access() -> tuple[bool, str]:
    """
    Request Windows UserNotificationListener access for toast fallback.
    Returns (granted, message). Bridge path does not need this.
    """
    global _notif_access_ok, _access_warned
    if sys.platform != "win32":
        return False, "Notification fallback is only available on Windows."
    try:
        from winrt.windows.ui.notifications.management import (  # type: ignore
            UserNotificationListener,
            UserNotificationListenerAccessStatus,
        )
        # Newer winrt projections expose get_current as a static; some builds
        # only expose it via the class's _get_current / factory helpers.
        get_current = getattr(UserNotificationListener, "get_current", None)
        if callable(get_current):
            listener = get_current()
        else:
            # Fallback: construct then use instance API if present
            listener = UserNotificationListener()  # type: ignore[call-arg]
            if hasattr(listener, "get_current") and callable(listener.get_current):
                listener = listener.get_current()
        status = listener.request_access_async().get()
        granted = status == UserNotificationListenerAccessStatus.ALLOWED
        _notif_access_ok = granted
        if granted:
            return True, "Windows notification access granted for WhatsApp fallback detection."
        msg = (
            "Windows notification access denied. "
            "Protocol detection still works while the WhatsApp bridge is linked; "
            "toast fallback is unavailable."
        )
        if not _access_warned:
            _access_warned = True
            # Don't speak this — bridge is the primary path
            _log(msg)
        return False, msg
    except Exception as e:
        _notif_access_ok = False
        # Soft: bridge path still works; avoid alarming the user
        return False, f"Toast fallback unavailable ({e}). Bridge detection is still active."


def clear_auto_reply_state() -> None:
    """Clear per-chat cooldowns / dedup so the next DM gets a fresh auto-reply."""
    with _lock:
        _cooldowns.clear()
        _dedup.clear()
        _cooldown_alerted.clear()
    _log("cleared auto-reply cooldowns and dedup")


def set_auto_reply_enabled(enabled: bool) -> str:
    global _enabled_cache
    path = _config_path()
    try:
        data: dict[str, Any] = {}
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        data["whatsapp_auto_reply"] = bool(enabled)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=4), encoding="utf-8")
    except Exception as e:
        return f"Could not save WhatsApp auto-reply setting: {e}"
    with _lock:
        _enabled_cache = bool(enabled)
    if enabled:
        clear_auto_reply_state()
        bridge.ensure_bridge()
        ok, access_msg = request_notification_access()
        start_watcher(force_restart=True)
        st = bridge.status().get("state", "unknown")
        base = (
            f"WhatsApp auto-reply is ON (bridge state={st}). "
            "New DMs are detected via the linked bridge. "
            "Per-chat cooldown was cleared so the next message will get a reply."
        )
        if not ok:
            return f"{base} {access_msg}"
        return f"{base} {access_msg}"
    stop_watcher()
    return "WhatsApp auto-reply is OFF."


def set_alert_callback(cb: Callable[[str], None] | None) -> None:
    global _alert_callback
    _alert_callback = cb


def _emit(msg: str) -> None:
    print(f"[WhatsAppWatch] {msg}")
    cb = _alert_callback
    if cb:
        try:
            cb(msg)
        except Exception as e:
            print(f"[WhatsAppWatch] alert callback failed: {e}")


def _sender_key(sender: str) -> str:
    return re.sub(r"\s+", " ", (sender or "").strip().lower())


def _mark_seen(nid: str) -> bool:
    if not nid:
        return True
    now = time.monotonic()
    with _lock:
        # Expire old ids so defer/retries and long sessions keep working
        dead = [k for k, t in _seen_ids.items() if now - t > _SEEN_TTL_SECS]
        for k in dead:
            del _seen_ids[k]
        if nid in _seen_ids:
            return False
        _seen_ids[nid] = now
        while len(_seen_ids) > _SEEN_MAX:
            _seen_ids.popitem(last=False)
    return True


def _soft_dedup_key(sender: str, body: str, jid: str = "") -> str:
    minute = int(time.time() // 60)
    raw = f"{_cooldown_key(sender, jid)}|{body}|{minute}"
    return "h:" + hashlib.md5(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _cooldown_key(sender: str, jid: str = "") -> str:
    """
    Cooldown is per chat/contact — never global.
    Prefer WhatsApp jid so Mom vs Ganji never share a cooldown.
    """
    j = (jid or "").strip().lower()
    if j and "@" in j:
        return f"jid:{j}"
    return f"name:{_sender_key(sender)}"


def decide_incoming(
    sender: str,
    body: str = "",
    *,
    is_group: bool = False,
    jid: str = "",
) -> str:
    if not is_auto_reply_enabled():
        return "disabled"
    s = (sender or "").strip()
    b = (body or "").lower()
    if not s and not (jid or "").strip():
        return "no_sender"
    if "automated message from" in b:
        return "own_reply"
    if _is_junk_or_self_name(s) and not (jid or "").strip():
        return "no_sender"
    low = s.lower()
    if re.fullmatch(r"(\(\d+\)\s*)?whatsapp( web)?", low):
        return "status"
    if low in ("status", "whatsapp", "whatsapp web"):
        return "status"
    if is_group or (jid or "").endswith("@g.us") or "," in s or " group" in low or low.endswith(" group"):
        return "group"

    try:
        from actions.whatsapp_control import has_pending_compose, get_actor_state
        if has_pending_compose() or get_actor_state() == "composing":
            return "defer"
    except Exception:
        pass

    key = _cooldown_key(s, jid)
    now = time.monotonic()
    with _lock:
        last = _cooldowns.get(key, 0)
        if now - last < _COOLDOWN_SECS:
            return "cooldown"
        dh = hashlib.md5(
            f"{key}|{body}".encode("utf-8", errors="ignore")
        ).hexdigest()[:16]
        if dh in _dedup and now - _dedup[dh] < _DEDUP_SECS:
            return "dedup"
        dead = [k for k, t in _dedup.items() if now - t > _DEDUP_SECS]
        for k in dead:
            del _dedup[k]
    return "allow"


def _mark_handled(sender: str, body: str, *, jid: str = "") -> None:
    key = _cooldown_key(sender, jid)
    now = time.monotonic()
    dh = hashlib.md5(f"{key}|{body}".encode("utf-8", errors="ignore")).hexdigest()[:16]
    with _lock:
        _cooldowns[key] = now
        _dedup[dh] = now


def _schedule_followup_reminder(sender: str) -> None:
    try:
        from actions.reminder import reminder
        when = datetime.now() + timedelta(minutes=_REMIND_MINUTES)
        reminder(
            parameters={
                "date": when.strftime("%Y-%m-%d"),
                "time": when.strftime("%H:%M"),
                "message": f"Contact {sender} back on WhatsApp",
            }
        )
    except Exception as e:
        print(f"[WhatsAppWatch] reminder failed: {e}")


def _parse_toast_sender(title: str, body: str) -> tuple[str, str]:
    t = (title or "").strip()
    b = (body or "").strip()
    if t.lower() in ("whatsapp", ""):
        m = re.match(r"^([^:]{1,80}):\s*(.*)$", b)
        if m:
            return m.group(1).strip(), m.group(2).strip()
        return "", b
    return t, b


def enqueue_incoming(
    sender: str,
    body: str = "",
    *,
    notif_id: str = "",
    source: str = "baileys",
    is_group: bool = False,
    jid: str = "",
    bypass_soft: bool = False,
) -> None:
    if notif_id and not _mark_seen(notif_id):
        return
    if not bypass_soft:
        soft = _soft_dedup_key(sender, body, jid)
        if not _mark_seen(soft):
            return
    _event_queue.put(
        {
            "kind": "incoming",
            "sender": sender,
            "body": body,
            "notif_id": notif_id,
            "source": source,
            "is_group": is_group,
            "jid": jid,
            "ts": time.time(),
        }
    )


def _clear_cooldown(sender: str, jid: str = "") -> None:
    key = _cooldown_key(sender, jid)
    with _lock:
        _cooldowns.pop(key, None)
        _cooldown_alerted.pop(key, None)


def _handle_allow(sender: str, body: str, jid: str = "") -> None:
    who = _announce_sender(sender)
    try:
        from actions.whatsapp_control import send_auto_reply
        if jid and "@" in jid and not _is_junk_or_self_name(sender):
            bridge.cache_set(sender, jid, sender)
        # Lock this chat before send so our own outgoing echo cannot re-trigger.
        _mark_handled(sender, body, jid=jid)
        result = send_auto_reply(sender, jid=jid)
        if result.startswith("DEFER:"):
            _clear_cooldown(sender, jid)
            def _later():
                time.sleep(_DEFER_SECS)
                enqueue_incoming(
                    sender,
                    body,
                    notif_id=f"defer:{int(time.time()*1000)}:{sender}",
                    source="defer",
                    jid=jid,
                    bypass_soft=True,
                )
            threading.Thread(target=_later, daemon=True).start()
            return
        if result.startswith("SKIP:"):
            _clear_cooldown(sender, jid)
            _log(f"skip auto-reply: {result}")
            return
        if not result.lower().startswith("sent"):
            _clear_cooldown(sender, jid)
            _emit(
                f"[WHATSAPP_ALERT] {who} messaged on WhatsApp, but auto-reply failed: {result}"
            )
            _log(f"auto-reply failed for {sender!r}: {result}")
            return
        _schedule_followup_reminder(who)
        _emit(
            f"[WHATSAPP_ALERT] {who} messaged you on WhatsApp. "
            f"I sent an automated reply and I will remind you to contact them back."
        )
        _log(f"auto-reply sent to {sender!r} announce={who!r} jid={jid!r}")
    except Exception as e:
        _clear_cooldown(sender, jid)
        _log(f"auto-reply error: {e}")
        _emit(f"[WHATSAPP_ALERT] {who} messaged on WhatsApp, but auto-reply failed: {e}")


def _policy_main() -> None:
    while not _stop_event.is_set():
        try:
            ev = _event_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            if ev.get("kind") != "incoming":
                continue
            sender = str(ev.get("sender") or "")
            body = str(ev.get("body") or "")
            is_group = bool(ev.get("is_group"))
            jid = str(ev.get("jid") or "")
            if jid and not is_group:
                try:
                    from actions import whatsapp_contacts_book as book
                    looked = book.display_for_jid(jid, sender) or sender
                    if not _is_junk_or_self_name(looked):
                        sender = looked
                except Exception:
                    pass
            decision = decide_incoming(sender, body, is_group=is_group, jid=jid)
            _log(
                f"incoming from={sender!r} src={ev.get('source')} "
                f"decision={decision} body={body[:40]!r}"
            )
            if decision == "defer":
                def _later(s=sender, b=body, j=jid):
                    time.sleep(_DEFER_SECS)
                    enqueue_incoming(
                        s,
                        b,
                        notif_id=f"defer:{int(time.time()*1000)}:{s}",
                        source="defer",
                        jid=j,
                        bypass_soft=True,
                    )
                threading.Thread(target=_later, daemon=True).start()
            elif decision == "cooldown":
                # One spoken notice per chat per cooldown window (not every message)
                key = _cooldown_key(sender, jid)
                now = time.monotonic()
                with _lock:
                    last_alert = _cooldown_alerted.get(key, 0.0)
                    should_alert = (now - last_alert) >= _COOLDOWN_SECS
                    if should_alert:
                        _cooldown_alerted[key] = now
                if should_alert:
                    mins = max(1, int(_COOLDOWN_SECS // 60))
                    who = _announce_sender(sender)
                    _emit(
                        f"[WHATSAPP_ALERT] {who} messaged again on WhatsApp. "
                        f"Auto-reply is on cooldown for about {mins} minutes for this chat."
                    )
            elif decision != "allow":
                pass
            else:
                _handle_allow(sender, body, jid=jid)
        except Exception as e:
            _log(f"policy error: {e}")
        finally:
            try:
                _event_queue.task_done()
            except Exception:
                pass


# ── Baileys poller (primary) ──────────────────────────────────────────────────

def _poll_main() -> None:
    global _event_cursor, _bridge_boot
    toast_on = False
    while not _stop_event.is_set():
        try:
            st = bridge.status()
            state = st.get("state")
            boot = str(st.get("bootId") or "")
            if boot and boot != _bridge_boot:
                latest = int(st.get("latest") or 0)
                _log(
                    f"bridge boot changed → skip backlog "
                    f"({_bridge_boot!r} → {boot!r}, cursor {_event_cursor} → {latest})"
                )
                _bridge_boot = boot
                _event_cursor = latest
            if state == "connected":
                if toast_on:
                    _stop_toast_sensor()
                    toast_on = False
                data = bridge.events_since(_event_cursor)
                if data.get("reset") or (
                    int(data.get("latest") or 0) < _event_cursor
                ):
                    _log("event cursor ahead of bridge — resetting")
                    _event_cursor = 0
                    data = bridge.events_since(0)
                rows = data.get("events") or []
                acked: list[str] = []
                for ev in rows:
                    try:
                        seq = int(ev.get("seq") or 0)
                        if seq > _event_cursor:
                            _event_cursor = seq
                        mid = str(ev.get("id") or "")
                        name = str(ev.get("name") or "")
                        text = str(ev.get("text") or "")
                        jid = str(ev.get("jid") or "")
                        lid = str(ev.get("lid") or "")
                        pn = str(ev.get("pn") or "")
                        is_group = bool(ev.get("isGroup"))
                        if mid:
                            acked.append(mid)
                        try:
                            from actions import whatsapp_contacts_book as book
                            if lid or pn:
                                book.remember_lid_mapping(lid=lid, phone_jid=pn or jid)
                            if not is_group:
                                looked = book.display_for_jid(pn or jid or lid, name)
                                if looked and not _is_junk_or_self_name(looked):
                                    name = looked
                            if _is_junk_or_self_name(name):
                                name = ""
                            elif name:
                                bridge._learn_ids(jid=jid, lid=lid, pn=pn, display=name)
                        except Exception:
                            pass
                        _log(f"poll event seq={seq} from={name!r} jid={jid!r}")
                        enqueue_incoming(
                            name,
                            text,
                            notif_id=f"baileys:{mid}" if mid else "",
                            source="baileys",
                            is_group=is_group,
                            jid=pn or jid,
                        )
                    except Exception:
                        continue
                if acked:
                    bridge.ack(acked)
                latest = int(data.get("latest") or _event_cursor)
                if latest > _event_cursor:
                    _event_cursor = latest
            else:
                if not toast_on and sys.platform == "win32":
                    _start_toast_sensor()
                    toast_on = True
        except Exception as e:
            _log(f"poll error: {e}")
        _stop_event.wait(_POLL_SECS)


# ── WinRT toast fallback (only when disconnected) ─────────────────────────────

def _extract_toast_texts(n) -> tuple[str, str]:
    title, body = "", ""
    try:
        toast = n.notification
        xml = toast.get_xml() if toast else None
        if xml:
            text = xml.get_xml() if hasattr(xml, "get_xml") else str(xml)
            texts = re.findall(r"<text[^>]*>([^<]+)</text>", text or "", flags=re.I)
            if texts:
                title = texts[0].strip()
                body = " ".join(t.strip() for t in texts[1:]) if len(texts) > 1 else ""
    except Exception:
        pass
    return title, body


def _is_whatsapp_notif(n) -> bool:
    try:
        app = str(
            getattr(n, "app_info", None)
            and getattr(n.app_info, "display_info", None)
            and getattr(n.app_info.display_info, "display_name", "")
            or ""
        ).lower()
        aumid = str(getattr(getattr(n, "app_info", None), "app_user_model_id", "") or "").lower()
        return "whatsapp" in app or "whatsapp" in aumid
    except Exception:
        return False


def _drain_winrt() -> None:
    try:
        from winrt.windows.ui.notifications.management import UserNotificationListener  # type: ignore
        from winrt.windows.ui.notifications import NotificationKinds  # type: ignore
    except Exception:
        return
    try:
        listener = UserNotificationListener.get_current()
        notifs = listener.get_notifications_async(NotificationKinds.TOAST).get()
        for n in notifs or []:
            try:
                if not _is_whatsapp_notif(n):
                    continue
                nid = str(getattr(n, "id", "") or "")
                title, body = _extract_toast_texts(n)
                sender, preview = _parse_toast_sender(title, body)
                if sender:
                    enqueue_incoming(
                        sender,
                        preview,
                        notif_id=f"toast:{nid}" if nid else "",
                        source="toast",
                    )
            except Exception:
                continue
    except Exception as e:
        print(f"[WhatsAppWatch] toast drain failed: {e}")


def _toast_sensor_main() -> None:
    global _notif_access_ok
    if sys.platform != "win32":
        return
    if _notif_access_ok is None:
        request_notification_access()
    if _notif_access_ok is False:
        return
    while not _toast_stop.is_set() and not _stop_event.is_set():
        try:
            if bridge.is_connected():
                break
            _drain_winrt()
        except Exception as e:
            print(f"[WhatsAppWatch] toast sensor: {e}")
        _toast_stop.wait(4.0)


def _start_toast_sensor() -> None:
    global _toast_thread
    _toast_stop.clear()
    if _toast_thread and _toast_thread.is_alive():
        return
    _toast_thread = threading.Thread(
        target=_toast_sensor_main, name="WhatsAppToastFallback", daemon=True
    )
    _toast_thread.start()
    print("[WhatsAppWatch] toast fallback ON (bridge not connected)")


def _stop_toast_sensor() -> None:
    _toast_stop.set()
    print("[WhatsAppWatch] toast fallback OFF (bridge connected)")


def start_watcher(*, force_restart: bool = False) -> None:
    global _policy_thread, _poll_thread
    if not is_auto_reply_enabled():
        return
    if force_restart:
        _stop_event.set()
        _stop_toast_sensor()
        for t in (_policy_thread, _poll_thread):
            if t is not None and t.is_alive():
                t.join(timeout=2.0)
        time.sleep(0.15)
    _stop_event.clear()
    bridge.ensure_bridge()
    if _policy_thread is None or not _policy_thread.is_alive():
        _policy_thread = threading.Thread(
            target=_policy_main, name="WhatsAppPolicy", daemon=True
        )
        _policy_thread.start()
    if _poll_thread is None or not _poll_thread.is_alive():
        _poll_thread = threading.Thread(
            target=_poll_main, name="WhatsAppBaileysPoll", daemon=True
        )
        _poll_thread.start()
    print("[WhatsAppWatch] started (Baileys poll + conditional toast)")
    _log("watcher started force_restart=" + str(force_restart))


def stop_watcher() -> None:
    _stop_event.set()
    _stop_toast_sensor()
    print("[WhatsAppWatch] stopped")
    _log("watcher stopped")
