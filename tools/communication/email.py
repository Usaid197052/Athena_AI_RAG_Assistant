"""
Email tools for Athena.

Default flow: draft -> confirmation -> send.
Never send silently. Credentials come from environment only.
"""

from __future__ import annotations

import json
import smtplib
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from config.settings import PROJECT_ROOT, get_settings
from logs.logger import get_logger
from security.path_guard import PathSecurityError, assert_safe_path

logger = get_logger("athena.email")

DRAFTS_DIR = PROJECT_ROOT / "data" / "sessions" / "email_drafts"


@dataclass
class EmailDraft:
    id: str
    to: str
    subject: str
    body: str
    cc: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )
    status: str = "draft"  # draft | sent | cancelled

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EmailDraft":
        return cls(**data)


def _drafts_dir() -> Path:
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    return DRAFTS_DIR


def _save_draft(draft: EmailDraft) -> Path:
    path = _drafts_dir() / f"{draft.id}.json"
    path.write_text(json.dumps(draft.to_dict(), indent=2), encoding="utf-8")
    return path


def _load_draft(draft_id: str) -> EmailDraft | None:
    path = _drafts_dir() / f"{draft_id}.json"
    if not path.exists():
        return None
    return EmailDraft.from_dict(json.loads(path.read_text(encoding="utf-8")))


def draft_email(to: str, subject: str, body: str, cc: str = "") -> str:
    if not str(to).strip():
        return "Error drafting email: recipient (to) is required."
    if not str(subject).strip() and not str(body).strip():
        return "Error drafting email: subject or body is required."

    draft = EmailDraft(
        id=str(uuid.uuid4()),
        to=str(to).strip(),
        subject=str(subject).strip(),
        body=str(body).strip(),
        cc=str(cc or "").strip(),
    )
    path = _save_draft(draft)
    logger.info("Created email draft %s", draft.id)
    return (
        "Email draft created (not sent).\n"
        f"draft_id: {draft.id}\n"
        f"to: {draft.to}\n"
        f"subject: {draft.subject}\n"
        f"body:\n{draft.body}\n"
        f"saved: {path}\n"
        "Say send_email with this draft_id after confirmation."
    )


