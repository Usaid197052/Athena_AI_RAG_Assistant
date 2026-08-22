import platform as _platform
import subprocess as _subprocess

# ── Nuclear: force CREATE_NO_WINDOW on EVERY subprocess call on Windows ───────
# This patches Popen itself, so no per-file flag is needed anywhere.
if _platform.system() == "Windows":
    _OrigPopen = _subprocess.Popen

    class _Popen(_OrigPopen):
        def __init__(self, args, **kw):
            kw["creationflags"] = kw.get("creationflags", 0) | _subprocess.CREATE_NO_WINDOW
            kw.pop("startupinfo", None)   # drop any stale/shared STARTUPINFO
            super().__init__(args, **kw)

    _subprocess.Popen = _Popen
# ─────────────────────────────────────────────────────────────────────────────

import asyncio
import hashlib
import multiprocessing
import os
import re
import threading
import time
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

# Windowed (noconsole) PyInstaller builds leave stdout/stderr as None.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8", errors="replace")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8", errors="replace")

import sounddevice as sd
from google import genai
from google.genai import types
from ui import AthenaUI
from memory.memory_manager import (
    load_memory, update_memory, format_memory_for_prompt,
    save_session_summary, peek_last_session, get_response_language,
    set_response_language, reset_response_language, is_session_language_key,
)
from memory.learner import (
    log_tool as learner_log_tool,
    log_correction as learner_log_correction,
    looks_like_correction,
    rollup as learner_rollup,
    apply_distill as learner_apply_distill,
)

from actions.file_processor import file_processor
from actions.dataframe_viewer import show_dataframe
from actions.flight_finder     import flight_finder
from actions.open_app          import open_app
from actions.weather_report    import weather_action
from actions.send_message      import send_message
from actions.whatsapp_control  import whatsapp_control
from actions.reminder          import reminder
from actions.computer_settings import computer_settings
from actions.screen_processor  import _capture_camera, _capture_screen
from actions.mt5_analysis      import mt5_analysis, capture_chart_snapshot, CHART_ANALYSIS_PROMPT
from actions.youtube_video     import youtube_video
from actions.desktop           import desktop_control
from actions.browser_control   import browser_control
from actions.file_controller   import file_controller
from actions.code_helper       import code_helper
from actions.dev_agent         import dev_agent
from actions.web_search        import web_search as web_search_action
from actions.computer_control  import computer_control
from actions.game_updater      import game_updater
from actions.event_monitor     import (
    ContinuousEventMonitor,
    manage_continuous_monitor,
    is_proactive_enabled,
    get_system_status as get_extended_system_status,
)
from actions.proactive         import ProactiveEngine
from actions.background_monitor import (
    add_monitor, remove_monitor, list_monitors, check_all as monitor_check_all,
)
from actions.web_search        import _news as _fetch_news_sync
from actions.shell_command     import shell_command
from actions.spotify_control   import spotify_control
from actions.explorer_navigate import explorer_navigate
from actions.whatsapp_watch    import (
    start_watcher as start_whatsapp_watcher,
    stop_watcher as stop_whatsapp_watcher,
    set_alert_callback as set_whatsapp_alert_callback,
    is_auto_reply_enabled as whatsapp_auto_reply_enabled,
)
from memory.config_manager     import get_brief_enabled, DEFAULT_ASSISTANT_NAME
from core.gemini_models import get_live_model, get_flash_model
from core.permissions import (
    evaluate_permission, remember_session_allow, get_confirm_timeout, RiskLevel,
    classify_user_permission_reply, tool_permission_key,
)
from core.logger import get_logger, log as athena_log, set_hud_sink, log_path


def classify_exit_intent(text: str) -> str | None:
    """Return 'shutdown', 'sleep', or None from a user utterance (any language / messy STT)."""
    raw = (text or "").strip().lower()
    if not raw:
        return None
    compact = re.sub(r"[\s'_]+", "", raw)
    cleaned = re.sub(r"\s+", " ", raw)

    # PC power — never treat as Athena quit
    if any(x in cleaned for x in (
        "the computer", "the pc", "the laptop", "my computer", "my pc", "the machine",
        "this computer", "this pc", "this laptop", "the desktop", "my laptop",
    )):
        return None
    if any(x in raw for x in ("पीसी", "पी सी", "कंप्यूटर", "کمپیوٹر", "పీసీ")):
        return None
    if re.search(r"\b(pc|computer|laptop|desktop)\b", cleaned):
        return None

    if any(p in compact for p in (
        "shutdownyourself", "shutyourselfdown", "shutyourselfoff",
        "quitathena", "exitatheena", "exitatheana", "exitathena",
        "quitjarvis", "exitjarvis", "killjarvis", "killathena",
        "shutdowncompletely", "closetheapp", "shutyourself",
        "athenashutdown", "youcanshutdown", "ucanshutdown", "canshutdown",
        "setyourselfdown",
    )):
        return "shutdown"

    if any(p in cleaned for p in (
        "shut down yourself", "shutdown yourself", "shut yourself down",
        "quit athena", "quit jarvis", "exit the app", "shut down completely",
        "turn yourself off", "kill yourself", "shut down", "shutdown",
    )):
        return "shutdown"

    if "that will be all" in cleaned and ("shut" in cleaned or "quit" in cleaned):
        return "shutdown"
    if re.search(r"shut\s*down", cleaned) or "shutdown" in compact:
        return "shutdown"
    if "शट" in raw and "डाउन" in raw:
        return "shutdown"
    if "షట్" in raw and "డౌన్" in raw:
        return "shutdown"
    return None


def classify_pc_power_intent(text: str) -> str | None:
    """Return 'shutdown' | 'restart' | 'sleep' when the user means the machine, else None."""
    raw = (text or "").strip()
    if not raw:
        return None
    cleaned = re.sub(r"\s+", " ", raw.lower())
    compact = re.sub(r"[\s'_]+", "", cleaned)

    pc = any(x in cleaned for x in (
        "the computer", "the pc", "the laptop", "my computer", "my pc", "the machine",
        "your computer", "this computer", "this pc", "this laptop", "the desktop",
        "my laptop", "my desktop", "the desktop",
    ))
    if not pc:
        pc = any(x in compact for x in (
            "thepc", "mypc", "thecomputer", "mycomputer", "thelaptop", "mylaptop",
            "themachine", "thedesktop", "thispc", "thiscomputer",
        ))
    if not pc:
        pc = any(x in raw for x in ("पीसी", "पी सी", "कंप्यूटर", "کمپیوٹر", "పీసీ"))
    if not pc:
        pc = bool(re.search(r"\b(pc|computer|laptop|desktop)\b", cleaned))
    if not pc:
        return None

    if (
        any(x in cleaned for x in ("restart", "reboot", "re start"))
        or any(x in compact for x in ("restart", "reboot", "स्टार्ट", "रीस्टार्ट", "रिस्टार्ट"))
    ):
        return "restart"
    if (
        re.search(r"shut\s*down", cleaned)
        or "shutdown" in compact
        or ("शट" in raw and "डाउन" in raw)
        or ("షట్" in raw and "డౌన్" in raw)
    ):
        return "shutdown"
    if re.search(r"\bsleep\b", cleaned) or "sleep" in compact or "स्लीप" in compact:
        return "sleep"
    return None


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024

def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are Athena, a professional AI assistant. "
            "Sound human: complete sentences, a natural reaction to what happened, not clipped. "
            "Always use the provided tools to complete tasks. "
            "Never simulate or guess results — always call the appropriate tool. "
            "Never call yourself Jarvis or JARVIS."
        )

_CTRL_RE = re.compile(r"<ctrl\d+>", re.IGNORECASE)

