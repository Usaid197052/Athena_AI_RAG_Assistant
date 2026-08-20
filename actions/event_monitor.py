"""
Continuous system + event monitoring for Athena.

Polls hardware and arbitrary watches; returns at most one [SYSTEM_ALERT] per call.
Used by main.py's background loop (respects speak guards / cooldowns).
"""

from __future__ import annotations

import json
import platform
import socket
import sys
import time
from pathlib import Path
from typing import Any

import psutil

from actions.system_monitor import (
    SystemMonitor,
    get_system_status as _base_system_status,
    _get_cpu_temp,
    _get_gpu_usage,
)

_OS = platform.system()
_DISK_FREE_PCT = 10.0
_DISK_FREE_GB = 15.0
_IDLE_SECS = 45 * 60  # warn after 45 min AFK
_EVENT_COOLDOWN = 600  # 10 min per event key


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _watches_path() -> Path:
    return _base_dir() / "memory" / "event_watches.json"


def _cfg_bool(key: str, default: bool = True) -> bool:
    try:
        from memory.config_manager import load_api_keys
        val = load_api_keys().get(key, default)
        if isinstance(val, str):
            return val.lower() in ("1", "true", "yes", "on")
        return bool(val) if val is not None else default
    except Exception:
        return default


def is_continuous_monitor_enabled() -> bool:
    return _cfg_bool("continuous_monitor_enabled", True)


def is_proactive_enabled() -> bool:
    return _cfg_bool("proactive_enabled", True)


def is_learning_enabled() -> bool:
    return _cfg_bool("learning_enabled", True)


def set_continuous_monitor_enabled(enabled: bool) -> str:
    return _set_cfg_flag("continuous_monitor_enabled", enabled, "Continuous system monitoring")


def set_proactive_enabled(enabled: bool) -> str:
    return _set_cfg_flag("proactive_enabled", enabled, "Proactive check-ins")


def set_learning_enabled(enabled: bool) -> str:
    return _set_cfg_flag("learning_enabled", enabled, "Habit learning")


def _set_cfg_flag(key: str, enabled: bool, label: str) -> str:
    try:
        from memory.config_manager import load_api_keys, CONFIG_FILE, ensure_config_dir
        ensure_config_dir()
        data = load_api_keys()
        data[key] = bool(enabled)
        CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")
    except Exception as e:
        return f"Could not save setting: {e}"
    state = "ON" if enabled else "OFF"
    return f"{label} is now {state}."


def load_watches() -> list[dict[str, Any]]:
    path = _watches_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_watches(watches: list[dict[str, Any]]) -> None:
    path = _watches_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(watches, indent=2), encoding="utf-8")


def add_process_watch(process_name: str) -> str:
    name = (process_name or "").strip()
    if not name:
        return "Specify a process name (e.g. chrome.exe or Discord)."
    watches = load_watches()
    key = name.lower()
    for w in watches:
        if w.get("type") == "process" and str(w.get("match", "")).lower() == key:
            return f"Already watching process '{name}'."
    watches.append(
        {
            "id": f"proc_{key.replace(' ', '_')}",
            "type": "process",
            "match": name,
            "on": "appear",  # alert when process appears while Athena is running
        }
    )
    save_watches(watches)
    return f"Watching for process '{name}'. I'll notify you when it starts."


def remove_process_watch(process_name: str) -> str:
    name = (process_name or "").strip().lower()
    watches = load_watches()
    kept = [
        w
        for w in watches
        if not (
            w.get("type") == "process"
            and str(w.get("match", "")).lower() == name
        )
    ]
    if len(kept) == len(watches):
        return f"No process watch found for '{process_name}'."
    save_watches(kept)
    return f"Stopped watching process '{process_name}'."


def list_watches() -> list[str]:
    out = []
    for w in load_watches():
        if w.get("type") == "process":
            out.append(f"process:{w.get('match')}")
        else:
            out.append(f"{w.get('type')}:{w.get('id')}")
    return out


def _idle_seconds() -> float:
    """Seconds since last keyboard/mouse input (Windows)."""
    if _OS != "Windows":
        return 0.0
    try:
        import ctypes
        from ctypes import wintypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        tick = ctypes.windll.kernel32.GetTickCount()
        return max(0.0, (tick - info.dwTime) / 1000.0)
    except Exception:
        return 0.0


def _battery_info() -> dict[str, Any] | None:
    try:
        bat = psutil.sensors_battery()
        if not bat:
            return None
        return {
            "percent": float(bat.percent),
            "plugged": bool(bat.power_plugged),
            "secs_left": bat.secsleft if bat.secsleft and bat.secsleft > 0 else None,
        }
    except Exception:
        return None


