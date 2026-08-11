"""
Tests for brain/planner.py

Run: python -m Tests.planner_test
"""

from brain.planner import extract_json, validate_plan, create_plan


def test_extract_json_plain():

    text = '{"steps": []}'

    assert extract_json(text) == {"steps": []}

    print("PASS: extract_json plain")


def test_extract_json_with_think_and_fences():

    text = (
        "<think>the user wants to open notepad</think>\n"
        "```json\n"
        '{"steps": [{"tool": "open_notepad", '
        '"arguments": {}, "description": "Open Notepad"}]}\n'
        "```"
    )

    plan = extract_json(text)

    assert plan["steps"][0]["tool"] == "open_notepad"

    print("PASS: extract_json with think + fences")


def test_validate_plan_rejects_unknown_tool():

    plan = {
        "steps": [
            {"tool": "not_a_real_tool", "arguments": {}}
        ]
    }

    error = validate_plan(plan)

    assert error is not None

    print("PASS: validate_plan rejects unknown tool")


def test_validate_plan_accepts_valid():

    plan = {
        "steps": [
            {"tool": "open_notepad", "arguments": {}}
        ]
    }

    assert validate_plan(plan) is None

    print("PASS: validate_plan accepts valid plan")


def test_create_plan_live():
    """
    Live test (requires Ollama). Skips on failure to connect.
    """

    try:
        plan = create_plan("open notepad")

    except Exception as e:
        print(f"SKIP: create_plan live ({e})")
        return

    assert "steps" in plan

    print(f"PASS: create_plan live -> {plan}")


if __name__ == "__main__":

    test_extract_json_plain()
    test_extract_json_with_think_and_fences()
    test_validate_plan_rejects_unknown_tool()
    test_validate_plan_accepts_valid()
    test_create_plan_live()

    print("\nAll planner tests done.")
