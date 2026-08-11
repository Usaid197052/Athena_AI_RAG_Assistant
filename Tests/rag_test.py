"""
Tests for the RAG package.

Run: python -m Tests.rag_test
"""

from pathlib import Path

from rag.ingest import chunk_text, extract_text
from rag import vector_store


def test_chunk_text():

    text = "word " * 500

    chunks = chunk_text(text, chunk_size=200, overlap=50)

    assert len(chunks) > 1

    print(f"PASS: chunk_text produced {len(chunks)} chunks")


def test_extract_text_txt(tmp_file="rag_demo.txt"):

    Path(tmp_file).write_text(
        "Athena is an offline assistant.",
        encoding="utf-8"
    )

    text = extract_text(tmp_file)

    assert "offline assistant" in text

    Path(tmp_file).unlink()

    print("PASS: extract_text reads txt")


def test_vector_store_cosine():

    # Two near-identical vectors should rank above an orthogonal one.
    vector_store.add_chunks(
        "unit_test_source",
        [
            ("apple", [1.0, 0.0, 0.0]),
            ("orange", [0.9, 0.1, 0.0]),
            ("carburetor", [0.0, 1.0, 0.0])
        ]
    )

    results = vector_store.search([1.0, 0.0, 0.0], top_k=2)

    top_texts = [text for _, _, text in results]

    assert "apple" in top_texts

    print(f"PASS: vector_store search -> {top_texts}")


if __name__ == "__main__":

    test_chunk_text()
    test_extract_text_txt()
    test_vector_store_cosine()

    print("\nAll RAG tests done.")
