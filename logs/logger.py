"""
Structured logging for Athena.

Keeps the legacy write_log / log_request helpers used by existing
modules, and adds standard library logging levels.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from config import ASSISTANT_NAME, LOG_FILE
from config.settings import get_settings

_SENSITIVE = re.compile(
    r"(password|token|api[_-]?key|secret|authorization|cookie)\s*[:=]\s*\S+",
    re.IGNORECASE,
)

_configured = False


def _redact(message: str) -> str:
    return _SENSITIVE.sub(r"\1=[REDACTED]", message)


class _AthenaFileHandler(logging.Handler):
    """Writes one `[timestamp] LEVEL message` line per record."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            line = (
                f"[{timestamp}] {record.levelname}: "
                f"{_redact(record.getMessage())}\n"
            )
            with open(LOG_FILE, "a", encoding="utf-8") as log_file:
                log_file.write(line)
        except Exception:
            self.handleError(record)


def configure_logging() -> logging.Logger:
    global _configured

    settings = get_settings()
    logger = logging.getLogger("athena")

    if _configured:
        return logger

    logger.setLevel(getattr(logging, settings.log_level, logging.INFO))
    logger.handlers.clear()
    logger.propagate = False
    logger.addHandler(_AthenaFileHandler())

    console = logging.StreamHandler()
    console.setFormatter(
        logging.Formatter("%(levelname)s | %(message)s")
    )
    console.setLevel(logging.WARNING)
    logger.addHandler(console)

    _configured = True
    return logger


def get_logger(name: str = "athena") -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)


def write_log(message: str) -> None:
    get_logger().info(_redact(str(message)))


def log_request(user_request: str) -> None:
    write_log(f"REQUEST: {user_request}")


def log_action(tool_name: str, arguments) -> None:
    write_log(f"ACTION: {tool_name} | ARGS: {_redact(str(arguments))}")


def log_result(result) -> None:
    write_log(f"RESULT: {_redact(str(result))}")


def log_wakeword(score, model_name: str = "hey_athena") -> None:
    write_log(
        f"WAKEWORD: {model_name} | "
        f"ASSISTANT: {ASSISTANT_NAME} | "
        f"SCORE: {float(score):.2f}"
    )