def _disk_alerts() -> list[str]:
    alerts = []
    paths = []
    if _OS == "Windows":
        for letter in ("C:\\", "D:\\"):
            if Path(letter).exists():
                paths.append(letter)
    else:
        paths.append("/")
    for p in paths:
        try:
            u = psutil.disk_usage(p)
            free_gb = u.free / (1024**3)
            free_pct = 100.0 - u.percent
            if free_gb <= _DISK_FREE_GB:
                label = p.rstrip("\\/") or p
                alerts.append(
                    f"[SYSTEM_ALERT] Disk {label} is low on space "
                    f"({free_gb:.0f} GB free, {free_pct:.0f}% free). "
                    "Warn the user briefly and suggest freeing disk space."
                )
        except Exception:
            continue
    return alerts


def _network_ok() -> bool:
    """True if any up, non-loopback NIC has a real IPv4/IPv6 address.

    On Windows, psutil family is an enum whose str() is '2' / '23', not 'AF_INET',
    so matching the name in str(family) always failed and every startup looked offline.
    """
    try:
        stats_map = psutil.net_if_stats()
        for name, addrs in psutil.net_if_addrs().items():
            stats = stats_map.get(name)
            if not stats or not stats.isup:
                continue
            lname = (name or "").lower()
            if "loopback" in lname:
                continue
            for a in addrs:
                fam = a.family
                fam_name = getattr(fam, "name", "") or ""
                ip = (getattr(a, "address", None) or "").split("%")[0].strip()
                if not ip:
                    continue
                is_v4 = fam == socket.AF_INET or fam_name == "AF_INET"
                is_v6 = fam == socket.AF_INET6 or fam_name == "AF_INET6"
                if is_v4:
                    if ip.startswith("127.") or ip.startswith("169.254."):
                        continue
                    return True
                if is_v6:
                    low = ip.lower()
                    if low in ("::1",) or low.startswith("fe80:"):
                        continue
                    return True
        return False
    except Exception:
        return True  # fail open


def _matching_processes(match: str) -> list[str]:
    needle = (match or "").lower()
    found = []
    for p in psutil.process_iter(["name"]):
        try:
            n = (p.info.get("name") or "")
            if needle in n.lower():
                found.append(n)
        except Exception:
            continue
    return found


def get_system_status(detail: bool = False, top_n: int = 8) -> dict:
    """Extended snapshot for the system_status tool."""
    result = _base_system_status(detail=detail, top_n=top_n)
    bat = _battery_info()
    if bat:
        result["battery_percent"] = round(bat["percent"], 1)
        result["battery_plugged"] = bat["plugged"]
    try:
        disk = psutil.disk_usage("C:\\" if _OS == "Windows" else "/")
        result["disk_free_gb"] = round(disk.free / (1024**3), 1)
        result["disk_percent_used"] = round(disk.percent, 1)
    except Exception:
        pass
    idle = _idle_seconds()
    if idle > 0:
        result["idle_minutes"] = round(idle / 60.0, 1)
    result["continuous_monitor"] = is_continuous_monitor_enabled()
    result["proactive"] = is_proactive_enabled()
    result["learning"] = is_learning_enabled()
    return result


