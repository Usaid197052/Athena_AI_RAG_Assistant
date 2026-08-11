"""
Athena Owl's Vigil — realtime desktop HUD.

Concept reference: resources/athena-concept-1-owls-vigil.html
Always-on-top corner widget with live phase, orb animation, vitals, and activity.
"""

from __future__ import annotations

import math
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from typing import Any

from config import ASSISTANT_NAME
from config.paths import is_frozen
from config.settings import PROJECT_ROOT, get_settings
from monitoring.status_store import read_status, recent_activity

# Palette — Concept 01 Owl's Vigil
VOID = "#0A0C10"
PANEL = "#12151C"
PANEL_EDGE = "#1E222C"
GOLD = "#D8B45C"
GOLD_DIM = "#8A733A"
TEAL = "#4C7B72"
IVORY = "#E9E2D0"
IVORY_DIM = "#8B8778"
TRACK = "#1D212A"
ORB_INNER = "#1B1F28"
IRIS = "#3A3220"
IRIS_DARK = "#16130C"

WINDOW_W = 360
WINDOW_H = 620
POLL_MS = 250
ANIM_MS = 40
VITALS_MS = 2000
CLOCK_MS = 1000

_DASHBOARD_PROC: subprocess.Popen | None = None


def _mode_from_status(status: dict) -> str:
    voice = str(status.get("voice") or "").lower()
    phase = str(status.get("ux_phase") or "").lower()
    if status.get("paused"):
        return "idle"
    if "speak" in voice or phase.startswith("speaking"):
        return "speaking"
    if voice in {"thinking", "working"} or any(
        phase.startswith(p) for p in ("thinking", "working", "planning", "searching")
    ):
        return "thinking"
    if status.get("listening") or voice in {"listening", "ready", "tray"}:
        return "listening"
    if "waiting for confirmation" in phase:
        return "thinking"
    return "idle"


def _status_message(mode: str, status: dict) -> str:
    detail = str(status.get("ux_detail") or "").strip()
    phase = str(status.get("ux_phase") or "").strip()
    task = str(status.get("current_task") or "").strip()
    if mode == "idle":
        return f'Say "{ASSISTANT_NAME}" to begin'
    if mode == "listening":
        return phase if phase and phase.lower() != "listening..." else "Listening…"
    if mode == "thinking":
        return phase or detail or "Working on it…"
    if mode == "speaking":
        return detail or phase or task or "Speaking…"
    return phase or "Ready"


def _relative_time(iso: str) -> str:
    if not iso:
        return ""
    try:
        stamp = datetime.fromisoformat(iso.replace("Z", ""))
        delta = datetime.now() - stamp
        seconds = int(delta.total_seconds())
        if seconds < 45:
            return "now"
        if seconds < 3600:
            return f"{max(1, seconds // 60)}m"
        if seconds < 86400:
            return f"{seconds // 3600}h"
        return f"{seconds // 86400}d"
    except Exception:
        return iso[-8:] if len(iso) >= 8 else iso


def _vitals() -> dict[str, float]:
    try:
        from monitoring.system_monitor import SystemMonitor

        snap = SystemMonitor().snapshot()
        return {
            "cpu": float(snap.get("cpu_percent") or 0),
            "ram": float(snap.get("ram_percent") or 0),
            "disk": float(snap.get("disk_percent") or 0),
        }
    except Exception:
        return {"cpu": 0.0, "ram": 0.0, "disk": 0.0}


def _pick_font(candidates: list[str], size: int, weight: str = "normal") -> tuple:
    """Return the first available family from candidates as a tk font tuple."""
    # tkinter resolves missing families at draw time; prefer known Windows fallbacks.
    for name in candidates:
        try:
            return (name, size, weight)
        except Exception:
            continue
    return ("Segoe UI", size, weight)


