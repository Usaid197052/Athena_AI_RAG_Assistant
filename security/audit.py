"""Audit trail for tool executions (no secrets)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from logs.logger import write_log


def audit_event(
    user_request: str | None,
    tool: str,
    arguments: dict[str, Any] | None,
    risk_level: str,
    permission: str,
    result: str,
    verification: str | None = None,
    error: str | None = None,
) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    parts = [
        f"AUDIT {timestamp}",
        f"Request: {user_request or '-'}",
        f"Tool: {tool}",
        f"Args: {arguments or {}}",
        f"Risk: {risk_level}",
        f"Permission: {permission}",
        f"Result: {result}",
    ]
    if verification is not None:
        parts.append(f"Verification: {verification}")
    if error:
        parts.append(f"Error: {error}")
    write_log(" | ".join(parts))
