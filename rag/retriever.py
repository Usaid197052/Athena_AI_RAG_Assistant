"""Retrieve relevant chunks from Athena's local vector memory."""

from __future__ import annotations

from rag.client import RagClient, RetrievalHit
from logs.logger import get_logger

logger = get_logger("athena.rag.retriever")


class Retriever:
    def __init__(self, client: RagClient | None = None, top_k: int = 4) -> None:
        self.client = client or RagClient()
        self.top_k = top_k

    def retrieve(self, query: str, top_k: int | None = None) -> list[RetrievalHit]:
        if not query.strip():
            return []

        if not self.client.available():
            return []

        try:
            from rag import vector_store

            if vector_store.count_chunks() == 0:
                return []

            embedding = self.client.embed(query)
            matches = vector_store.search(embedding, top_k=top_k or self.top_k)
            hits = [
                RetrievalHit(score=score, source=source, text=text)
                for score, source, text in matches
            ]
            logger.info("RAG retrieved %s chunks for query", len(hits))
            return hits
        except Exception as exc:
            logger.warning("RAG retrieve failed: %s", exc)
            return []
