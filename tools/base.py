"""
Common tool interface for Athena.

Every tool exposes metadata (risk, permissions, schema) plus
execute() and optional verify().
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class ToolResult:
    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    verified: bool | None = None

    def __str__(self) -> str:
        return self.message


@dataclass
class Tool(ABC):
    name: str
    description: str
    risk_level: RiskLevel = RiskLevel.LOW
    requires_confirmation: bool = False
    input_schema: dict[str, Any] = field(default_factory=dict)

    @abstractmethod
    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        raise NotImplementedError

    def verify(self, arguments: dict[str, Any], result: ToolResult) -> bool:
        """Optional post-action check. Default: trust execute()."""
        return result.success

    def run(self, arguments: dict[str, Any] | None = None) -> ToolResult:
        arguments = arguments or {}
        result = self.execute(arguments)
        result.verified = self.verify(arguments, result)
        if result.success and result.verified is False:
            result.success = False
            result.message = (
                f"{result.message} (verification failed)"
            )
        return result


class FunctionTool(Tool):
    """Wraps a plain callable as a Tool for gradual migration."""

    def __init__(
        self,
        name: str,
        description: str,
        func: Callable[..., Any],
        risk_level: RiskLevel = RiskLevel.LOW,
        requires_confirmation: bool = False,
        input_schema: dict[str, Any] | None = None,
        verify_fn: Callable[[dict[str, Any], ToolResult], bool] | None = None,
    ):
        super().__init__(
            name=name,
            description=description,
            risk_level=risk_level,
            requires_confirmation=requires_confirmation,
            input_schema=input_schema or {},
        )
        self._func = func
        self._verify_fn = verify_fn

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            output = self._func(**arguments) if arguments else self._func()
            message = str(output)
            success = not message.lower().startswith("error")
            return ToolResult(success=success, message=message, data={"raw": output})
        except TypeError:
            # Some legacy tools ignore kwargs differently
            output = self._func(**arguments)
            return ToolResult(success=True, message=str(output), data={"raw": output})
        except Exception as exc:
            return ToolResult(success=False, message=f"Execution Error: {exc}")

    def verify(self, arguments: dict[str, Any], result: ToolResult) -> bool:
        if self._verify_fn is not None:
            return self._verify_fn(arguments, result)
        return result.success
