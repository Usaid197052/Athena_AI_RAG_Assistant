"""Ingest Athena personal/project memory into the local RAG store."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag.search import ingest_document


def main() -> int:
    path = ROOT / "data" / "memory" / "projects.md"
    if not path.exists():
        print(f"Missing {path}")
        return 1
    print(ingest_document(str(path)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
