"""Build prompt-ready context strings from RAG hits + session state."""

from __future__ import annotations

from typing import Any

from rag.client import RetrievalHit
from security.sanitizer import sanitize_external_content


def build_rag_context(hits: list[RetrievalHit], max_chars: int = 2500) -> str:
    if not hits:
        return ""

    parts: list[str] = []
    used = 0
    for hit in hits:
        safe_text = sanitize_external_content(
            hit.text.strip(),
            source="document",
            max_chars=max(400, max_chars - used),
        )
        block = f"[{hit.source} | score={hit.score:.2f}]\n{safe_text}"
        if used + len(block) > max_chars:
            break
        parts.append(block)
        used += len(block)

    return "\n\n".join(parts)


def build_planning_context(
    user_request: str,
    rag_context: str = "",
    session: dict[str, Any] | None = None,
) -> str:
    sections: list[str] = []

    if session:
        session_lines = [
            f"{key}: {value}"
            for key, value in session.items()
            if value not in (None, "", [], {})
        ]
        if session_lines:
            sections.append("Session state:\n" + "\n".join(session_lines))

    if rag_context:
        sections.append(
            "Retrieved memory (use for project paths, preferences, prior facts):\n"
            + rag_context
        )

    sections.append(f"User request:\n{user_request}")
    return "\n\n".join(sections)


def should_use_rag(user_text: str) -> bool:
    """Heuristic: retrieve memory when the request likely needs personal/project context."""
    text = user_text.lower()
    triggers = (
        "project",
        "my ",
        "etl",
        "clickhouse",
        "airflow",
        "pipeline",
        "document",
        "remember",
        "yesterday",
        "workflow",
        "where is",
        "open my",
        "continue",
        "preference",
        "notes",
    )
    return any(token in text for token in triggers)
