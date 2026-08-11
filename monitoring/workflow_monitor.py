"""
Wire event-bus consumers that update activity/status.
"""

from __future__ import annotations

from typing import Any

from core.event_bus import get_event_bus
from monitoring.status_store import append_activity, write_status

_REGISTERED = False


def _on_task_completed(payload: dict[str, Any]) -> None:
    goal = payload.get("goal") or payload.get("task_id") or "task"
    append_activity(f"Task completed: {goal}", category="task", event="TASK_COMPLETED")
    write_status(current_task=None, voice="ready")


def _on_task_failed(payload: dict[str, Any]) -> None:
    reason = payload.get("reason") or "unknown"
    tool = payload.get("tool") or "tool"
    append_activity(
        f"Task failed at {tool}: {reason}",
        category="task",
        event="TASK_FAILED",
    )
    write_status(last_error=str(reason))


def _on_task_cancelled(payload: dict[str, Any]) -> None:
    append_activity(
        f"Task cancelled at step {payload.get('step')}",
        category="task",
        event="TASK_CANCELLED",
    )


def register_event_consumers() -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    bus = get_event_bus()
    bus.subscribe("TASK_COMPLETED", _on_task_completed)
    bus.subscribe("TASK_FAILED", _on_task_failed)
    bus.subscribe("TASK_CANCELLED", _on_task_cancelled)
    _REGISTERED = True
