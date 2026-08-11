"""
System observation tools (read-only by default).
"""

from __future__ import annotations

import shutil

import psutil

from core.ollama_manager import OllamaManager
from openclaw.health import health_report


def get_system_status():
    """
    Snapshot of CPU/RAM/disk and key Athena dependencies.
    """
    cpu = psutil.cpu_percent(interval=0.2)
    memory = psutil.virtual_memory()
    disk = shutil.disk_usage("C:\\")

    ollama_ok = OllamaManager().is_running()
    claw = health_report()

    return (
        f"CPU: {cpu:.0f}%\n"
        f"RAM: {memory.percent:.0f}% "
        f"({memory.used // (1024**3)}/{memory.total // (1024**3)} GB)\n"
        f"Disk C: {disk.used // (1024**3)}/{disk.total // (1024**3)} GB "
        f"({(disk.used / disk.total) * 100:.0f}%)\n"
        f"Ollama: {'online' if ollama_ok else 'offline'}\n"
        f"OpenClaw: "
        f"{'online' if claw.get('ok') else 'offline/disabled'}"
    )


def list_processes(limit=15):
    rows = []
    for proc in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            info = proc.info
            rss = (info.get("memory_info").rss if info.get("memory_info") else 0)
            rows.append((rss, info.get("pid"), info.get("name") or "?"))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    rows.sort(reverse=True)
    lines = [
        f"{pid}\t{name}\t{rss // (1024**2)} MB"
        for rss, pid, name in rows[: max(1, int(limit))]
    ]
    return "PID\tNAME\tRSS_MB\n" + "\n".join(lines)