class OwlsVigilApp:
    """Realtime Owl's Vigil HUD window."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.mode = "idle"
        self._bar_count = 28
        self._t0 = time.perf_counter()
        self._vitals_cache = {"cpu": 0.0, "ram": 0.0, "disk": 0.0}
        self._vitals_thread: threading.Thread | None = None
        self._vitals_stop = threading.Event()
        self._last_activity_sig = ""

        self.root = tk.Tk()
        self.root.title(f"{ASSISTANT_NAME} — Owl's Vigil")
        self.root.configure(bg=VOID)
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-alpha", 0.98)
        except tk.TclError:
            pass

        self._fonts()
        self._build()
        self._place_top_right()
        self._bind_drag()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(ANIM_MS, self._tick_animation)
        self.root.after(POLL_MS, self._tick_status)
        self.root.after(CLOCK_MS, self._tick_clock)
        self._start_vitals_worker()
        self._refresh_all(force=True)

    def _fonts(self) -> None:
        self.font_brand = _pick_font(["Cinzel", "Georgia", "Times New Roman"], 14, "bold")
        self.font_ui = _pick_font(["Inter", "Segoe UI", "Calibri"], 10)
        self.font_ui_sm = _pick_font(["Inter", "Segoe UI", "Calibri"], 9)
        self.font_mono = _pick_font(["JetBrains Mono", "Cascadia Mono", "Consolas"], 9)
        self.font_mono_sm = _pick_font(["JetBrains Mono", "Cascadia Mono", "Consolas"], 8)
        self.font_label = _pick_font(["Inter", "Segoe UI", "Calibri"], 8)
        self.font_chip = _pick_font(["Inter", "Segoe UI", "Calibri"], 8)

    def _place_top_right(self) -> None:
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        margin = 24
        x = max(0, sw - WINDOW_W - margin)
        y = margin
        self.root.geometry(f"{WINDOW_W}x{WINDOW_H}+{x}+{y}")

    def _bind_drag(self) -> None:
        self._drag_x = 0
        self._drag_y = 0

        def start(event):
            self._drag_x = event.x_root - self.root.winfo_x()
            self._drag_y = event.y_root - self.root.winfo_y()

        def move(event):
            self.root.geometry(
                f"+{event.x_root - self._drag_x}+{event.y_root - self._drag_y}"
            )

        for widget in (self.root, self.shell, self.header, self.hint_label):
            widget.bind("<Button-1>", start)
            widget.bind("<B1-Motion>", move)

    def _build(self) -> None:
        outer = tk.Frame(self.root, bg=VOID, padx=10, pady=10)
        outer.pack(fill="both", expand=True)

        self.hint_label = tk.Label(
            outer,
            text="Owl's Vigil · live · drag to move",
            bg=VOID,
            fg=IVORY_DIM,
            font=self.font_label,
        )
        self.hint_label.pack(pady=(0, 8))

        self.shell = tk.Frame(
            outer,
            bg=PANEL,
            highlightbackground=PANEL_EDGE,
            highlightthickness=1,
            padx=18,
            pady=16,
        )
        self.shell.pack(fill="both", expand=True)

        # Wordmark
        self.header = tk.Frame(self.shell, bg=PANEL)
        self.header.pack(fill="x", pady=(0, 8))

        glyph = tk.Canvas(
            self.header, width=20, height=20, bg=PANEL, highlightthickness=0
        )
        glyph.pack(side="left")
        glyph.create_oval(2, 2, 18, 18, outline=GOLD, width=1.5)
        glyph.create_rectangle(9, 5, 11, 15, fill=GOLD, outline="")

        tk.Label(
            self.header,
            text=ASSISTANT_NAME.upper(),
            bg=PANEL,
            fg=IVORY,
            font=self.font_brand,
        ).pack(side="left", padx=(10, 0))

        self.mode_label = tk.Label(
            self.header,
            text="Idle",
            bg=PANEL,
            fg=IVORY_DIM,
            font=self.font_label,
        )
        self.mode_label.pack(side="right")

        # Orb stage
        self.orb_canvas = tk.Canvas(
            self.shell,
            width=220,
            height=220,
            bg=PANEL,
            highlightthickness=0,
        )
        self.orb_canvas.pack(pady=(4, 0))
        self._draw_orb_static()
        self._bar_ids: list[int] = []
        self._create_bars()

        # Status row
        status_row = tk.Frame(self.shell, bg=PANEL)
        status_row.pack(fill="x", pady=(10, 0))

        left = tk.Frame(status_row, bg=PANEL)
        left.pack(side="left", fill="x", expand=True)

        self.dot = tk.Canvas(left, width=10, height=14, bg=PANEL, highlightthickness=0)
        self.dot.pack(side="left")
        self._dot_id = self.dot.create_oval(2, 4, 8, 10, fill=TEAL, outline="")

        self.status_text = tk.Label(
            left,
            text=f'Say "{ASSISTANT_NAME}" to begin',
            bg=PANEL,
            fg=IVORY,
            font=self.font_ui,
            anchor="w",
            justify="left",
            wraplength=230,
        )
        self.status_text.pack(side="left", fill="x", expand=True)

        self.clock_label = tk.Label(
            status_row, text="--:--:--", bg=PANEL, fg=IVORY_DIM, font=self.font_mono
        )
        self.clock_label.pack(side="right")

        # Vitals
        vitals = tk.Frame(self.shell, bg=PANEL)
        vitals.pack(fill="x", pady=(14, 0))
        self._vital_fills: dict[str, tk.Frame] = {}
        self._vital_tracks: dict[str, tk.Frame] = {}
        for key, label, color in (
            ("cpu", "CPU", TEAL),
            ("ram", "Memory", GOLD_DIM),
            ("disk", "Disk", TEAL),
        ):
            cell = tk.Frame(
                vitals,
                bg="#14171E",
                highlightbackground=PANEL_EDGE,
                highlightthickness=1,
                padx=8,
                pady=7,
            )
            cell.pack(side="left", fill="x", expand=True, padx=(0 if key == "cpu" else 4, 0))
            tk.Label(
                cell, text=label, bg="#14171E", fg=IVORY_DIM, font=self.font_label, anchor="w"
            ).pack(fill="x")
            track = tk.Frame(cell, bg=TRACK, height=3)
            track.pack(fill="x", pady=(5, 0))
            track.pack_propagate(False)
            fill = tk.Frame(track, bg=color, width=1, height=3)
            fill.place(x=0, y=0, relheight=1.0, width=1)
            self._vital_tracks[key] = track
            self._vital_fills[key] = fill

        # Services
        services = tk.Frame(self.shell, bg=PANEL)
        services.pack(fill="x", pady=(12, 0))
        self._service_vars: dict[str, tk.StringVar] = {}
        for row_keys in (("voice", "ollama"), ("rag", "openclaw")):
            row = tk.Frame(services, bg=PANEL)
            row.pack(fill="x", pady=2)
            for key in row_keys:
                cell = tk.Frame(
                    row,
                    bg=PANEL,
                    highlightbackground=PANEL_EDGE,
                    highlightthickness=1,
                    padx=8,
                    pady=6,
                )
                cell.pack(side="left", fill="x", expand=True, padx=(0 if key in ("voice", "rag") else 4, 0))
                tk.Label(
                    cell,
                    text=key.upper(),
                    bg=PANEL,
                    fg=IVORY_DIM,
                    font=self.font_label,
                ).pack(side="left")
                var = tk.StringVar(value="—")
                self._service_vars[key] = var
                tk.Label(
                    cell, textvariable=var, bg=PANEL, fg=IVORY, font=self.font_mono_sm
                ).pack(side="right")

        # Activity log
        log_frame = tk.Frame(self.shell, bg=PANEL)
        log_frame.pack(fill="both", expand=True, pady=(14, 0))
        tk.Frame(log_frame, bg=PANEL_EDGE, height=1).pack(fill="x", pady=(0, 8))

        self.log_box = tk.Frame(log_frame, bg=PANEL)
        self.log_box.pack(fill="both", expand=True)
        self._log_rows: list[tuple[tk.Label, tk.Label]] = []
        for _ in range(5):
            row = tk.Frame(self.log_box, bg=PANEL)
            row.pack(fill="x", pady=1)
            t = tk.Label(row, text="", bg=PANEL, fg="#5B5748", font=self.font_mono_sm, width=4, anchor="w")
            t.pack(side="left")
            m = tk.Label(
                row,
                text="",
                bg=PANEL,
                fg=IVORY_DIM,
                font=self.font_mono_sm,
                anchor="w",
                justify="left",
                wraplength=260,
            )
            m.pack(side="left", fill="x", expand=True)
            self._log_rows.append((t, m))

        # Mode chips (live indicators, not demo controls)
        chips = tk.Frame(self.shell, bg=PANEL)
        chips.pack(fill="x", pady=(14, 0))
        self._chip_labels: dict[str, tk.Label] = {}
        for mode in ("idle", "listening", "thinking", "speaking"):
            chip = tk.Label(
                chips,
                text=mode.capitalize(),
                bg=PANEL,
                fg=IVORY_DIM,
                font=self.font_chip,
                padx=10,
                pady=4,
                highlightbackground=PANEL_EDGE,
                highlightthickness=1,
            )
            chip.pack(side="left", padx=3)
            self._chip_labels[mode] = chip

        self.footer = tk.Label(
            self.shell,
            text=f"v{self.settings.athena_version} · realtime",
            bg=PANEL,
            fg=IVORY_DIM,
            font=self.font_label,
        )
        self.footer.pack(pady=(12, 0))

    def _draw_orb_static(self) -> None:
        c = self.orb_canvas
        cx, cy = 110, 110
        # rings
        c.create_oval(cx - 100, cy - 100, cx + 100, cy + 100, outline="#1A2A28", width=1)
        c.create_oval(cx - 85, cy - 85, cx + 85, cy + 85, outline="#2A2618", width=1)
        # orb body
        self._orb_id = c.create_oval(
            cx - 66, cy - 66, cx + 66, cy + 66, fill=ORB_INNER, outline=GOLD, width=1
        )
        # iris
        c.create_oval(cx - 29, cy - 29, cx + 29, cy + 29, fill=IRIS_DARK, outline="")
        c.create_oval(cx - 26, cy - 26, cx + 26, cy + 26, fill=IRIS, outline="")
        # pupil (rectangle / circle morph via coords)
        self._pupil_id = c.create_oval(
            cx - 4.5, cy - 15, cx + 4.5, cy + 15, fill=GOLD, outline=""
        )

    def _create_bars(self) -> None:
        c = self.orb_canvas
        cx, cy = 110, 110
        radius = 58
        self._bar_ids.clear()
        for i in range(self._bar_count):
            angle = (i / self._bar_count) * 2 * math.pi
            # start near ring
            x0 = cx + math.sin(angle) * radius
            y0 = cy - math.cos(angle) * radius
            x1 = cx + math.sin(angle) * (radius + 4)
            y1 = cy - math.cos(angle) * (radius + 4)
            bid = c.create_line(x0, y0, x1, y1, fill=GOLD_DIM, width=2, capstyle=tk.ROUND)
            self._bar_ids.append(bid)
            # store angle on canvas item via parallel list
        self._bar_angles = [
            (i / self._bar_count) * 2 * math.pi for i in range(self._bar_count)
        ]

    def _set_orb_mode(self, mode: str) -> None:
        c = self.orb_canvas
        cx, cy = 110, 110
        if mode == "listening":
            c.itemconfig(self._orb_id, outline="#E0C070", width=2)
            c.coords(self._pupil_id, cx - 4.5, cy - 11, cx + 4.5, cy + 11)
            self.dot.itemconfig(self._dot_id, fill=GOLD)
        elif mode == "thinking":
            c.itemconfig(self._orb_id, outline=TEAL, width=2)
            c.coords(self._pupil_id, cx - 6, cy - 6, cx + 6, cy + 6)
            self.dot.itemconfig(self._dot_id, fill=TEAL)
        elif mode == "speaking":
            c.itemconfig(self._orb_id, outline=GOLD, width=2)
            c.coords(self._pupil_id, cx - 4.5, cy - 13, cx + 4.5, cy + 13)
            self.dot.itemconfig(self._dot_id, fill=GOLD)
        else:
            c.itemconfig(self._orb_id, outline="#6A5A30", width=1)
            c.coords(self._pupil_id, cx - 4.5, cy - 15, cx + 4.5, cy + 15)
            self.dot.itemconfig(self._dot_id, fill=TEAL)

        for name, chip in self._chip_labels.items():
            if name == mode:
                chip.configure(bg=GOLD, fg=VOID, highlightbackground=GOLD)
            else:
                chip.configure(bg=PANEL, fg=IVORY_DIM, highlightbackground=PANEL_EDGE)

    def _animate_bars(self) -> None:
        t = (time.perf_counter() - self._t0) * 1000
        mode = self.mode
        cx, cy = 110, 110
        base_r = 58
        c = self.orb_canvas
        for i, bid in enumerate(self._bar_ids):
            angle = self._bar_angles[i]
            h = 4.0
            if mode == "listening":
                h = 4 + 16 * (0.4 + 0.6 * math.sin(t / 200 + i)) * (0.5 + 0.5 * abs(math.sin(t / 180 + i * 0.3)))
            elif mode == "speaking":
                h = 4 + 20 * (0.4 + 0.6 * math.sin(t / 150 + i * 0.7))
            elif mode == "thinking":
                h = 4 + 6 * abs(math.sin(t / 400 + i * 0.5))
            h = max(3.0, h)
            opacity_idle = mode == "idle"
            color = "#3A3420" if opacity_idle else GOLD_DIM
            x0 = cx + math.sin(angle) * base_r
            y0 = cy - math.cos(angle) * base_r
            x1 = cx + math.sin(angle) * (base_r + h)
            y1 = cy - math.cos(angle) * (base_r + h)
            c.coords(bid, x0, y0, x1, y1)
            c.itemconfig(bid, fill=color)

    def _set_vital(self, key: str, percent: float) -> None:
        track = self._vital_tracks[key]
        fill = self._vital_fills[key]
        track.update_idletasks()
        width = max(1, int(track.winfo_width() * max(0.0, min(100.0, percent)) / 100.0))
        fill.place(x=0, y=0, relheight=1.0, width=width)

    def _update_log(self, activity: list[dict[str, Any]]) -> None:
        if not activity:
            activity = [
                {
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "message": f"{ASSISTANT_NAME} is standing watch",
                }
            ]
        for index, (t_label, m_label) in enumerate(self._log_rows):
            if index < len(activity):
                item = activity[index]
                t_label.configure(text=_relative_time(str(item.get("timestamp", ""))))
                msg = str(item.get("message", ""))[:72]
                m_label.configure(text=msg, fg=IVORY if index == 0 else IVORY_DIM)
            else:
                t_label.configure(text="")
                m_label.configure(text="")

    def _refresh_all(self, force: bool = False) -> None:
        status = read_status()
        mode = _mode_from_status(status)
        message = _status_message(mode, status)

        if force or mode != self.mode:
            self.mode = mode
            self.mode_label.configure(text=mode.capitalize())
            self._set_orb_mode(mode)

        self.status_text.configure(text=message)

        for key, var in self._service_vars.items():
            var.set(str(status.get(key, "unknown")))

        for key in ("cpu", "ram", "disk"):
            self._set_vital(key, self._vitals_cache.get(key, 0.0))

        activity = recent_activity(5)
        sig = "|".join(
            f"{i.get('timestamp')}:{i.get('message')}" for i in activity[:5]
        )
        if force or sig != self._last_activity_sig:
            self._last_activity_sig = sig
            self._update_log(activity)

    def _tick_animation(self) -> None:
        try:
            self._animate_bars()
        except tk.TclError:
            return
        self.root.after(ANIM_MS, self._tick_animation)

    def _tick_status(self) -> None:
        try:
            self._refresh_all()
        except tk.TclError:
            return
        except Exception:
            pass
        self.root.after(POLL_MS, self._tick_status)

    def _tick_clock(self) -> None:
        try:
            self.clock_label.configure(text=datetime.now().strftime("%H:%M:%S"))
        except tk.TclError:
            return
        self.root.after(CLOCK_MS, self._tick_clock)

    def _start_vitals_worker(self) -> None:
        def loop() -> None:
            while not self._vitals_stop.wait(VITALS_MS / 1000):
                try:
                    self._vitals_cache = _vitals()
                except Exception:
                    pass

        # Prime once without blocking UI long — cpu_percent(0.1) is ok off-thread.
        def prime() -> None:
            try:
                self._vitals_cache = _vitals()
            except Exception:
                pass

        threading.Thread(target=prime, daemon=True).start()
        self._vitals_stop.clear()
        self._vitals_thread = threading.Thread(
            target=loop, name="athena-vigil-vitals", daemon=True
        )
        self._vitals_thread.start()

    def _on_close(self) -> None:
        self._vitals_stop.set()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def open_dashboard() -> None:
    """
    Launch (or focus) the Owl's Vigil realtime GUI.

    Spawns a separate process so the system tray is not blocked.
    """
    global _DASHBOARD_PROC

    if _DASHBOARD_PROC is not None and _DASHBOARD_PROC.poll() is None:
        # Already running — nothing else to do from another process boundary.
        return

    if is_frozen():
        command = [sys.executable, "--dashboard"]
    else:
        command = [sys.executable, "-m", "ui.dashboard"]

    _DASHBOARD_PROC = subprocess.Popen(
        command,
        cwd=str(PROJECT_ROOT),
    )


def main() -> None:
    OwlsVigilApp().run()


if __name__ == "__main__":
    main()
