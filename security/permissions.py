"""Permission decisions based on risk + settings."""

from __future__ import annotations

from dataclasses import dataclass

from config.settings import get_settings
from security.risk import RiskLevel, classify_risk


@dataclass
class PermissionDecision:
    allowed: bool
    requires_confirmation: bool
    risk_level: RiskLevel
    reason: str


def evaluate_permission(tool_name: str) -> PermissionDecision:
    settings = get_settings()
    risk = classify_risk(tool_name)

    if risk == RiskLevel.CRITICAL:
        return PermissionDecision(
            allowed=False,
            requires_confirmation=True,
            risk_level=risk,
            reason="Critical actions are denied by default.",
        )

    if risk == RiskLevel.LOW:
        return PermissionDecision(
            allowed=True,
            requires_confirmation=not settings.auto_execute_low_risk,
            risk_level=risk,
            reason="Low risk auto-execute.",
        )

    if risk == RiskLevel.MEDIUM:
        return PermissionDecision(
            allowed=True,
            requires_confirmation=settings.confirm_medium_risk,
            risk_level=risk,
            reason="Medium risk requires confirmation when enabled.",
        )

    # HIGH
    return PermissionDecision(
        allowed=True,
        requires_confirmation=settings.confirm_high_risk,
        risk_level=risk,
        reason="High risk requires confirmation.",
    )


def requires_confirmation(tool_name: str) -> bool:
    decision = evaluate_permission(tool_name)
    return decision.allowed and decision.requires_confirmation
