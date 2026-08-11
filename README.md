# Athena

Local-first Windows AI PC agent (formerly Jarvis).

**Athena thinks, tools act, OpenClaw executes, RAG remembers, Whisper hears, TTS speaks.**

## Quick start

```powershell
cd D:\Projects\Jarvis
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python scripts\scan_apps.py
python scripts\health_check.py
python main.py
```

Tray UI:

```powershell
python gui\tray_app.py
```

Dashboard (Owl's Vigil realtime HUD):

```powershell
python -m ui.dashboard
```

## First milestone

Say: **"Hey Athena, open Visual Studio."**

Or a mission/workflow:

> "Hey Athena, prepare my data engineering environment."

Then ask **"status"** for checklist progress.

## Packaging

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1
```

See `docs/packaging.md`.

## Docs

Start with `docs/installation.md`. Also: architecture, configuration, security, tools, email, RAG, voice, vision, UI, packaging, troubleshooting.

## Model

Default: Ollama `qwen3.5:9b` (configurable via `.env`).
