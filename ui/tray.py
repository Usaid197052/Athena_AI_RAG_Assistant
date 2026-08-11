"""
System tray controller for Athena.

Menu mirrors the product guide. Heavy AI work stays in the main process.
"""

from __future__ import annotations

import subprocess
import sys
import webbrowser

from PIL import Image, ImageDraw
import pystray

from config import ASSISTANT_NAME, LOG_FILE, PROJECT_ROOT
from config.paths import is_frozen
from monitoring.health_monitor import HealthMonitor
from monitoring.status_store import read_status, write_status
from ui.dashboard import open_dashboard


SUMMARY_FILE = PROJECT_ROOT / "memory" / "summaries.log"
PERMISSIONS_FILE = PROJECT_ROOT / "config" / "permissions.yaml"


class AthenaTray:
    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._paused = False
        self._health = HealthMonitor(interval_seconds=60)
        write_status(voice="tray", listening=False, paused=False)
        self._health.start()

        self._icon = pystray.Icon(
            ASSISTANT_NAME.lower(),
            self._create_image(),
            f"{ASSISTANT_NAME} Assistant",
            menu=self._build_menu(),
        )

    def _create_image(self):
        # Owl's Vigil glyph: gold vertical pupil on deep void.
        image = Image.new("RGBA", (64, 64), (10, 12, 16, 255))
        draw = ImageDraw.Draw(image)
        draw.ellipse((10, 10, 54, 54), outline=(216, 180, 92, 255), width=3)
        draw.ellipse((20, 20, 44, 44), fill=(22, 19, 12, 255))
        draw.rounded_rectangle((29, 18, 35, 46), radius=3, fill=(216, 180, 92, 255))
        return image

    def _status_label(self, _item=None) -> str:
        if self._paused:
            return "Status: Paused"
        if self._is_running():
            return "Status: Listening"
        status = read_status()
        return f"Status: {status.get('voice', 'Stopped').title()}"

    def _build_menu(self):
        return pystray.Menu(
            pystray.MenuItem(ASSISTANT_NAME, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(self._status_label, None, enabled=False),
            pystray.MenuItem(
                lambda item: (
                    f"Stop Listening"
                    if self._is_running()
                    else "Start Listening"
                ),
                self._toggle_listening,
            ),
            pystray.MenuItem(
                lambda item: "Resume" if self._paused else "Pause",
                self._toggle_pause,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open Dashboard", self._open_dashboard),
            pystray.MenuItem("Settings (.env)", self._open_settings),
            pystray.MenuItem("Recent Activity", self._open_activity),
            pystray.MenuItem("Permissions", self._open_permissions),
            pystray.MenuItem("Open Logs", self._open_logs),
            pystray.MenuItem("Restart Services", self._restart_services),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self._quit),
        )

    def _is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _toggle_listening(self, icon, item):
        if self._is_running():
            self._stop()
        else:
            self._paused = False
            self._start()
        icon.update_menu()

    def _toggle_pause(self, icon, item):
        if not self._is_running() and not self._paused:
            return
        if self._paused:
            self._paused = False
            self._start()
            write_status(paused=False, listening=True, voice="listening")
        else:
            self._paused = True
            self._stop()
            write_status(paused=True, listening=False, voice="paused")
        icon.update_menu()

    def _start(self):
        if self._is_running():
            return

        if is_frozen():
            command = [sys.executable, "--voice"]
        else:
            command = [sys.executable, str(PROJECT_ROOT / "main.py")]

        self._process = subprocess.Popen(
            command,
            cwd=str(PROJECT_ROOT),
        )
        write_status(listening=True, paused=False, voice="listening")

    def _stop(self):
        if self._is_running():
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None
        write_status(listening=False, voice="idle")

    def _open_dashboard(self, icon, item):
        open_dashboard()

    def _open_settings(self, icon, item):
        env_path = PROJECT_ROOT / ".env"
        target = env_path if env_path.exists() else PROJECT_ROOT / ".env.example"
        webbrowser.open(target.as_uri())

    def _open_activity(self, icon, item):
        # Same live HUD — activity feed is part of Owl's Vigil.
        open_dashboard()

    def _open_permissions(self, icon, item):
        if PERMISSIONS_FILE.exists():
            webbrowser.open(PERMISSIONS_FILE.as_uri())

    def _open_logs(self, icon, item):
        if LOG_FILE.exists():
            webbrowser.open(LOG_FILE.as_uri())
        if SUMMARY_FILE.exists():
            webbrowser.open(SUMMARY_FILE.as_uri())

    def _restart_services(self, icon, item):
        was_running = self._is_running()
        self._stop()
        self._health.check_once()
        if was_running and not self._paused:
            self._start()
        icon.update_menu()

    def _quit(self, icon, item):
        self._stop()
        self._health.stop()
        write_status(listening=False, voice="offline")
        icon.stop()

    def run(self):
        self._icon.run()


def main():
    AthenaTray().run()


if __name__ == "__main__":
    main()
