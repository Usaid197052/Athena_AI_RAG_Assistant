"""
Application launcher with verification.

Resolves names via the matcher; never requires the LLM to supply paths.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

from openclaw.executor import execute_launch
from tools.applications.matcher import match_application
from tools.applications.process_manager import is_running
from tools.base import RiskLevel, Tool, ToolResult


NEW_CONSOLE = subprocess.CREATE_NEW_CONSOLE


def launch_target(entry: dict[str, Any]) -> ToolResult:
    target = entry.get("target")
    display = entry.get("display_name", "application")

    if not target:
        return ToolResult(success=False, message=f"No launch target for {display}.")

    path = Path(target)
    if not path.exists() and path.suffix.lower() == ".exe":
        # Allow PATH-only names like notepad.exe
        if path.name != target:
            return ToolResult(
                success=False,
                message=f"Executable not found: {target}",
            )

    creationflags = 0
    if path.name.lower() in {"cmd.exe", "powershell.exe", "pwsh.exe"}:
        creationflags = NEW_CONSOLE

    result = execute_launch(
        target=str(target),
        display_name=display,
        creationflags=creationflags,
    )
    return result


def open_application(application_name: str) -> ToolResult:
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

    launch_result = launch_target(entry)
    if not launch_result.success:
        return launch_result

    # Brief wait then verify process/window presence
    time.sleep(1.5)
    running = is_running(entry)
    if not running:
        # Windows Store aliases (e.g. Calculator) can take longer
        time.sleep(1.5)
        running = is_running(entry)
    verified = running
    message = (
        f"{entry['display_name']} is open."
        if verified
        else (
            f"Launched {entry['display_name']}, "
            "but I could not verify the process yet."
        )
    )

    return ToolResult(
        success=True,
        message=message,
        data={
            "display_name": entry["display_name"],
            "target": entry.get("target"),
            "verified": verified,
        },
        verified=verified,
    )


class OpenApplicationTool(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="open_application",
            description=(
                "Open an installed Windows application by friendly name "
                "(e.g. Visual Studio, Notepad, Docker Desktop). "
                "Do not pass executable paths."
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
        name = arguments.get("application_name", "")
        return open_application(str(name))

    def verify(self, arguments: dict[str, Any], result: ToolResult) -> bool:
        if not result.success:
            return False
        if result.verified is not None:
            return result.verified
        return True
