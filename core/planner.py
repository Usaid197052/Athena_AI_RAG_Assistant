"""Core planner facade — wraps brain.planner with context injection."""

from __future__ import annotations

from typing import Any

from brain.planner import create_plan as _create_plan
from brain.tool_call_validator import validate_plan_steps


def create_plan(
    user_request: str,
    planning_context: str | None = None,
) -> dict[str, Any]:
    plan = _create_plan(
        user_request,
        extra_context=planning_context or "",
    )

    if plan.get("error"):
        return plan

    error = validate_plan_steps(plan.get("steps") or [])
    if error:
        return {
            "steps": [],
            "error": error,
            "raw_response": plan.get("raw_response"),
        }
    return plan
