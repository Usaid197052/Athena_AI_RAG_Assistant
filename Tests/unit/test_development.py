"""Unit tests for Stage G development tools."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tools.development.git_tools import git_status
from tools.development.project_tools import create_project, read_project, write_code
from tools.development.python_tools import inspect_traceback, run_python, run_tests
from tools.registry import get_registry, reset_registry


def test_registry_has_development_tools():
    reset_registry()
    registry = get_registry()
    for name in (
        "git_status",
        "git_diff",
        "git_log",
        "create_branch",
        "git_commit",
        "run_python",
        "run_tests",
        "inspect_traceback",
        "create_project",
        "read_project",
        "write_code",
    ):
        assert registry.has(name), name


def test_create_and_read_project(tmp_path: Path):
    result = create_project("demo_app", str(tmp_path), kind="python")
    assert result.startswith("Project created:")
    root = tmp_path / "demo_app"
    assert (root / "README.md").exists()
    assert (root / "requirements.txt").exists()

    summary = read_project(str(root))
    assert "Project:" in summary
    assert "README.md" in summary or "Markers:" in summary


def test_write_code_and_run_python(tmp_path: Path):
    script = tmp_path / "hello.py"
    written = write_code(str(script), 'print("athena-ok")\n')
    assert written.startswith("Wrote")
    output = run_python(str(script))
    assert "athena-ok" in output
    assert "exit_code=0" in output


def test_inspect_traceback_summary():
    sample = """\
Traceback (most recent call last):
  File "x.py", line 1, in <module>
    raise ValueError("boom")
ValueError: boom
"""
    summary = inspect_traceback(text=sample)
    assert "Traceback summary:" in summary
    assert "ValueError: boom" in summary


def test_git_status_on_temp_repo(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "athena@test.local"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Athena Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "a.txt").write_text("x\n", encoding="utf-8")
    status = git_status(str(tmp_path))
    assert "Error:" not in status
    assert "a.txt" in status or "No commits" in status or status


def test_run_tests_smoke(tmp_path: Path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_smoke.py").write_text(
        "def test_ok():\n    assert True\n",
        encoding="utf-8",
    )
    result = run_tests(str(tmp_path))
    assert "Tests passed" in result or "passed" in result.lower()
