from datetime import datetime
from pathlib import Path

from brain.ollama_client import ask_athena
from memory import short_term
from logs.logger import write_log


SUMMARY_FILE = Path("memory/summaries.log")

# Summarize once short-term memory is at least this full.
SUMMARIZE_AFTER_EXCHANGES = 8


def summarize_conversation():
    """
    Compresses current short-term memory into a rolling summary.
    The summary replaces old exchanges as long-term context.
    """

    exchanges = short_term.get_exchanges()

    if not exchanges:
        return short_term.get_summary()

    transcript = "\n".join(
        f"User: {e['user']}\nAthena: "
        f"{e.get('athena', e.get('jarvis', ''))}"
        for e in exchanges
    )

    previous_summary = short_term.get_summary()

    prompt = f"""
You summarize conversations for an AI assistant's memory.

Previous summary (may be empty):
{previous_summary}

New conversation:
{transcript}

Write an updated summary in under 120 words. Keep only facts,
preferences, names, and unfinished tasks worth remembering.
Return plain text only.
"""

    summary = ask_athena(prompt).strip()

    short_term.set_summary(summary)

    _persist_summary(summary)

    return summary


def maybe_summarize():
    """
    Summarizes automatically when short-term memory is filling up.
    """

    if len(short_term.get_exchanges()) >= SUMMARIZE_AFTER_EXCHANGES:
        return summarize_conversation()

    return None


def _persist_summary(summary):

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    SUMMARY_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(SUMMARY_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}]\n{summary}\n\n")

    write_log("MEMORY: summary persisted to memory/summaries.log")
