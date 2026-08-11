"""
Post-action verification for Athena tools.

Deterministic checks only — the LLM does not invent success.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.applications.matcher import match_application
from tools.applications.process_manager import is_running
from tools.base import ToolResult


def verify_tool_result(
    tool_name: str,
    arguments: dict[str, Any],
    result: str | ToolResult,
) -> tuple[bool, str]:
    """
    Returns (verified_ok, message).
    """
    text = str(result)
    lower = text.lower()

    if lower.startswith("error") or "execution error" in lower:
        return False, "Result reported an error."

    if isinstance(result, ToolResult) and result.verified is not None:
        return bool(result.verified), (
            "Tool-reported verification passed."
            if result.verified
            else "Tool-reported verification failed."
        )

    if tool_name in {
        "open_application",
        "open_visual_studio",
        "open_notepad",
        "open_calculator",
        "open_cmd",
        "open_powershell",
    }:
        name = arguments.get("application_name")
        if not name:
            defaults = {
                "open_visual_studio": "Visual Studio",
                "open_notepad": "Notepad",
                "open_calculator": "Calculator",
                "open_cmd": "Command Prompt",
                "open_powershell": "Windows PowerShell",
            }
            name = defaults.get(tool_name)
        if not name:
            return True, "No application name to verify."
        match = match_application(str(name))
        if match.status != "matched" or not match.entry:
            return False, match.message
        running = is_running(match.entry)
        return running, (
            f"{match.entry['display_name']} process verified."
            if running
            else f"{match.entry['display_name']} process not found."
        )

    if tool_name == "close_application":
        name = arguments.get("application_name", "")
        match = match_application(str(name))
        if match.status != "matched" or not match.entry:
            return True, "Close target unresolved; accepting tool message."
        running = is_running(match.entry)
        return (not running), (
            f"{match.entry['display_name']} is closed."
            if not running
            else f"{match.entry['display_name']} is still running."
        )

    if tool_name in {"create_file", "write_file", "copy_file", "move_file", "rename_file"}:
        path_key = {
            "create_file": "file_path",
            "write_file": "file_path",
            "copy_file": "destination_path",
            "move_file": "destination_path",
            "rename_file": "new_name",
        }[tool_name]
        path = Path(str(arguments.get(path_key, "")))
        # move/copy may land inside a directory destination
        if tool_name in {"copy_file", "move_file"} and path.exists() and path.is_dir():
            source_name = Path(str(arguments.get("source_path", ""))).name
            path = path / source_name
        exists = path.exists()
        return exists, (
            f"Verified path exists: {path}"
            if exists
            else f"Expected path missing: {path}"
        )

    if tool_name == "delete_file":
        path = Path(str(arguments.get("file_path", "")))
        gone = not path.exists()
        return gone, (
            f"Verified deleted: {path}"
            if gone
            else f"File still exists: {path}"
        )

    if tool_name in {"run_python_script", "run_cmd_command", "run_powershell_command"}:
        # Legacy tools return text; treat explicit failure markers as failed.
        if "error" in lower and "successfully" not in lower:
            return False, "Command output suggests failure."
        return True, "Command completed without explicit error marker."

    return True, "No specific verifier; accepted result."
