from collections import deque

from logs.logger import write_log


MAX_EXCHANGES = 10


_exchanges = deque(maxlen=MAX_EXCHANGES)

_summary = ""


def add_exchange(user_text, athena_text):
    """
    Stores one user/assistant exchange in short-term memory.
    """

    _exchanges.append(
        {
            "user": user_text,
            "athena": athena_text
        }
    )

    write_log(
        f"MEMORY: stored exchange "
        f"({len(_exchanges)}/{MAX_EXCHANGES})"
    )


def get_exchanges():

    return list(_exchanges)


def get_summary():

    return _summary


def set_summary(summary):

    global _summary

    _summary = summary

    write_log("MEMORY: conversation summary updated")


def get_context():
    """
    Returns the conversation context as plain text for prompts:
    the long-term summary (if any) followed by recent exchanges.
    """

    parts = []

    if _summary:
        parts.append(
            f"Summary of earlier conversation:\n{_summary}"
        )

    for exchange in _exchanges:
        assistant = exchange.get(
            "athena",
            exchange.get("jarvis", "")
        )
        parts.append(f"User: {exchange['user']}")
        parts.append(f"Athena: {assistant}")

    return "\n".join(parts)


def clear():

    global _summary

    _exchanges.clear()
    _summary = ""

    write_log("MEMORY: cleared")