def _clean_transcript(text: str) -> str:    
    text = _CTRL_RE.sub("", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return text.strip()


def _pcm16_rms(data: bytes) -> float:
    """Cheap RMS of 16-bit PCM — used to kick a screen-share still as soon as the user talks."""
    n = len(data) // 2
    if n < 16:
        return 0.0
    acc = 0.0
    count = 0
    for i in range(0, n, 8):
        s = int.from_bytes(data[2 * i : 2 * i + 2], "little", signed=True)
        acc += s * s
        count += 1
    return (acc / count) ** 0.5 if count else 0.0

TOOL_DECLARATIONS = [
    {
        "name": "open_app",
        "description": (
            "Opens any application on the computer. "
            "Use this whenever the user asks to open, launch, or start any app, "
            "website, or program. Always call this tool — never just say you opened it."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Exact name of the application (e.g. 'WhatsApp', 'Chrome', 'Spotify')"
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "web_search",
        "description": (
            "Searches the web. Use for ANY question about current facts, events, prices, "
            "or topics — always prefer this over guessing. "
            "Modes: 'search' (default), 'news' (latest headlines on a topic), "
            "'research' (deep comprehensive answer), 'price' (product cost lookup), "
            "'compare' (side-by-side comparison of items)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query":  {"type": "STRING", "description": "Search query or topic"},
                "mode":   {"type": "STRING", "description": "search | news | research | price | compare"},
                "items":  {"type": "ARRAY",  "items": {"type": "STRING"}, "description": "Items to compare (compare mode)"},
                "aspect": {"type": "STRING", "description": "Comparison aspect: price | specs | reviews | features"},
            },
            "required": ["query"]
        }
    },
    {
        "name": "mt5_analysis",
        "description": (
            "Read-only MetaTrader 5 analysis. Never places orders. "
            "When the user asks buy or sell, call ta or analyze and the result includes BIAS BUY|SELL|WAIT — "
            "you MUST speak that bias; do not refuse as 'I cannot give trading advice'. "
            "quote = bid/ask/spread. ta = indicators plus BIAS. analyze = ta plus calendar. "
            "fa = calendar plus short news. status = terminal connected. "
            "snapshot = ONE still of the MT5 chart window. NEVER share_screen for trading or charts. "
            "Prefer quote/ta/analyze when they name a pair without asking to look."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "status | quote | ta | analyze | fa | snapshot (default: analyze)",
                },
                "symbol": {
                    "type": "STRING",
                    "description": "MT5 symbol e.g. EURUSD, XAUUSD, GBPJPY, US30",
                },
                "timeframe": {
                    "type": "STRING",
                    "description": "M1 | M5 | M15 | M30 | H1 | H4 | D1 | W1 (default H1)",
                },
                "fundamentals": {
                    "type": "BOOLEAN",
                    "description": "If true with analyze, also fetch a short news pass",
                },
                "text": {
                    "type": "STRING",
                    "description": "User question about the chart (snapshot only)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "system_status",
        "description": (
            "Returns real-time system metrics: CPU usage, RAM, GPU load, CPU temperature, "
            "uptime, and process count. Use when the user asks about computer performance, "
            "temperature, memory, or resource usage. "
            "Set detail=true to include top processes by RAM."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "detail": {"type": "BOOLEAN", "description": "Include top processes by memory (default false)"},
                "top_n":  {"type": "INTEGER", "description": "How many top processes when detail=true (default 8)"},
            },
        }
    },
    {
        "name": "weather_report",
        "description": "Gives the weather report to user",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "City name"}
            },
            "required": ["city"]
        }
    },
    {
        "name": "whatsapp_control",
        "description": (
            "WhatsApp via linked Baileys bridge (not Desktop GUI). "
            "ALWAYS use this for WhatsApp (not send_message). "
            "Names in results and alerts are the user's Contacts folder names, "
            "not WhatsApp usernames. "
            "action=compose with contact AND message — drafts a text signed "
            "'Composed by Athena' and does NOT send. Pass the spoken saved name "
            "as contact (Contacts/ VCF/CSV), then WhatsApp. contact can also be "
            "a group name or a phone with country code. "
            "To send a file/photo: compose with path (or media=screenshot). "
            "To send a voice note: compose with voice=true and message=spoken text "
            "(or action=voice_note). After user confirms, action=send. "
            "action=read with contact (optional limit) returns a transcript — "
            "summarize in your spoken reply. action=unread lists unread chats. "
            "action=abort clears draft. action=link opens WhatsApp Setup. "
            "auto_reply_on / auto_reply_off / auto_reply_status for DM auto-replies "
            "(never groups). auto_reply_clear_cooldown resets per-chat cooldown. "
            "Read/unread do not send. Do not claim sent unless the tool result says Sent."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":  {"type": "STRING", "description": "compose | send | abort | read | unread | voice_note | link | auto_reply_on | auto_reply_off | auto_reply_status | auto_reply | auto_reply_clear_cooldown"},
                "contact": {"type": "STRING", "description": "Saved contact name from Contacts/, group name, or phone number with country code"},
                "message": {"type": "STRING", "description": "Message body for compose, or spoken text for a voice note"},
                "receiver": {"type": "STRING", "description": "Alias for contact"},
                "message_text": {"type": "STRING", "description": "Alias for message"},
                "path": {"type": "STRING", "description": "Local file path to send as photo/video/document"},
                "caption": {"type": "STRING", "description": "Optional caption for media"},
                "media": {"type": "STRING", "description": "screenshot to capture the screen and send it"},
                "voice": {"type": "STRING", "description": "true to compose a TTS voice note from message"},
                "limit": {"type": "STRING", "description": "Max messages for action=read (default 15, max 40)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "send_message",
        "description": (
            "Compose/send on Gmail, Telegram, etc. — NOT WhatsApp (use whatsapp_control). "
            "action=compose with receiver + message_text, then action=send after confirm. "
            "Gmail uses the Gmail API (OAuth); if AUTH_REQUIRED, user must run "
            "python actions/gmail_bridge_client.py --login after adding gmail client_id/secret. "
            "Do not claim sent unless the tool result says Sent."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":       {"type": "STRING", "description": "compose (default) | send | abort"},
                "receiver":     {"type": "STRING", "description": "Recipient email (Gmail) or name"},
                "message_text": {"type": "STRING", "description": "Message body"},
                "platform":     {"type": "STRING", "description": "gmail | telegram | discord | etc. (not whatsapp)"},
                "subject":      {"type": "STRING", "description": "Email subject (Gmail)"},
            },
            "required": ["platform"]
        }
    },
    {
        "name": "reminder",
        "description": "Sets a timed reminder using Task Scheduler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "date":    {"type": "STRING", "description": "Date in YYYY-MM-DD format"},
                "time":    {"type": "STRING", "description": "Time in HH:MM format (24h)"},
                "message": {"type": "STRING", "description": "Reminder message text"}
            },
            "required": ["date", "time", "message"]
        }
    },
    {
        "name": "youtube_video",
        "description": (
            "Controls YouTube. Use for: playing videos, summarizing a video's content, "
            "getting video info, or showing trending videos."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "play | summarize | get_info | trending (default: play)"},
                "query":  {"type": "STRING", "description": "Search query for play action"},
                "save":   {"type": "BOOLEAN", "description": "Save summary to Notepad (summarize only)"},
                "region": {"type": "STRING", "description": "Country code for trending e.g. TR, US"},
                "url":    {"type": "STRING", "description": "Video URL for get_info action"},
            },
            "required": []
        }
    },
    {
        "name": "screen_process",
        "description": (
            "Captures the screen or webcam image and lets you analyze it. "
            "MUST be called when user asks what is on screen, what you see, "
            "look at camera, analyze my screen, etc. "
            "You have NO visual ability without this tool unless screen sharing is already on. "
            "After the image is captured it is sent directly to you — describe what you see and answer the user's question. "
            "When using camera: the live view stays open until user says close it or calls close_camera."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {"type": "STRING", "description": "'screen' to capture display, 'camera' for webcam. Default: 'screen'"},
                "text":  {"type": "STRING", "description": "The question or instruction about the captured image"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "share_screen",
        "description": (
            "Start or stop live screen sharing (pictures only, no computer audio). "
            "Call start when the user says share my screen / show my screen continuously. "
            "Call stop when they say stop sharing. "
            "While sharing, live stills of the display are sent as the user talks — "
            "you already see the current screen; do not call screen_process for every question. "
            "Answer from the latest still, not an earlier window. "
            "Default is off. Camera is a different tool (screen_process angle=camera). "
            "Do NOT use this for MetaTrader, charts, graphs, or trading — use mt5_analysis action=snapshot."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "start | stop | status (default: start)"
                }
            },
            "required": []
        }
    },
    {
        "name": "close_camera",
        "description": (
            "Closes the live camera view shown on screen. "
            "Call when user says: close camera, stop camera, turn off camera, "
            "kamerayı kapat, kapat, creepy, etc."
        ),
        "parameters": {"type": "OBJECT", "properties": {}, "required": []}
    },
    {
        "name": "computer_settings",
        "description": (
            "Controls the computer: volume, brightness, window management, keyboard shortcuts, "
            "typing text on screen, closing apps, fullscreen, dark mode, WiFi, restart, shutdown, sleep, "
            "close_application by name, scrolling, tab management, zoom, screenshots, lock screen, "
            "refresh/reload page. Use for ANY single computer control command. "
            "Volume: action=volume_set with value 0-100. "
            "'turn volume to max'/max → value=100; 'turn volume to mid'/mid → value=50; "
            "'turn volume to low'/low → value=15. Do not use volume_up/volume_down for these. "
            "Call immediately for PC shutdown/restart/sleep — do not ask first; the overlay confirms."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "The action to perform (e.g. volume_set, volume_up, sleep, close_application, shutdown)"},
                "description": {"type": "STRING", "description": "Natural language description of what to do"},
                "value":       {"type": "STRING", "description": "Optional value: volume level (0-100, or max/mid/low), text to type, app name for close_application, etc."},
                "app_name":    {"type": "STRING", "description": "Application name for close_application"},
                "name":        {"type": "STRING", "description": "Alias for app_name"},
            },
            "required": []
        }
    },
    {
        "name": "browser_control",
        "description": (
            "Controls any web browser. Use for: opening websites, searching the web, "
            "clicking elements, filling forms, scrolling, screenshots, navigation, any web-based task. "
            "Simple open/search requests launch the user's own browser normally (their real profile "
            "and logged-in accounts); interactive actions (click, type, fill_form...) attach an "
            "automation browser. "
            "Always pass the 'browser' parameter when the user specifies a browser (e.g. 'open in Edge', "
            "'use Firefox', 'open Chrome'). Multiple browsers can run simultaneously."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "go_to | search | click | type | scroll | fill_form | smart_click | smart_type | get_text | get_url | press | new_tab | close_tab | screenshot | back | forward | reload | switch | list_browsers | close | close_all"},
                "browser":     {"type": "STRING", "description": "Target browser: chrome | edge | firefox | opera | operagx | brave | vivaldi | safari. Omit to use the currently active browser."},
                "url":         {"type": "STRING", "description": "URL for go_to / new_tab action"},
                "query":       {"type": "STRING", "description": "Search query for search action"},
                "engine":      {"type": "STRING", "description": "Search engine: google | bing | duckduckgo | yandex (default: google)"},
                "selector":    {"type": "STRING", "description": "CSS selector for click/type"},
                "text":        {"type": "STRING", "description": "Text to click or type"},
                "description": {"type": "STRING", "description": "Element description for smart_click/smart_type"},
                "direction":   {"type": "STRING", "description": "up | down for scroll"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount in pixels (default: 500)"},
                "key":         {"type": "STRING", "description": "Key name for press action (e.g. Enter, Escape, F5)"},
                "path":        {"type": "STRING", "description": "Save path for screenshot"},
                "incognito":   {"type": "BOOLEAN", "description": "Open in private/incognito mode"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "file_controller",
        "description": (
            "Manages files and folders on any drive (including D:): list, open, create, delete, "
            "move, copy, paste, rename, read, write, find, disk usage. "
            "Copy with destination = drive letter OR volume label (e.g. 'Project Data', 'DATA'). "
            "Copy WITHOUT destination puts the file on the clipboard; then action=paste with "
            "destination, or paste with no destination to Ctrl+V into the focused Explorer window. "
            "Use action=open with path='D:' or 'D:\\\\' to open a drive in Explorer. "
            "Prefer this for known paths; use explorer_navigate to browse folders by looking at the screen."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "list | open | create_file | create_folder | delete | move | copy | paste | rename | read | write | find | largest | disk_usage | organize_desktop | info"},
                "path":        {"type": "STRING", "description": "File/folder path or shortcut: desktop, downloads, documents, home, D:, D drive, volume label (Project Data), etc."},
                "destination": {"type": "STRING", "description": "Destination for move/copy/paste: path, drive letter (E:), or volume label (Project Data). Omit on copy to use clipboard."},
                "new_name":    {"type": "STRING", "description": "New name for rename"},
                "content":     {"type": "STRING", "description": "Content for create_file/write"},
                "name":        {"type": "STRING", "description": "File name to search for or open"},
                "extension":   {"type": "STRING", "description": "File extension to search (e.g. .pdf)"},
                "count":       {"type": "INTEGER", "description": "Number of results for largest"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "shell_command",
        "description": (
            "Runs a CMD or PowerShell command on the computer. "
            "Call immediately — do not ask first; the overlay confirms. "
            "Set as_admin=true for commands that need Administrator "
            "(bcdedit, DISM, firewall, services). Windows will show a UAC prompt. "
            "Use for system tasks that other tools cannot do."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "command": {"type": "STRING", "description": "The command to run"},
                "shell":   {"type": "STRING", "description": "cmd | powershell (default: cmd)"},
                "timeout": {"type": "INTEGER", "description": "Timeout in seconds (default 30, max 120)"},
                "as_admin": {
                    "type": "BOOLEAN",
                    "description": "If true, run elevated (Windows UAC). Also auto-set for bcdedit/DISM/netsh firewall/etc.",
                },
            },
            "required": ["command"]
        }
    },
    {
        "name": "spotify_control",
        "description": (
            "Controls Spotify Desktop via Web API (Premium for playback). "
            "ONE call per request. action=play with query for a song, playlist name, or liked songs; "
            "empty query resumes. Optional shuffle/repeat on the SAME play call "
            "(e.g. shuffle liked songs → action=play query='liked songs' shuffle=on). "
            "pause/next/previous for transport. Standalone shuffle/repeat with state=on|off|toggle. "
            "Only report success if the tool result confirms track/playlist/state."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "play | pause | next | previous | shuffle | repeat",
                },
                "query": {
                    "type": "STRING",
                    "description": (
                        "For play: song/artist, playlist name, or liked songs. "
                        "Empty = resume current playback."
                    ),
                },
                "shuffle": {
                    "type": "STRING",
                    "description": "Optional on play: on | off. Or use action=shuffle with state.",
                },
                "repeat": {
                    "type": "STRING",
                    "description": "Optional on play: on | off | track. Or use action=repeat with state.",
                },
                "state": {
                    "type": "STRING",
                    "description": "For action=shuffle or repeat: on | off | toggle (repeat also: track)",
                },
            },
            "required": ["action"]
        }
    },
    {
        "name": "explorer_navigate",
        "description": (
            "Navigates File Explorer by reading the screen: open Explorer, list visible items, "
            "double-click a folder by name, go up, close window, expand/collapse tree. "
            "Use when the user wants to browse folders visually. One vision step per call — "
            "chain calls for multi-level paths. Prefer file_controller when the full path is known."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "open_explorer | look | open_folder | go_up | close_folder | close_window | expand | collapse | focus"},
                "path":   {"type": "STRING", "description": "Optional path for open_explorer (e.g. D:)"},
                "name":   {"type": "STRING", "description": "Folder/file name for open_folder / expand / collapse"},
                "folder": {"type": "STRING", "description": "Alias for name"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "desktop_control",
        "description": "Controls the desktop: wallpaper, organize, clean, list, stats.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "wallpaper | wallpaper_url | organize | clean | list | stats | task"},
                "path":   {"type": "STRING", "description": "Image path for wallpaper"},
                "url":    {"type": "STRING", "description": "Image URL for wallpaper_url"},
                "mode":   {"type": "STRING", "description": "by_type or by_date for organize"},
                "task":   {"type": "STRING", "description": "Natural language desktop task"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "code_helper",
        "description": (
            "Writes, edits, shows, explains, runs, or builds code. "
            "Generated Python/SQL/etc. is shown in the on-screen content panel "
            "(each write replaces the previous panel). "
            "action=show with file_path displays an existing file in the panel — "
            "do not regenerate. "
            "action=run may pass inline code (no file_path) to execute a snippet. "
            "To save the last generated snippet, pass output_path only (or a save description) "
            "— do not regenerate. "
            "Only pass output_path when the user asked to save a file."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "write | edit | show | explain | run | build | auto (default: auto)"},
                "description": {"type": "STRING", "description": "What the code should do or what change to make"},
                "language":    {"type": "STRING", "description": "Programming language (default: python)"},
                "output_path": {"type": "STRING", "description": "Where to save the file. Alone = save last generated snippet."},
                "file_path":   {"type": "STRING", "description": "Path to existing file for show/edit/explain/run/build"},
                "code":        {"type": "STRING", "description": "Raw code string for explain, show, or run (inline execute)"},
                "args":        {"type": "STRING", "description": "CLI arguments for run/build"},
                "timeout":     {"type": "INTEGER", "description": "Execution timeout in seconds (default: 30)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "dev_agent",
        "description": "Builds complete multi-file projects from scratch: plans, writes files, installs deps, opens VSCode, runs and fixes errors.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "description":  {"type": "STRING", "description": "What the project should do"},
                "language":     {"type": "STRING", "description": "Programming language (default: python)"},
                "project_name": {"type": "STRING", "description": "Optional project folder name"},
                "timeout":      {"type": "INTEGER", "description": "Run timeout in seconds (default: 30)"},
            },
            "required": ["description"]
        }
    },
    {
        "name": "computer_control",
        "description": "Direct computer control: type, click, hotkeys, scroll, move mouse, screenshots, find elements on screen.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "type | smart_type | click | double_click | right_click | hotkey | press | scroll | move | copy | paste | screenshot | wait | clear_field | focus_window | screen_find | screen_click | random_data | user_data"},
                "text":        {"type": "STRING", "description": "Text to type or paste"},
                "x":           {"type": "INTEGER", "description": "X coordinate"},
                "y":           {"type": "INTEGER", "description": "Y coordinate"},
                "keys":        {"type": "STRING", "description": "Key combination e.g. 'ctrl+c'"},
                "key":         {"type": "STRING", "description": "Single key e.g. 'enter'"},
                "direction":   {"type": "STRING", "description": "up | down | left | right"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount (default: 3)"},
                "seconds":     {"type": "NUMBER",  "description": "Seconds to wait"},
                "title":       {"type": "STRING",  "description": "Window title for focus_window"},
                "description": {"type": "STRING",  "description": "Element description for screen_find/screen_click"},
                "type":        {"type": "STRING",  "description": "Data type for random_data"},
                "field":       {"type": "STRING",  "description": "Field for user_data: name|email|city"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
                "path":        {"type": "STRING",  "description": "Save path for screenshot"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "game_updater",
        "description": (
            "THE ONLY tool for ANY Steam or Epic Games request. "
            "Use for: installing, downloading, updating games, listing installed games, "
            "checking download status, scheduling updates. "
            "ALWAYS call directly for any Steam/Epic/game request. "
            "NEVER use browser_control or web_search for Steam/Epic."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING",  "description": "update | install | list | download_status | schedule | cancel_schedule | schedule_status (default: update)"},
                "platform":  {"type": "STRING",  "description": "steam | epic | both (default: both)"},
                "game_name": {"type": "STRING",  "description": "Game name (partial match supported)"},
                "app_id":    {"type": "STRING",  "description": "Steam AppID for install (optional)"},
                "hour":      {"type": "INTEGER", "description": "Hour for scheduled update 0-23 (default: 3)"},
                "minute":    {"type": "INTEGER", "description": "Minute for scheduled update 0-59 (default: 0)"},
                "shutdown_when_done": {"type": "BOOLEAN", "description": "Shut down PC when download finishes"},
            },
            "required": []
        }
    },
    {
        "name": "flight_finder",
        "description": "Searches Google Flights and speaks the best options.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "origin":      {"type": "STRING",  "description": "Departure city or airport code"},
                "destination": {"type": "STRING",  "description": "Arrival city or airport code"},
                "date":        {"type": "STRING",  "description": "Departure date (any format)"},
                "return_date": {"type": "STRING",  "description": "Return date for round trips"},
                "passengers":  {"type": "INTEGER", "description": "Number of passengers (default: 1)"},
                "cabin":       {"type": "STRING",  "description": "economy | premium | business | first"},
                "save":        {"type": "BOOLEAN", "description": "Save results to Notepad"},
            },
            "required": ["origin", "destination", "date"]
        }
    },
    {
        "name": "manage_monitor",
        "description": (
            "Add, remove, or list background NEWS monitoring topics. "
            "Athena checks these topics once a day and alerts when there is a new development. "
            "Use 'add' when the user says 'monitor X', 'track X', 'follow X'. "
            "Use 'remove' when the user says 'stop monitoring X'. "
            "Use 'list' when the user asks what news topics are monitored. "
            "For continuous PC monitoring / proactive check-ins / process watches, "
            "use manage_continuous_monitor instead."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type":        "STRING",
                    "description": "add | remove | list",
                },
                "topic": {
                    "type":        "STRING",
                    "description": "Topic to monitor or stop monitoring (e.g. 'space exploration', 'AI news')",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "manage_continuous_monitor",
        "description": (
            "Control Athena's continuous PC monitoring, proactive notifications, and habit learning. "
            "Always-on by default: CPU/RAM/temp/GPU, battery, disk space, network, idle, "
            "optional process watches, and local habit learning (app routines / tool lessons). "
            "action=status | enable | disable | watch | unwatch | enable_proactive | disable_proactive | "
            "learning_on | learning_off | learning_status | forget_learned. "
            "watch/unwatch need process name (e.g. Discord.exe). "
            "Use when user asks to watch the PC, whether learning is on, stop learning, "
            "forget learned habits, or watch an app starting."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": (
                        "status | enable | disable | watch | unwatch | enable_proactive | "
                        "disable_proactive | learning_on | learning_off | learning_status | forget_learned"
                    ),
                },
                "process": {
                    "type": "STRING",
                    "description": "Process name for watch/unwatch (e.g. chrome.exe)",
                },
                "target": {
                    "type": "STRING",
                    "description": "Optional: 'monitor' or 'proactive' when enabling/disabling",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "sleep_assistant",
        "description": (
            "Puts Athena to sleep: hides the HUD window and keeps the process "
            "running in the system tray. Call this when the user says "
            "'go to sleep', 'hide yourself', 'close the window', "
            "'that's all for now', or wants the dashboard/HUD hidden — "
            "in ANY language. "
            "Do NOT use this to shut down completely or to put the PC to sleep."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
        "name": "shutdown_athena",
        "description": (
            "Fully quits Athena and exits the process. "
            "Call ONLY when the user explicitly wants to shut down completely, "
            "quit Athena, or end the program forever — e.g. 'quit Athena', "
            "'shut down completely', 'exit the app'. "
            "Do NOT call for 'go to sleep' or hiding the window "
            "(use sleep_assistant instead). "
            "The user can say this in ANY language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
    "name": "file_processor",
    "description": (
        "Processes any file that the user has uploaded or dropped onto the interface. "
        "Use this when the user refers to an uploaded file and wants an action on it. "
        "Supports: images (describe/ocr/resize/compress/convert), "
        "PDFs (summarize/extract_text/to_word), "
        "Word docs & text files (summarize/fix/reformat/translate), "
        "CSV/Excel (analyze/stats/filter/sort/convert), "
        "JSON/XML (validate/format/analyze), "
        "code files (explain/review/fix/optimize/run/document/test), "
        "audio (transcribe/trim/convert/info), "
        "video (trim/extract_audio/extract_frame/compress/transcribe/info), "
        "archives (list/extract), "
        "presentations (summarize/extract_text). "
        "ALWAYS call this tool when a file has been uploaded and the user gives a command about it. "
        "If the user's command is ambiguous, pick the most logical action for that file type."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "file_path": {
                "type": "STRING",
                "description": "Full path to the uploaded file. Leave empty to use the currently uploaded file."
            },
            "action": {
                "type": "STRING",
                "description": (
                    "What to do with the file. Examples by type:\n"
                    "image: describe | ocr | resize | compress | convert | info\n"
                    "pdf: summarize | extract_text | to_word | info\n"
                    "docx/txt: summarize | fix | reformat | translate_hint | word_count | to_bullet\n"
                    "csv/excel: analyze | stats | filter | sort | convert | info\n"
                    "json: validate | format | analyze | to_csv\n"
                    "code: explain | review | fix | optimize | run | document | test\n"
                    "audio: transcribe | trim | convert | info\n"
                    "video: trim | extract_audio | extract_frame | compress | transcribe | info | convert\n"
                    "archive: list | extract\n"
                    "pptx: summarize | extract_text | analyze"
                )
            },
            "instruction": {
                "type": "STRING",
                "description": "Free-form instruction if action doesn't cover it. E.g. 'translate this to Turkish', 'find all email addresses'"
            },
            "format": {
                "type": "STRING",
                "description": "Target format for conversion. E.g. 'mp3', 'pdf', 'csv', 'png'"
            },
            "width":     {"type": "INTEGER", "description": "Target width for image resize"},
            "height":    {"type": "INTEGER", "description": "Target height for image resize"},
            "scale":     {"type": "NUMBER",  "description": "Scale factor for image resize (e.g. 0.5)"},
            "quality":   {"type": "INTEGER", "description": "Quality 1-100 for image/video compress"},
            "start":     {"type": "STRING",  "description": "Start time for trim: seconds or HH:MM:SS"},
            "end":       {"type": "STRING",  "description": "End time for trim: seconds or HH:MM:SS"},
            "timestamp": {"type": "STRING",  "description": "Timestamp for video frame extraction HH:MM:SS"},
            "column":    {"type": "STRING",  "description": "Column name for CSV filter/sort"},
            "value":     {"type": "STRING",  "description": "Filter value for CSV filter"},
            "condition": {"type": "STRING",  "description": "Filter condition: equals|contains|gt|lt"},
            "ascending": {"type": "BOOLEAN", "description": "Sort order for CSV sort (default: true)"},
            "save":      {"type": "BOOLEAN", "description": "Save result to file (default: true)"},
            "destination": {"type": "STRING", "description": "Output folder for archive extract"},
        },
        "required": []
    }
},
    {
        "name": "show_dataframe",
        "description": (
            "Load a CSV, TSV, JSON, JSONL, Parquet, or Excel file with pandas + numpy "
            "and render a structured table in the HUD content panel. "
            "Use this whenever the user wants to SEE, VIEW, or PREVIEW a dataset, "
            "dataframe, table, or a dropped spreadsheet — including 'show last N rows', "
            "'show first 20 rows', 'sort by column X', or 'show only columns A, B'. "
            "Do NOT use code_helper run or file_processor analyze to view tabular data. "
            "Leave file_path empty to use the currently uploaded file."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "file_path": {
                    "type": "STRING",
                    "description": "Full path to the file. Leave empty to use the current HUD upload."
                },
                "max_rows": {
                    "type": "INTEGER",
                    "description": "Rows to show. Omit to show all rows (up to 5000). Scroll vertically in the panel."
                },
                "max_cols": {
                    "type": "INTEGER",
                    "description": "Columns to show. Omit to show all columns (up to 80). Scroll horizontally in the panel."
                },
                "all": {
                    "type": "BOOLEAN",
                    "description": "If true, show all rows and columns (within panel limits)."
                },
                "offset": {
                    "type": "INTEGER",
                    "description": "Starting row index (0-based). E.g. offset=200 to start from row 200."
                },
                "tail": {
                    "type": "BOOLEAN",
                    "description": "If true, show the LAST max_rows rows instead of the first. Use for 'show last N rows'."
                },
                "columns": {
                    "type": "STRING",
                    "description": "Comma-separated column names to include. Empty = all columns."
                },
                "sort_by": {
                    "type": "STRING",
                    "description": "Column name to sort by before displaying."
                },
                "sort_asc": {
                    "type": "BOOLEAN",
                    "description": "Sort ascending (default true). Set false for descending."
                },
            },
        }
    },
    {
        "name": "save_memory",
        "description": (
            "Save an important personal fact about the user to long-term memory. "
            "Call this silently whenever the user reveals something worth remembering: "
            "name, age, city, job, preferences, hobbies, relationships, projects, future plans, "
            "or explicit habits/routines (category=learned). "
            "Do NOT call for: weather, reminders, searches, or one-time commands. "
            "Do NOT announce that you are saving — just call it silently. "
            "Values must be in English regardless of the conversation language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": (
                        "identity — name, age, birthday, city, job, language, nationality | "
                        "preferences — favorite food/color/music/film/game/sport, hobbies | "
                        "projects — active projects, goals, things being built | "
                        "relationships — friends, family, partner, colleagues | "
                        "wishes — future plans, things to buy, travel dreams | "
                        "notes — habits, schedule, anything else worth remembering | "
                        "learned — explicit routines the user states (work hours, primary apps)"
                    )
                },
                "key":   {"type": "STRING", "description": "Short snake_case key (e.g. name, favorite_food, sister_name)"},
                "value": {"type": "STRING", "description": "Concise value in English (e.g. Fatih, pizza, older sister)"},
            },
            "required": ["category", "key", "value"]
        }
    },
]

