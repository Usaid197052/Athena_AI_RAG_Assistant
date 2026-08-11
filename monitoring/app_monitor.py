"""
Application monitor — tracks whether watched processes are alive.
"""

from __future__ import annotations

import threading
from typing import Any

from core.event_bus import get_event_bus
from logs.logger import get_logger
from monitoring.status_store import append_activity
from tools.applications.discovery import load_registry
from tools.applications.matcher import match_application
from tools.applications.process_manager import is_running

logger = get_logger("athena.monitor.apps")


class AppMonitor:
    def __init__(
        self,
        watched: list[str] | None = None,
        interval_seconds: float = 60.0,
    ) -> None:
        self.watched = watched or ["Docker Desktop", "Visual Studio"]
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._was_running: dict[str, bool] = {}

    def check_once(self) -> dict[str, Any]:
        registry = load_registry()
        report: dict[str, Any] = {}
        bus = get_event_bus()

        for name in self.watched:
            match = match_application(name, registry)
            if match.status != "matched" or not match.entry:
                report[name] = "not_found"
                continue
            running = is_running(match.entry)
            report[name] = "running" if running else "stopped"
            previous = self._was_running.get(name)
            if previous is True and not running:
                bus.publish(
                    "APPLICATION_CRASHED",
                    {"application": name, "display_name": match.entry["display_name"]},
                )
                append_activity(
                    f"{match.entry['display_name']} stopped unexpectedly",
                    category="alert",
                    event="APPLICATION_CRASHED",
                )
            self._was_running[name] = running

        return report

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        def loop() -> None:
            logger.info("App monitor started")
            self.check_once()
            while not self._stop.wait(self.interval_seconds):
                try:
                    self.check_once()
                except Exception as exc:
                    logger.warning("App monitor error: %s", exc)

        self._stop.clear()
        self._thread = threading.Thread(target=loop, name="athena-app-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
