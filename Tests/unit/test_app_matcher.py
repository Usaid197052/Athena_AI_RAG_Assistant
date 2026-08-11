from tools.applications.discovery import normalize_name
from tools.applications.matcher import match_application


SAMPLE_REGISTRY = {
    "visual studio": {
        "display_name": "Microsoft Visual Studio",
        "aliases": ["vs", "visual studio", "devenv"],
        "launch_type": "executable",
        "target": r"C:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\devenv.exe",
        "process_names": ["devenv.exe"],
    },
    "google chrome": {
        "display_name": "Google Chrome",
        "aliases": ["chrome", "google chrome"],
        "launch_type": "executable",
        "target": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "process_names": ["chrome.exe"],
    },
    "chrome beta": {
        "display_name": "Chrome Beta",
        "aliases": ["chrome", "chrome beta"],
        "launch_type": "executable",
        "target": r"C:\Program Files\Google\Chrome Beta\Application\chrome.exe",
        "process_names": ["chrome.exe"],
    },
    "notepad": {
        "display_name": "Notepad",
        "aliases": ["notepad", "text editor"],
        "launch_type": "executable",
        "target": r"C:\Windows\System32\notepad.exe",
        "process_names": ["notepad.exe"],
    },
}


def test_normalize_name():
    assert normalize_name("  Visual Studio! ") == "visual studio"


def test_exact_and_alias_match():
    result = match_application("VS", SAMPLE_REGISTRY)
    assert result.status == "matched"
    assert result.entry["display_name"] == "Microsoft Visual Studio"


def test_notepad_match():
    result = match_application("Notepad", SAMPLE_REGISTRY)
    assert result.status == "matched"
    assert "notepad" in result.entry["target"].lower()


def test_ambiguous_chrome():
    result = match_application("Chrome", SAMPLE_REGISTRY)
    assert result.status == "ambiguous"
    assert len(result.matches) >= 2


def test_not_found():
    result = match_application("Definitely Missing App", SAMPLE_REGISTRY)
    assert result.status == "not_found"
