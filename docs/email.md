# Athena Email

Default policy from the build guide:

```text
draft → confirmation → send
```

Athena never silently sends mail.

## Tools

### Drafts / send
- `draft_email` — create a local draft (`data/sessions/email_drafts/`)
- `list_email_drafts` / `read_email_draft` / `search_email_drafts`
- `send_email` — HIGH risk, always requires confirmation

### Inbox (IMAP)
- `search_inbox` (`query`, `limit`, `unread_only`) — SUBJECT/FROM search
- `read_email` (`message_id`, optional `folder`) — read one message

Prefer:

```text
draft_email(... ) → review → send_email(draft_id=...)
```

```text
search_inbox(query="Maryam") → read_email(message_id=...)
```

## Configuration

In `.env` (never commit secrets):

```text
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=you@example.com
SMTP_PASSWORD=...
SMTP_FROM=you@example.com
SMTP_USE_TLS=true

IMAP_HOST=imap.example.com
IMAP_PORT=993
IMAP_USERNAME=you@example.com
IMAP_PASSWORD=...
IMAP_FOLDER=INBOX
IMAP_USE_SSL=true
```

If `IMAP_USERNAME` / `IMAP_PASSWORD` are blank, Athena falls back to `SMTP_*` credentials.

## Example

> "Draft an email to Maryam saying I'll follow up tomorrow."

Athena creates a draft and asks before any `send_email` step.

> "Search my inbox for ClickHouse."

Athena uses `search_inbox` then can `read_email` on a selected id.
