"""
Safe git inspection and local mutation tools.

Never pushes to remotes. Destructive git operations are blocked.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from security.path_guard import PathSecurityError, assert_safe_path


_BLOCKED_GIT_FLAGS = {
    "--force",
    "-f",
    "--hard",
    "--mirror",
    "--delete",
    "-D",
}


def _git_bin() -> str | None:
    return shutil.which("git")


def _resolve_repo(path: str | None = None) -> Path:
    raw = path or "."
    try:
        return assert_safe_path(raw, operation="read", must_exist=True)
    except PathSecurityError as exc:
        raise PathSecurityError(str(exc)) from exc


def _run_git(args: list[str], cwd: Path, timeout: float = 30.0) -> tuple[bool, str]:
    binary = _git_bin()
    if not binary:
        return False, "git not found on PATH."

    lowered = {a.lower() for a in args}
    if lowered & {f.lower() for f in _BLOCKED_GIT_FLAGS}:
        return False, f"Blocked unsafe git flags in: {' '.join(args)}"

    try:
        completed = subprocess.run(
            [binary, *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:
        return False, f"git failed: {exc}"

    out = (completed.stdout or "").strip()
    err = (completed.stderr or "").strip()
    if completed.returncode != 0:
        return False, err or out or f"git exited {completed.returncode}"
    return True, out or "(no output)"


def git_status(path: str | None = None) -> str:
    try:
        repo = _resolve_repo(path)
    except PathSecurityError as exc:
        return f"Error: {exc}"
    ok, output = _run_git(["status", "--short", "--branch"], repo)
    if not ok:
        return f"Error: {output}"
    return output


def git_diff(path: str | None = None, staged: bool = False) -> str:
    try:
        repo = _resolve_repo(path)
    except PathSecurityError as exc:
        return f"Error: {exc}"
    args = ["diff", "--stat"]
    if staged:
        args.insert(1, "--cached")
    ok, output = _run_git(args, repo)
    if not ok:
        return f"Error: {output}"
    return output


def git_log(path: str | None = None, limit: int = 10) -> str:
    try:
        repo = _resolve_repo(path)
    except PathSecurityError as exc:
        return f"Error: {exc}"
    n = max(1, min(int(limit or 10), 50))
    ok, output = _run_git(
        ["log", f"-{n}", "--oneline", "--decorate"],
        repo,
    )
    if not ok:
        return f"Error: {output}"
    return output


def create_branch(branch_name: str, path: str | None = None) -> str:
    name = (branch_name or "").strip()
    if not name or any(ch in name for ch in " \t\n\"'"):
        return "Error: invalid branch name."
    if name.startswith("-"):
        return "Error: branch name must not start with '-'."
    try:
        repo = _resolve_repo(path)
    except PathSecurityError as exc:
        return f"Error: {exc}"
    ok, output = _run_git(["checkout", "-b", name], repo)
    if not ok:
        return f"Error: {output}"
    return f"Created and checked out branch '{name}'."


def git_commit(message: str, path: str | None = None, add_all: bool = False) -> str:
    msg = (message or "").strip()
    if not msg:
        return "Error: commit message is required."
    try:
        repo = _resolve_repo(path)
    except PathSecurityError as exc:
        return f"Error: {exc}"

    if add_all:
        ok, output = _run_git(["add", "-A"], repo)
        if not ok:
            return f"Error staging: {output}"

    ok, output = _run_git(["commit", "-m", msg], repo)
    if not ok:
        return f"Error: {output}"
    return f"Committed: {output}"
