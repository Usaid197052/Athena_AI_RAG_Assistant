"""
Project scaffolding and code write helpers.
"""

from __future__ import annotations

from pathlib import Path

from security.path_guard import PathSecurityError, assert_safe_path, validate_destination


_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "dist",
    "build",
    ".mypy_cache",
}


def create_project(name: str, parent_dir: str, kind: str = "python") -> str:
    """
    Create a minimal project scaffold under parent_dir/name.
    """
    project_name = (name or "").strip()
    if not project_name or any(ch in project_name for ch in r'\/:*?"<>|'):
        return "Error: invalid project name."

    try:
        parent = assert_safe_path(parent_dir, operation="create", must_exist=True)
        root = validate_destination(parent / project_name)
    except PathSecurityError as exc:
        return f"Error: {exc}"

    if root.exists():
        return f"Error: project already exists: {root}"

    kind_norm = (kind or "python").strip().lower()
    try:
        root.mkdir(parents=True, exist_ok=False)
        if kind_norm == "python":
            (root / "README.md").write_text(
                f"# {project_name}\n\nCreated by Athena.\n",
                encoding="utf-8",
            )
            (root / "requirements.txt").write_text("", encoding="utf-8")
            pkg = root / project_name.replace("-", "_").replace(" ", "_").lower()
            pkg.mkdir(exist_ok=True)
            (pkg / "__init__.py").write_text('"""Package."""\n', encoding="utf-8")
            (pkg / "main.py").write_text(
                'def main() -> None:\n    print("hello")\n\n\nif __name__ == "__main__":\n    main()\n',
                encoding="utf-8",
            )
            (root / "tests").mkdir(exist_ok=True)
            (root / "tests" / "__init__.py").write_text("", encoding="utf-8")
        else:
            (root / "README.md").write_text(
                f"# {project_name}\n\nCreated by Athena ({kind_norm}).\n",
                encoding="utf-8",
            )
    except Exception as exc:
        return f"Error creating project: {exc}"

    return f"Project created: {root}"


def read_project(path: str, max_entries: int = 80) -> str:
    """Summarize a project directory: key files and shallow tree."""
    try:
        root = assert_safe_path(path, operation="read", must_exist=True)
    except PathSecurityError as exc:
        return f"Error: {exc}"
    if not root.is_dir():
        return f"Error: Not a directory: {root}"

    limit = max(10, min(int(max_entries or 80), 200))
    lines: list[str] = [f"Project: {root}"]

    markers = []
    for name in (
        "pyproject.toml",
        "requirements.txt",
        "setup.py",
        "package.json",
        "Cargo.toml",
        "go.mod",
        "README.md",
        "Dockerfile",
        "docker-compose.yml",
    ):
        if (root / name).exists():
            markers.append(name)
    if markers:
        lines.append("Markers: " + ", ".join(markers))

    lines.append("Tree:")
    count = 0
    for item in sorted(root.rglob("*")):
        if any(part in _SKIP_DIRS for part in item.parts):
            continue
        try:
            rel = item.relative_to(root)
        except ValueError:
            continue
        # Cap depth for readability
        if len(rel.parts) > 3:
            continue
        prefix = "  " * (len(rel.parts) - 1)
        suffix = "/" if item.is_dir() else ""
        lines.append(f"{prefix}{rel.name}{suffix}")
        count += 1
        if count >= limit:
            lines.append(f"... truncated after {limit} entries")
            break

    if count == 0:
        lines.append("(empty)")
    return "\n".join(lines)


def write_code(file_path: str, content: str, overwrite: bool = True) -> str:
    """
    Write source code to a file with path safety checks.
    Does not push or run tests — caller should verify separately.
    """
    if content is None:
        return "Error: content is required."
    try:
        path = validate_destination(file_path)
        if path.exists() and not overwrite:
            return f"Error: file exists and overwrite=False: {path}"
        # Also block protected locations for writes
        assert_safe_path(path, operation="write")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(content), encoding="utf-8")
    except PathSecurityError as exc:
        return f"Error: {exc}"
    except Exception as exc:
        return f"Error writing code: {exc}"

    if not path.exists():
        return f"Error: write verification failed for {path}"
    return f"Wrote {len(str(content))} characters to {path}"
