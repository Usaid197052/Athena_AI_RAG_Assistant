"""
Tests for executor/plan_executor.py

Run: python -m Tests.plan_executor_test
"""

from executor.plan_executor import resolve_placeholders, execute_plan


def test_resolve_placeholders_string():

    results = ["hello", "world"]

    assert resolve_placeholders("{{step_1}}", results) == "hello"

    print("PASS: resolve_placeholders string")


def test_resolve_placeholders_nested():

    results = ["notes.txt"]

    arguments = {"file_path": "{{step_1}}"}

    resolved = resolve_placeholders(arguments, results)

    assert resolved == {"file_path": "notes.txt"}

    print("PASS: resolve_placeholders nested dict")


def test_execute_plan_runs_safe_steps(tmp_file="planner_demo.txt"):

    plan = {
        "steps": [
            {
                "tool": "create_file",
                "arguments": {"file_path": tmp_file},
                "description": "Create demo file"
            }
        ]
    }

    outcome = execute_plan(plan)

    assert outcome["completed"] is True

    print(f"PASS: execute_plan safe steps -> {outcome['summary']}")

    # Cleanup
    from tools.file_tools import delete_file
    delete_file(tmp_file)


def test_execute_plan_cancels_dangerous():

    plan = {
        "steps": [
            {
                "tool": "delete_file",
                "arguments": {"file_path": "does_not_matter.txt"},
                "description": "Delete a file"
            }
        ]
    }

    outcome = execute_plan(
        plan,
        confirm_callback=lambda step: False
    )

    assert outcome["completed"] is False

    print("PASS: execute_plan cancels dangerous step")


if __name__ == "__main__":

    test_resolve_placeholders_string()
    test_resolve_placeholders_nested()
    test_execute_plan_runs_safe_steps()
    test_execute_plan_cancels_dangerous()

    print("\nAll plan executor tests done.")
