"""Context engine — assembles session + RAG + conversation for the core."""

from __future__ import annotations

from typing import Any

from memory.session import get_session
from rag.context_builder import build_planning_context
from rag.memory_manager import MemoryManager


class ContextEngine:
    def __init__(self, memory: MemoryManager | None = None) -> None:
        self.memory = memory or MemoryManager()

    def build(self, user_text: str, force_rag: bool = False) -> dict[str, Any]:
        rag_context, hits = self.memory.retrieve_for_request(
            user_text,
            force=force_rag,
        )
        session = get_session().to_dict()
        conversation = self.memory.conversation_context()

        planning_blob = build_planning_context(
            user_request=user_text,
            rag_context=rag_context,
            session=session,
        )

        return {
            "user_text": user_text,
            "session": session,
            "conversation": conversation,
            "rag_context": rag_context,
            "rag_hits": hits,
            "planning_context": planning_blob,
        }
