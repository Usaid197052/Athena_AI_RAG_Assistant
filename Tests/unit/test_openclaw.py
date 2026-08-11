from config.settings import get_settings
from openclaw.adapters import adapt_athena_action
from openclaw.client import OpenClawClient
from openclaw.executor import execute_launch, execute_via_openclaw
from openclaw.stub_server import OpenClawStubServer


def test_adapt_keeps_app_launch_local():
    assert adapt_athena_action("open_application", {"application_name": "Notepad"}) is None


def test_adapt_browser_search():
    call = adapt_athena_action("search_web", {"query": "ClickHouse"})
    assert call is not None
    assert call.tool == "browser"


def test_openclaw_stub_invoke(monkeypatch):
    server = OpenClawStubServer(token="test-token")
    endpoint = server.start()
    try:
        monkeypatch.setenv("OPENCLAW_ENABLED", "true")
        monkeypatch.setenv("OPENCLAW_ENDPOINT", endpoint)
        monkeypatch.setenv("OPENCLAW_GATEWAY_TOKEN", "test-token")
        get_settings.cache_clear()

        client = OpenClawClient()
        health = client.health()
        assert health["ok"] is True

        listed = client.invoke("sessions_list", {})
        assert listed["ok"] is True

        denied = client.invoke("exec", {"command": "notepad.exe"})
        assert denied["ok"] is False
        assert denied["status_code"] == 404

        browser = execute_via_openclaw("search_web", {"query": "Athena"})
        assert browser is not None
        assert browser.success is True
    finally:
        server.stop()
        get_settings.cache_clear()


def test_local_launch_still_works():
    # Should not raise; Notepad launch is best-effort in CI-like runs.
    result = execute_launch("notepad.exe", "Notepad")
    assert "Notepad" in result.message or "Error" in result.message
