import ollama

from config import EMBEDDING_MODEL


def embed_text(text):
    """
    Returns the embedding vector for a piece of text using a
    local Ollama embedding model.
    """

    response = ollama.embeddings(
        model=EMBEDDING_MODEL,
        prompt=text
    )

    return response["embedding"]
