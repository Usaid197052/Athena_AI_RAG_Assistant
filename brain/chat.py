from brain.ollama_client import ask_athena
from brain.prompt_manager import chat_system_prompt
from memory import short_term, summarizer


def chat_with_athena(user_request, extra_context: str = ""):

    context = short_term.get_context()
    memory_block = ""
    if extra_context.strip():
        memory_block = (
            "\nRetrieved memory (use only if relevant):\n"
            f"{extra_context}\n"
        )

    prompt = f"""
{chat_system_prompt(context)}
{memory_block}
User:
{user_request}
"""

    response = ask_athena(prompt)

    short_term.add_exchange(user_request, response)

    summarizer.maybe_summarize()

    return response


# Backward-compatible alias
chat_with_jarvis = chat_with_athena
