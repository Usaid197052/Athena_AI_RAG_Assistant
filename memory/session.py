"""
Structured session state for Athena.

Tracks the current application/project/task so follow-ups like
"Open it" can resolve against recent context.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class SessionState:
    current_application: str | None = None
    current_project: str | None = None
    current_directory: str | None = None
    current_browser: str | None = None
    current_task: str | None = None
    last_action: str | None = None
    last_tool: str | None = None
    last_tool_result: str | None = None
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def update(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if hasattr(self, key) and value is not None:
                setattr(self, key, value)
        self.updated_at = datetime.now().isoformat(timespec="seconds")


_SESSION = SessionState()


def get_session() -> SessionState:
    return _SESSION


def reset_session() -> SessionState:
    global _SESSION
    _SESSION = SessionState()
    return _SESSION


def note_tool_result(tool_name: str, arguments: dict[str, Any], result: str) -> None:
    session = get_session()
    session.update(
        last_tool=tool_name,
        last_action=tool_name,
        last_tool_result=str(result)[:500],
    )

    if tool_name in {"open_application", "open_visual_studio", "open_notepad", "open_calculator"}:
        name = arguments.get("application_name")
        if not name and tool_name == "open_visual_studio":
            name = "Visual Studio"
        if not name and tool_name == "open_notepad":
            name = "Notepad"
        if name:
            session.update(current_application=str(name))

    if tool_name == "close_application":
        closed = arguments.get("application_name")
        if closed and session.current_application:
            if str(closed).lower() in session.current_application.lower():
                session.update(current_application=None)
