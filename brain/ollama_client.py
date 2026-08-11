from ollama import chat

from config import OLLAMA_MODEL


def ask_athena(prompt):
    """
    Sends a prompt to Ollama and returns the response.
    """

    response = chat(
        model=OLLAMA_MODEL,
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    return response["message"]["content"]


# Backward-compatible alias
ask_jarvis = ask_athena
