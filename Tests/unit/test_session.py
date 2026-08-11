from memory.session import get_session, note_tool_result, reset_session


def test_session_tracks_opened_app():
    reset_session()
    note_tool_result(
        "open_application",
        {"application_name": "Visual Studio"},
        "Visual Studio is open.",
    )
    session = get_session()
    assert session.current_application == "Visual Studio"
    assert session.last_tool == "open_application"
