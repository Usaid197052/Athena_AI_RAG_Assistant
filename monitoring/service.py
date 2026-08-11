"""
Start / stop Athena background monitors.
"""

from __future__ import annotations

from monitoring.app_monitor import AppMonitor
from monitoring.health_monitor import HealthMonitor
from monitoring.system_monitor import SystemMonitor
from monitoring.workflow_monitor import register_event_consumers

_system: SystemMonitor | None = None
_health: HealthMonitor | None = None
_apps: AppMonitor | None = None


def start_monitors() -> dict[str, str]:
    global _system, _health, _apps

    register_event_consumers()

    _system = _system or SystemMonitor()
    _health = _health or HealthMonitor()
    _apps = _apps or AppMonitor()

    _system.start()
    _health.start()
    _apps.start()

    return {
        "system": "started",
        "health": "started",
        "apps": "started",
    }


def stop_monitors() -> None:
    if _system:
        _system.stop()
    if _health:
        _health.stop()
    if _apps:
        _apps.stop()
