"""
Athena version / update check (Phase 53).

Reports the installed Athena version. Optional remote check is disabled by
default — never update blindly while a mission is running.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import get_settings  # noqa: E402


def current_version() -> str:
    return str(get_settings().athena_version)


def check_update(remote_url: str | None = None) -> dict:
    """
    Local version report. If remote_url is provided, fetch a JSON document:
      {"version": "1.2.3", "notes": "..."}
    and compare. Does not download or install anything.
    """
    local = current_version()
    report = {
        "local_version": local,
        "update_available": False,
        "remote_version": None,
        "notes": None,
        "action": "none",
    }
    if not remote_url:
        report["action"] = "report_only"
        return report

    try:
        import requests

        response = requests.get(remote_url, timeout=10)
        response.raise_for_status()
        data = response.json()
        remote = str(data.get("version") or "").strip()
        report["remote_version"] = remote or None
        report["notes"] = data.get("notes")
        if remote and remote != local:
            report["update_available"] = True
            report["action"] = "notify_only"
        else:
            report["action"] = "up_to_date"
    except Exception as exc:
        report["action"] = "check_failed"
        report["notes"] = str(exc)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Athena version / update check")
    parser.add_argument(
        "--remote",
        default="",
        help="Optional URL to a version JSON document (notify only, never auto-install)",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON")
    args = parser.parse_args(argv)

    report = check_update(args.remote or None)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Athena version: {report['local_version']}")
        if report.get("remote_version"):
            print(f"Remote version: {report['remote_version']}")
        if report.get("update_available"):
            print("Update available (notify only — do not update during a mission).")
            if report.get("notes"):
                print(f"Notes: {report['notes']}")
        elif report["action"] == "up_to_date":
            print("Up to date.")
        elif report["action"] == "check_failed":
            print(f"Remote check failed: {report.get('notes')}")
        else:
            print("Local report only (no remote URL configured).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
