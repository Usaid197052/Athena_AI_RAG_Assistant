"""
Windows application discovery.

Builds a normalized local registry from Start Menu shortcuts,
common install locations, and PATH — never hard-coded machine paths.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from config.settings import get_settings
from logs.logger import get_logger

logger = get_logger("athena.apps.discovery")

KNOWN_ALIASES: dict[str, list[str]] = {
    "visual studio": ["vs", "devenv", "microsoft visual studio"],
    "visual studio code": ["vscode", "code", "vs code"],
    "notepad": ["text editor"],
    "calculator": ["calc"],
    "command prompt": ["cmd", "terminal"],
    "windows powershell": ["powershell", "ps"],
    "docker desktop": ["docker"],
    "google chrome": ["chrome"],
    "microsoft edge": ["edge"],
    "mozilla firefox": ["firefox"],
}


def normalize_name(name: str) -> str:
    text = name.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _shortcut_dirs() -> list[Path]:
    dirs: list[Path] = []
    program_data = os.environ.get("PROGRAMDATA")
    appdata = os.environ.get("APPDATA")
    if program_data:
        dirs.append(Path(program_data) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    if appdata:
        dirs.append(Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    return [d for d in dirs if d.exists()]


def _resolve_lnk(path: Path) -> str | None:
    """Resolve a .lnk target using PowerShell (no pywin32 required)."""
    try:
        import subprocess

        script = (
            f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{path}');"
            f"$s.TargetPath"
        )
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        target = (completed.stdout or "").strip()
        if target and Path(target).exists():
            return target
    except Exception as exc:
        logger.debug("Failed to resolve shortcut %s: %s", path, exc)
    return None


def _entry_from_target(display_name: str, target: str, launch_type: str = "executable") -> dict[str, Any]:
    key = normalize_name(display_name)
    aliases = list(KNOWN_ALIASES.get(key, []))
    aliases.append(key)
    stem = normalize_name(Path(target).stem)
    if stem and stem not in aliases:
        aliases.append(stem)
    return {
        "display_name": display_name,
        "aliases": sorted(set(aliases)),
        "launch_type": launch_type,
        "target": target,
        "process_names": [Path(target).name.lower()],
    }


def scan_start_menu() -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}

    for root in _shortcut_dirs():
        for lnk in root.rglob("*.lnk"):
            display = lnk.stem
            target = _resolve_lnk(lnk)
            if not target:
                continue
            lower = target.lower()
            if not (lower.endswith(".exe") or lower.endswith(".bat") or lower.endswith(".cmd")):
                continue
            key = normalize_name(display)
            if key in registry:
                continue
            registry[key] = _entry_from_target(display, target)

    return registry


PATH_ALLOWLIST = {
    "notepad",
    "calc",
    "cmd",
    "powershell",
    "pwsh",
    "code",
    "devenv",
    "chrome",
    "msedge",
    "firefox",
    "explorer",
    "wt",
    "docker",
    "python",
    "py",
}


def scan_path_executables() -> dict[str, dict[str, Any]]:
    """Index a small allowlist of PATH executables (not every system binary)."""
    registry: dict[str, dict[str, Any]] = {}
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)

    for directory in path_dirs:
        if not directory:
            continue
        folder = Path(directory)
        if not folder.is_dir():
            continue
        try:
            for exe in folder.glob("*.exe"):
                stem = normalize_name(exe.stem)
                if stem not in PATH_ALLOWLIST:
                    continue
                key = stem
                if key in registry:
                    continue
                registry[key] = _entry_from_target(exe.stem, str(exe))
        except PermissionError:
            continue

    return registry


def scan_common_apps() -> dict[str, dict[str, Any]]:
    """Light scan of well-known Windows locations without hard-coding one machine."""
    registry: dict[str, dict[str, Any]] = {}
    candidates: list[tuple[str, list[Path]]] = [
        (
            "Visual Studio",
            list(Path(r"C:\Program Files\Microsoft Visual Studio").glob(r"*\*\Common7\IDE\devenv.exe"))
            if Path(r"C:\Program Files\Microsoft Visual Studio").exists()
            else [],
        ),
        (
            "Docker Desktop",
            [
                Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
                / "Docker"
                / "Docker"
                / "Docker Desktop.exe"
            ],
        ),
        ("Notepad", [Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "notepad.exe"]),
        ("Calculator", [Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "calc.exe"]),
        ("Command Prompt", [Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "cmd.exe"]),
        (
            "Windows PowerShell",
            [
                Path(os.environ.get("WINDIR", r"C:\Windows"))
                / "System32"
                / "WindowsPowerShell"
                / "v1.0"
                / "powershell.exe"
            ],
        ),
    ]

    for display, paths in candidates:
        for path in paths:
            if path.exists():
                key = normalize_name(display)
                entry = _entry_from_target(display, str(path))
                if key == "calculator":
                    entry["process_names"] = [
                        "calc.exe",
                        "calculator.exe",
                        "calculatorapp.exe",
                    ]
                registry[key] = entry
                break

    return registry


def build_registry(include_start_menu: bool = True) -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}

    # Lower-priority sources first; higher-quality sources overwrite.
    for key, entry in scan_path_executables().items():
        registry.setdefault(key, entry)

    if include_start_menu:
        for key, entry in scan_start_menu().items():
            registry.setdefault(key, entry)

    registry.update(scan_common_apps())
    return registry


def save_registry(registry: dict[str, dict[str, Any]], path: Path | None = None) -> Path:
    settings = get_settings()
    path = path or settings.application_registry_file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    logger.info("Saved application registry (%s apps) to %s", len(registry), path)
    return path


def load_registry(path: Path | None = None, refresh: bool = False) -> dict[str, dict[str, Any]]:
    settings = get_settings()
    path = path or settings.application_registry_file

    if refresh or not path.exists():
        registry = build_registry(include_start_menu=True)
        save_registry(registry, path)
        return registry

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Corrupt registry, rebuilding: %s", exc)
        registry = build_registry(include_start_menu=True)
        save_registry(registry, path)
        return registry
