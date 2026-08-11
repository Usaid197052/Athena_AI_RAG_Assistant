"""
High-level memory manager for Athena.

Combines short-term conversation memory with RAG retrieval.
Does not dump secrets into prompts.
"""

from __future__ import annotations

from typing import Any

from memory import short_term
from rag.client import RagClient
from rag.context_builder import build_rag_context, should_use_rag
from rag.retriever import Retriever
from logs.logger import get_logger

logger = get_logger("athena.rag.memory")


class MemoryManager:
    def __init__(self) -> None:
        self.client = RagClient()
        self.retriever = Retriever(self.client)

    def conversation_context(self) -> str:
        return short_term.get_context()

    def remember_exchange(self, user_text: str, athena_text: str) -> None:
        short_term.add_exchange(user_text, athena_text)

    def retrieve_for_request(
        self,
        user_text: str,
        force: bool = False,
    ) -> tuple[str, list[dict[str, Any]]]:
        if not force and not should_use_rag(user_text):
            return "", []

        hits = self.retriever.retrieve(user_text)
        context = build_rag_context(hits)
        serialised = [
            {"score": h.score, "source": h.source, "text": h.text}
            for h in hits
        ]
        if context:
            logger.info("Attached RAG context (%s chars)", len(context))
        return context, serialised

    def status(self) -> dict[str, Any]:
        return self.client.status()
