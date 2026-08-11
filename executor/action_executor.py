from tools.registry import get_registry


def execute_action(tool_name, arguments):
    registry = get_registry()

    if not registry.has(tool_name):
        return f"Tool '{tool_name}' not found."

    try:
        result = registry.execute(tool_name, arguments or {})
        return str(result)
    except Exception as e:
        return f"Execution Error: {e}"
