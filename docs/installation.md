# Athena Installation

## Requirements

- Windows 10/11
- Python 3.12
- Git
- Ollama with a local chat model (recommended: `qwen3.5:9b`)
- Microphone / speakers for voice

## Setup

```powershell
cd D:\Projects\Jarvis
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
copy .env.example .env
```

Pull models:

```powershell
ollama pull qwen3.5:9b
ollama pull nomic-embed-text
```

## Run

Voice loop:

```powershell
python main.py
```

Tray + Owl's Vigil dashboard:

```powershell
python gui\tray_app.py
```

Health check:

```powershell
python scripts\health_check.py
```

## Optional

- OpenClaw gateway — set `OPENCLAW_ENABLED=true` and `OPENCLAW_ENDPOINT`
- SMTP / IMAP — see `docs/email.md`
- Windows startup — `scripts\install_startup.ps1`
- Packaged exe — see `docs/packaging.md`