class ContinuousEventMonitor:
    """
    Continuous watcher: hardware + battery/disk/network/idle + process watches.
    Returns one [SYSTEM_ALERT] string or None.
    """

    def __init__(self, thresholds: dict | None = None):
        self._sys = SystemMonitor(thresholds=thresholds)
        self._last_alert: dict[str, float] = {}
        self._proc_seen: dict[str, bool] = {}
        self._on_battery: bool | None = None
        self._net_was_ok: bool | None = None  # None = not sampled yet
        self._idle_warned = False

    def _can(self, key: str, cooldown: float = _EVENT_COOLDOWN) -> bool:
        return (time.monotonic() - self._last_alert.get(key, 0)) > cooldown

    def _record(self, key: str) -> None:
        self._last_alert[key] = time.monotonic()

    def check(self) -> str | None:
        # Habit learner tick — runs even when continuous alerts are off / no alert fires
        try:
            from memory.learner import tick as learner_tick
            learner_tick()
        except Exception:
            pass

        if not is_continuous_monitor_enabled():
            return None

        # Hardware first (CPU/RAM/temp/GPU)
        hw = self._sys.check()
        if hw:
            return hw

        # Battery
        bat = _battery_info()
        if bat:
            plugged = bat["plugged"]
            pct = bat["percent"]
            if self._on_battery is None:
                self._on_battery = not plugged
            elif plugged and self._on_battery:
                self._on_battery = False
                if self._can("ac_restored", 120):
                    self._record("ac_restored")
                    return (
                        "[SYSTEM_ALERT] Power connected — battery is charging. "
                        "Briefly mention this to the user."
                    )
            elif (not plugged) and (not self._on_battery):
                self._on_battery = True
                if self._can("on_battery", 120):
                    self._record("on_battery")
                    return (
                        f"[SYSTEM_ALERT] Device switched to battery power "
                        f"({pct:.0f}% remaining). Briefly inform the user."
                    )
            if (not plugged) and pct <= 20 and self._can("bat_low"):
                self._record("bat_low")
                return (
                    f"[SYSTEM_ALERT] Battery is low at {pct:.0f}%. "
                    "Warn the user to plug in the charger."
                )
            if (not plugged) and pct <= 10 and self._can("bat_critical", 180):
                self._record("bat_critical")
                return (
                    f"[SYSTEM_ALERT] Battery critically low at {pct:.0f}%. "
                    "Urge the user to plug in immediately."
                )

        # Disk space
        for alert in _disk_alerts():
            key = "disk:" + alert[40:60]
            if self._can(key):
                self._record(key)
                return alert

        # Network down / restored — first sample only records state (no false startup alarm)
        ok = _network_ok()
        if self._net_was_ok is None:
            self._net_was_ok = ok
        elif self._net_was_ok and not ok and self._can("net_down", 180):
            self._net_was_ok = False
            self._record("net_down")
            return (
                "[SYSTEM_ALERT] Network connectivity appears down "
                "(no active interface with a real IP). Inform the user briefly."
            )
        elif ok and not self._net_was_ok and self._can("net_up", 120):
            self._net_was_ok = True
            self._record("net_up")
            return (
                "[SYSTEM_ALERT] Network connectivity is back. "
                "Briefly tell the user."
            )
        else:
            self._net_was_ok = ok

        # Idle / AFK
        idle = _idle_seconds()
        if idle >= _IDLE_SECS:
            if not self._idle_warned and self._can("idle", 1800):
                self._idle_warned = True
                self._record("idle")
                mins = int(idle // 60)
                return (
                    f"[SYSTEM_ALERT] No keyboard or mouse activity for about {mins} minutes. "
                    "Gently check if the user is still there or wants a break reminder. "
                    "One short sentence."
                )
        else:
            self._idle_warned = False

        # Custom process watches (appear)
        for w in load_watches():
            if w.get("type") != "process":
                continue
            match = str(w.get("match") or "")
            if not match:
                continue
            key = match.lower()
            running = bool(_matching_processes(match))
            was = self._proc_seen.get(key, False)
            if running and not was:
                self._proc_seen[key] = True
                if self._can(f"proc:{key}", 300):
                    self._record(f"proc:{key}")
                    return (
                        f"[SYSTEM_ALERT] Watched process '{match}' just started. "
                        "Briefly notify the user."
                    )
            elif not running:
                self._proc_seen[key] = False

        return None


def manage_continuous_monitor(parameters: dict | None = None) -> str:
    """Tool entry: control continuous monitoring / proactive / process watches."""
    params = parameters or {}
    action = str(params.get("action", "status") or "status").lower().strip().replace("-", "_")
    target = str(
        params.get("process")
        or params.get("name")
        or params.get("topic")
        or ""
    ).strip()

    if action in ("status", "list", "learning_status", "learning", "is_learning"):
        watches = list_watches()
        return (
            f"Continuous monitor: {'ON' if is_continuous_monitor_enabled() else 'OFF'}. "
            f"Proactive check-ins: {'ON' if is_proactive_enabled() else 'OFF'}. "
            f"Learning: {'ON' if is_learning_enabled() else 'OFF'}. "
            f"Process watches: {', '.join(watches) if watches else '(none)'}."
        )
    if action in ("enable", "on", "start"):
        what = str(params.get("target") or params.get("mode") or "monitor").lower()
        if "proactive" in what:
            return set_proactive_enabled(True)
        if "learn" in what:
            return set_learning_enabled(True)
        return set_continuous_monitor_enabled(True)
    if action in ("disable", "off", "stop"):
        what = str(params.get("target") or params.get("mode") or "monitor").lower()
        if "proactive" in what:
            return set_proactive_enabled(False)
        if "learn" in what:
            return set_learning_enabled(False)
        if target:
            return remove_process_watch(target)
        return set_continuous_monitor_enabled(False)
    if action in ("watch", "watch_process", "add"):
        if not target:
            return "Specify a process name to watch (e.g. Discord.exe)."
        return add_process_watch(target)
    if action in ("unwatch", "remove"):
        if not target:
            return "Specify which process watch to remove."
        return remove_process_watch(target)
    if action in ("enable_proactive", "proactive_on"):
        return set_proactive_enabled(True)
    if action in ("disable_proactive", "proactive_off"):
        return set_proactive_enabled(False)
    if action in ("learning_on", "enable_learning", "learn_on"):
        return set_learning_enabled(True)
    if action in ("learning_off", "disable_learning", "learn_off"):
        return set_learning_enabled(False)
    if action in ("forget_learned", "clear_learned", "reset_learning"):
        try:
            from memory.memory_manager import forget_learned
            from memory.learner import clear_journals
            msg = forget_learned()
            clear_journals()
            return msg + " Activity journals cleared."
        except Exception as e:
            return f"Could not clear learned data: {e}"
    return (
        "Unknown action. Use status | learning_status | enable | disable | watch | unwatch | "
        "enable_proactive | disable_proactive | learning_on | learning_off | forget_learned."
    )
