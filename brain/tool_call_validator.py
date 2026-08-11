"""
Validate structured tool calls before execution.
"""

from __future__ import annotations

from typing import Any

from tools.registry import get_registry


def validate_tool_call(payload: dict[str, Any]) -> str | None:
    """
    Returns an error string if invalid, otherwise None.
    Expected shape: {"tool": str, "arguments": dict}
    """
    if not isinstance(payload, dict):
        return "Tool call must be a JSON object."

    tool = payload.get("tool")
    if not isinstance(tool, str) or not tool.strip():
        return "Tool call missing tool name."

    registry = get_registry()
    if not registry.has(tool):
        return f"Unknown tool '{tool}'."

    arguments = payload.get("arguments", {})
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return "Tool arguments must be an object."

    entry = registry.get(tool)
    schema = entry.input_schema if entry else {}
    required = schema.get("required") or []
    for key in required:
        if key not in arguments or arguments[key] in (None, ""):
            return f"Missing required argument '{key}' for tool '{tool}'."

    return None


def validate_plan_steps(steps: list[Any]) -> str | None:
    if not isinstance(steps, list) or not steps:
        return "Plan contains no steps."

    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            return f"Step {index} is not an object."
        error = validate_tool_call(
            {
                "tool": step.get("tool"),
                "arguments": step.get("arguments", {}),
            }
        )
        if error:
            return f"Step {index}: {error}"
    return None
