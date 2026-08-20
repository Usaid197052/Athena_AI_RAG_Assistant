# Athena

Windows voice assistant built on **Gemini Live** (native audio). A PyQt6 HUD listens, talks, and runs tools on this machine.

There are **two separate programs**. Do not mix them.

| App | Command | What it does |
|---|---|---|
| General assistant | `python main.py` | Desktop, files, WhatsApp, Gmail, search, vision, read-only MT5 analysis. **No auto-trading.** |
| Trading desk | `python trading_main.py` | MetaTrader 5 demo desk only. Auto-trades behind a risk engine. **No WhatsApp, files, or desktop control.** |

Gemini never calls `order_send`. The assistant can analyze charts; only `trading_main.py` may place demo orders.

---

## Requirements

- Windows 10/11 (MetaTrader tools and several OS actions are Windows-only)
- Python 3.11 or 3.12
- Microphone (voice)
- [Gemini API key](https://aistudio.google.com/apikey)
- For trading: MetaTrader 5 terminal, **demo** account, Algo Trading enabled

```bash
pip install -r requirements.txt
```

On first run, the HUD asks for the Gemini key and writes `config/api_keys.json` (gitignored).

---

## Run the assistant

```bash
python main.py
```

Defaults to **English**. Switch language only if you explicitly ask; a new process always starts in English.

Sleep hides the HUD to the tray (wake word or tray icon). Shutdown quits Athena, not the PC.

### Assistant capabilities

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
- Read-only **MetaTrader 5** quotes, TA (BIAS BUY/SELL/WAIT), calendar/news, chart snapshot — never places orders

Risky tools ask once (HUD + voice: “go ahead” / “abort”). Low-risk tools auto-run.

---

## Run the trading desk

Keep MT5 open and logged into a **demo**. Then:

```bash
python trading_main.py
```

The HUD shows account type, equity, daily P&L, Athena positions, last bias, and **Pause / Resume / Flatten**. Flatten closes only tickets with Athena’s magic number.

### How auto-trade works

On each new bar (and if bias later flips off WAIT on the same bar):

1. Session hours (default **07:00–21:00 UTC**, weekdays)
2. High-impact news blackout (30 min before / 15 min after)
3. TA + light FA + risk card
4. If BIAS is **BUY** or **SELL** and every gate passes → market order with ATR SL/TP

WAIT does not close winners. Profit exit is TP; loss exit is SL. Opposite bias closes the Athena position only — no reverse on the same tick.

### Hard rules (v1)

- **Demo only.** Live accounts are refused.
- Default volume **0.01** lots; every order has SL and TP
- Magic number (default `20260820`) — Athena manages only her tickets
- One Athena position per symbol
- Kill switch: daily loss cap (~3% equity), max 3 open Athena positions, wide spread, `auto_trade` off, session, news
- Idempotent: one fire per `(symbol, bar time, bias)`
- Sleep / shutdown pause auto-trade

### Trading config

Edit `config/trading.json`:

| Key | Meaning |
|---|---|
| `symbols` | e.g. `["EURUSD"]` |
| `timeframe` | `H1` (also `M15`, `H4`, …) |
| `volume` | lots |
| `sl_atr` / `tp_atr` | stop/target as ATR multiples |
| `magic` | Athena ticket filter |
| `daily_loss_pct` | kill new entries when hit |
| `max_spread_points` | block wide quotes |
| `auto_trade` | `true` / `false` (Pause/Resume also writes this) |
| `session_start_utc` / `session_end_utc` | no new entries outside this window |
| `watch_interval_sec` | how often the watch-loop polls |

Voice tools on this process only: `trading_desk`, `mt5_analysis`, `trading_control` (`status` \| `pause` \| `resume` \| `flatten`), `web_search`, sleep, shutdown.

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

### Trading logs

Separate from the assistant log:

| File | Contents |
|---|---|
| `logs/athena.log` | General assistant |
| `logs/trading/desk.log` | Watch ticks, TA score, gates, fills |
| `logs/trading/decisions.jsonl` | One JSON object per desk/exec decision |
| `memory/trading_journal.json` | Desk journal |

---

## Layout

```
main.py                 # Assistant — Gemini Live, full tool surface
trading_main.py         # Trading desk — own live class, own tools
ui.py                   # Shared PyQt6 HUD
core/prompt.txt         # Assistant persona + routing
core/prompt_trading.txt # Trading persona (fills only if tools say FILLED)
core/permissions.py     # Risk levels / voice confirmation
core/logger.py          # logs/athena.log
core/trading_logger.py  # logs/trading/
actions/                # Tools (WhatsApp, files, MT5 analysis, desk, …)
config/trading.json     # Desk symbols, risk, session, magic
config/api_keys.json    # Gemini key (create on first run)
dashboard/              # Phone / web remote
whatsapp_bridge/        # Local Baileys server
memory/                 # Long-term memory, journals, OAuth (gitignored secrets)
```

`actions/mt5_executor.py` is imported only by the trading desk, not by `main.py`.

---

## Troubleshooting

| Symptom | Check |
|---|---|
| No voice | Mic, API key, Gemini Live model in Settings |
| MT5 “could not connect” | Terminal open, logged in, Market Watch has the symbol |
| Assistant will not buy/sell | Expected — `main.py` is analysis only. Use `python trading_main.py` |
| Desk never fills | HUD last bias/block; `logs/trading/desk.log`. WAIT = no order. Session, news, pause, daily loss, or live account will BLOCK |
| Order rejected | Algo Trading on in MT5; account must be demo |
| WhatsApp not linked | Settings → WhatsApp Setup, scan QR, import contacts |

---

Trading features are for **demo/education**. They are not financial advice. You can lose money on live accounts; this build refuses live `order_send`.
