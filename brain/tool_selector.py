from brain.ollama_client import ask_athena
from tools.tool_registry import TOOLS


def select_tool(user_request):

    available_tools = "\n".join(TOOLS.keys())

    prompt = f"""
You are a desktop AI assistant.

Available tools:

{available_tools}

Rules:
- Return ONLY the tool name.
- No explanations.
- No markdown.
- No punctuation.
- Return exactly one tool name.

User Request:
{user_request}
"""

    response = ask_athena(prompt)

    return response.strip()