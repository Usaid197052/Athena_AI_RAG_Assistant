"""Scan installed Windows applications into the local registry."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.applications.discovery import build_registry, save_registry


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan Windows apps for Athena")
    parser.add_argument(
        "--skip-start-menu",
        action="store_true",
        help="Faster scan without resolving Start Menu shortcuts",
    )
    args = parser.parse_args()

    registry = build_registry(include_start_menu=not args.skip_start_menu)
    path = save_registry(registry)
    print(f"Indexed {len(registry)} applications -> {path}")
    for key in sorted(registry)[:20]:
        print(f"  - {registry[key]['display_name']}")
    if len(registry) > 20:
        print(f"  ... and {len(registry) - 20} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
