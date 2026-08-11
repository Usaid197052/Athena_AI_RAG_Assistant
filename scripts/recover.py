"""
Recover Athena state from a backup directory created by scripts/backup.py.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import PROJECT_ROOT


def main() -> int:
    parser = argparse.ArgumentParser(description="Recover Athena from backup")
    parser.add_argument("backup_dir", help="Path to athena_backup_* directory")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be restored without writing",
    )
    args = parser.parse_args()

    backup = Path(args.backup_dir)
    manifest_path = backup / "backup_manifest.json"
    if not manifest_path.exists():
        print(f"Missing manifest: {manifest_path}")
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    copied = manifest.get("copied") or []

    for relative in copied:
        source = backup / relative
        target = PROJECT_ROOT / relative
        if not source.exists():
            print(f"Skip missing: {relative}")
            continue
        print(f"{'Would restore' if args.dry_run else 'Restoring'}: {relative}")
        if args.dry_run:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)

    print("Recovery complete." if not args.dry_run else "Dry run complete.")
    print("Note: .env / secrets are never restored automatically.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
