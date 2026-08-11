from monitoring.status_store import (
    append_activity,
    read_status,
    recent_activity,
    set_ux_phase,
    write_status,
)
from monitoring.system_monitor import SystemMonitor
from monitoring.workflow_monitor import register_event_consumers
from core.event_bus import get_event_bus
from ui.dashboard import _mode_from_status, _status_message


def test_status_roundtrip(tmp_path, monkeypatch):
    import monitoring.status_store as store

    monkeypatch.setattr(store, "STATUS_FILE", tmp_path / "status.json")
    monkeypatch.setattr(store, "ACTIVITY_FILE", tmp_path / "activity.jsonl")

    write_status(voice="ready", ollama="ready")
    status = read_status()
    assert status["voice"] == "ready"
    assert status["ollama"] == "ready"

    append_activity("Opened Notepad", category="task")
    items = recent_activity(5)
    assert items
    assert items[0]["message"] == "Opened Notepad"


def test_ux_phase(tmp_path, monkeypatch):
    import monitoring.status_store as store

    monkeypatch.setattr(store, "STATUS_FILE", tmp_path / "status.json")
    set_ux_phase("Thinking...", "Transcribing speech", voice="thinking")
    status = read_status()
    assert status["ux_phase"] == "Thinking..."
    assert "Transcribing" in status["ux_detail"]
    assert status["voice"] == "thinking"


def test_system_monitor_snapshot():
    snap = SystemMonitor().snapshot()
    assert "cpu_percent" in snap
    assert "ram_percent" in snap


def test_event_consumers_write_activity(tmp_path, monkeypatch):
    import monitoring.status_store as store

    monkeypatch.setattr(store, "STATUS_FILE", tmp_path / "status.json")
    monkeypatch.setattr(store, "ACTIVITY_FILE", tmp_path / "activity.jsonl")

    register_event_consumers()
    get_event_bus().publish("TASK_COMPLETED", {"goal": "Open Notepad"})
    items = recent_activity(5)
    assert any("Open Notepad" in i["message"] for i in items)


def test_dashboard_mode_mapping():
    assert _mode_from_status({"paused": True}) == "idle"
    assert _mode_from_status({"listening": True, "voice": "listening"}) == "listening"
    assert _mode_from_status({"voice": "thinking", "ux_phase": "Thinking..."}) == "thinking"
    assert _mode_from_status({"voice": "speaking", "ux_phase": "Speaking..."}) == "speaking"
    assert "Athena" in _status_message("idle", {}) or "begin" in _status_message("idle", {})
    assert _status_message("listening", {"ux_phase": ""}) == "Listening…"
