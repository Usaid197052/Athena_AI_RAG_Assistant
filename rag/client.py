"""
Athena RAG client — thin facade over the existing local vector store.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from logs.logger import get_logger

logger = get_logger("athena.rag")


@dataclass
class RetrievalHit:
    score: float
    source: str
    text: str


class RagClient:
    """Connectivity + status for the local RAG subsystem."""

    def available(self) -> bool:
        try:
            from rag import vector_store

            _ = vector_store.count_chunks()
            return True
        except Exception as exc:
            logger.warning("RAG unavailable: %s", exc)
            return False

    def status(self) -> dict[str, Any]:
        try:
            from rag import vector_store

            return {
                "ok": True,
                "chunks": vector_store.count_chunks(),
                "sources": vector_store.list_sources(),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def embed(self, text: str) -> list[float]:
        from rag.embeddings import embed_text

        return embed_text(text)
