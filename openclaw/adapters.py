"""
Map Athena-approved actions onto OpenClaw Gateway tools.

Important: Gateway HTTP `/tools/invoke` denies `exec`/`spawn`/`shell` by
default. Application launching therefore stays on Athena's local executor
unless the operator explicitly allowlists an HTTP-safe tool.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class OpenClawCall:
    tool: str
    args: dict[str, Any]
    action: str | None = None
    notes: str = ""


def adapt_browser_navigate(url: str) -> OpenClawCall:
    return OpenClawCall(
        tool="browser",
        args={"action": "open", "url": url},
        notes="Requires browser tool enabled in OpenClaw policy.",
    )


def adapt_browser_search(query: str) -> OpenClawCall:
    return OpenClawCall(
        tool="browser",
        args={"action": "search", "query": query},
        notes="Requires browser tool enabled in OpenClaw policy.",
    )


def adapt_sessions_list() -> OpenClawCall:
    return OpenClawCall(tool="sessions_list", args={})


def adapt_athena_action(action_name: str, arguments: dict[str, Any]) -> OpenClawCall | None:
    """
    Returns an OpenClaw call for actions Athena prefers to delegate,
    or None when Athena should execute locally.
    """
    if action_name in {"search_web", "browser_search"}:
        return adapt_browser_search(str(arguments.get("query") or arguments.get("q") or ""))

    if action_name in {"open_url", "browser_open"}:
        return adapt_browser_navigate(str(arguments.get("url") or ""))

    # App launches remain local — Gateway denies exec over HTTP by default.
    if action_name in {
        "open_application",
        "close_application",
        "open_visual_studio",
        "open_notepad",
    }:
        return None

    return None
