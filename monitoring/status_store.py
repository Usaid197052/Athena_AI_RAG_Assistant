"""
Persistent Athena status for tray / dashboard IPC.

Written by the agent process; read by UI processes.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from config.settings import PROJECT_ROOT, get_settings

STATUS_FILE = PROJECT_ROOT / "data" / "cache" / "athena_status.json"
ACTIVITY_FILE = PROJECT_ROOT / "data" / "logs" / "activity.jsonl"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def default_status() -> dict[str, Any]:
    settings = get_settings()
    return {
        "assistant": settings.assistant_name,
        "version": settings.athena_version,
        "updated_at": _now(),
        "voice": "idle",
        "listening": False,
        "paused": False,
        "rag": "unknown",
        "ollama": "unknown",
        "openclaw": "disabled" if not settings.openclaw_enabled else "unknown",
        "memory": "ready",
        "current_task": None,
        "last_error": None,
        "ux_phase": "Idle",
        "ux_detail": "",
    }


def set_ux_phase(phase: str, detail: str = "", **extra: Any) -> dict[str, Any]:
    """
    Publish a user-facing progress phrase (Phase 55 Professional UX).

    Examples: Thinking..., Searching memory..., Opening Visual Studio...
    """
    updates: dict[str, Any] = {
        "ux_phase": phase,
        "ux_detail": detail or "",
    }
    updates.update({k: v for k, v in extra.items() if v is not None})
    return write_status(**updates)


def read_status() -> dict[str, Any]:
    if not STATUS_FILE.exists():
        return default_status()
    try:
        data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        base = default_status()
        base.update(data)
        return base
    except Exception:
        return default_status()


def write_status(**updates: Any) -> dict[str, Any]:
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    current = read_status()
    current.update({k: v for k, v in updates.items() if v is not None})
    current["updated_at"] = _now()
    STATUS_FILE.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current


def append_activity(message: str, category: str = "info", **extra: Any) -> None:
    ACTIVITY_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": _now(),
        "category": category,
        "message": message,
        **extra,
    }
    with open(ACTIVITY_FILE, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def recent_activity(limit: int = 20) -> list[dict[str, Any]]:
    if not ACTIVITY_FILE.exists():
        return []
    lines = ACTIVITY_FILE.read_text(encoding="utf-8").splitlines()
    items: list[dict[str, Any]] = []
    for line in lines[-max(1, limit) :]:
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return list(reversed(items))
