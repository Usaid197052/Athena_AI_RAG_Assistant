"""
Docker inspection tools for Athena.

Deterministic subprocess calls — the LLM never invents docker commands
to run blindly; these helpers wrap known-safe read operations.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any


def _docker_bin() -> str | None:
    return shutil.which("docker")


def _run(args: list[str], timeout: float = 20.0) -> tuple[bool, str]:
    binary = _docker_bin()
    if not binary:
        return False, "Docker CLI not found on PATH."
    try:
        completed = subprocess.run(
            [binary, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:
        return False, f"Docker command failed: {exc}"

    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or "").strip()
        return False, err or f"Docker exited with code {completed.returncode}"
    return True, (completed.stdout or "").strip()


def check_docker() -> str:
    ok, output = _run(["info", "--format", "{{.ServerVersion}}"])
    if not ok:
        # Distinguish daemon-down vs missing CLI
        if "not found" in output.lower():
            return f"Docker unavailable: {output}"
        return (
            "Docker CLI found but the engine looks unavailable. "
            f"Detail: {output}"
        )
    version = output or "unknown"
    ok_ps, ps_out = _run(["ps", "--format", "{{.Names}}"])
    running = [line for line in (ps_out.splitlines() if ok_ps else []) if line.strip()]
    return (
        f"Docker engine online (server {version}). "
        f"Running containers: {len(running)}"
        + (f" ({', '.join(running[:8])})" if running else "")
    )


def list_containers(all_containers: bool = False) -> str:
    args = ["ps", "--format", "{{json .}}"]
    if all_containers:
        args.insert(1, "-a")
    ok, output = _run(args)
    if not ok:
        return f"Error listing containers: {output}"
    if not output.strip():
        return "No containers found."

    lines = []
    for raw in output.splitlines():
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        name = row.get("Names") or row.get("names") or "?"
        status = row.get("Status") or row.get("status") or "?"
        image = row.get("Image") or row.get("image") or "?"
        lines.append(f"{name}\t{status}\t{image}")
    return "NAME\tSTATUS\tIMAGE\n" + "\n".join(lines) if lines else "No containers found."


def docker_compose_ps(project_dir: str) -> str:
    binary = _docker_bin()
    if not binary:
        return "Error: Docker CLI not found on PATH."
    try:
        completed = subprocess.run(
            [binary, "compose", "ps", "--format", "json"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except Exception as exc:
        return f"Error running docker compose ps: {exc}"

    if completed.returncode != 0:
        return f"Error: {(completed.stderr or completed.stdout or '').strip()}"

    text = (completed.stdout or "").strip()
    if not text:
        return "No compose services found."

    # compose may emit a JSON array or NDJSON depending on version
    rows: list[dict[str, Any]] = []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            rows = [item for item in parsed if isinstance(item, dict)]
    except json.JSONDecodeError:
        for line in text.splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)

    if not rows:
        return text[:1000]

    lines = []
    for row in rows:
        name = row.get("Name") or row.get("Service") or "?"
        state = row.get("State") or row.get("Status") or "?"
        lines.append(f"{name}: {state}")
    return "Compose services:\n" + "\n".join(lines)