def list_email_drafts(limit: int = 10) -> str:
    files = sorted(_drafts_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return "No email drafts found."

    lines = []
    for path in files[: max(1, int(limit))]:
        try:
            draft = EmailDraft.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
        lines.append(
            f"{draft.id[:8]}…  [{draft.status}]  to={draft.to}  subject={draft.subject}"
        )
    return "Email drafts:\n" + "\n".join(lines)


def read_email_draft(draft_id: str) -> str:
    draft = _load_draft(draft_id.strip())
    if draft is None:
        # allow short prefix match
        matches = [
            path
            for path in _drafts_dir().glob("*.json")
            if path.stem.startswith(draft_id.strip())
        ]
        if len(matches) == 1:
            draft = EmailDraft.from_dict(
                json.loads(matches[0].read_text(encoding="utf-8"))
            )
        elif len(matches) > 1:
            return "Multiple drafts match that id prefix. Use the full draft_id."
        else:
            return f"Draft not found: {draft_id}"

    return (
        f"draft_id: {draft.id}\n"
        f"status: {draft.status}\n"
        f"to: {draft.to}\n"
        f"cc: {draft.cc or '(none)'}\n"
        f"subject: {draft.subject}\n"
        f"body:\n{draft.body}"
    )


def search_email_drafts(query: str) -> str:
    needle = query.lower().strip()
    if not needle:
        return "Error: search query is required."

    hits = []
    for path in _drafts_dir().glob("*.json"):
        try:
            draft = EmailDraft.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
        blob = f"{draft.to} {draft.cc} {draft.subject} {draft.body}".lower()
        if needle in blob:
            hits.append(
                f"{draft.id[:8]}…  [{draft.status}]  to={draft.to}  subject={draft.subject}"
            )
    if not hits:
        return f"No drafts matched '{query}'."
    return "Matching drafts:\n" + "\n".join(hits[:20])


def send_email(
    draft_id: str = "",
    to: str = "",
    subject: str = "",
    body: str = "",
    cc: str = "",
) -> str:
    """
    Send an email. Prefer draft_id. Requires SMTP settings in .env.
    This tool is HIGH risk and must go through confirmation.
    """
    settings = get_settings()
    if not settings.smtp_host or not settings.smtp_username or not settings.smtp_from:
        return (
            "Error: SMTP is not configured. Set SMTP_HOST, SMTP_PORT, "
            "SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM in .env."
        )

    draft = None
    if draft_id.strip():
        draft = _load_draft(draft_id.strip())
        if draft is None:
            matches = [
                path
                for path in _drafts_dir().glob("*.json")
                if path.stem.startswith(draft_id.strip())
            ]
            if len(matches) == 1:
                draft = EmailDraft.from_dict(
                    json.loads(matches[0].read_text(encoding="utf-8"))
                )
            else:
                return f"Draft not found: {draft_id}"
        if draft.status == "sent":
            return f"Draft {draft.id} was already sent."
        to = draft.to
        subject = draft.subject
        body = draft.body
        cc = draft.cc

    if not str(to).strip():
        return "Error sending email: recipient (to) is required."

    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    if cc:
        message["Cc"] = cc
    message["Subject"] = subject or "(no subject)"
    message.set_content(body or "")

    recipients = [addr.strip() for addr in to.split(",") if addr.strip()]
    if cc:
        recipients.extend(addr.strip() for addr in cc.split(",") if addr.strip())

    try:
        if settings.smtp_use_tls:
            with smtplib.SMTP(settings.smtp_host, int(settings.smtp_port), timeout=30) as smtp:
                smtp.starttls()
                if settings.smtp_password:
                    smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(message, to_addrs=recipients)
        else:
            with smtplib.SMTP_SSL(settings.smtp_host, int(settings.smtp_port), timeout=30) as smtp:
                if settings.smtp_password:
                    smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(message, to_addrs=recipients)
    except Exception as exc:
        logger.warning("SMTP send failed: %s", exc)
        return f"Error sending email: {exc}"

    if draft is not None:
        draft.status = "sent"
        _save_draft(draft)

    # Never log body contents
    logger.info("Sent email to=%s subject=%s", to, subject)
    return f"Email sent to {to} with subject '{subject}'."


def save_email_attachment_note(file_path: str) -> str:
    """
    Validate a local file exists for later manual attach workflows.
    """
    try:
        path = assert_safe_path(file_path, operation="read", must_exist=True)
    except PathSecurityError as exc:
        return f"Error: {exc}"
    if not path.is_file():
        return f"Error: not a file: {path}"
    return f"Attachment candidate ready: {path} ({path.stat().st_size} bytes)"


def _imap_settings():
    settings = get_settings()
    host = (settings.imap_host or "").strip()
    user = (settings.imap_username or settings.smtp_username or "").strip()
    password = settings.imap_password or settings.smtp_password or ""
    if not host or not user:
        return None, (
            "Error: IMAP is not configured. Set IMAP_HOST and IMAP_USERNAME "
            "(and IMAP_PASSWORD) in .env. SMTP_* credentials are used as fallback "
            "for username/password when IMAP_* is blank."
        )
    return settings, None


def _decode_header_value(raw: str | bytes | None) -> str:
    from email.header import decode_header, make_header

    if raw is None:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="replace")
        return str(raw)


def _imap_connect(settings):
    import imaplib

    host = settings.imap_host.strip()
    port = int(settings.imap_port or 993)
    user = (settings.imap_username or settings.smtp_username or "").strip()
    password = settings.imap_password or settings.smtp_password or ""
    if settings.imap_use_ssl:
        client = imaplib.IMAP4_SSL(host, port, timeout=30)
    else:
        client = imaplib.IMAP4(host, port, timeout=30)
    client.login(user, password)
    return client


def _extract_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if ctype == "text/plain" and "attachment" not in disp.lower():
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace").strip()
        return "(no plain-text body)"
    payload = msg.get_payload(decode=True) or b""
    charset = msg.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace").strip()


