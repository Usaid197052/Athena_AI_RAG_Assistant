from pathlib import Path

from rag.ingest import extract_text, chunk_text
from rag.embeddings import embed_text
from rag import vector_store
from brain.ollama_client import ask_athena
from logs.logger import write_log


def ingest_document(file_path):
    """
    Tool: reads a PDF/DOCX/TXT/MD file, embeds it, and stores it
    in the local vector store.
    """

    try:

        text = extract_text(file_path)

        chunks = chunk_text(text)

        if not chunks:
            return f"No text found in {file_path}."

        embedded = [
            (chunk, embed_text(chunk))
            for chunk in chunks
        ]

        source = Path(file_path).name

        count = vector_store.add_chunks(source, embedded)

        write_log(
            f"RAG: ingested '{source}' ({count} chunks)"
        )

        return (
            f"Ingested {source} into memory "
            f"({count} chunks)."
        )

    except Exception as e:

        return f"Error ingesting document: {e}"


def query_documents(question, top_k=3):
    """
    Tool: answers a question using the ingested documents.
    """

    try:

        if vector_store.count_chunks() == 0:
            return (
                "No documents have been ingested yet. "
                "Ask me to ingest a document first."
            )

        query_embedding = embed_text(question)

        matches = vector_store.search(
            query_embedding,
            top_k=top_k
        )

        if not matches:
            return "No relevant information found."

        context = "\n\n".join(
            f"[{source}]\n{text}"
            for _, source, text in matches
        )

        write_log(
            f"RAG: query '{question}' matched "
            f"{len(matches)} chunks"
        )

        prompt = f"""
You are Athena, a voice assistant answering from documents.

Use ONLY the context below to answer. If the answer is not in
the context, say you could not find it in the documents.

Rules:
- Plain spoken English. No markdown. No emojis.
- Keep the answer short. It will be read aloud.

Context:
{context}

Question:
{question}
"""

        return ask_athena(prompt).strip()

    except Exception as e:

        return f"Error searching documents: {e}"


def list_ingested_documents():
    """
    Tool: lists documents currently in the vector store.
    """

    sources = vector_store.list_sources()

    if not sources:
        return "No documents have been ingested yet."

    return "Ingested documents: " + ", ".join(sources)
