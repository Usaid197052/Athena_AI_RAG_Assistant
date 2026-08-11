"""
Python execution and test helpers.

Deterministic wrappers — Athena does not invent shell one-liners for tests.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from security.path_guard import PathSecurityError, assert_safe_path


def run_python(script_path: str, args: str | None = None) -> str:
    """Run a Python script and return stdout/stderr with exit code."""
    try:
        path = assert_safe_path(script_path, operation="read", must_exist=True)
    except PathSecurityError as exc:
        return f"Error: {exc}"
    if not path.is_file():
        return f"Error: Not a file: {path}"

    cmd = [sys.executable, str(path)]
    if args:
        cmd.extend(str(args).split())

    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except Exception as exc:
        return f"Error running Python: {exc}"

    parts = [
        f"exit_code={completed.returncode}",
        (completed.stdout or "").strip(),
        (completed.stderr or "").strip(),
    ]
    body = "\n".join(p for p in parts if p)
    if completed.returncode != 0:
        return f"Error running Python script:\n{body}"
    return body or "(no output)"


def run_tests(path: str | None = None, pattern: str | None = None) -> str:
    """
    Run pytest when available, otherwise unittest discovery.
    """
    try:
        target = assert_safe_path(path or ".", operation="read", must_exist=True)
    except PathSecurityError as exc:
        return f"Error: {exc}"

    cmd = [sys.executable, "-m", "pytest", "-q", "--tb=short"]
    if pattern:
        cmd.extend(["-k", str(pattern)])
    if target.is_file():
        cmd.append(str(target))
    else:
        # Prefer Tests/ or tests/ if present under the folder
        for candidate in ("Tests", "tests", "test"):
            sub = target / candidate
            if sub.is_dir():
                cmd.append(str(sub))
                break
        else:
            cmd.append(str(target))

    try:
        completed = subprocess.run(
            cmd,
            cwd=str(target if target.is_dir() else target.parent),
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except FileNotFoundError:
        return "Error: pytest is not available."
    except Exception as exc:
        # Fall back to unittest if pytest module missing
        if "No module named pytest" in str(exc) or "pytest" in str(exc).lower():
            return _run_unittest(target)
        return f"Error running tests: {exc}"

    out = (completed.stdout or "").strip()
    err = (completed.stderr or "").strip()
    if "No module named pytest" in err:
        return _run_unittest(target)

    body = "\n".join(p for p in (out, err) if p) or "(no output)"
    if completed.returncode != 0:
        return f"Tests failed (exit {completed.returncode}):\n{body}"
    return f"Tests passed:\n{body}"


def _run_unittest(target: Path) -> str:
    start = str(target if target.is_dir() else target.parent)
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", start, "-q"],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except Exception as exc:
        return f"Error running unittest: {exc}"
    body = ((completed.stdout or "") + (completed.stderr or "")).strip() or "(no output)"
    if completed.returncode != 0:
        return f"Tests failed (exit {completed.returncode}):\n{body}"
    return f"Tests passed:\n{body}"


def _extract_tracebacks(raw: str) -> list[str]:
    """Pull complete traceback blocks including the final exception line."""
    lines = raw.splitlines()
    blocks: list[str] = []
    i = 0
    while i < len(lines):
        if lines[i].startswith("Traceback (most recent call last):"):
            start = i
            i += 1
            while i < len(lines):
                line = lines[i]
                # Frame lines are indented; the exception type is not.
                if line.startswith((" ", "\t")) or not line.strip():
                    i += 1
                    continue
                # Include the exception line, then stop this block.
                i += 1
                break
            blocks.append("\n".join(lines[start:i]).strip())
            continue
        i += 1
    return blocks


def inspect_traceback(text: str | None = None, file_path: str | None = None) -> str:
    """
    Extract and summarize a Python traceback from text or a log file.
    """
    raw = text or ""
    if file_path:
        try:
            path = assert_safe_path(file_path, operation="read", must_exist=True)
            raw = path.read_text(encoding="utf-8", errors="replace")
        except PathSecurityError as exc:
            return f"Error: {exc}"
        except Exception as exc:
            return f"Error reading file: {exc}"

    if not raw.strip():
        return "Error: no traceback text provided."

    matches = _extract_tracebacks(raw)
    if not matches:
        # Soft fallback: last non-empty lines that look like an error
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        if not lines:
            return "No traceback found."
        return "No full traceback found. Last lines:\n" + "\n".join(lines[-12:])

    block = matches[-1].strip()
    last_line = block.splitlines()[-1] if block.splitlines() else ""
    frames = [ln.strip() for ln in block.splitlines() if ln.strip().startswith("File ")]
    summary = [
        "Traceback summary:",
        f"Frames: {len(frames)}",
        f"Error: {last_line}",
    ]
    if frames:
        summary.append(f"Top frame: {frames[0]}")
        summary.append(f"Bottom frame: {frames[-1]}")
    summary.append("")
    summary.append(block)
    return "\n".join(summary)
