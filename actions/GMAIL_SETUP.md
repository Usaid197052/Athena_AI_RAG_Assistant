# Gmail API bridge (Athena)

Gmail compose/send uses the official Gmail API (no browser GUI).

## One-time Google Cloud setup

1. Open [Google Cloud Console](https://console.cloud.google.com/)
2. Create/select a project
3. Enable **Gmail API**
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**
   - Application type: **Desktop app**
5. Under the OAuth client, add authorized redirect URI:
   ```
   http://127.0.0.1:8766/
   ```
6. If the consent screen is in **Testing**, add your Google account as a test user
7. Copy Client ID and Client Secret into `config/api_keys.json`:

```json
{
  "gmail": {
    "client_id": "YOUR_CLIENT_ID.apps.googleusercontent.com",
    "client_secret": "YOUR_CLIENT_SECRET",
    "redirect_uri": "http://127.0.0.1:8766/"
  }
}
```

## Link Athena

```bash
python actions/gmail_bridge_client.py --login
```

A browser opens → sign in → allow send access. Tokens are stored in `memory/gmail_oauth/` (gitignored).

Check status:

```bash
python actions/gmail_bridge_client.py --status
```

## Usage

Same as before via `send_message`:

- `action=compose` with `platform=gmail`, `receiver`, `message_text`, optional `subject`
- User confirms → `action=send`
- Does **not** claim sent unless the tool result starts with `Sent`

Cost: Gmail API is free for normal personal use within Google quotas.
