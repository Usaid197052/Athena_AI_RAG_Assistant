"""
Execution adapter: OpenClaw for delegated tools, local subprocess for launches.
"""

from __future__ import annotations

import subprocess
from typing import Any

from logs.logger import get_logger
from openclaw.adapters import adapt_athena_action
from openclaw.client import OpenClawClient
from openclaw.health import is_openclaw_available
from tools.base import ToolResult

logger = get_logger("athena.openclaw.executor")


def execute_launch(
    target: str,
    display_name: str,
    creationflags: int = 0,
) -> ToolResult:
    """
    Launch an executable locally.

    OpenClaw Gateway HTTP denies exec/spawn by default, so Athena keeps
    deterministic local launching for applications.
    """
    try:
        subprocess.Popen([target], creationflags=creationflags)
        return ToolResult(
            success=True,
            message=f"Launched {display_name}.",
            data={"target": target, "provider": "local"},
        )
    except Exception as exc:
        return ToolResult(
            success=False,
            message=f"Error opening {display_name}: {exc}",
        )


def execute_via_openclaw(
    action_name: str,
    arguments: dict[str, Any] | None = None,
) -> ToolResult | None:
    """
    Attempt OpenClaw delegation. Returns None when Athena should run locally.
    """
    arguments = arguments or {}
    call = adapt_athena_action(action_name, arguments)
    if call is None:
        return None

    if not is_openclaw_available():
        # Let Athena use its local fallback for browser actions.
        return None

    try:
        client = OpenClawClient()
        result = client.invoke(tool=call.tool, args=call.args, action=call.action)
        if result.get("ok"):
            return ToolResult(
                success=True,
                message=f"OpenClaw completed '{call.tool}'.",
                data={"provider": "openclaw", "result": result.get("result")},
            )
        return ToolResult(
            success=False,
            message=(
                f"OpenClaw rejected '{call.tool}': "
                f"{result.get('error') or result.get('status_code')}"
            ),
            data={"provider": "openclaw", "raw": result},
        )
    except Exception as exc:
        logger.warning("OpenClaw invoke failed: %s", exc)
        return ToolResult(
            success=False,
            message=f"OpenClaw is unavailable, so I couldn't execute that action. ({exc})",
            data={"provider": "openclaw"},
        )
