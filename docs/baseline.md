# Athena Baseline (2026-08-10)

Recorded before the `athena-rearchitecture` migration work.

## Environment

| Component | Status |
|-----------|--------|
| Python | 3.12.4 |
| Ollama | 0.32.1 |
| Chat model | `qwen3.5:9b` (installed; guide target ~9.5B class) |
| Other models | `qwen3:8b`, `nomic-embed-text`, `qwen2.5-coder:7b` |
| OpenClaw | Not integrated yet |
| RAG | Local JSON vector store + Ollama embeddings |
| Voice | Wake (Whisper/OWW), Faster-Whisper STT, Piper TTS |
| Tray UI | `gui/tray_app.py` (Athena-branded) |

## Current folder structure

```text
Jarvis/   (filesystem path; product name is Athena)
├── main.py
├── brain/          ollama, planner, chat, intent, action parser
├── config/         ASSISTANT_NAME + voice/model settings
├── executor/       plan + action execution
├── gui/            system tray
├── logs/           file logger → athena.log
├── memory/         short-term + summarizer
├── permissions/    dangerous-tool confirmation set
├── rag/            ingest, search, embeddings, vector store
├── tools/          apps, files, terminal, system, registry
├── vision/         screenshot, OCR, UI automation
├── voice/          wake, STT, TTS
└── Tests/
```

## What currently works

- Voice loop: wake → STT → intent → chat or multi-step plan → TTS
- Hard-coded app openers: Visual Studio, Notepad, Calculator, CMD, PowerShell
- File / terminal / system tools with confirmation for dangerous ops
- RAG ingest + query
- Screenshot / OCR / basic UI automation
- System tray start/stop

## Known limitations / bugs

- Application paths are hard-coded (machine-specific VS path)
- No Windows application discovery / fuzzy matching
- No generic `open_application` tool
- No OpenClaw execution layer
- No central orchestrator (logic lives in `main.py`)
- Config is constants only (no `.env` / pydantic settings)
- Logging is plain text, not structured levels
- Folder still named `Jarvis`; some legacy aliases remain (`ask_jarvis`, exit phrases)

## Dependencies

See `requirements.txt`. Foundation packages for rearchitecture:
`pydantic`, `pydantic-settings`, `python-dotenv`, `pyyaml`, `psutil`, `pytest`, `requests`.

## Backup

- Git branch: `athena-rearchitecture`
- Filesystem backup: `D:\Projects\Backups\Jarvis_pre_athena_*`
