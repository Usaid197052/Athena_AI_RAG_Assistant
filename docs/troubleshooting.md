# Athena Troubleshooting

## Ollama unavailable

> "The local AI model isn't available."

Check `ollama serve` and `OLLAMA_HOST` / `OLLAMA_MODEL`.

## OpenClaw unavailable

Athena falls back to local launchers when OpenClaw is disabled/offline.

## RAG unavailable

Athena continues without long-term memory for the current turn.

## Microphone / TTS

Run `python scripts\health_check.py`. Confirm Windows privacy settings allow mic access.

## Application not found

Rescan: `python scripts\scan_apps.py`. Prefer friendly names (`Visual Studio`), not hard-coded paths.

## Dashboard stale

Status file: `data/cache/athena_status.json`. Open tray → Restart Services, then re-open the HUD:

```powershell
python -m ui.dashboard
```
