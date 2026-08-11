import json
from pathlib import Path

import numpy as np

from config.settings import PROJECT_ROOT


STORE_FILE = PROJECT_ROOT / "rag" / "store" / "vector_store.json"


def _load():

    if not STORE_FILE.exists():
        return {"chunks": []}

    with open(STORE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(store):

    STORE_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(STORE_FILE, "w", encoding="utf-8") as f:
        json.dump(store, f)


def add_chunks(source, chunks_with_embeddings):
    """
    Adds embedded chunks for a source document, replacing any
    previous entries from the same source.
    """

    store = _load()

    store["chunks"] = [
        chunk
        for chunk in store["chunks"]
        if chunk["source"] != source
    ]

    for text, embedding in chunks_with_embeddings:

        store["chunks"].append(
            {
                "source": source,
                "text": text,
                "embedding": embedding
            }
        )

    _save(store)

    return len(chunks_with_embeddings)


def search(query_embedding, top_k=3):
    """
    Returns the top_k most similar chunks by cosine similarity:
    [(score, source, text), ...]
    """

    store = _load()

    chunks = store["chunks"]

    if not chunks:
        return []

    query = np.array(query_embedding, dtype=np.float32)
    query_norm = np.linalg.norm(query)
    if query_norm == 0:
        return []

    expected_dim = int(query.shape[0])
    usable = [
        chunk
        for chunk in chunks
        if isinstance(chunk.get("embedding"), list)
        and len(chunk["embedding"]) == expected_dim
    ]

    if not usable:
        return []

    matrix = np.array(
        [chunk["embedding"] for chunk in usable],
        dtype=np.float32,
    )

    norms = np.linalg.norm(matrix, axis=1) * query_norm
    norms[norms == 0] = 1e-10

    scores = matrix @ query / norms
    top_indices = np.argsort(scores)[::-1][:top_k]

    return [
        (
            float(scores[i]),
            usable[i]["source"],
            usable[i]["text"],
        )
        for i in top_indices
    ]


def count_chunks():

    return len(_load()["chunks"])


def list_sources():

    return sorted(
        {chunk["source"] for chunk in _load()["chunks"]}
    )
