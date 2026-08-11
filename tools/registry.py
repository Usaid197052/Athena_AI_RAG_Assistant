"""
Athena tool registry.

Discovers registered tools and exposes definitions for the LLM
without leaking implementation details.
"""

from __future__ import annotations

from typing import Any

from tools.base import RiskLevel, Tool, ToolResult


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return sorted(self._tools.keys())

    def definitions(self) -> list[dict[str, Any]]:
        """LLM-facing tool definitions (no code paths)."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "risk_level": tool.risk_level.value,
                "requires_confirmation": tool.requires_confirmation,
                "input_schema": tool.input_schema,
            }
            for tool in self._tools.values()
        ]

    def execute(self, name: str, arguments: dict[str, Any] | None = None) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult(
                success=False,
                message=f"Tool '{name}' not found.",
            )
        return tool.run(arguments or {})

    def as_legacy_dict(self) -> dict[str, Any]:
        """
        Compatibility shim: name -> callable(**kwargs) returning str.
        """

        def make_caller(tool_name: str):
            def caller(**kwargs):
                return str(self.execute(tool_name, kwargs))

            return caller

        return {name: make_caller(name) for name in self._tools}


_REGISTRY: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        from tools.bootstrap import build_registry

        _REGISTRY = build_registry()
    return _REGISTRY


def reset_registry() -> None:
    global _REGISTRY
    _REGISTRY = None
