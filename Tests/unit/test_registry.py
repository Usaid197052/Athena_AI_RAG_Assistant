from tools.registry import get_registry, reset_registry


def test_registry_contains_open_application():
    reset_registry()
    registry = get_registry()
    assert registry.has("open_application")
    assert registry.has("close_application")
    tool = registry.get("open_application")
    assert "application_name" in tool.input_schema.get("properties", {})


def test_legacy_aliases_exist():
    registry = get_registry()
    for name in (
        "open_notepad",
        "open_visual_studio",
        "open_calculator",
        "open_cmd",
        "open_powershell",
    ):
        assert registry.has(name)
