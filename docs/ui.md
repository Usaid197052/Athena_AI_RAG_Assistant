# Athena UI

## Tray

```powershell
python gui\tray_app.py
# or
python -m ui.tray
```

Menu:
- Status
- Start / Stop Listening
- Pause / Resume
- Open Dashboard
- Settings (`.env`)
- Recent Activity
- Permissions
- Open Logs
- Restart Services
- Exit

Tray glyph matches **Owl's Vigil** (gold pupil on void).

## Dashboard — Concept 01 “Owl's Vigil”

Realtime always-on-top desktop HUD (tkinter), not a browser page.

Source concept: `resources/athena-concept-1-owls-vigil.html`

```powershell
python -m ui.dashboard
# or
python app.py --dashboard
# or from tray: Open Dashboard
```

Shows (live, ~250 ms status poll):
- Cinzel-style **ATHENA** wordmark + mode label
- Animated owl-eye orb (Idle / Listening / Thinking / Speaking)
- Live phase / UX status line + clock
- CPU · Memory · Disk vitals
- Voice / Ollama / RAG / OpenClaw chips
- Recent activity log

Window stays topmost; drag the header to reposition. Spawned as a separate process from the tray so listening is not blocked.

## Professional UX phases (Phase 55)

`monitoring.status_store.set_ux_phase()` is updated by the voice loop, orchestrator, and plan executor. Orb mode is derived from voice + UX phase.

## Status IPC

`data/cache/athena_status.json` — agent/monitors write; tray/dashboard read.

Activity feed: `data/logs/activity.jsonl`

## Screen targeting

- `find_on_screen` — OCR locate + coordinates
- `click_text` — OCR click with `match_index`
- `click_at` — absolute coordinates
- `scroll_screen` / `type_text` / `press_key`
