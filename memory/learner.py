"""
Local habit learner — app/tool stats on-device; Flash distill applied from session summary.

No background threads. tick() is called from ContinuousEventMonitor.check().
"""
from __future__ import annotations

import json
import platform
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

_OS = platform.system()
_IDLE_SKIP_SECS = 120.0          # don't count AFK time toward app usage
_FLUSH_SECS = 120.0              # journal flush cadence
_JOURNAL_DAYS = 7
_EXP_MAX = 80
_TICK_INTERVAL_MIN = 8 / 60.0    # ~8s monitor poll → minutes credit
_BROWSER_EXES = frozenset({
    "chrome", "chrome.exe",
    "msedge", "msedge.exe",
    "firefox", "firefox.exe",
    "brave", "brave.exe",
    "opera", "opera.exe",
    "vivaldi", "vivaldi.exe",
})
_CORRECTION_RE = re.compile(
    r"\b(no i meant|no,? i meant|wrong|don't|dont|do not|stop that|"
    r"abort|cancel that|not what i|i said|i meant)\b",
    re.IGNORECASE,
)

_lock = Lock()
_last_flush = 0.0
_last_rollup = 0.0
_dirty = False
_activity: dict[str, Any] | None = None
_experience: dict[str, Any] | None = None


def _base_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _activity_path() -> Path:
    return _base_dir() / "memory" / "activity_journal.json"


def _experience_path() -> Path:
    return _base_dir() / "memory" / "experience_log.json"


def _empty_activity() -> dict:
    return {"days": {}, "updated": ""}


def _empty_experience() -> dict:
    return {"events": [], "tool_counts": {}, "updated": ""}


def _load_json(path: Path, empty: dict) -> dict:
    if not path.exists():
        return dict(empty)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else dict(empty)
    except Exception:
        return dict(empty)


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _ensure_loaded() -> None:
    global _activity, _experience
    if _activity is None:
        _activity = _load_json(_activity_path(), _empty_activity())
    if _experience is None:
        _experience = _load_json(_experience_path(), _empty_experience())


def _prune_activity(activity: dict) -> None:
    days = activity.get("days")
    if not isinstance(days, dict):
        activity["days"] = {}
        return
    cutoff = (datetime.now() - timedelta(days=_JOURNAL_DAYS)).strftime("%Y-%m-%d")
    for d in list(days.keys()):
        if d < cutoff:
            del days[d]


def is_learning_enabled() -> bool:
    try:
        from actions.event_monitor import is_learning_enabled as _flag
        return _flag()
    except Exception:
        try:
            from memory.config_manager import load_api_keys
            val = load_api_keys().get("learning_enabled", True)
            if isinstance(val, str):
                return val.lower() in ("1", "true", "yes", "on")
            return bool(val) if val is not None else True
        except Exception:
            return True


def _idle_seconds() -> float:
    try:
        from actions.event_monitor import _idle_seconds as _idle
        return float(_idle())
    except Exception:
        return 0.0


