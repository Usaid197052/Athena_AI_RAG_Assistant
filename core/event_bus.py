"""
Simple in-process event bus for Athena monitors and core.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

from logs.logger import get_logger

logger = get_logger("athena.events")

Handler = Callable[[dict[str, Any]], None]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: Handler) -> None:
        self._handlers[event_type].append(handler)

    def publish(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        data = dict(payload or {})
        data.setdefault("type", event_type)
        logger.info("Event %s", event_type)
        for handler in list(self._handlers.get(event_type, [])):
            try:
                handler(data)
            except Exception as exc:
                logger.warning("Event handler failed for %s: %s", event_type, exc)
        for handler in list(self._handlers.get("*", [])):
            try:
                handler(data)
            except Exception as exc:
                logger.warning("Wildcard handler failed: %s", exc)


_BUS = EventBus()


def get_event_bus() -> EventBus:
    return _BUS
