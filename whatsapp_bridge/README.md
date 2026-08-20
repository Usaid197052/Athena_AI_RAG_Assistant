# Athena WhatsApp Bridge (Baileys)

Local WhatsApp Web protocol bridge used by Athena. Listens only on `127.0.0.1:8765`.

## Packaged app (new users)

In Athena: **Settings ⚙ → WhatsApp Setup**.

1. Scan the QR with your phone: WhatsApp → Linked Devices → Link a device.
2. Import a `Contacts.vcf` or Google CSV so spoken names resolve to numbers.

The packaged build includes Node and `node_modules` so you do not need to run `npm install`.

## Developer (from source)

- Node.js 18+
- One-time QR link with your phone (Linked Devices)

```bash
cd whatsapp_bridge
npm install
npm start
```

Athena can also spawn this automatically via `actions/whatsapp_bridge_client.py`.

Auth session is stored in `memory/whatsapp_baileys/` (gitignored).  
When a QR is needed, it is written to `memory/whatsapp_baileys/qr.png` — Athena also shows it in WhatsApp Setup.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/status` | `qr` / `connecting` / `connected` / `disconnected` |
| POST | `/resolve` | `{ "name": "Mom" }` → jid |
| POST | `/send` | `{ "jid", "text" }` or `{ "jid", "mediaPath", "caption", "ptt" }` |
| GET | `/messages?jid=&limit=` | last messages in a chat |
| GET | `/chats?unread=1` | unread chat list |
| GET | `/events?since=N` | inbound ring buffer |
| POST | `/ack` | `{ "ids": [...] }` |

## Notification fallback

While the bridge is **connected**, Athena detects messages from the protocol (Desktop notifications not required).  
If the bridge is down, Athena may use Windows notification access as a backup — grant access when prompted on auto-reply enable.
