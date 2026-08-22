# Athena

Windows voice assistant built on **Gemini Live** (native audio). A PyQt6 HUD listens, talks, and runs tools on this machine.

The **trading desk** (auto-trade, MT5 executor, trading HUD) lives in a separate repo: **Athena_Trading_v1** (`d:\AI\Athena_Trading_v1`).

This repo is the **personal assistant only** — read-only MT5 analysis, no auto-trading.

```bash
pip install -r requirements.txt
python main.py
```

---

## Requirements

- Windows 10/11 (MetaTrader tools and several OS actions are Windows-only)
- Python 3.11 or 3.12
- Microphone (voice)
- [Gemini API key](https://aistudio.google.com/apikey)
- Optional: MetaTrader 5 for read-only chart analysis

On first run, the HUD asks for the Gemini key and writes `config/api_keys.json` (gitignored).

---

## Run

Defaults to **English**. Switch language only if you explicitly ask; a new process always starts in English.

Sleep hides the HUD to the tray (wake word or tray icon). Shutdown quits Athena, not the PC.

### Capabilities

- Real-time voice + typed commands
- Screen / camera vision (`screen_process`); live screen share when you ask
- Launch apps, volume, brightness, Wi‑Fi, windows, Explorer, shell (permission-gated)
- Files: list/open/read/write, dropped-file analysis, DataFrame viewer
- Web search (`search` / `news` / `research` / `price` / `compare`)
- WhatsApp (local Baileys bridge), Gmail API, Spotify Desktop, YouTube
- Weather, flights, reminders, Steam/Epic game updates
- Persistent memory, session summaries, optional morning briefing
- Hardware alerts (CPU / RAM / GPU / temp)
- Topic news monitor (crypto/finance topics are blocked)
- Phone dashboard (QR / local HTTPS)
- Read-only **MetaTrader 5** quotes, TA (BIAS BUY/SELL/WAIT), calendar/news, chart snapshot — **never places orders**

Risky tools ask once (HUD + voice: “go ahead” / “abort”). Low-risk tools auto-run.

---

## Optional integrations

### WhatsApp

**Settings → WhatsApp Setup.** Scan the QR (WhatsApp → Linked Devices). Import `Contacts.vcf` or a Google CSV so spoken names resolve.

From source you also need Node 18+:

```bash
cd whatsapp_bridge
npm install
npm start
```

Athena can spawn the bridge itself. Session files live in `memory/whatsapp_baileys/` (gitignored). Details: `whatsapp_bridge/README.md`.

### Gmail

Enable Gmail API, put desktop OAuth client id/secret in `config/api_keys.json`, then:

```bash
python actions/gmail_bridge_client.py --login
```

See `actions/GMAIL_SETUP.md`.

### Spotify

Desktop app + browser login when Athena reports `AUTH_REQUIRED` (or `python actions/spotify_control.py --login`).

### MT5 logs (read-only analysis)

| File | Contents |
|---|---|
| `logs/athena.log` | Assistant |
| `logs/mt5/connection.log` | MT5 IPC connect / drop / reconnect |
| `logs/mt5/events.jsonl` | Structured MT5 connection events |

---

## Layout

```
main.py                 # Assistant — Gemini Live, full tool surface
ui.py                   # PyQt6 HUD
core/prompt.txt         # Assistant persona + routing
core/permissions.py     # Risk levels / voice confirmation
core/logger.py          # logs/athena.log
actions/                # Tools (WhatsApp, files, MT5 analysis, …)
config/api_keys.json    # Gemini key (create on first run)
dashboard/              # Phone / web remote
whatsapp_bridge/        # Local Baileys server
memory/                 # Long-term memory, OAuth (gitignored secrets)
```

---

## Troubleshooting

| Symptom | Check |
|---|---|
| No voice | Mic, API key, Gemini Live model in Settings |
| MT5 “could not connect” | Terminal open, logged in, Market Watch has the symbol |
| Assistant will not buy/sell | Expected — use **Athena_Trading_v1** for auto-trade |
| WhatsApp not linked | Settings → WhatsApp Setup, scan QR, import contacts |
