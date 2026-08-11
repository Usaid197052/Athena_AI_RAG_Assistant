"""
Close / focus application tools.
"""

from __future__ import annotations

from typing import Any

from tools.applications.matcher import match_application
from tools.applications.process_manager import close_application as close_procs
from tools.applications.process_manager import is_running
from tools.base import RiskLevel, Tool, ToolResult


def close_application(application_name: str) -> ToolResult:
    match = match_application(application_name)

    if match.status == "not_found":
        return ToolResult(success=False, message=match.message)

    if match.status == "ambiguous":
        return ToolResult(
            success=False,
            message=match.message,
            data={"matches": [m["display_name"] for m in match.matches]},
        )

    entry = match.entry
    assert entry is not None

    if not is_running(entry):
        return ToolResult(
            success=True,
            message=f"{entry['display_name']} is not running.",
            data={"display_name": entry["display_name"]},
            verified=True,
        )

    message = close_procs(entry)
    still = is_running(entry)
    ok = not still
    return ToolResult(
        success=ok,
        message=message if ok else f"{message} (still detected running)",
        data={"display_name": entry["display_name"]},
        verified=ok,
    )


class CloseApplicationTool(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="close_application",
            description=(
                "Close a running Windows application by friendly name. "
                "Do not pass PIDs or executable paths."
            ),
            risk_level=RiskLevel.LOW,
            requires_confirmation=False,
            input_schema={
                "type": "object",
                "properties": {
                    "application_name": {
                        "type": "string",
                        "description": "Friendly application name",
                    }
                },
                "required": ["application_name"],
            },
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return close_application(str(arguments.get("application_name", "")))
