from security.risk import RiskLevel, classify_risk, reset_risk_cache
from tools.communication.email import (
    draft_email,
    list_email_drafts,
    read_email_draft,
    search_email_drafts,
    send_email,
)
from tools.registry import get_registry, reset_registry
from permissions.permissions import requires_confirmation


def test_draft_and_list_email(tmp_path, monkeypatch):
    import tools.communication.email as email_mod

    monkeypatch.setattr(email_mod, "DRAFTS_DIR", tmp_path)
    result = draft_email(
        to="maryam@example.com",
        subject="Follow up",
        body="I'll follow up tomorrow.",
    )
    assert "draft_id:" in result
    assert "not sent" in result.lower()

    listed = list_email_drafts()
    assert "maryam@example.com" in listed
    assert "Follow up" in listed

    found = search_email_drafts("follow up")
    assert "Follow up" in found


def test_send_email_requires_smtp_config(tmp_path, monkeypatch):
    import tools.communication.email as email_mod
    from config.settings import get_settings

    monkeypatch.setattr(email_mod, "DRAFTS_DIR", tmp_path)
    drafted = draft_email("a@b.com", "Hi", "Body")
    draft_id = [
        line.split(":", 1)[1].strip()
        for line in drafted.splitlines()
        if line.startswith("draft_id:")
    ][0]

    get_settings.cache_clear()
    monkeypatch.setenv("SMTP_HOST", "")
    get_settings.cache_clear()
    result = send_email(draft_id=draft_id)
    assert "SMTP is not configured" in result


def test_send_email_is_high_risk_and_confirmed():
    reset_risk_cache()
    assert classify_risk("send_email") == RiskLevel.HIGH
    assert requires_confirmation("send_email") is True
    assert classify_risk("draft_email") == RiskLevel.MEDIUM


def test_registry_has_email_tools():
    reset_registry()
    registry = get_registry()
    for name in (
        "draft_email",
        "send_email",
        "list_email_drafts",
        "read_email_draft",
        "search_email_drafts",
        "search_inbox",
        "read_email",
    ):
        assert registry.has(name)


def test_search_inbox_requires_imap_config(monkeypatch):
    from config.settings import get_settings
    from tools.communication.email import search_inbox

    monkeypatch.setenv("IMAP_HOST", "")
    monkeypatch.setenv("SMTP_HOST", "")
    get_settings.cache_clear()
    result = search_inbox("test")
    assert "IMAP is not configured" in result
    get_settings.cache_clear()
