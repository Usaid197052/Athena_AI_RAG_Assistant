"""
Process helpers for installed applications.

Never terminate a PID unless it is verified to belong to the
requested application entry.
"""

from __future__ import annotations

from typing import Any

import psutil


def _process_names(entry: dict[str, Any]) -> set[str]:
    names = {n.lower() for n in entry.get("process_names", []) if n}
    target = entry.get("target")
    if target:
        from pathlib import Path

        names.add(Path(target).name.lower())
    return names


def find_processes(entry: dict[str, Any]) -> list[psutil.Process]:
    wanted = _process_names(entry)
    found: list[psutil.Process] = []

    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            name = (proc.info.get("name") or "").lower()
            exe = (proc.info.get("exe") or "").lower()
            if name in wanted:
                found.append(proc)
                continue
            target = (entry.get("target") or "").lower()
            if target and exe and exe == target.lower():
                found.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return found


def is_running(entry: dict[str, Any]) -> bool:
    return bool(find_processes(entry))


def close_application(entry: dict[str, Any], timeout: float = 5.0) -> str:
    procs = find_processes(entry)
    if not procs:
        return f"{entry.get('display_name', 'Application')} is not running."

    wanted = _process_names(entry)
    closed = 0

    for proc in procs:
        try:
            name = (proc.name() or "").lower()
            if name not in wanted:
                continue
            proc.terminate()
            try:
                proc.wait(timeout=timeout)
            except psutil.TimeoutExpired:
                proc.kill()
            closed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            return f"Could not close process: {exc}"

    display = entry.get("display_name", "Application")
    return f"Closed {display} ({closed} process/es)."
