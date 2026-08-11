# Athena RAG

Athena uses a local vector store plus Ollama embeddings (`nomic-embed-text`).

## Modules

- `rag/client.py` — availability / status
- `rag/retriever.py` — similarity search
- `rag/context_builder.py` — prompt packaging + when to retrieve
- `rag/memory_manager.py` — short-term + RAG facade
- Existing: `ingest.py`, `search.py`, `embeddings.py`, `vector_store.py`

## Seed memory

```powershell
python scripts\ingest_memory.py
```

Loads `data/memory/projects.md` (project paths, preferred IDE, preferences).

## Behaviour

The orchestrator retrieves RAG context when the request looks personal/project-related
(e.g. "open my ETL project"), then injects it into the planner.
