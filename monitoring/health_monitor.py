"""
Health monitor for Ollama, RAG, OpenClaw and related services.
"""

from __future__ import annotations

import threading
from typing import Any

from core.event_bus import get_event_bus
from core.ollama_manager import OllamaManager
from logs.logger import get_logger
from monitoring.status_store import append_activity, write_status
from openclaw.health import health_report
from rag.client import RagClient

logger = get_logger("athena.monitor.health")


class HealthMonitor:
    def __init__(self, interval_seconds: float = 45.0) -> None:
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._previous: dict[str, str] = {}

    def check_once(self) -> dict[str, Any]:
        ollama_ok = OllamaManager().is_running()
        rag = RagClient().status()
        claw = health_report()

        status = {
            "ollama": "ready" if ollama_ok else "offline",
            "rag": "ready" if rag.get("ok") else "offline",
            "openclaw": (
                "connected"
                if claw.get("ok")
                else ("disabled" if not claw.get("enabled") else "offline")
            ),
            "memory": "ready",
        }
        write_status(**status)

        bus = get_event_bus()
        if self._previous.get("ollama") == "ready" and status["ollama"] == "offline":
            bus.publish("OLLAMA_FAILED", status)
            append_activity("Ollama became unavailable", category="alert", event="OLLAMA_FAILED")
        if self._previous.get("openclaw") == "connected" and status["openclaw"] == "offline":
            bus.publish("OPENCLAW_FAILED", status)
            append_activity("OpenClaw became unavailable", category="alert", event="OPENCLAW_FAILED")

        self._previous = dict(status)
        return status

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        def loop() -> None:
            logger.info("Health monitor started")
            self.check_once()
            while not self._stop.wait(self.interval_seconds):
                try:
                    self.check_once()
                except Exception as exc:
                    logger.warning("Health monitor error: %s", exc)

        self._stop.clear()
        self._thread = threading.Thread(target=loop, name="athena-health-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
