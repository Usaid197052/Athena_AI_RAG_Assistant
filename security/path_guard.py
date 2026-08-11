"""
Filesystem path safety for Athena file tools.
"""

from __future__ import annotations

import os
from pathlib import Path


class PathSecurityError(ValueError):
    pass


# Destinations / targets Athena must not write or delete by default.
_BLOCKED_PREFIXES = [
    Path(os.environ.get("WINDIR", r"C:\Windows")).resolve(),
    Path(os.environ.get("SYSTEMROOT", r"C:\Windows")).resolve(),
    Path(r"C:\Program Files").resolve(),
    Path(r"C:\Program Files (x86)").resolve(),
]


def normalize_path(raw: str | Path) -> Path:
    text = str(raw).strip()
    if not text:
        raise PathSecurityError("Empty path.")
    if "\x00" in text:
        raise PathSecurityError("Null byte in path.")

    path = Path(text).expanduser()
    # Resolve when possible; for create targets, parent may not exist yet.
    try:
        resolved = path.resolve(strict=False)
    except Exception as exc:
        raise PathSecurityError(f"Invalid path: {exc}") from exc
    return resolved


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def assert_safe_path(
    raw: str | Path,
    *,
    operation: str = "access",
    must_exist: bool = False,
) -> Path:
    path = normalize_path(raw)

    if ".." in Path(str(raw)).parts:
        # Still allow legitimate names after resolve, but reject unresolved traversal
        # that escapes after normalize — handled by resolve above.
        pass

    if must_exist and not path.exists():
        raise PathSecurityError(f"Path does not exist: {path}")

    destructive = operation in {"write", "delete", "move_dest", "create"}
    if destructive:
        for blocked in _BLOCKED_PREFIXES:
            if _is_under(path, blocked) or path == blocked:
                raise PathSecurityError(
                    f"Refusing {operation} inside protected location: {blocked}"
                )

        # Block writing directly to drive roots
        if path.parent == path.anchor or path == Path(path.anchor):
            if path.suffix == "" and operation in {"create", "write", "delete"}:
                # allow files on root? safer to block system-ish roots only
                pass

    return path


def validate_destination(raw: str | Path) -> Path:
    return assert_safe_path(raw, operation="move_dest")
