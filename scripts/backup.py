"""
Backup Athena configuration, memory, registry, and permissions.

Excludes credentials, tokens, and sensitive caches.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import PROJECT_ROOT, get_settings


INCLUDE = [
    "config/permissions.yaml",
    "config/settings.py",
    ".env.example",
    "data/application_registry/apps.json",
    "data/memory",
    "data/sessions",
    "rag/store/vector_store.json",
    "memory/summaries.log",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup Athena state")
    parser.add_argument(
        "--dest",
        default=str(PROJECT_ROOT / "data" / "backups"),
        help="Backup parent directory",
    )
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = Path(args.dest) / f"athena_backup_{stamp}"
    dest.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    for relative in INCLUDE:
        source = PROJECT_ROOT / relative
        if not source.exists():
            continue
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)
        copied.append(relative)

    settings = get_settings()
    meta = {
        "created_at": stamp,
        "version": settings.athena_version,
        "copied": copied,
        "excluded": [".env", "credentials", "tokens", "logs with secrets"],
    }
    (dest / "backup_manifest.json").write_text(
        json.dumps(meta, indent=2),
        encoding="utf-8",
    )
    print(f"Backup written to {dest}")
    print(f"Files/folders: {len(copied)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