def search_inbox(query: str = "", limit: int = 10, unread_only: bool = False) -> str:
    """
    Search the IMAP inbox. Query matches SUBJECT/FROM/BODY (IMAP TEXT/OR).
    Never returns passwords; bodies are truncated in list view.
    """
    settings, err = _imap_settings()
    if err:
        return err

    folder = (settings.imap_folder or "INBOX").strip() or "INBOX"
    max_n = max(1, min(int(limit or 10), 30))
    criteria_parts: list[str] = []
    if unread_only:
        criteria_parts.append("UNSEEN")
    needle = (query or "").strip()
    if needle:
        # Escape double quotes in IMAP string
        safe = needle.replace('"', "")
        criteria_parts.append(f'(OR SUBJECT "{safe}" FROM "{safe}")')
    criteria = " ".join(criteria_parts) if criteria_parts else "ALL"

    try:
        client = _imap_connect(settings)
    except Exception as exc:
        return f"Error connecting to IMAP: {exc}"

    try:
        typ, _ = client.select(folder, readonly=True)
        if typ != "OK":
            return f"Error selecting folder '{folder}'."
        typ, data = client.search(None, criteria)
        if typ != "OK" or not data or not data[0]:
            return f"No messages matched in {folder}."
        ids = data[0].split()
        ids = list(reversed(ids))[:max_n]
        lines = [f"Inbox search ({folder}) — {len(ids)} shown:"]
        for raw_id in ids:
            typ, fetched = client.fetch(raw_id, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if typ != "OK" or not fetched or not fetched[0]:
                continue
            header_blob = fetched[0][1]
            from email import message_from_bytes

            msg = message_from_bytes(header_blob)
            subject = _decode_header_value(msg.get("Subject"))
            sender = _decode_header_value(msg.get("From"))
            date = _decode_header_value(msg.get("Date"))
            uid = raw_id.decode() if isinstance(raw_id, bytes) else str(raw_id)
            lines.append(f"- id={uid}  from={sender}  subject={subject}  date={date}")
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("IMAP search failed: %s", exc)
        return f"Error searching inbox: {exc}"
    finally:
        try:
            client.logout()
        except Exception:
            pass


def read_email(message_id: str, folder: str = "") -> str:
    """
    Read one IMAP message by sequence id from search_inbox.
    """
    settings, err = _imap_settings()
    if err:
        return err
    mid = str(message_id or "").strip()
    if not mid.isdigit():
        return "Error: message_id must be a numeric IMAP sequence id from search_inbox."

    target_folder = (folder or settings.imap_folder or "INBOX").strip() or "INBOX"
    try:
        client = _imap_connect(settings)
    except Exception as exc:
        return f"Error connecting to IMAP: {exc}"

    try:
        typ, _ = client.select(target_folder, readonly=True)
        if typ != "OK":
            return f"Error selecting folder '{target_folder}'."
        typ, fetched = client.fetch(mid.encode(), "(RFC822)")
        if typ != "OK" or not fetched or not fetched[0]:
            return f"Message not found: {mid}"
        from email import message_from_bytes

        msg = message_from_bytes(fetched[0][1])
        subject = _decode_header_value(msg.get("Subject"))
        sender = _decode_header_value(msg.get("From"))
        to = _decode_header_value(msg.get("To"))
        date = _decode_header_value(msg.get("Date"))
        body = _extract_body(msg)
        from security.sanitizer import sanitize_external_content

        safe_body = sanitize_external_content(body, source="email", max_chars=4000)
        return (
            f"id: {mid}\n"
            f"folder: {target_folder}\n"
            f"from: {sender}\n"
            f"to: {to}\n"
            f"date: {date}\n"
            f"subject: {subject}\n"
            f"body:\n{safe_body}"
        )
    except Exception as exc:
        logger.warning("IMAP read failed: %s", exc)
        return f"Error reading email: {exc}"
    finally:
        try:
            client.logout()
        except Exception:
            pass