# --- Plugin system ---


class SleepRequested(Exception):
    """Raised inside the live TaskGroup to tear down Gemini when HUD sleeps."""


class AthenaLive:

    def __init__(self, ui: AthenaUI):
        self.ui             = ui
        self._asst_name     = DEFAULT_ASSISTANT_NAME   # updated each session from config
        self.session              = None
        self.audio_in_queue       = None
        self.out_queue            = None
        self._loop                = None
        self._is_speaking         = False
        self._speaking_lock       = threading.Lock()
        self._phone_active        = False   # True while phone mic PCM is arriving
        self._pending_vision       = None    # (img_bytes, mime_type, question, angle) to inject after tool response
        self._vision_cam_active    = False   # True if camera was opened for vision → auto-close after response
        self._vision_close_pending = False   # True after vision injected; next turn_complete closes camera
        self._vision_last_time     = 0.0     # monotonic time of last screen_process call (cooldown guard)
        self._vision_busy          = False   # True while a vision capture/inject cycle is in flight
        self._share_screen         = False   # user-consented screen share (stills while talking)
        self._share_last_hash      = ""
        self._share_lock           = threading.Lock()
        self._share_push_lock: asyncio.Lock | None = None
        self._share_last_sent      = 0.0
        self._share_turn_sent      = False
        self._share_mic_armed      = False
        self._share_inflight: asyncio.Task | None = None
        self._interrupted          = False   # True while draining audio after user interrupt
        # Voice/text permission: pending risky tool waiting for "go ahead" / "abort"
        self._pending_permission: dict | None = None
        # After user grants, next matching tool call may run once without re-asking
        self._voice_granted_key: str | None = None
        self._voice_granted_name: str | None = None  # tool name fallback match
        self._voice_granted_until: float = 0.0
        # Avoid Gemini re-calling a tool we already ran after a spoken grant
        self._completed_grants: dict[str, tuple[float, str]] = {}
        self._grant_in_progress: str | None = None
        self._grant_in_progress_name: str | None = None
        self._code_helper_lock: asyncio.Lock | None = None
        self._shutdown_started = False
        self._hold_mic = False          # True while waiting for farewell / sleep speech
        self._last_model_audio = 0.0    # monotonic time of last Gemini audio or transcript chunk
        reset_response_language()
        self.ui.on_text_command   = self._on_text_command
        self.ui.on_remote_clicked = self._make_remote_key
        self.ui.on_interrupt      = self.interrupt
        self.ui.on_sleep_requested = self.request_sleep
        self.ui.on_wake_requested  = self.request_wake
        self.ui.on_quit_requested  = self.request_quit
        self.ui.on_api_config_saved = self.request_reconnect
        # HUD sleep / wake-word standby
        self._hud_sleeping = False
        self._sleep_request: asyncio.Event | None = None
        self._wake_event: asyncio.Event | None = None
        self._reconnect_needed = False
        self._wake_listener = None
        self._pending_wake_greeting = False  # speak "I'm back" after reconnect from sleep
        # File logging + mirror HUD lines to logs/athena.log
        get_logger()
        set_hud_sink(None)  # HUD is source; we hook write_log below
        _orig_write = self.ui.write_log
        def _logged_write(text: str):
            _orig_write(text)
            try:
                athena_log(text, "info")
            except Exception:
                pass
        self.ui.write_log = _logged_write  # type: ignore[method-assign]
        athena_log(f"Athena logger ready → {log_path()}")
        try:
            from core.mt5_log import set_hud_sink as set_mt5_hud
            from actions.mt5_analysis import start_mt5_keepalive
            set_mt5_hud(self.ui.write_log)
            start_mt5_keepalive()
        except Exception as e:
            athena_log(f"MT5 keepalive: {e}", "warning")
        self._turn_done_event: asyncio.Event | None = None
        self._dashboard     = None
        self._briefing_sent    = False          # morning briefing fires once per process
        self._sys_monitor      = ContinuousEventMonitor()  # continuous hardware + events
        self._proactive        = ProactiveEngine()
        self._last_user_speech = time.monotonic()  # updated on every user utterance
        self._session_log: list[str] = []          # conversation turns for end-of-session summary
        self._whatsapp_alerts: list[str] = []
        self._whatsapp_alerts_lock = threading.Lock()

        def _wa_alert(msg: str):
            with self._whatsapp_alerts_lock:
                self._whatsapp_alerts.append(msg)
            try:
                self.ui.write_log(f"SYS: {msg[:120]}")
            except Exception:
                pass

        set_whatsapp_alert_callback(_wa_alert)
        if whatsapp_auto_reply_enabled():
            try:
                from actions.whatsapp_bridge_client import ensure_bridge
                ensure_bridge()
            except Exception as e:
                athena_log(f"WhatsApp bridge start: {e}")
            start_whatsapp_watcher()

    def request_sleep(self) -> None:
        """Hide HUD and pause Gemini; start wake-word after session ends."""
        if self._hud_sleeping:
            return
        self._hud_sleeping = True
        self._share_screen = False
        self._share_last_hash = ""
        try:
            self.ui.hide_to_tray()
        except Exception:
            pass
        self.ui.set_state("SLEEPING")
        if self._loop and self._sleep_request is not None:
            def _signal():
                if self._wake_event is not None:
                    self._wake_event.clear()
                self._sleep_request.set()
            self._loop.call_soon_threadsafe(_signal)

    def request_wake(self) -> None:
        """Show HUD and resume Gemini (stops local wake-word in run loop)."""
        was_sleeping = self._hud_sleeping
        self._hud_sleeping = False
        self._hold_mic = False
        try:
            self.ui.show_from_tray()
        except Exception:
            pass
        if was_sleeping:
            self._pending_wake_greeting = True
            self.ui.set_state("THINKING")
        if self._loop and self._wake_event is not None:
            self._loop.call_soon_threadsafe(self._wake_event.set)

    def request_quit(self) -> None:
        """Full process exit from tray Quit."""
        self.ui.write_log("SYS: Quit requested from tray.")
        try:
            self._stop_wake_listener()
        except Exception:
            pass
        import os as _os
        _os._exit(0)

    def _begin_shutdown(self) -> None:
        """Full process quit (from tool or spoken 'shut yourself down')."""
        if getattr(self, "_shutdown_started", False):
            return
        self._shutdown_started = True
        self._hold_mic = True
        self.ui.write_log("SYS: Shutdown requested.")

        async def _do_shutdown():
            try:
                await asyncio.wait_for(self._wait_for_farewell_speech(), timeout=2.0)
            except Exception:
                pass
            await asyncio.sleep(0.25)
            await self._save_session_summary()
            try:
                await asyncio.to_thread(learner_rollup)
            except Exception:
                pass
            try:
                self._stop_wake_listener()
            except Exception:
                pass
            try:
                athena_log("SYS: Shutdown complete.")
            except Exception:
                pass
            import os as _os
            _os._exit(0)

        if self._loop:
            self._loop.call_soon_threadsafe(lambda: asyncio.create_task(_do_shutdown()))
        else:
            asyncio.create_task(_do_shutdown())

    def request_reconnect(self) -> None:
        """Drop the Live session so the next loop iteration uses the new key/model."""
        self._reconnect_needed = True
        try:
            self.ui.write_log("SYS: Reconnecting with saved API key / voice model…")
            self.ui.set_state("THINKING")
        except Exception:
            pass
        if self._loop and self._sleep_request is not None:
            def _signal():
                if self._sleep_request is not None:
                    self._sleep_request.set()
            self._loop.call_soon_threadsafe(_signal)
        elif self._loop and self._wake_event is not None:
            # Sleeping / not in a session — wake so run() reconnects
            self._hud_sleeping = False
            self._loop.call_soon_threadsafe(self._wake_event.set)

    def _start_wake_listener(self) -> None:
        try:
            from core.wakeword import WakeWordListener
            if self._wake_listener is None:
                self._wake_listener = WakeWordListener()
            elif self._wake_listener.running:
                return
            name = self.ui.assistant_name or self._asst_name or DEFAULT_ASSISTANT_NAME
            self._wake_listener.start(
                assistant_name=name,
                on_wake=self.request_wake,
                log=self.ui.write_log,
            )
        except Exception as e:
            self.ui.write_log(f"ERR: Wake-word unavailable — {e}")
            self.ui.write_log("SYS: Use the tray icon to show Athena.")

    def _stop_wake_listener(self) -> None:
        wl = self._wake_listener
        if wl is not None:
            try:
                wl.stop()
            except Exception:
                pass

    @staticmethod
    def _is_sleep_exc(exc: BaseException) -> bool:
        if isinstance(exc, SleepRequested):
            return True
        # TaskGroup wraps task errors in ExceptionGroup (3.11+)
        try:
            if isinstance(exc, BaseExceptionGroup):
                return any(AthenaLive._is_sleep_exc(e) for e in exc.exceptions)
        except NameError:
            pass
        return "SLEEP_REQUESTED" in str(exc)

    async def _sleep_watcher(self):
        """Cancel the live TaskGroup when sleep is requested."""
        assert self._sleep_request is not None
        await self._sleep_request.wait()
        raise SleepRequested("SLEEP_REQUESTED")
    def _make_remote_key(self):
        """Called from Qt main thread when user presses Remote Control."""
        if self._dashboard is None:
            err = getattr(self, "_dashboard_error", "") or (
                "fastapi/uvicorn missing — pip install fastapi \"uvicorn[standard]\" cryptography"
            )
            self.ui.write_log(f"SYS: Dashboard unavailable — {err}")
            return None
        key    = ""
        url    = self._dashboard.get_url()
        manual = self._dashboard.get_manual_url()
        return url, key, url, manual

    def _on_text_command(self, text: str):
        if not self._loop:
            return
        # Intercept grant/deny while a risky tool is waiting
        if self._pending_permission:
            verdict = classify_user_permission_reply(text)
            if verdict:
                asyncio.run_coroutine_threadsafe(
                    self._resolve_voice_permission(verdict, text),
                    self._loop,
                )
                return
            athena_log(f"Permission pending; typed text not classified: {text!r}")
        else:
            exit_kind = classify_exit_intent(text)
            if exit_kind == "shutdown":
                self._begin_shutdown()
                return
            pc = classify_pc_power_intent(text)
            if pc:
                asyncio.run_coroutine_threadsafe(self._request_pc_power(pc), self._loop)
                return
        if not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self._send_text_with_share(text),
            self._loop,
        )

    async def _send_text_with_share(self, text: str) -> None:
        if not self.session:
            return
        if self._share_screen and not self._pending_permission:
            sent = await self._inject_share_frame(text)
            if sent:
                return
        await self.session.send_client_content(
            turns={"parts": [{"text": text}]},
            turn_complete=True,
        )

    def _schedule_share_frame(self, reason: str, force: bool = False) -> None:
        if not self._share_screen or not self.session:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = self._loop
        if loop is None:
            return

        def _go(r=reason, f=force):
            self._share_inflight = asyncio.create_task(
                self._push_share_frame_realtime(r, f)
            )

        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            _go()
        else:
            try:
                loop.call_soon_threadsafe(_go)
            except Exception:
                pass

    async def _send_live_image(self, img_b: bytes, mime_t: str) -> None:
        await self.session.send_realtime_input(
            video={"data": img_b, "mime_type": mime_t or "image/jpeg"}
        )

    async def _push_share_frame_realtime(self, reason: str = "", force: bool = False) -> bool:
        """Push a JPEG into the Live stream so Gemini sees the screen before it answers."""
        if not self._share_screen or not self.session:
            return False
        if self._hud_sleeping or getattr(self, "_shutdown_started", False):
            return False
        now = time.monotonic()
        if not force and self._share_turn_sent and (now - self._share_last_sent) < 0.8:
            return False
        if force and self._share_turn_sent and (now - self._share_last_sent) < 0.4:
            return False
        lock = self._share_push_lock
        if lock is None:
            lock = asyncio.Lock()
            self._share_push_lock = lock
        async with lock:
            if not self._share_screen or not self.session:
                return False
            now = time.monotonic()
            if force and self._share_turn_sent and (now - self._share_last_sent) < 0.4:
                return False
            try:
                img_b, mime_t = await asyncio.to_thread(_capture_screen)
            except Exception as e:
                athena_log(f"Screen share capture failed: {e}", "warning")
                print(f"[Share] capture failed: {e}")
                return False
            digest = hashlib.md5(img_b).hexdigest()
            with self._share_lock:
                same = digest == self._share_last_hash
                if not same:
                    self._share_last_hash = digest
            if same and not force:
                return False
            try:
                await self._send_live_image(img_b, mime_t)
            except Exception as e:
                athena_log(f"Screen share inject failed: {e}", "warning")
                print(f"[Share] inject failed: {e}")
                return False
            self._share_turn_sent = True
            self._share_last_sent = time.monotonic()
            tag = reason or "live"
            athena_log(f"Screen share frame sent ({len(img_b):,} bytes, {tag})")
            print(f"[Share] {len(img_b):,} bytes ({tag})")
            return True

    async def _inject_share_frame(self, user_text: str) -> bool:
        """Typed-command path: send the current still and the text in one turn."""
        if not self._share_screen or not self.session:
            return False
        try:
            img_b, mime_t = await asyncio.to_thread(_capture_screen)
        except Exception as e:
            athena_log(f"Screen share capture failed: {e}", "warning")
            print(f"[Share] capture failed: {e}")
            return False
        digest = hashlib.md5(img_b).hexdigest()
        with self._share_lock:
            self._share_last_hash = digest
        import base64 as _b64
        b64 = _b64.b64encode(img_b).decode("ascii")
        note = (
            (user_text or "").strip()
            or "The user is talking. Use the attached current screen."
        )
        try:
            await self.session.send_client_content(
                turns={"parts": [
                    {"inline_data": {"mime_type": mime_t, "data": b64}},
                    {"text": (
                        "[SCREEN_SHARE] Current display (pictures only, no computer audio). "
                        f"{note} Answer using THIS image — not an earlier window."
                    )},
                ]},
                turn_complete=True,
            )
            self._share_turn_sent = True
            self._share_last_sent = time.monotonic()
            athena_log(f"Screen share frame sent ({len(img_b):,} bytes, typed)")
            print(f"[Share] {len(img_b):,} bytes (typed)")
            return True
        except Exception as e:
            athena_log(f"Screen share inject failed: {e}", "warning")
            print(f"[Share] inject failed: {e}")
            return False

    @staticmethod
    def _grant_fp(name: str, args: dict) -> str:
        return json.dumps({"name": name, "args": args}, sort_keys=True, default=str)

    def _arm_pending_permission(self, name: str, args: dict, decision) -> None:
        """Open the existing permission overlay (voice + phone) for a risky tool."""
        now = time.monotonic()
        key = tool_permission_key(name, args)
        self._pending_permission = {
            "name": name,
            "args": args,
            "summary": decision.summary,
            "risk": decision.risk_level.value,
            "key": key,
            "expires": now + get_confirm_timeout(),
            "asked": True,
        }
        self.ui.write_log(
            f"SYS: Awaiting permission — {decision.summary} "
            f"(say 'go ahead' / 'permission granted' or 'abort')"
        )
        athena_log(f"Permission REQUIRED — {decision.summary}")
        print(f"[ATHENA] ⏳ permission required: {decision.summary}")
        if self._dashboard:
            asyncio.create_task(self._dashboard.broadcast({
                "type": "permission",
                "risk": decision.risk_level.value,
                "summary": decision.summary,
                "reason": decision.reason,
                "timeout": get_confirm_timeout(),
            }))
        if not self.ui.muted:
            self.ui.set_state("LISTENING")

    async def _request_pc_power(self, action: str) -> None:
        """Spoken/typed PC shutdown/restart/sleep → same overlay as computer_settings."""
        args = {"action": action}
        key = tool_permission_key("computer_settings", args)
        now = time.monotonic()
        pending = self._pending_permission
        if pending and now < float(pending.get("expires", 0)) and pending.get("key") == key:
            return
        decision = evaluate_permission("computer_settings", args)
        if not decision.allowed:
            self.ui.write_log(f"SYS: {decision.reason or 'PC power denied.'}")
            return
        if not decision.requires_confirmation:
            result = await self._run_granted_tool("computer_settings", args)
            if self.session:
                await self.session.send_client_content(
                    turns={"parts": [{"text": (
                        "[SYSTEM] The PC power action already COMPLETED. "
                        f"Result: {result}. Tell the user this outcome. "
                        "Do NOT call the tool again."
                    )}]},
                    turn_complete=True,
                )
            return
        self._arm_pending_permission("computer_settings", args, decision)
        if self.session:
            await self.session.send_client_content(
                turns={"parts": [{"text": (
                    f"PERMISSION_REQUIRED ({decision.risk_level.value}): "
                    f"{decision.summary}. "
                    "Ask the user aloud ONCE, briefly, for permission "
                    "('say go ahead or abort'). Then STOP and wait. "
                    "Do NOT ask a second time. Do NOT call this tool again. "
                    "Do NOT perform or claim you did it yet. "
                    "The system will execute it when they grant permission "
                    "and will send you the COMPLETED result."
                )}]},
                turn_complete=True,
            )

    async def _run_granted_tool(self, name: str, args: dict) -> str:
        """Execute a pending tool after the user granted permission."""
        class _GrantedCall:
            def __init__(self):
                self.id = "granted-local"
                self.name = name
                self.args = args

        fr = await self._execute_tool(_GrantedCall())
        try:
            return str((fr.response or {}).get("result") or "Done.")
        except Exception:
            return "Done."

    async def _resolve_voice_permission(self, verdict: str, user_text: str = "") -> None:
        """Handle spoken/typed grant or abort for a pending risky tool."""
        pending = self._pending_permission
        if not pending:
            return
        if time.monotonic() > float(pending.get("expires", 0)):
            self._pending_permission = None
            self.ui.write_log("SYS: Permission request expired.")
            if self.session:
                await self.session.send_client_content(
                    turns={"parts": [{
                        "text": (
                            "[SYSTEM] The pending permission request expired. "
                            "Tell the user briefly and wait for a new request."
                        )
                    }]},
                    turn_complete=True,
                )
            return

        summary = pending.get("summary", pending.get("name", "action"))
        name = pending.get("name", "")
        args = pending.get("args") or {}
        key = pending.get("key") or tool_permission_key(name, args)

        if verdict == "deny":
            self._pending_permission = None
            self._voice_granted_key = None
            self._voice_granted_name = None
            if name in ("send_message", "whatsapp_control"):
                try:
                    if name == "whatsapp_control":
                        from actions.whatsapp_control import clear_pending
                        clear_pending()
                    else:
                        from actions.send_message import clear_pending_draft
                        clear_pending_draft()
                except Exception:
                    pass
            self.ui.write_log(f"SYS: Permission ABORTED — {summary}")
            athena_log(f"Permission ABORTED — {summary}")
            print(f"[ATHENA] 🚫 voice abort: {summary}")
            try:
                learner_log_tool(name, str(args.get("action", "")), "cancelled")
            except Exception:
                pass
            if self.session:
                await self.session.send_client_content(
                    turns={"parts": [{
                        "text": (
                            f"[SYSTEM] User ABORTED the pending action ({summary}). "
                            f"Acknowledge briefly. Do NOT call the tool. "
                            f"Any composed message draft was cleared and was not sent."
                        )
                    }]},
                    turn_complete=True,
                )
            return

        # grant — run the tool here. Do not wait for Gemini to call it again.
        self._pending_permission = None
        self._voice_granted_key = None
        self._voice_granted_name = None
        self._voice_granted_until = 0.0
        if str(pending.get("risk", "")).lower() == "medium":
            remember_session_allow(name, str(args.get("action", "")))
        self.ui.write_log(f"SYS: Permission GRANTED — {summary}")
        athena_log(f"Permission GRANTED — {summary} ({name}) utterance={user_text!r}")
        print(f"[ATHENA] ✅ voice grant: {summary}")
        fp = self._grant_fp(name, args)
        self._grant_in_progress = fp
        self._grant_in_progress_name = name
        try:
            result = await self._run_granted_tool(name, args)
        except Exception as e:
            result = f"Granted, but the action failed: {e}"
            traceback.print_exc()
        finally:
            self._grant_in_progress = None
            self._grant_in_progress_name = None
        self._completed_grants[fp] = (time.monotonic(), result)
        cutoff = time.monotonic() - 120.0
        self._completed_grants = {
            k: v for k, v in self._completed_grants.items() if v[0] >= cutoff
        }
        args_json = json.dumps(args, ensure_ascii=False)
        if self.session:
            await self.session.send_client_content(
                turns={"parts": [{
                    "text": (
                        f"[SYSTEM] Permission was granted and the action already COMPLETED. "
                        f"Tool '{name}' args={args_json}. Result: {result}. "
                        f"Tell the user this outcome. Do NOT ask for permission. "
                        f"Do NOT call the tool again."
                    )
                }]},
                turn_complete=True,
            )

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        if value:
            self.ui.set_state("SPEAKING")
        elif not self.ui.muted:
            self.ui.set_state("LISTENING")

    def _speech_busy(self) -> bool:
        q = self.audio_in_queue
        queued = False
        if q is not None:
            try:
                queued = not q.empty()
            except Exception:
                queued = False
        with self._speaking_lock:
            speaking = self._is_speaking
        # Cover gaps between Live audio chunks and the pause around a tool call
        recent = (time.monotonic() - self._last_model_audio) < 1.4
        return queued or speaking or recent

    async def _wait_for_farewell_speech(self, timeout: float = 36.0) -> None:
        """Wait until Gemini has finished the current spoken reply (or timeout)."""
        self._hold_mic = True
        if getattr(self.ui, "muted", False):
            await asyncio.sleep(0.25)
            return
        t0 = time.monotonic()
        start_deadline = t0 + 14.0
        end_deadline = t0 + timeout
        heard = False
        while time.monotonic() < start_deadline:
            if self._speech_busy():
                heard = True
                break
            await asyncio.sleep(0.05)
        if not heard:
            await asyncio.sleep(0.6)
            if not self._speech_busy():
                return
        # Require a sustained quiet stretch so a tool-call pause is not treated as done
        quiet_needed = 1.5
        quiet_start = None
        while time.monotonic() < end_deadline:
            if self._speech_busy():
                quiet_start = None
            else:
                if quiet_start is None:
                    quiet_start = time.monotonic()
                elif time.monotonic() - quiet_start >= quiet_needed:
                    await asyncio.sleep(0.4)
                    return
            await asyncio.sleep(0.05)

    def interrupt(self) -> None:
        """Stop Athena mid-speech: drain queued audio and open mic immediately."""
        if getattr(self, "_shutdown_started", False) or self._hold_mic:
            return
        self._interrupted = True
        q = self.audio_in_queue
        if q:
            drained = 0
            while True:
                try:
                    q.get_nowait()
                    drained += 1
                except Exception:
                    break
            if drained:
                print(f"[ATHENA] ✋ Interrupted — {drained} audio chunks discarded")
        self.set_speaking(False)
        if self._turn_done_event:
            self._turn_done_event.clear()
        self.ui.write_log("SYS: Interrupted — listening...")

    def speak(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.speak(f"Sir, {tool_name} encountered an error. {short}")

    def _build_config(self) -> types.LiveConnectConfig:
        from datetime import datetime

        # Load customization from config
        try:
            _cfg = json.loads(open(API_CONFIG_PATH, encoding="utf-8").read())
            self._asst_name = (_cfg.get("assistant_name") or DEFAULT_ASSISTANT_NAME).strip()
            _user_name = (_cfg.get("user_name") or "").strip()
        except Exception:
            self._asst_name = DEFAULT_ASSISTANT_NAME
            _user_name = ""

        memory     = load_memory()
        mem_str    = format_memory_for_prompt(memory)
        sys_prompt = _load_system_prompt()

        now      = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times for reminders.\n\n"
        )

        # Identity injection — overrides any hardcoded name in prompt.txt
        _addr = (f"ADDRESS: Always call the user '{_user_name}' and say \"sir\"."
                 if _user_name
                 else "ADDRESS: Always address the user as \"sir\".")
        identity_ctx = (
            f"[IDENTITY]\n"
            f"Your name is {self._asst_name}. You are a woman — speak and act as a female assistant. "
            f"Always refer to yourself as {self._asst_name}. "
            f"Never call yourself Jarvis, JARVIS, or J.A.R.V.I.S.\n"
            f"{_addr}\n"
            f"RESPONSE LANGUAGE: Default English. Currently speaking {get_response_language()}. "
            f"The user may speak any language — understand it, but do not mirror it. "
            f"Switch language only if they explicitly command it; silently save_memory "
            f"preferences/response_language with the English name of that language. "
            f"A new app start is always English.\n"
            f"SPEECH STYLE: Warm, human, and complete. React to what happened "
            f"(relief, surprise, satisfaction, concern) in a natural way. "
            f"Several full sentences — never clipped or absolute. Contractions are welcome. "
            f"No chatbot filler, no 'as an AI'.\n\n"
        )

        parts = [time_ctx, identity_ctx]
        if mem_str:
            parts.append(mem_str)
        parts.append(sys_prompt)

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            session_resumption=types.SessionResumptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Sulafat"
                    )
                )
            ),
        )

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})

        print(f"[ATHENA] 🔧 {name}  {args}")
        athena_log(f"TOOL {name} {args}")
        self.ui.set_state("THINKING")

        # ── Permission gate (voice/text: Athena asks, user says go ahead / abort) ─
        local_grant = getattr(fc, "id", "") == "granted-local"
        if name != "save_memory" and not local_grant:
            fp = self._grant_fp(name, args)
            now = time.monotonic()
            if self._grant_in_progress and (
                self._grant_in_progress == fp or name == self._grant_in_progress_name
            ):
                if not self.ui.muted:
                    self.ui.set_state("LISTENING")
                return types.FunctionResponse(
                    id=fc.id, name=name,
                    response={"result": (
                        "ALREADY_RUNNING: The user granted permission and this action "
                        "is executing now. Stay silent. Do NOT ask again. Do NOT call again."
                    )},
                )
            prev = self._completed_grants.get(fp)
            if prev and now - prev[0] < 90:
                if not self.ui.muted:
                    self.ui.set_state("LISTENING")
                return types.FunctionResponse(
                    id=fc.id, name=name,
                    response={"result": (
                        f"ALREADY_DONE: {prev[1]}. Tell the user this outcome. "
                        f"Do NOT ask for permission. Do NOT call the tool again."
                    )},
                )
            decision = evaluate_permission(name, args)
            if not decision.allowed:
                msg = decision.reason or "Action denied."
                print(f"[ATHENA] 🚫 denied {name}: {msg}")
                try:
                    learner_log_tool(name, str(args.get("action", "")), "denied")
                except Exception:
                    pass
                if not self.ui.muted:
                    self.ui.set_state("LISTENING")
                return types.FunctionResponse(
                    id=fc.id, name=name,
                    response={"result": msg},
                )
            if decision.requires_confirmation:
                key = tool_permission_key(name, args)
                now = time.monotonic()
                preapproved = (
                    now < self._voice_granted_until
                    and (
                        self._voice_granted_key == key
                        or self._voice_granted_name == name
                    )
                )
                if preapproved:
                    print(f"[ATHENA] ✅ voice-granted {name}")
                    athena_log(f"Permission pre-approved — executing {name}")
                    self._voice_granted_key = None
                    self._voice_granted_name = None
                    self._voice_granted_until = 0.0
                    self._pending_permission = None
                    if decision.risk_level == RiskLevel.MEDIUM:
                        remember_session_allow(name, str(args.get("action", "")))
                else:
                    # Already waiting on this (or any) permission — do NOT re-ask
                    pending = self._pending_permission
                    if pending and now < float(pending.get("expires", 0)):
                        same = pending.get("key") == key or pending.get("name") == name
                        if same:
                            athena_log(f"Permission still pending (no re-ask) — {pending.get('summary')}")
                            msg = (
                                "WAIT_FOR_USER: Permission was already requested once. "
                                "This is NOT a system error or failure. "
                                "Do NOT invent a 'system constraint' or technical issue. "
                                "Do NOT ask again. Stay silent. The system will run the action "
                                "when the user says 'go ahead' / 'you may proceed' / "
                                "'permission granted', or cancel it on 'abort'."
                            )
                            if not self.ui.muted:
                                self.ui.set_state("LISTENING")
                            return types.FunctionResponse(
                                id=fc.id, name=name,
                                response={"result": msg},
                            )
                        # Different action while one is pending — replace pending
                        athena_log(
                            f"Replacing pending permission "
                            f"{pending.get('summary')} → {decision.summary}"
                        )

                    self._arm_pending_permission(name, args, decision)
                    msg = (
                        f"PERMISSION_REQUIRED ({decision.risk_level.value}): "
                        f"{decision.summary}. "
                        f"Ask the user aloud ONCE, briefly, for permission "
                        f"('say go ahead or abort'). Then STOP and wait. "
                        f"Do NOT ask a second time. Do NOT call this tool again. "
                        f"Do NOT perform or claim you did it yet. "
                        f"The system will execute it when they grant permission "
                        f"and will send you the COMPLETED result."
                    )
                    return types.FunctionResponse(
                        id=fc.id, name=name,
                        response={"result": msg},
                    )

        if name == "save_memory":
            category = args.get("category", "notes")
            key      = args.get("key", "")
            value    = args.get("value", "")
            if key and value:
                if is_session_language_key(key):
                    set_response_language(value)
                    print(f"[Memory] 🌐 session language: {get_response_language()} (not persisted)")
                else:
                    update_memory({category: {key: {"value": value}}})
                    print(f"[Memory] 💾 save_memory: {category}/{key} = {value}")
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "ok", "silent": True}
            )

        loop   = asyncio.get_event_loop()
        result = "Done."
        exec_fp = self._grant_fp(name, args)

        # Remember outcomes so Gemini does not re-call the same tool in a loop
        _dedup_tools = ("code_helper", "dev_agent", "show_dataframe")
        if name in _dedup_tools and not local_grant:
            prev = self._completed_grants.get(exec_fp)
            if prev and time.monotonic() - prev[0] < 120:
                if not self.ui.muted:
                    self.ui.set_state("LISTENING")
                return types.FunctionResponse(
                    id=fc.id, name=name,
                    response={"result": (
                        f"ALREADY_DONE: {prev[1]}. Tell the user this outcome. "
                        f"Do NOT ask for permission. Do NOT call the tool again."
                    )},
                )

        try:
            if name == "open_app":
                r = await loop.run_in_executor(None, lambda: open_app(parameters=args, response=None, player=self.ui))
                result = r or f"Opened {args.get('app_name')}."

            elif name == "weather_report":
                r = await loop.run_in_executor(None, lambda: weather_action(parameters=args, player=self.ui))
                result = r or "Weather delivered."

            elif name == "browser_control":
                r = await loop.run_in_executor(None, lambda: browser_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "file_controller":
                r = await loop.run_in_executor(None, lambda: file_controller(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "shell_command":
                r = await loop.run_in_executor(None, lambda: shell_command(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "spotify_control":
                r = await loop.run_in_executor(None, lambda: spotify_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "explorer_navigate":
                r = await loop.run_in_executor(None, lambda: explorer_navigate(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "whatsapp_control":
                r = await loop.run_in_executor(None, lambda: whatsapp_control(parameters=args, player=self.ui))
                result = r or "WhatsApp action failed."
            elif name == "send_message":
                r = await loop.run_in_executor(None, lambda: send_message(parameters=args, response=None, player=self.ui, session_memory=None))
                result = r or f"Message sent to {args.get('receiver')}."

            elif name == "reminder":
                r = await loop.run_in_executor(None, lambda: reminder(parameters=args, response=None, player=self.ui))
                result = r or "Reminder set."

            elif name == "youtube_video":
                r = await loop.run_in_executor(None, lambda: youtube_video(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif name == "mt5_analysis":
                _mt5_act = str(args.get("action") or "analyze").strip().lower().replace("-", "_")
                if _mt5_act == "snapshot":
                    import time as _t_mod
                    _now = _t_mod.monotonic()
                    if self._vision_busy or (_now - self._vision_last_time) < 4.0:
                        result = (
                            "A chart snapshot is still being processed. "
                            "Do not call mt5_analysis snapshot or share_screen again."
                        )
                    else:
                        self._vision_busy = True
                        self._vision_last_time = _now
                        try:
                            img_b, mime_t, note = await loop.run_in_executor(
                                None, capture_chart_snapshot
                            )
                        except Exception as e:
                            self._vision_busy = False
                            result = (
                                f"Chart snapshot failed: {e}. "
                                "Ask the user to open MetaTrader 5 so the chart window is visible."
                            )
                        else:
                            user_q = str(
                                args.get("text") or args.get("question") or "Analyze this chart."
                            ).strip()
                            prompt = (
                                f"{CHART_ANALYSIS_PROMPT}\n{note}\n"
                                f"User request: {user_q}"
                            )
                            self._pending_vision = (img_b, mime_t, prompt, "screen")
                            print(f"[MT5] snapshot {len(img_b):,} bytes — {note}")
                            result = (
                                f"[VISION_ACTIVE] Chart captured ({note}). "
                                f"Immediately say ONE short natural sentence in {get_response_language()}, "
                                "telling them you are looking at the chart right now. "
                                "Do NOT describe or guess content — the actual image arrives in the NEXT message. "
                                "Never call share_screen."
                            )
                else:
                    r = await loop.run_in_executor(
                        None, lambda: mt5_analysis(parameters=args, player=self.ui)
                    )
                    result = r or "MT5 analysis failed."

            elif name == "screen_process":
                import time as _t_mod
                _now = _t_mod.monotonic()
                _cooldown = 4.0  # seconds — covers echo window after speaking ends
                if self._vision_busy or (_now - self._vision_last_time) < _cooldown:
                    _wait = max(0, _cooldown - (_now - self._vision_last_time))
                    print(f"[Vision] ⏳ Cooldown active ({_wait:.1f}s remaining) — ignoring duplicate call")
                    result = "Vision is still processing the previous request. I will not call this again."
                else:
                    self._vision_busy      = True
                    self._vision_last_time = _now
                    angle     = args.get("angle", "screen").lower()
                    user_text = args.get("text", "What do you see?")
                    if angle == "camera":
                        img_b, mime_t = await loop.run_in_executor(None, _capture_camera)
                        self.ui.start_camera_stream()
                        self._vision_cam_active = True
                        print(f"[Vision] 📷 Camera: {len(img_b):,} bytes")
                        _stall = "camera"
                    else:
                        img_b, mime_t = await loop.run_in_executor(None, _capture_screen)
                        print(f"[Vision] 🖥️  Screen: {len(img_b):,} bytes")
                        _stall = "screen"
                    self._pending_vision = (img_b, mime_t, user_text, angle)
                    result = (
                        f"[VISION_ACTIVE] {_stall.capitalize()} captured. "
                        f"Immediately say ONE short natural sentence in {get_response_language()}, "
                        f"telling them you are looking at their {_stall} right now. "
                        f"Do NOT describe or guess content — the actual image arrives in the NEXT message."
                    )

            elif name == "close_camera":
                self.ui.stop_camera_stream()
                result = "Camera closed."

            elif name == "share_screen":
                action = str(args.get("action") or "start").lower().strip().replace("-", "_")
                if action in ("stop", "off", "end"):
                    self._share_screen = False
                    self._share_last_hash = ""
                    self._share_turn_sent = False
                    self._share_mic_armed = False
                    self.ui.write_log("SYS: Screen share OFF")
                    athena_log("Screen share OFF")
                    result = "Screen sharing stopped. I no longer receive screen snapshots until you start sharing again."
                elif action in ("status", "state"):
                    result = (
                        "Screen sharing is on. Live stills of the display are sent while the user talks. Answer from the latest still."
                        if self._share_screen
                        else "Screen sharing is off. Say share my screen to start. This is pictures only — no computer audio."
                    )
                else:
                    self._share_screen = True
                    self._share_last_hash = ""
                    self._share_turn_sent = False
                    self._share_mic_armed = False
                    result = (
                        "Screen sharing is on. Live stills of the display arrive as the user talks. "
                        "Answer from the CURRENT still, not an earlier window. "
                        "No computer audio is shared. Say stop sharing to turn it off. "
                        "Do not call screen_process for every follow-up question."
                    )
                    self.ui.write_log("SYS: Screen share ON — stills while you talk.")
                    athena_log("Screen share ON")
                    print("[ATHENA] Screen share ON")
                    self._schedule_share_frame("start", force=True)

            elif name == "computer_settings":
                _cs_action = str(args.get("action") or "").lower().strip().replace("-", "_").replace(" ", "_")
                if _cs_action in ("sleep", "sleep_pc", "shutdown", "restart"):
                    _cs_args = dict(args)
                    async def _deferred_pc_power(_a=_cs_action, _p=_cs_args):
                        await self._wait_for_farewell_speech()
                        try:
                            await asyncio.to_thread(
                                computer_settings,
                                parameters=_p,
                                response=None,
                                player=self.ui,
                            )
                        except Exception as e:
                            print(f"[ATHENA] deferred PC {_a} failed: {e}")
                    asyncio.create_task(_deferred_pc_power())
                    result = {
                        "sleep": "Putting the computer to sleep now.",
                        "sleep_pc": "Putting the computer to sleep now.",
                        "shutdown": "Shutting down the computer now.",
                        "restart": "Restarting the computer now.",
                    }.get(_cs_action, "Done.")
                else:
                    r = await loop.run_in_executor(None, lambda: computer_settings(parameters=args, response=None, player=self.ui))
                    result = r or "Done."

            elif name == "desktop_control":
                r = await loop.run_in_executor(None, lambda: desktop_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "code_helper":
                if self._code_helper_lock is None:
                    self._code_helper_lock = asyncio.Lock()
                if self._code_helper_lock.locked():
                    result = (
                        "ALREADY_RUNNING: code_helper is executing. Stay silent. "
                        "Do NOT call again."
                    )
                else:
                    async with self._code_helper_lock:
                        r = await loop.run_in_executor(
                            None,
                            lambda: code_helper(parameters=args, player=self.ui, speak=self.speak),
                        )
                        result = r or "Done."

            elif name == "dev_agent":
                r = await loop.run_in_executor(None, lambda: dev_agent(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "web_search":
                r = await loop.run_in_executor(None, lambda: web_search_action(parameters=args, player=self.ui))
                result = r or "Done."
                # Mirror results to the on-screen content panel
                _mode = args.get("mode", "search")
                if r and not r.startswith("No results") and not r.startswith("Search failed"):
                    _query = args.get("query") or ", ".join(args.get("items", []))
                    _label = f"{_mode.upper()} — {_query[:38]}" if _query else _mode.upper()
                    self.ui.show_content(_label, r)
            elif name == "file_processor":
                if not args.get("file_path") and self.ui.current_file:
                    args["file_path"] = self.ui.current_file
                r = await loop.run_in_executor(
                    None,
                    lambda: file_processor(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Done."

            elif name == "show_dataframe":
                if not args.get("file_path") and self.ui.current_file:
                    args["file_path"] = self.ui.current_file
                r = await loop.run_in_executor(
                    None,
                    lambda: show_dataframe(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Done."

            elif name == "computer_control":
                r = await loop.run_in_executor(None, lambda: computer_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "game_updater":
                r = await loop.run_in_executor(None, lambda: game_updater(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "flight_finder":
                r = await loop.run_in_executor(None, lambda: flight_finder(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "system_status":
                detail = bool(args.get("detail", False))
                top_n = int(args.get("top_n", 8) or 8)
                r = await loop.run_in_executor(
                    None, lambda: get_extended_system_status(detail=detail, top_n=top_n)
                )
                result = str(r)

            elif name == "manage_continuous_monitor":
                r = await loop.run_in_executor(
                    None, lambda: manage_continuous_monitor(parameters=args)
                )
                result = r or "Done."

            elif name == "manage_monitor":
                action = args.get("action", "").lower().strip()
                topic  = args.get("topic", "").strip()
                if action == "add" and topic:
                    result = await asyncio.to_thread(add_monitor, topic)
                elif action == "remove" and topic:
                    result = await asyncio.to_thread(remove_monitor, topic)
                elif action == "list":
                    topics = await asyncio.to_thread(list_monitors)
                    result = ("Monitoring: " + ", ".join(topics)) if topics else "No topics are being monitored."
                else:
                    result = "Specify action (add/remove/list) and a topic."

            elif name == "sleep_assistant":
                if getattr(self, "_shutdown_started", False):
                    result = "Shutdown already in progress."
                else:
                    self._hold_mic = True
                    self.ui.write_log("SYS: Sleep requested.")
                    async def _do_sleep():
                        await self._wait_for_farewell_speech()
                        await asyncio.sleep(0.35)
                        self.request_sleep()
                    asyncio.create_task(_do_sleep())
                    result = (
                        f"Going to sleep. Say Hey {self.ui.assistant_name} "
                        "or use the tray icon to wake me."
                    )

            elif name in ("shutdown_athena", "shutdown_Athena", "shutdown_jarvis"):
                self._begin_shutdown()
                result = "Shutting down completely. Goodbye, sir."

            else:
                result = f"Unknown tool: {name}"

        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            self.speak_error(name, e)
            try:
                learner_log_tool(name, str(args.get("action", "")), "fail")
            except Exception:
                pass
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            print(f"[ATHENA] 📤 {name} → {str(result)[:80]}")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": result}
            )

        if not self.ui.muted:
            self.ui.set_state("LISTENING")

        try:
            rlow = str(result).lower()
            if "permission_required" in rlow or "wait_for_user" in rlow:
                pass  # pending — not a final outcome
            elif "already_running" in rlow or "already_done" in rlow:
                pass
            elif any(x in rlow for x in ("fail", "error", "exception", "could not", "unable")):
                learner_log_tool(name, str(args.get("action", "")), "fail")
            else:
                learner_log_tool(name, str(args.get("action", "")), "ok")
                if name in ("code_helper", "dev_agent", "show_dataframe"):
                    self._completed_grants[exec_fp] = (
                        time.monotonic(), str(result)[:4000]
                    )
                    cutoff = time.monotonic() - 120.0
                    self._completed_grants = {
                        k: v for k, v in self._completed_grants.items()
                        if v[0] >= cutoff
                    }
        except Exception:
            pass

        print(f"[ATHENA] 📤 {name} → {str(result)[:80]}")
        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result}
        )

    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            await self.session.send_realtime_input(media=msg)

    async def _listen_audio(self):
        print("[ATHENA] 🎤 Mic started")
        loop = asyncio.get_event_loop()

        def callback(indata, frames, time_info, status):
            with self._speaking_lock:
                Athena_speaking = self._is_speaking
            phone_listen = False
            dash = self._dashboard
            if dash is not None:
                try:
                    phone_listen = bool(dash.phone_listen_active())
                except Exception:
                    phone_listen = False
            if (
                not Athena_speaking
                and not self._hold_mic
                and not getattr(self, "_shutdown_started", False)
                and not self.ui.muted
                and not phone_listen
            ):
                data = indata.tobytes()
                loop.call_soon_threadsafe(
                    self.out_queue.put_nowait,
                    {"data": data, "mime_type": "audio/pcm"}
                )
                if (
                    self._share_screen
                    and not self._share_mic_armed
                    and _pcm16_rms(data) > 700
                ):
                    self._share_mic_armed = True
                    self._schedule_share_frame("mic-start", force=True)

        try:
            with sd.InputStream(
                samplerate=SEND_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                callback=callback,
            ):
                print("[ATHENA] 🎤 Mic stream open")
                while True:
                    await asyncio.sleep(0.1)
        except Exception as e:
            print(f"[ATHENA] ❌ Mic: {e}")
            raise

    async def _receive_audio(self):
        print("[ATHENA] 👂 Recv started")
        out_buf, in_buf = [], []

        try:
            while True:
                async for response in self.session.receive():

                    if response.data:
                        if self._interrupted:
                            pass  # discard: interrupted
                        else:
                            self._last_model_audio = time.monotonic()
                            if self._turn_done_event and self._turn_done_event.is_set():
                                self._turn_done_event.clear()
                            # Split into ~50 ms chunks so interrupt() stops audio within 50 ms
                            # (24000 Hz × 2 bytes/sample × 0.05 s = 2400 bytes per slice)
                            _audio_data = response.data
                            _SLICE = 2400
                            for _i in range(0, len(_audio_data), _SLICE):
                                self.audio_in_queue.put_nowait(_audio_data[_i : _i + _SLICE])

                    if response.server_content:
                        sc = response.server_content

                        if sc.output_transcription and sc.output_transcription.text:
                            self._last_model_audio = time.monotonic()
                            txt = _clean_transcript(sc.output_transcription.text)
                            if txt and txt != (out_buf[-1] if out_buf else ""):
                                out_buf.append(txt)

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = _clean_transcript(sc.input_transcription.text)
                            if txt:
                                first_chunk = not in_buf
                                in_buf.append(txt)
                                self._last_user_speech = time.monotonic()
                                if (
                                    self._share_screen
                                    and not self._pending_permission
                                ):
                                    if first_chunk:
                                        self._schedule_share_frame("speech-start", force=True)
                                    elif (time.monotonic() - self._share_last_sent) > 1.2:
                                        self._schedule_share_frame("speech-refresh", force=False)

                        if sc.turn_complete:
                            if self._turn_done_event:
                                self._turn_done_event.set()

                            # If this turn_complete ends an interrupted response, clear the
                            # flag and skip all further processing for that turn.
                            if self._interrupted:
                                self._interrupted = False
                                in_buf  = []
                                out_buf = []
                                continue

                            full_in = " ".join(in_buf).strip()
                            if full_in:
                                self.ui.write_log(f"You: {full_in}")
                                self._session_log.append(f"User: {full_in}")
                                try:
                                    if looks_like_correction(full_in):
                                        prev = ""
                                        for line in reversed(self._session_log[:-1]):
                                            if line.startswith(f"{self._asst_name}:") or line.startswith("Athena:"):
                                                prev = line.split(":", 1)[-1].strip()
                                                break
                                        learner_log_correction(full_in, prev)
                                except Exception:
                                    pass
                                if self._dashboard:
                                    asyncio.create_task(self._dashboard.broadcast({
                                        "type": "log", "speaker": "user",
                                        "text": full_in,
                                        "ts": datetime.now().isoformat(),
                                    }))
                                # Voice permission grant/abort while a risky tool is pending
                                if self._pending_permission:
                                    verdict = classify_user_permission_reply(full_in)
                                    if verdict:
                                        await self._resolve_voice_permission(verdict, full_in)
                                    else:
                                        athena_log(
                                            f"Permission pending; voice not classified: {full_in!r}"
                                        )
                                else:
                                    # Spoken full quit — do not wait for Gemini to call shutdown_athena
                                    exit_kind = classify_exit_intent(full_in)
                                    if exit_kind == "shutdown":
                                        self._begin_shutdown()
                                    else:
                                        pc = classify_pc_power_intent(full_in)
                                        if pc:
                                            await self._request_pc_power(pc)
                                if not self._pending_permission and self._share_screen:
                                    t = self._share_inflight
                                    if t is not None and not t.done():
                                        try:
                                            await asyncio.wait_for(asyncio.shield(t), timeout=1.8)
                                        except Exception:
                                            pass
                                    if not self._share_turn_sent:
                                        await self._push_share_frame_realtime("turn-end", force=True)
                            self._share_mic_armed = False
                            self._share_turn_sent = False
                            in_buf = []

                            full_out = " ".join(out_buf).strip()
                            if full_out:
                                self.ui.write_log(f"{self._asst_name}: {full_out}")
                                self._session_log.append(f"{self._asst_name}: {full_out}")
                                if self._dashboard:
                                    asyncio.create_task(self._dashboard.broadcast({
                                        "type": "log", "speaker": "Athena",
                                        "text": full_out,
                                        "ts": datetime.now().isoformat(),
                                        "unprompted": time.time() < getattr(self, "_unprompted_until", 0),
                                    }))
                                lo = full_out.lower()
                                if not getattr(self, "_shutdown_started", False) and (
                                    "shutting down completely" in lo
                                    or "i'm completely shutting down" in lo
                                    or "i am shutting down" in lo
                                ):
                                    self._begin_shutdown()
                            out_buf = []

                            # Vision injection: model finished tool-response turn → now send the image
                            if self._pending_vision and self.session:
                                import base64 as _b64
                                img_b, mime_t, question, angle = self._pending_vision
                                self._pending_vision = None
                                b64 = _b64.b64encode(img_b).decode("ascii")
                                print(f"[Vision] 📤 {len(img_b):,} bytes (angle={angle}) → main session")
                                await self.session.send_client_content(
                                    turns={"parts": [
                                        {"inline_data": {"mime_type": mime_t, "data": b64}},
                                        {"text": question},
                                    ]},
                                    turn_complete=True,
                                )
                                # Mark next turn_complete behaviour depending on angle
                                if self._vision_cam_active:
                                    # Camera: keep busy until Athena finishes speaking the answer
                                    self._vision_cam_active    = False
                                    self._vision_close_pending = True
                                else:
                                    # Screen-only: no camera to close; release busy flag now
                                    self._vision_busy = False
                            elif self._vision_close_pending:
                                # This turn_complete IS the vision answer — close camera + release busy flag
                                self._vision_close_pending = False
                                self._vision_busy = False
                                async def _cam_close():
                                    await asyncio.sleep(2.0)
                                    self.ui.stop_camera_stream()
                                asyncio.create_task(_cam_close())

                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            print(f"[ATHENA] 📞 {fc.name}")
                            fr = await self._execute_tool(fc)
                            fn_responses.append(fr)
                        await self.session.send_tool_response(
                            function_responses=fn_responses
                        )
        except Exception as e:
            err_str = str(e)
            _transient = (
                "1011" in err_str
                or "Internal error occurred" in err_str
                or "ConnectionClosed" in type(e).__name__
            )
            if _transient:
                print("[ATHENA] Gemini Live connection dropped (server error) — will reconnect.")
                self.ui.write_log("SYS: Connection dropped (server error). Reconnecting…")
            else:
                print(f"[ATHENA] ❌ Recv: {e}")
                traceback.print_exc()
            raise

    async def _play_audio(self):
        print("[ATHENA] 🔊 Play started")

        stream = sd.RawOutputStream(
            samplerate=RECEIVE_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
        )
        stream.start()

        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        self.audio_in_queue.get(),
                        timeout=0.1
                    )
                except asyncio.TimeoutError:
                    if (
                        self._turn_done_event
                        and self._turn_done_event.is_set()
                        and self.audio_in_queue.empty()
                    ):
                        if self._hold_mic and (time.monotonic() - self._last_model_audio) < 1.4:
                            continue
                        self.set_speaking(False)
                        self._turn_done_event.clear()
                    continue

                self.set_speaking(True)

                # Batch all immediately-available chunks into one write to reduce
                # thread-pool round-trips (was one asyncio.to_thread per 50ms slice).
                # Cap at ~200 ms so interrupt() still stops audio within ~200 ms.
                batch = bytearray(chunk)
                while len(batch) < 9600:   # 9600 bytes ≈ 200 ms at 24 kHz / 16-bit mono
                    try:
                        batch.extend(self.audio_in_queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                try:
                    pcm = bytes(batch)
                    dash = self._dashboard
                    if dash is not None and dash.phone_listen_active():
                        await dash.send_phone_audio(pcm)
                    else:
                        await asyncio.to_thread(stream.write, pcm)
                except (RuntimeError, asyncio.CancelledError):
                    break   # executor shutting down — exit cleanly
        except Exception as e:
            print(f"[ATHENA] ❌ Play: {e}")
            raise
        finally:
            self.set_speaking(False)
            stream.stop()
            stream.close()

    # ── Morning briefing ────────────────────────────────────────────────────────

    async def _send_wake_greeting(self) -> None:
        """Short spoken ack after waking from tray / wake-word sleep."""
        await asyncio.sleep(0.4)
        if not self.session or self._hud_sleeping:
            return
        name = self.ui.assistant_name or self._asst_name or "Athena"
        prompt = (
            f"[WAKE_GREETING] You just woke from sleep. "
            f"Say you're back in one short natural sentence — "
            f"e.g. \"I'm back.\" / \"{name} online.\" / \"Back with you.\" "
            f"Vary it. Do not call any tools. Do not read this instruction aloud."
        )
        try:
            await self.session.send_client_content(
                turns={"parts": [{"text": prompt}]},
                turn_complete=True,
            )
            self.ui.write_log("SYS: Wake greeting sent.")
        except Exception as e:
            self.ui.write_log(f"ERR: Wake greeting failed — {e}")

    async def _send_startup_briefing(self) -> None:
        """
        Two-phase briefing optimized for speed:
          Phase 1 — instant greeting (no tools) → speech starts in <1s
          Phase 2 — news pre-fetched in a background thread while Phase 1 plays,
                    delivered as ready text (no Gemini tool-call round-trip) and
                    shown on the UI content panel. Waits for turn_complete event
                    instead of a fixed sleep so there is no unnecessary gap.
        """
        memory   = load_memory()
        identity = memory.get("identity", {})

        def _val(k: str) -> str:
            e = identity.get(k, {})
            return (e.get("value", "") if isinstance(e, dict) else str(e)).strip()

        lang = get_response_language(memory)
        name = _val("name")
        time_str = datetime.now().strftime("%H:%M")

        # Start fetching news immediately — runs in parallel while phase 1 plays
        loop = asyncio.get_event_loop()
        news_future = loop.run_in_executor(None, _fetch_news_sync, "top world news today")

        await asyncio.sleep(0.3)
        if not self.session:
            return

        # ── Phase 1: instant greeting ─────────────────────────────────────────
        lang_clause = f" Respond in {lang}."
        name_clause = f" Address the user as {name}." if name else ""

        # Inject last session context if available — peek marks briefed, keeps history
        last = await asyncio.to_thread(peek_last_session)
        session_clause = ""
        if last:
            try:
                _delta = (datetime.now() - datetime.strptime(last["date"], "%Y-%m-%d")).days
                _when  = "earlier today" if _delta == 0 else ("yesterday" if _delta == 1 else f"{_delta} days ago")
            except Exception:
                _when = "last time"
            session_clause = (
                f" Also briefly and naturally mention that {_when}: {last['summary']}"
            )

        p1 = (
            f"Greet the user warmly in a human, natural way — mention it is {time_str}, "
            f"and say you're grabbing today's news.{session_clause} "
            f"Keep it to 2 short sentences max. Contractions, no chatbot filler. "
            f"Do not call any tools.{lang_clause}{name_clause}"
        )

        # Clear the turn-done event so we can wait for Phase 1 to finish
        if self._turn_done_event:
            self._turn_done_event.clear()

        await self.session.send_client_content(
            turns={"parts": [{"text": p1}]},
            turn_complete=True,
        )
        self.ui.write_log("SYS: Briefing phase 1 (greeting) sent.")

        # ── Phase 2: fire as soon as Phase 1 audio is done ───────────────────
        async def _deliver_news():
            try:
                lang_str = f" Respond in {lang}." if lang else ""

                # Wait for news fetch (already running) and Phase 1 turn-complete
                # in parallel — whichever takes longer determines the wait time
                news_done   = asyncio.wrap_future(news_future)
                turn_waited = False
                if self._turn_done_event:
                    try:
                        await asyncio.wait_for(self._turn_done_event.wait(), timeout=6.0)
                        turn_waited = True
                    except asyncio.TimeoutError:
                        pass

                # Extra buffer: turn_complete fires when Gemini finishes *generating*
                # Phase 1, but audio may still be playing.  Waiting a beat here
                # prevents Phase 2 audio from arriving while Phase 1 is mid-sentence
                # (which sounds like a "repeated first response" to the user).
                if turn_waited:
                    await asyncio.sleep(0.8)
                else:
                    await asyncio.sleep(1.0)

                try:
                    news_text = await asyncio.wait_for(news_done, timeout=4.0)
                except Exception:
                    news_text = ""

                if not self.session:
                    return

                if news_text and len(news_text) > 60:
                    # Show on UI content panel immediately
                    self.ui.show_content("NEWS — top world news today", news_text)

                    p2 = (
                        f"[BRIEFING] Here are today's top news headlines:\n{news_text}\n\n"
                        "Pick ONE headline, summarise it in one sentence, then say the full list "
                        f"is displayed on screen. Do not call any tools.{lang_str}"
                    )
                else:
                    p2 = (
                        "News headlines could not be fetched right now. "
                        f"Let the user know briefly.{lang_str}"
                    )

                await self.session.send_client_content(
                    turns={"parts": [{"text": p2}]},
                    turn_complete=True,
                )
                self.ui.write_log("SYS: Briefing phase 2 (news) sent.")
            except Exception as e:
                print(f"[Briefing] Phase 2 error: {e}")
                self.ui.write_log(f"SYS: Briefing phase 2 failed: {e}")

        asyncio.create_task(_deliver_news())

    # ── Session memory ──────────────────────────────────────────────────────────

    async def _save_session_summary(self) -> None:
        """Summarise the current session; optionally distill lessons/compact patch (same Flash call)."""
        log = self._session_log
        if len(log) < 3:          # need at least one exchange to be worth saving
            return
        self._session_log = []    # reset immediately so the next session starts clean

        memory = load_memory()
        lang = get_response_language(memory)

        convo = "\n".join(log[-40:])   # cap at last 40 turns to stay within token budget
        prompt = (
            f"Analyze this conversation. Respond with ONLY valid JSON (no markdown fences) in this shape:\n"
            f'{{"summary":"1-2 sentences in {lang} about what the user accomplished or discussed",'
            f'"lessons":["optional short style/tool lesson", "..."],'
            f'"upsert":{{"category":{{"key":"value"}}}},'
            f'"forget":[["notes","stale_key"]]}}\n'
            f"Rules: summary is required. lessons max 3, only if clear. "
            f"upsert only for facts clearly stated this session. "
            f"forget only keys the user contradicted; never forget identity/name. "
            f"Use empty lessons [], upsert {{}}, forget [] when nothing applies.\n\n"
            f"Conversation:\n{convo}"
        )
        try:
            from google import genai as _genai
            from core.gemini_models import get_flash_model
            client = _genai.Client(api_key=_get_api_key())
            resp   = await asyncio.to_thread(
                client.models.generate_content,
                model=get_flash_model(),
                contents=prompt,
            )
            raw = (resp.text or "").strip()
            payload = None
            if raw:
                # Strip optional ```json fences
                cleaned = raw
                if cleaned.startswith("```"):
                    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
                    cleaned = re.sub(r"\s*```$", "", cleaned)
                try:
                    payload = json.loads(cleaned)
                except Exception:
                    # Fallback: treat whole response as summary text
                    save_session_summary(raw[:280], lang)
                    payload = None

            if isinstance(payload, dict):
                summary = str(payload.get("summary") or "").strip()
                if summary:
                    save_session_summary(summary, lang)
                try:
                    learner_apply_distill(payload)
                except Exception as e:
                    print(f"[Memory] ⚠️ Distill apply failed: {e}")
            try:
                await asyncio.to_thread(learner_rollup)
            except Exception as e:
                print(f"[Memory] ⚠️ Rollup failed: {e}")
        except Exception as e:
            print(f"[Memory] ⚠️ Session summary failed: {e}")

    # ── System monitor ──────────────────────────────────────────────────────────

    async def _run_system_monitor(self) -> None:
        """Background task: continuous system/event alerts when metrics or watches fire."""
        while True:
            await asyncio.sleep(8)
            alert = await asyncio.to_thread(self._sys_monitor.check)
            if not alert or not self.session:
                continue
            # Don't interrupt an active conversation
            with self._speaking_lock:
                speaking = self._is_speaking
            if speaking or (time.monotonic() - self._last_user_speech) < 10:
                continue
            try:
                await self.session.send_client_content(
                    turns={"parts": [{"text": alert}]},
                    turn_complete=True,
                )
                try:
                    self.ui.write_log(f"SYS: {alert[:120]}")
                except Exception:
                    pass
            except Exception as e:
                print(f"[Monitor] Could not send alert: {e}")

    # ── WhatsApp auto-reply alerts ──────────────────────────────────────────────

    async def _run_whatsapp_alerts(self) -> None:
        """Drain [WHATSAPP_ALERT] lines from the watcher into the live session."""
        while True:
            await asyncio.sleep(2)
            if not self.session:
                continue
            with self._whatsapp_alerts_lock:
                if not self._whatsapp_alerts:
                    continue
                alerts = list(self._whatsapp_alerts)
                self._whatsapp_alerts.clear()
            with self._speaking_lock:
                speaking = self._is_speaking
            if speaking or (time.monotonic() - self._last_user_speech) < 5:
                # put back and wait
                with self._whatsapp_alerts_lock:
                    self._whatsapp_alerts = alerts + self._whatsapp_alerts
                continue
            for alert in alerts:
                try:
                    await self.session.send_client_content(
                        turns={"parts": [{"text": alert}]},
                        turn_complete=True,
                    )
                    await asyncio.sleep(4)
                except Exception as e:
                    print(f"[WhatsAppWatch] could not speak alert: {e}")

    # ── Background monitor ──────────────────────────────────────────────────────

    async def _run_background_monitor(self) -> None:
        """Check user-configured topics once per day; speak alerts when new headlines appear."""
        await asyncio.sleep(300)          # wait 5 min after startup before first check
        while True:
            if self.session:
                # Don't interrupt if user spoke recently or Athena is mid-sentence
                with self._speaking_lock:
                    speaking = self._is_speaking
                recent_speech = (time.monotonic() - self._last_user_speech) < 30
                if not speaking and not recent_speech:
                    try:
                        alerts = await asyncio.to_thread(monitor_check_all)
                        memory = load_memory()
                        lang   = get_response_language(memory)
                        for alert in alerts:
                            msg = (
                                f"{alert}\n\n"
                                f"Inform the user about this development naturally in {lang}. "
                                "One brief sentence only."
                            )
                            await self.session.send_client_content(
                                turns={"parts": [{"text": msg}]},
                                turn_complete=True,
                            )
                            self.ui.write_log(f"SYS: Monitor alert sent.")
                            await asyncio.sleep(6)   # gap between consecutive alerts
                    except Exception as e:
                        print(f"[Monitor] ⚠️ Background check error: {e}")
            await asyncio.sleep(1800)     # check every 30 minutes

    # ── Proactive mode ──────────────────────────────────────────────────────────

    async def _run_proactive_mode(self) -> None:
        """
        Background task: periodically checks if the user has been silent long enough,
        then hands time + memory + system context to Gemini for a proactive check-in.
        """
        while True:
            await asyncio.sleep(45)   # evaluate often; engine enforces silence/cooldown

            if not self.session:
                continue
            if not is_proactive_enabled():
                continue

            with self._speaking_lock:
                speaking = self._is_speaking
            if speaking:
                continue

            if not self._proactive.should_trigger(self._last_user_speech):
                continue

            self._proactive.mark_triggered()
            self._unprompted_until = time.time() + 45

            try:
                memory       = await asyncio.to_thread(load_memory)
                monitors     = await asyncio.to_thread(list_monitors)
                recent_turns = self._session_log[-8:] if self._session_log else []
                snapshot     = await asyncio.to_thread(get_extended_system_status, False, 5)
                prompt = self._proactive.build_prompt(
                    memory       = memory,
                    monitors     = monitors or None,
                    recent_turns = recent_turns or None,
                    system_snapshot = snapshot,
                )
                await self.session.send_client_content(
                    turns={"parts": [{"text": prompt}]},
                    turn_complete=True,
                )
                self.ui.write_log("SYS: Proactive check-in.")
            except Exception as e:
                print(f"[Proactive] ⚠️ {e}")

    # ── Phone audio relay ────────────────────────────────────────────────────────

    async def _relay_phone_audio(self) -> None:
        """Forward phone mic PCM chunks from dashboard queue into the Gemini Live session."""
        q = self._dashboard._phone_audio_queue
        while True:
            try:
                chunk = await asyncio.wait_for(q.get(), timeout=1.0)
            except asyncio.TimeoutError:
                # No audio for 1 s → phone mic inactive, give PC mic back
                self._phone_active = False
                continue
            self._phone_active = True   # phone is streaming — silence PC mic
            with self._speaking_lock:
                speaking = self._is_speaking
            if not speaking and not self.ui.muted:
                try:
                    self.out_queue.put_nowait(chunk)
                except asyncio.QueueFull:
                    pass

    def _on_phone_connected(self, kind: str = "signin") -> None:
        if kind == "reconnect":
            self.ui.write_log("SYS: Phone reconnected.")
        else:
            self.ui.write_log("SYS: Phone signed in.")
        self.ui.notify_phone_connected()

    def _dashboard_toggle_mute(self):
        self.ui.muted = not self.ui.muted
        return bool(self.ui.muted)

    def _dashboard_permission(self, allow: bool, remember: bool) -> None:
        if not self._loop:
            return

        async def _run():
            pending = self._pending_permission
            if allow and remember and pending:
                remember_session_allow(
                    str(pending.get("name") or ""),
                    str((pending.get("args") or {}).get("action") or ""),
                )
            await self._resolve_voice_permission(
                "grant" if allow else "deny",
                "remote-app",
            )

        asyncio.run_coroutine_threadsafe(_run(), self._loop)

    # ── dashboard command relay ─────────────────────────────────────────────

    async def _process_dashboard_commands(self) -> None:
        while True:
            try:
                text = await asyncio.wait_for(
                    self._dashboard._command_queue.get(), timeout=0.5
                )
                if not text:
                    continue
                # Wait up to 8s for session to become ready after a wake
                for _ in range(80):
                    if self.session:
                        break
                    await asyncio.sleep(0.1)
                if self.session:
                    if self._pending_permission:
                        verdict = classify_user_permission_reply(text)
                        if verdict:
                            await self._resolve_voice_permission(verdict, text)
                            self.ui.write_log(f"[Web]: {text} (permission {verdict})")
                            continue
                        athena_log(
                            f"Permission pending; dashboard text not classified: {text!r}"
                        )
                    else:
                        pc = classify_pc_power_intent(text)
                        if pc:
                            await self._request_pc_power(pc)
                            self.ui.write_log(f"[Web]: {text}")
                            continue
                    await self._send_text_with_share(text)
                    self.ui.write_log(f"[Web]: {text}")
                else:
                    print(f"[Dashboard] Dropped command (no session): {text}")
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                print(f"[Dashboard] Command error: {e}")
                await asyncio.sleep(0.5)

    # ── main loop ───────────────────────────────────────────────────────────

    async def run(self):
        self._loop = asyncio.get_event_loop()
        self._sleep_request = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._wake_event.set()  # start awake

        # Start dashboard (optional — needs: pip install fastapi "uvicorn[standard]" cryptography)
        try:
            from dashboard.server import DashboardServer
            self._dashboard = DashboardServer()
            self._dashboard.set_connect_callback(self._on_phone_connected)
            self._dashboard.set_wake_callback(self.request_wake)
            self._dashboard.set_sleep_callback(self.request_sleep)
            self._dashboard.set_interrupt_callback(self.interrupt)
            self._dashboard.set_mute_callback(self._dashboard_toggle_mute)
            self._dashboard.set_permission_callback(self._dashboard_permission)
            self._dashboard.set_file_callback(getattr(self.ui, "set_current_file", None))
            self._dashboard.set_config_callback(getattr(self.ui, "apply_remote_config", None))
            asyncio.create_task(self._dashboard.serve())
            # Runs for the whole lifetime, not just inside an active session
            asyncio.create_task(self._process_dashboard_commands())
            _orig_content = self.ui.show_content

            def _relay_content(title, text, html=False, nowrap=False):
                _orig_content(title, text, html=html, nowrap=nowrap)
                if self._dashboard and self._loop:
                    asyncio.run_coroutine_threadsafe(
                        self._dashboard.broadcast({
                            "type": "content",
                            "title": str(title),
                            "text": str(text),
                            "unprompted": time.time() < getattr(self, "_unprompted_until", 0),
                        }),
                        self._loop,
                    )

            self.ui.show_content = _relay_content  # type: ignore[method-assign]
        except Exception as e:
            print(f"[Dashboard] Disabled: {e}")
            traceback.print_exc()
            try:
                athena_log(f"SYS: Dashboard disabled — {e}")
            except Exception:
                pass
            self._dashboard = None
            self._dashboard_error = str(e)

        while True:
            # Stay offline while HUD is sleeping (wake-word / tray will set _wake_event)
            if self._hud_sleeping:
                self.ui.set_state("SLEEPING")
                if self._dashboard:
                    try:
                        await self._dashboard.broadcast({"type": "status", "state": "sleeping"})
                    except Exception:
                        pass
                self._start_wake_listener()
                assert self._wake_event is not None
                await self._wake_event.wait()
                self._stop_wake_listener()
                if self._sleep_request is not None:
                    self._sleep_request.clear()
                self._conn_backoff = 3
                continue

            exited_for_sleep = False
            try:
                print("[ATHENA] Connecting...")
                self.ui.set_state("THINKING")
                config = self._build_config()

                # Fresh client on every reconnect — avoids stale HTTP session state
                client = genai.Client(
                    api_key=_get_api_key(),
                    http_options={"api_version": "v1beta"}
                )

                async with (
                    client.aio.live.connect(model=get_live_model(), config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session          = session
                    self.audio_in_queue   = asyncio.Queue()
                    self.out_queue        = asyncio.Queue(maxsize=200)
                    self._turn_done_event = asyncio.Event()
                    self._code_helper_lock = asyncio.Lock()
                    self._share_push_lock = asyncio.Lock()

                    # Reset transient state that must not carry over from a previous session
                    self._pending_vision       = None
                    self._vision_cam_active    = False
                    self._vision_close_pending = False
                    self._vision_busy          = False
                    self._vision_last_time     = 0.0
                    self._share_last_hash      = ""
                    self._share_turn_sent      = False
                    self._share_mic_armed      = False
                    self._share_inflight       = None
                    self._interrupted          = False
                    self._pending_permission   = None
                    self._voice_granted_key    = None
                    self._voice_granted_name   = None
                    self._voice_granted_until  = 0.0
                    # If sleep was requested during connect, keep the signal and exit
                    if self._hud_sleeping:
                        if self._sleep_request is not None:
                            self._sleep_request.set()
                    elif self._sleep_request is not None:
                        self._sleep_request.clear()

                    print("[ATHENA] Connected.")
                    self.ui.set_state("LISTENING")
                    self.ui.write_log(f"SYS: {self._asst_name} online.")

                    if self._dashboard:
                        await self._dashboard.broadcast({"type": "status", "state": "active"})

                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())
                    tg.create_task(self._run_system_monitor())
                    tg.create_task(self._run_background_monitor())
                    tg.create_task(self._run_proactive_mode())
                    tg.create_task(self._run_whatsapp_alerts())
                    tg.create_task(self._sleep_watcher())
                    if whatsapp_auto_reply_enabled():
                        try:
                            from actions.whatsapp_bridge_client import ensure_bridge
                            ensure_bridge()
                        except Exception:
                            pass
                        start_whatsapp_watcher()
                    if self._dashboard:
                        tg.create_task(self._relay_phone_audio())

                    # Morning briefing — fires once per process launch (if enabled)
                    if not self._briefing_sent and get_brief_enabled():
                        self._briefing_sent = True
                        tg.create_task(self._send_startup_briefing())
                    elif self._pending_wake_greeting:
                        self._pending_wake_greeting = False
                        tg.create_task(self._send_wake_greeting())

            except KeyboardInterrupt:
                raise
            except SystemExit:
                raise
            except BaseException as e:
                # Catches both Exception and BaseExceptionGroup (Python 3.11+
                # TaskGroup raises BaseExceptionGroup when tasks are cancelled
                # externally, which `except Exception` would miss, letting the
                # exception escape the while-loop and causing asyncio.run() to
                # start shutdown — resulting in "executor after shutdown" errors).
                if self._is_sleep_exc(e):
                    exited_for_sleep = True
                    if self._reconnect_needed:
                        print("[ATHENA] Reconnecting after API/model change.")
                        self._reconnect_needed = False
                        if self._sleep_request is not None:
                            self._sleep_request.clear()
                    else:
                        print("[ATHENA] Sleep requested — pausing Gemini.")
                else:
                    err_str = str(e)
                    _transient = (
                        "1011" in err_str
                        or "Internal error occurred" in err_str
                        or "ConnectionClosed" in err_str
                        or "ConnectionClosed" in type(e).__name__
                    )
                    if _transient:
                        print("[ATHENA] Gemini Live server error — reconnecting.")
                        self.ui.write_log("SYS: Connection dropped. Reconnecting…")
                        self._conn_backoff = 3
                    else:
                        print(f"[ATHENA] Error ({type(e).__name__}): {e}")
                        traceback.print_exc()

                    # Invalid API key — stop hammering the API, prompt re-configuration
                    if "API key not valid" in err_str or "1007" in err_str:
                        self.ui.write_log("ERR: API key invalid — please re-enter your key.")
                        self.ui.set_state("SLEEPING")
                        self.ui.prompt_reconfig()
                        while not self.ui._win._ready:
                            await asyncio.sleep(1)
                        print("[ATHENA] New API key saved — reconnecting...")
                        _conn_backoff = 3
                        continue

                    # Network / timeout errors — log clearly and back off
                    is_net_err = any(k in err_str for k in (
                        "TimeoutError", "timed out", "getaddrinfo", "CancelledError",
                        "ConnectionRefusedError", "OSError", "Cannot connect",
                    ))
                    if is_net_err:
                        _conn_backoff = min(getattr(self, "_conn_backoff", 3) * 2, 60)
                        self._conn_backoff = _conn_backoff
                        self.ui.write_log(
                            f"NET: Bağlantı kurulamadı — {_conn_backoff}s sonra tekrar deneniyor. "
                            "(VPN gerekiyor olabilir)"
                        )
                    else:
                        self._conn_backoff = 3
            finally:
                self.session = None
                # Only save if there was a real conversation (≥3 turns)
                if len(self._session_log) >= 3:
                    asyncio.create_task(self._save_session_summary())

            self.set_speaking(False)

            if getattr(self, "_shutdown_started", False):
                return

            # Sleep teardown (or wake-during-teardown) — skip error reconnect backoff
            if self._hud_sleeping or exited_for_sleep:
                continue

            self.ui.set_state("SLEEPING")

            if self._dashboard:
                await self._dashboard.broadcast({"type": "status", "state": "sleeping"})

            delay = getattr(self, "_conn_backoff", 3)
            print(f"[ATHENA] Reconnecting in {delay}s...")
            await asyncio.sleep(delay)

def main():
    if getattr(sys, "frozen", False):
        os.chdir(BASE_DIR)
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "Athena.Desktop"
                )
            except Exception:
                pass

    if "--scheduled-game-update" in sys.argv:
        from actions.game_updater import game_updater as _gu
        print(_gu({"action": "update", "platform": "both"}))
        return

    face = None
    for candidate in (
        BASE_DIR / "config" / "athena.png",
        BASE_DIR / "config" / "athena.ico",
        BASE_DIR / "face.png",
        BASE_DIR / "config" / "Athena.ico",
    ):
        if candidate.exists():
            face = candidate
            break
    ui = AthenaUI(str(face) if face else "face.png")

    def runner():
        ui.wait_for_api_key()
        Athena = AthenaLive(ui)
        try:
            asyncio.run(Athena.run())
        except KeyboardInterrupt:
            print("\n🔴 Shutting down...")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()