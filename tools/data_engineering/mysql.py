"""
MariaDB / MySQL connectivity checks.
"""

from __future__ import annotations

import socket

from config.settings import get_settings


def check_mysql() -> str:
    settings = get_settings()
    host = settings.mysql_host
    port = int(settings.mysql_port)
    try:
        with socket.create_connection((host, port), timeout=3):
            return f"MySQL/MariaDB port open at {host}:{port}."
    except OSError as exc:
        return f"MySQL/MariaDB unavailable at {host}:{port}: {exc}"