def _sanitize_title(title: str) -> str:
    t = (title or "").strip()
    if not t:
        return ""
    t = re.sub(r"https?://\S+", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\b[\w.+-]+@[\w.-]+\.\w+\b", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:60]


def _foreground_app() -> tuple[str, str]:
    """Return (exe_stem_lower, sanitized_title). Empty on failure / non-Windows."""
    if _OS != "Windows":
        return "", ""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return "", ""

        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value or ""

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        exe = ""
        if h:
            try:
                size = wintypes.DWORD(260)
                path_buf = ctypes.create_unicode_buffer(260)
                if kernel32.QueryFullProcessImageNameW(h, 0, path_buf, ctypes.byref(size)):
                    exe = Path(path_buf.value).name
            finally:
                kernel32.CloseHandle(h)
        if not exe:
            return "", ""

        stem = exe.lower()
        if stem in _BROWSER_EXES or stem.replace(".exe", "") + ".exe" in _BROWSER_EXES:
            return stem.replace(".exe", ""), ""
        return stem.replace(".exe", ""), _sanitize_title(title)
    except Exception:
        return "", ""


def _flush_if_needed(force: bool = False) -> None:
    global _last_flush, _dirty
    now = time.monotonic()
    if not _dirty and not force:
        return
    if not force and (now - _last_flush) < _FLUSH_SECS:
        return
    _ensure_loaded()
    assert _activity is not None and _experience is not None
    _prune_activity(_activity)
    _activity["updated"] = datetime.now().isoformat(timespec="seconds")
    _experience["updated"] = datetime.now().isoformat(timespec="seconds")
    _save_json(_activity_path(), _activity)
    _save_json(_experience_path(), _experience)
    _last_flush = now
    _dirty = False


def tick() -> None:
    """Record ~one monitor interval of foreground app time. No-op if learning off or idle."""
    global _dirty
    if not is_learning_enabled():
        return
    if _idle_seconds() >= _IDLE_SKIP_SECS:
        return

    exe, _title = _foreground_app()
    if not exe:
        return

    with _lock:
        _ensure_loaded()
        assert _activity is not None
        day = datetime.now().strftime("%Y-%m-%d")
        hour = str(datetime.now().hour)
        days = _activity.setdefault("days", {})
        day_map = days.setdefault(day, {})
        hour_map = day_map.setdefault(hour, {})
        hour_map[exe] = float(hour_map.get(exe, 0.0)) + _TICK_INTERVAL_MIN
        _dirty = True
        _flush_if_needed()

    # Occasional local rollup (every ~30 min of wall time while ticking)
    global _last_rollup
    now = time.monotonic()
    if now - _last_rollup >= 1800:
        _last_rollup = now
        try:
            rollup()
        except Exception as e:
            print(f"[Learner] rollup error: {e}")


def log_tool(tool: str, action: str = "", outcome: str = "ok") -> None:
    """Record a tool outcome. outcome: ok|fail|denied|cancelled."""
    global _dirty
    if not is_learning_enabled():
        return
    tool = (tool or "").strip()
    if not tool:
        return
    action = (action or "").strip()
    outcome = (outcome or "ok").strip().lower()
    if outcome not in ("ok", "fail", "denied", "cancelled"):
        outcome = "ok"

    with _lock:
        _ensure_loaded()
        assert _experience is not None
        events = _experience.setdefault("events", [])
        events.append({
            "t": datetime.now().isoformat(timespec="seconds"),
            "kind": "tool",
            "tool": tool,
            "action": action,
            "outcome": outcome,
        })
        _experience["events"] = events[-_EXP_MAX:]

        key = f"{tool}:{action}:{outcome}" if action else f"{tool}:{outcome}"
        counts = _experience.setdefault("tool_counts", {})
        counts[key] = int(counts.get(key, 0)) + 1
        _dirty = True
        _flush_if_needed()


def looks_like_correction(text: str) -> bool:
    return bool(text and _CORRECTION_RE.search(text))


def log_correction(user_text: str, prev_athena: str = "") -> None:
    global _dirty
    if not is_learning_enabled():
        return
    user_text = (user_text or "").strip()
    if not user_text or not looks_like_correction(user_text):
        return
    with _lock:
        _ensure_loaded()
        assert _experience is not None
        events = _experience.setdefault("events", [])
        events.append({
            "t": datetime.now().isoformat(timespec="seconds"),
            "kind": "correction",
            "user": user_text[:200],
            "prev": (prev_athena or "")[:200],
        })
        _experience["events"] = events[-_EXP_MAX:]
        _dirty = True
        _flush_if_needed()


def clear_journals() -> None:
    """Wipe activity + experience journals (used by forget_learned)."""
    global _activity, _experience, _dirty
    with _lock:
        _activity = _empty_activity()
        _experience = _empty_experience()
        _save_json(_activity_path(), _activity)
        _save_json(_experience_path(), _experience)
        _dirty = False


def _minutes_by_app(activity: dict, day_filter: str | None = None) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    days = activity.get("days") or {}
    for day, hours in days.items():
        if day_filter and day != day_filter:
            continue
        if not isinstance(hours, dict):
            continue
        for _hour, apps in hours.items():
            if not isinstance(apps, dict):
                continue
            for exe, mins in apps.items():
                try:
                    totals[str(exe)] += float(mins)
                except (TypeError, ValueError):
                    continue
    return dict(totals)


def _work_hours_hint(activity: dict) -> str:
    """Infer typical active hours from 7-day hour histogram."""
    hour_totals: dict[int, float] = defaultdict(float)
    days = activity.get("days") or {}
    for _day, hours in days.items():
        if not isinstance(hours, dict):
            continue
        for hour, apps in hours.items():
            try:
                h = int(hour)
            except ValueError:
                continue
            if not isinstance(apps, dict):
                continue
            hour_totals[h] += sum(float(v) for v in apps.values() if isinstance(v, (int, float)))
    if not hour_totals:
        return ""
    # Hours with at least 20% of peak activity
    peak = max(hour_totals.values())
    active = sorted(h for h, m in hour_totals.items() if m >= peak * 0.25)
    if not active:
        return ""
    start, end = active[0], active[-1]
    if start == end:
        return f"typically around {start:02d}:00"
    return f"typically {start:02d}:00-{end:02d}:00"


def _fmt_minutes(mins: float) -> str:
    if mins < 1:
        return f"{int(mins * 60)}s"
    if mins < 60:
        return f"{mins:.0f}m"
    return f"{mins / 60:.1f}h"


def rollup() -> None:
    """Compute learned.routines / today / lessons from local journals. No API."""
    if not is_learning_enabled():
        return
    with _lock:
        _ensure_loaded()
        _flush_if_needed(force=True)
        assert _activity is not None and _experience is not None
        activity = json.loads(json.dumps(_activity))  # shallow isolate
        experience = json.loads(json.dumps(_experience))

    by_app = _minutes_by_app(activity)
    top = sorted(by_app.items(), key=lambda x: x[1], reverse=True)[:5]
    primary = ", ".join(f"{name} ({_fmt_minutes(m)})" for name, m in top) if top else ""

    today = datetime.now().strftime("%Y-%m-%d")
    today_apps = sorted(
        _minutes_by_app(activity, day_filter=today).items(),
        key=lambda x: x[1],
        reverse=True,
    )[:3]
    today_str = ", ".join(f"{n} {_fmt_minutes(m)}" for n, m in today_apps) if today_apps else ""

    work = _work_hours_hint(activity)

    patch: dict[str, Any] = {"learned": {}}
    routines: dict[str, Any] = {}
    if work:
        routines["work_hours"] = {"value": work}
    if primary:
        routines["primary_apps"] = {"value": primary}
    if routines:
        patch["learned"]["routines"] = routines
    if today_str:
        patch["learned"]["today"] = {"summary": {"value": today_str}}

    # Lessons from tool cancel/deny counters (n >= 3)
    lessons: dict[str, Any] = {}
    counts = experience.get("tool_counts") or {}
    for key, n in counts.items():
        try:
            n = int(n)
        except (TypeError, ValueError):
            continue
        if n < 3:
            continue
        parts = str(key).split(":")
        if len(parts) < 2:
            continue
        tool = parts[0]
        outcome = parts[-1]
        action = parts[1] if len(parts) == 3 else ""
        if outcome == "cancelled":
            label = f"often cancels {tool}" + (f" {action}" if action else "")
            lessons[f"{tool}_{action or 'any'}_cancel".replace(" ", "_")] = {"value": label}
        elif outcome == "denied":
            label = f"often denied {tool}" + (f" {action}" if action else "")
            lessons[f"{tool}_{action or 'any'}_denied".replace(" ", "_")] = {"value": label}
        elif outcome == "fail":
            label = f"{tool} often fails" + (f" on {action}" if action else "")
            lessons[f"{tool}_{action or 'any'}_fail".replace(" ", "_")] = {"value": label}

    if lessons:
        patch["learned"]["lessons"] = lessons

    if not patch["learned"]:
        return

    from memory.memory_manager import update_memory
    update_memory(patch)
    print(f"[Learner] Rollup saved ({len(top)} apps, {len(lessons)} lessons)")


def apply_distill(payload: dict | None) -> None:
    """
    Merge Flash session-distill JSON into learned + compact patch.
    Expected keys: lessons[], upsert{}, forget[[]]
    """
    if not isinstance(payload, dict):
        return
    try:
        from memory.memory_manager import update_memory, apply_compact_patch

        lessons = payload.get("lessons")
        if isinstance(lessons, list) and lessons:
            learned_lessons = {}
            for i, line in enumerate(lessons[:5]):
                text = str(line or "").strip()
                if not text:
                    continue
                # Stable-ish key from first words
                slug = re.sub(r"[^\w]+", "_", text.lower())[:40].strip("_") or f"lesson_{i}"
                learned_lessons[slug] = {"value": text[:200]}
            if learned_lessons:
                update_memory({"learned": {"lessons": learned_lessons}})

        upsert = payload.get("upsert")
        forget = payload.get("forget")
        if upsert or forget:
            apply_compact_patch(
                upsert if isinstance(upsert, dict) else None,
                forget if isinstance(forget, list) else None,
            )
    except Exception as e:
        print(f"[Learner] apply_distill error: {e}")
