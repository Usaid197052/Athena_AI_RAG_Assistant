"""
Browser tools — prefer OpenClaw when enabled; otherwise open locally.
"""

from __future__ import annotations

import webbrowser

from openclaw.executor import execute_via_openclaw
from tools.base import RiskLevel, Tool, ToolResult


def open_url(url: str) -> ToolResult:
    delegated = execute_via_openclaw("open_url", {"url": url})
    if delegated is not None:
        return delegated

    if not url.strip():
        return ToolResult(success=False, message="Error opening URL: empty URL.")
    try:
        webbrowser.open(url)
        return ToolResult(
            success=True,
            message=f"Opened URL: {url}",
            data={"provider": "local"},
        )
    except Exception as exc:
        return ToolResult(success=False, message=f"Error opening URL: {exc}")


def search_web(query: str) -> ToolResult:
    delegated = execute_via_openclaw("search_web", {"query": query})
    if delegated is not None:
        return delegated

    if not query.strip():
        return ToolResult(success=False, message="Error searching web: empty query.")
    url = f"https://www.bing.com/search?q={query.replace(' ', '+')}"
    try:
        webbrowser.open(url)
        return ToolResult(
            success=True,
            message=f"Opened web search for: {query}",
            data={"provider": "local", "url": url},
        )
    except Exception as exc:
        return ToolResult(success=False, message=f"Error searching web: {exc}")


class OpenUrlTool(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="open_url",
            description="Open a URL in the browser (OpenClaw when available).",
            risk_level=RiskLevel.LOW,
            input_schema={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        )

    def execute(self, arguments):
        return open_url(str(arguments.get("url", "")))


class SearchWebTool(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="search_web",
            description="Search the web (OpenClaw browser tool when available).",
            risk_level=RiskLevel.LOW,
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        )

    def execute(self, arguments):
        return search_web(str(arguments.get("query", "")))
