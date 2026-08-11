from brain.tool_call_validator import validate_plan_steps, validate_tool_call
from rag.context_builder import should_use_rag
from tools.registry import reset_registry


def test_should_use_rag_for_projects():
    assert should_use_rag("Open my ClickHouse project") is True
    assert should_use_rag("Open Notepad") is False


def test_validate_open_application_requires_name():
    reset_registry()
    assert validate_tool_call({"tool": "open_application", "arguments": {}})
    assert (
        validate_tool_call(
            {
                "tool": "open_application",
                "arguments": {"application_name": "Notepad"},
            }
        )
        is None
    )


def test_validate_unknown_tool():
    reset_registry()
    assert validate_tool_call({"tool": "hack_the_planet", "arguments": {}})


def test_validate_plan_steps():
    reset_registry()
    error = validate_plan_steps(
        [
            {
                "tool": "open_application",
                "arguments": {"application_name": "Notepad"},
            }
        ]
    )
    assert error is None
