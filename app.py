"""
Athena application entrypoint.

Usage:
  python app.py              -> system tray
  python app.py --voice      -> voice agent loop
  python app.py --dashboard  -> Owl's Vigil realtime HUD
  Athena.exe                 -> system tray (frozen)
  Athena.exe --voice         -> voice agent loop (frozen)
  Athena.exe --dashboard     -> Owl's Vigil realtime HUD (frozen)
"""

from __future__ import annotations

import sys


def main() -> None:
    if "--voice" in sys.argv:
        from main import main as voice_main

        voice_main()
        return

    if "--dashboard" in sys.argv:
        from ui.dashboard import main as dashboard_main

        dashboard_main()
        return

    if "--health" in sys.argv:
        from pathlib import Path

        from config.paths import is_frozen, project_root
        from scripts.health_check import main as health_main

        code = health_main()
        if is_frozen():
            # Windowed builds have no console — persist the last health snapshot.
            report = project_root() / "data" / "cache" / "health_report.txt"
            report.parent.mkdir(parents=True, exist_ok=True)
            # Re-run capture by importing status helpers
            from monitoring.status_store import read_status

            status = read_status()
            report.write_text(
                "Athena health finished with code "
                f"{code}\nStatus file updated_at={status.get('updated_at')}\n"
                "See logs/athena.log and data/cache/athena_status.json for details.\n",
                encoding="utf-8",
            )
        raise SystemExit(code)

    from ui.tray import main as tray_main

    tray_main()


if __name__ == "__main__":
    main()
