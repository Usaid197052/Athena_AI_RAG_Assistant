"""OpenClaw health checks."""

from __future__ import annotations

from typing import Any

from openclaw.client import OpenClawClient


def is_openclaw_available() -> bool:
    client = OpenClawClient()
    if not client.enabled:
        return False
    report = client.health()
    return bool(report.get("ok"))


def health_report() -> dict[str, Any]:
    client = OpenClawClient()
    report = client.health()
    report["enabled"] = client.enabled
    report["endpoint"] = client.endpoint
    report["token_configured"] = bool(client.token)
    return report
