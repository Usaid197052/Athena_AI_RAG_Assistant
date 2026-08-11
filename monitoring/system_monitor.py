"""
System resource monitor — local thresholds, event-driven notifications.
"""

from __future__ import annotations

import shutil
import threading
import time
from typing import Any

import psutil

from core.event_bus import get_event_bus
from logs.logger import get_logger
from monitoring.status_store import append_activity

logger = get_logger("athena.monitor.system")


class SystemMonitor:
    def __init__(
        self,
        interval_seconds: float = 30.0,
        disk_low_percent: float = 90.0,
        ram_high_percent: float = 95.0,
    ) -> None:
        self.interval_seconds = interval_seconds
        self.disk_low_percent = disk_low_percent
        self.ram_high_percent = ram_high_percent
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_alerts: set[str] = set()

    def snapshot(self) -> dict[str, Any]:
        memory = psutil.virtual_memory()
        disk = shutil.disk_usage("C:\\")
        return {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "ram_percent": memory.percent,
            "disk_percent": (disk.used / disk.total) * 100 if disk.total else 0,
        }

    def check_once(self) -> list[str]:
        bus = get_event_bus()
        snap = self.snapshot()
        fired: list[str] = []

        if snap["disk_percent"] >= self.disk_low_percent:
            key = "DISK_LOW"
            if key not in self._last_alerts:
                bus.publish(key, snap)
                append_activity(
                    f"Disk usage high: {snap['disk_percent']:.0f}%",
                    category="alert",
                    event=key,
                )
                self._last_alerts.add(key)
                fired.append(key)
        else:
            self._last_alerts.discard("DISK_LOW")

        if snap["ram_percent"] >= self.ram_high_percent:
            key = "RAM_HIGH"
            if key not in self._last_alerts:
                bus.publish(key, snap)
                append_activity(
                    f"RAM usage high: {snap['ram_percent']:.0f}%",
                    category="alert",
                    event=key,
                )
                self._last_alerts.add(key)
                fired.append(key)
        else:
            self._last_alerts.discard("RAM_HIGH")

        return fired

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        def loop() -> None:
            logger.info("System monitor started")
            while not self._stop.wait(self.interval_seconds):
                try:
                    self.check_once()
                except Exception as exc:
                    logger.warning("System monitor error: %s", exc)

        self._stop.clear()
        self._thread = threading.Thread(target=loop, name="athena-system-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
