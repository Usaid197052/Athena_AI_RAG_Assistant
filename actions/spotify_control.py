"""
Spotify control for Athena.

Web API is the brain; Spotify Desktop is the speaker.
- PKCE OAuth with refresh tokens in config/api_keys.json
- Never steals window focus
- One Gemini call can play + set shuffle/repeat
- Internal retries for 401 / 429 / post-transfer 404
- SMTC only for transport when already playing and API fails
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from difflib import SequenceMatcher
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCOPES = " ".join(
    [
        "user-modify-playback-state",
        "user-read-playback-state",
        "user-read-currently-playing",
        "playlist-read-private",
        "playlist-read-collaborative",
        "user-library-read",
    ]
)

DEFAULT_REDIRECT = "http://127.0.0.1:8888/callback"
AUTH_PORT = 8888
TOKEN_URL = "https://accounts.spotify.com/api/token"
AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
API_BASE = "https://api.spotify.com/v1"

_ACTION_ALIASES = {
    "skip": "next",
    "skip_song": "next",
    "skip_track": "next",
    "next_song": "next",
    "next_track": "next",
    "forward": "next",
    "prev": "previous",
    "previous_song": "previous",
    "previous_track": "previous",
    "prev_track": "previous",
    "prev_song": "previous",
    "go_back": "previous",
    "back": "previous",
    "resume": "play",
    "unpause": "play",
    "play_pause": "play",
    "toggle": "play",
    "toggle_playback": "play",
    "play_song": "play",
    "play_track": "play",
    "search": "play",
    "play_playlist": "play",
    "play_liked": "play",
}

_LIKED_PATTERNS = (
    "liked songs",
    "liked song",
    "my liked",
    "favorites",
    "favourites",
    "saved songs",
    "saved tracks",
    "beğenilenler",
    "begenenler",
    "beğendiklerim",
    "begendiklerim",
    "beğenilen şarkılar",
    "begenen sarkilar",
)

_playlist_cache: dict[str, Any] = {"ts": 0.0, "items": [], "user_id": ""}
_auth_bg_started = False
_auth_bg_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Paths / config
# ---------------------------------------------------------------------------

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _config_path() -> Path:
    return _base_dir() / "config" / "api_keys.json"


def _load_config() -> dict:
    path = _config_path()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _atomic_save_config(data: dict) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def _spotify_cfg() -> dict:
    data = _load_config()
    sp = data.get("spotify")
    return sp if isinstance(sp, dict) else {}


def _save_spotify_fields(**fields: Any) -> None:
    data = _load_config()
    sp = data.get("spotify") if isinstance(data.get("spotify"), dict) else {}
    sp = dict(sp)
    for k, v in fields.items():
        if v is None:
            sp.pop(k, None)
        else:
            sp[k] = v
    data["spotify"] = sp
    _atomic_save_config(data)


def _clear_tokens() -> None:
    _save_spotify_fields(access_token=None, refresh_token=None, expires_at=None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_action(action: str) -> str:
    a = (action or "").lower().strip().replace(" ", "_").replace("-", "_")
    if a in _ACTION_ALIASES:
        return _ACTION_ALIASES[a]
    if any(k in a for k in ("skip", "next_track", "next_song")):
        return "next"
    if any(k in a for k in ("previous", "prev_track", "prev_song", "go_back")):
        return "previous"
    return a


def _norm_text(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


def _is_liked_query(query: str) -> bool:
    q = _norm_text(query)
    if not q:
        return False
    return any(p in q or q == _norm_text(p) for p in _LIKED_PATTERNS)


def _parse_by_query(query: str) -> tuple[str, str]:
    """Return (track_part, artist_part). artist may be empty."""
    m = re.search(r"\s+by\s+", query, flags=re.IGNORECASE)
    if not m:
        return query.strip(), ""
    return query[: m.start()].strip(), query[m.end() :].strip()


# ---------------------------------------------------------------------------
# Desktop process (no focus steal)
# ---------------------------------------------------------------------------

def _spotify_running() -> bool:
    try:
        import psutil

        for proc in psutil.process_iter(["name"]):
            name = (proc.info.get("name") or "").lower()
            if name.startswith("spotify") and "crash" not in name and "helper" not in name:
                return True
    except Exception:
        pass
    return False


def _spotify_exe() -> str | None:
    candidates = [
        os.path.expandvars(r"%APPDATA%\Spotify\Spotify.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\Spotify.exe"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _open_in_browser(url: str) -> None:
    """Open a URL. Frozen Windows builds cannot rely on webbrowser + python.exe."""
    if sys.platform == "win32":
        try:
            os.startfile(url)  # type: ignore[attr-defined]
            return
        except Exception:
            pass
    webbrowser.open(url)


def _login_hint() -> str:
    if getattr(sys, "frozen", False):
        return "finish the browser login that Athena opens, then ask again"
    return "run python actions/spotify_control.py --login, then ask again"


def _open_uri(uri: str) -> None:
    if sys.platform == "win32":
        try:
            os.startfile(uri)  # type: ignore[attr-defined]
            return
        except Exception:
            pass
        exe = _spotify_exe()
        if exe:
            flags = getattr(subprocess, "DETACHED_PROCESS", 0)
            subprocess.Popen([exe, "--uri=" + uri], creationflags=flags)
            return
    webbrowser.open(uri)


def _open_spotify() -> bool:
    exe = _spotify_exe()
    if exe and sys.platform == "win32":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen([exe], creationflags=flags)
        return True
    try:
        if sys.platform == "win32":
            os.startfile("spotify:")  # type: ignore[attr-defined]
        else:
            webbrowser.open("spotify:")
        return True
    except Exception:
        return False


def _ensure_spotify(wait: float = 2.5) -> bool:
    if _spotify_running():
        return True
    if not _open_spotify():
        return False
    deadline = time.monotonic() + max(wait, 1.0)
    while time.monotonic() < deadline:
        if _spotify_running():
            time.sleep(0.6)
            return True
        time.sleep(0.25)
    return _spotify_running()


# ---------------------------------------------------------------------------
# PKCE OAuth
# ---------------------------------------------------------------------------

def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def _auth_url(client_id: str, redirect_uri: str, challenge: str, state: str) -> str:
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def _exchange_code(client_id: str, code: str, verifier: str, redirect_uri: str) -> dict:
    r = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": verifier,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=20,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Token exchange failed ({r.status_code}): {r.text[:200]}")
    return r.json()


def _persist_token_response(payload: dict, *, keep_refresh: str | None = None) -> None:
    access = payload.get("access_token") or ""
    refresh = payload.get("refresh_token") or keep_refresh or ""
    expires_in = int(payload.get("expires_in") or 3600)
    if not access:
        raise RuntimeError("No access_token in Spotify response.")
    fields: dict[str, Any] = {
        "access_token": access,
        "expires_at": time.time() + expires_in - 60,
    }
    if refresh:
        fields["refresh_token"] = refresh
    _save_spotify_fields(**fields)


def _port_in_use(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True


def _run_oauth_flow(*, timeout: float = 120.0, open_browser: bool = True) -> str:
    """Blocking PKCE login. Returns success message or raises."""
    cfg = _spotify_cfg()
    client_id = str(cfg.get("client_id") or "").strip()
    redirect_uri = str(cfg.get("redirect_uri") or DEFAULT_REDIRECT).strip()
    if not client_id:
        raise RuntimeError(
            "Missing spotify.client_id in config/api_keys.json. "
            "Create an app at https://developer.spotify.com/dashboard "
            f"with redirect URI {DEFAULT_REDIRECT}, then add the Client ID."
        )
    if redirect_uri != DEFAULT_REDIRECT:
        # Still allow custom URI if user set one, but warn on port mismatch
        pass
    parsed = urlparse(redirect_uri)
    port = parsed.port or AUTH_PORT
    if port != AUTH_PORT and redirect_uri == DEFAULT_REDIRECT:
        port = AUTH_PORT

    if _port_in_use(port):
        raise RuntimeError(
            f"Port {port} is in use. Free it, or keep redirect URI "
            f"{DEFAULT_REDIRECT} and stop whatever is listening on {port}."
        )

    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)
    box: dict[str, Any] = {"code": None, "error": None, "state": None}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            qs = parse_qs(urlparse(self.path).query)
            box["code"] = (qs.get("code") or [None])[0]
            box["error"] = (qs.get("error") or [None])[0]
            box["state"] = (qs.get("state") or [None])[0]
            ok = bool(box["code"]) and not box["error"]
            body = (
                b"<html><body><h2>Athena Spotify linked.</h2>"
                b"<p>You can close this tab.</p></body></html>"
                if ok
                else b"<html><body><h2>Authorization failed.</h2></body></html>"
            )
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):  # silence
            return

    server = HTTPServer(("127.0.0.1", port), Handler)
    server.timeout = 1.0
    url = _auth_url(client_id, redirect_uri, challenge, state)
    if open_browser:
        _open_in_browser(url)
    else:
        print(f"Open this URL to authorize:\n{url}\n")

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and box["code"] is None and box["error"] is None:
        server.handle_request()
    server.server_close()

    if box["error"]:
        raise RuntimeError(f"Spotify auth error: {box['error']}")
    if not box["code"]:
        raise RuntimeError(
            "Spotify login timed out. " + (
                "Ask Athena to play again so the browser login can retry."
                if getattr(sys, "frozen", False)
                else "Run again: python actions/spotify_control.py --login"
            )
        )
    if box["state"] != state:
        raise RuntimeError("OAuth state mismatch. Try login again.")

    payload = _exchange_code(client_id, box["code"], verifier, redirect_uri)
    _persist_token_response(payload)
    return "Spotify linked. You can use voice controls now."


def _start_background_auth() -> None:
    """Open browser + local callback without blocking the voice loop."""
    global _auth_bg_started
    with _auth_bg_lock:
        if _auth_bg_started:
            return
        _auth_bg_started = True

    def _worker():
        global _auth_bg_started
        try:
            _run_oauth_flow(timeout=180.0, open_browser=True)
        except Exception:
            pass
        finally:
            with _auth_bg_lock:
                _auth_bg_started = False

    threading.Thread(target=_worker, daemon=True).start()


def _refresh_access_token() -> str | None:
    cfg = _spotify_cfg()
    client_id = str(cfg.get("client_id") or "").strip()
    refresh = str(cfg.get("refresh_token") or "").strip()
    if not client_id or not refresh:
        return None
    r = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": client_id,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=20,
    )
    if r.status_code != 200:
        try:
            err = r.json().get("error")
        except Exception:
            err = None
        if err == "invalid_grant" or r.status_code in (400, 401):
            _clear_tokens()
        return None
    payload = r.json()
    _persist_token_response(payload, keep_refresh=refresh)
    return str(payload.get("access_token") or "")


def _get_access_token() -> str | None:
    cfg = _spotify_cfg()
    access = str(cfg.get("access_token") or "").strip()
    expires_at = float(cfg.get("expires_at") or 0)
    if access and time.time() < expires_at:
        return access
    return _refresh_access_token() or (access if access else None)


def _auth_status() -> str | None:
    """Return an error string if auth is missing; else None."""
    cfg = _spotify_cfg()
    client_id = str(cfg.get("client_id") or "").strip()
    if not client_id:
        return (
            "Spotify is not configured. Create an app at "
            "https://developer.spotify.com/dashboard with redirect URI "
            f"{DEFAULT_REDIRECT}, then add "
            '{"spotify": {"client_id": "YOUR_CLIENT_ID", '
            f'"redirect_uri": "{DEFAULT_REDIRECT}"}} '
            "to config/api_keys.json next to Athena.exe. After that, "
            f"{_login_hint()}."
        )
    if not str(cfg.get("refresh_token") or "").strip():
        _start_background_auth()
        return (
            "AUTH_REQUIRED: Finish Spotify login in the browser that just opened "
            f"({_login_hint()})."
        )
    if not _get_access_token():
        _start_background_auth()
        return (
            "AUTH_REQUIRED: Spotify session expired. Finish login in the browser "
            f"({_login_hint()})."
        )
    return None


# ---------------------------------------------------------------------------
# Web API client
# ---------------------------------------------------------------------------

def _api(
    method: str,
    path: str,
    *,
    params: dict | None = None,
    body: dict | None = None,
    token: str | None = None,
    retry_401: bool = True,
    retry_429: bool = True,
) -> tuple[int, Any]:
    tok = token or _get_access_token()
    if not tok:
        return 401, {"error": {"message": "No access token"}}

    url = path if path.startswith("http") else f"{API_BASE}{path}"
    headers = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    data = json.dumps(body).encode("utf-8") if body is not None else None

    try:
        r = requests.request(method, url, headers=headers, params=params, data=data, timeout=15)
    except Exception as e:
        return 0, {"error": {"message": str(e)}}

    status = r.status_code
    if status == 401 and retry_401:
        new_tok = _refresh_access_token()
        if new_tok:
            return _api(method, path, params=params, body=body, token=new_tok, retry_401=False, retry_429=retry_429)
        _clear_tokens()
        return 401, {"error": {"message": "unauthorized"}}

    if status == 429 and retry_429:
        wait = float(r.headers.get("Retry-After") or 1)
        time.sleep(min(max(wait, 0.5), 5.0))
        return _api(method, path, params=params, body=body, token=tok, retry_401=False, retry_429=False)

    if not r.content:
        return status, None
    try:
        return status, r.json()
    except Exception:
        return status, {"raw": r.text[:300]}


# ---------------------------------------------------------------------------
# Device targeting
# ---------------------------------------------------------------------------

def _pick_desktop_device(devices: list[dict]) -> dict | None:
    computers = [d for d in devices if str(d.get("type") or "").lower() == "computer"]
    pool = computers or devices
    if not pool:
        return None

    def score(d: dict) -> tuple:
        name = str(d.get("name") or "").lower()
        is_spotify = 1 if "spotify" in name else 0
        is_computer = 1 if str(d.get("type") or "").lower() == "computer" else 0
        # Prefer desktop Spotify; never prefer phone just because active
        return (is_computer, is_spotify, 1 if d.get("is_active") else 0)

    return max(pool, key=score)


def _resolve_desktop_device(poll_s: float = 5.0) -> tuple[str | None, str | None]:
    """
    Returns (device_id, error_message).
    Starts desktop app, polls Connect, transfers if needed.
    """
    if not _ensure_spotify():
        return None, "Could not start Spotify. Is it installed and signed in?"

    deadline = time.monotonic() + poll_s
    device = None
    while time.monotonic() < deadline:
        status, data = _api("GET", "/me/player/devices")
        if status == 200 and isinstance(data, dict):
            devices = data.get("devices") or []
            device = _pick_desktop_device(devices)
            if device and device.get("id"):
                break
        time.sleep(0.4)

    if not device or not device.get("id"):
        return None, (
            "Spotify Desktop is not visible to Connect. "
            "Open Spotify, sign in, and try again."
        )

    device_id = str(device["id"])
    if not device.get("is_active"):
        st, _ = _api(
            "PUT",
            "/me/player",
            body={"device_ids": [device_id], "play": False},
        )
        if st in (200, 202, 204):
            time.sleep(0.7)
        elif st == 404:
            time.sleep(0.7)
    return device_id, None


def _player_play(device_id: str, body: dict) -> tuple[int, Any]:
    status, data = _api(
        "PUT",
        "/me/player/play",
        params={"device_id": device_id},
        body=body,
    )
    if status == 404:
        time.sleep(0.7)
        status, data = _api(
            "PUT",
            "/me/player/play",
            params={"device_id": device_id},
            body=body,
            retry_401=False,
        )
    return status, data


def _get_playback() -> dict:
    status, data = _api("GET", "/me/player")
    if status == 200 and isinstance(data, dict):
        return data
    return {}


def _proof_from_playback(pb: dict) -> str:
    item = pb.get("item") or {}
    name = item.get("name") or ""
    artists = ", ".join(
        a.get("name", "") for a in (item.get("artists") or []) if a.get("name")
    )
    ctx = (pb.get("context") or {}) or {}
    ctx_type = str(ctx.get("type") or "")
    shuffle = "on" if pb.get("shuffle_state") else "off"
    repeat = str(pb.get("repeat_state") or "off")
    is_playing = bool(pb.get("is_playing"))
    track = name
    if artists:
        track = f"{name} by {artists}" if name else artists
    parts = []
    if track:
        parts.append(track)
    if ctx_type == "playlist":
        parts.append("(playlist)")
    elif ctx_type == "collection":
        parts.append("(Liked Songs)")
    status = "playing" if is_playing else "paused"
    extra = f"shuffle {shuffle}, repeat {repeat}"
    if parts:
        return f"{status}: {', '.join(parts)}; {extra}"
    return f"{status}; {extra}"


# ---------------------------------------------------------------------------
# Playlists / search
# ---------------------------------------------------------------------------

def _current_user_id() -> str:
    if _playlist_cache.get("user_id"):
        return str(_playlist_cache["user_id"])
    status, data = _api("GET", "/me")
    if status == 200 and isinstance(data, dict):
        uid = str(data.get("id") or "")
        _playlist_cache["user_id"] = uid
        return uid
    return ""


def _fetch_playlists(force: bool = False) -> list[dict]:
    now = time.time()
    if not force and _playlist_cache["items"] and now - float(_playlist_cache["ts"]) < 300:
        return list(_playlist_cache["items"])

    items: list[dict] = []
    offset = 0
    while True:
        status, data = _api(
            "GET",
            "/me/playlists",
            params={"limit": 50, "offset": offset},
        )
        if status != 200 or not isinstance(data, dict):
            break
        batch = data.get("items") or []
        items.extend(batch)
        if len(batch) < 50 or not data.get("next"):
            break
        offset += 50
        if offset > 500:
            break

    _playlist_cache["items"] = items
    _playlist_cache["ts"] = now
    return items


def _playlist_score(query: str, name: str) -> float:
    q = _norm_text(query)
    n = _norm_text(name)
    if not q or not n:
        return 0.0
    if q == n:
        return 1.0
    if n.startswith(q) or q.startswith(n):
        return 0.92
    if q in n or n in q:
        return 0.85
    return SequenceMatcher(None, q, n).ratio()


def _match_playlist(query: str) -> dict | None:
    playlists = _fetch_playlists()
    if not playlists:
        return None
    uid = _current_user_id()
    scored: list[tuple[float, dict]] = []
    for pl in playlists:
        name = pl.get("name") or ""
        sc = _playlist_score(query, name)
        if sc < 0.72:
            continue
        owner = ((pl.get("owner") or {}).get("id") or "")
        if uid and owner == uid:
            sc += 0.02
        scored.append((sc, pl))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def _search_track(query: str) -> dict | None:
    track_q, artist_q = _parse_by_query(query)
    if artist_q:
        q = f'track:"{track_q}" artist:"{artist_q}"'
    else:
        q = track_q
    status, data = _api(
        "GET",
        "/search",
        params={"q": q, "type": "track", "limit": 5},
    )
    if status != 200 or not isinstance(data, dict):
        # Fallback without field filters
        status, data = _api(
            "GET",
            "/search",
            params={"q": query, "type": "track", "limit": 5},
        )
    if status != 200 or not isinstance(data, dict):
        return None
    items = ((data.get("tracks") or {}).get("items")) or []
    if not items:
        return None

    tq = _norm_text(track_q)
    aq = _norm_text(artist_q)

    def score(tr: dict) -> float:
        name = _norm_text(tr.get("name") or "")
        arts = [_norm_text(a.get("name") or "") for a in (tr.get("artists") or [])]
        ns = SequenceMatcher(None, tq, name).ratio() if tq else 0
        if tq == name:
            ns = 1.0
        elif tq and tq in name:
            ns = max(ns, 0.9)
        as_ = 0.0
        if aq:
            as_ = max((SequenceMatcher(None, aq, a).ratio() for a in arts), default=0)
            if any(aq == a or aq in a for a in arts):
                as_ = max(as_, 0.95)
        else:
            as_ = 0.5
        return ns * 0.65 + as_ * 0.35

    return max(items, key=score)


# ---------------------------------------------------------------------------
# Shuffle / repeat
# ---------------------------------------------------------------------------

def _apply_shuffle(device_id: str, state: str) -> str:
    s = (state or "").lower().strip()
    if s in ("toggle", ""):
        pb = _get_playback()
        want = not bool(pb.get("shuffle_state"))
    elif s in ("on", "true", "1", "yes"):
        want = True
    elif s in ("off", "false", "0", "no"):
        want = False
    else:
        return f"Unknown shuffle state '{state}'. Use on, off, or toggle."

    st, _ = _api(
        "PUT",
        "/me/player/shuffle",
        params={"state": "true" if want else "false", "device_id": device_id},
    )
    if st == 403:
        return "Shuffle needs Spotify Premium."
    if st not in (200, 202, 204):
        return f"Could not set shuffle ({st})."
    return f"Shuffle {'on' if want else 'off'}."


def _map_repeat(state: str, current: str | None = None) -> str | None:
    s = (state or "").lower().strip()
    if s in ("on", "context", "playlist", "all"):
        return "context"
    if s in ("off", "false", "0", "no"):
        return "off"
    if s in ("track", "song", "one"):
        return "track"
    if s in ("toggle", ""):
        cur = (current or "off").lower()
        return "off" if cur in ("context", "track") else "context"
    return None


def _apply_repeat(device_id: str, state: str) -> str:
    pb = _get_playback()
    mapped = _map_repeat(state, str(pb.get("repeat_state") or "off"))
    if not mapped:
        return f"Unknown repeat state '{state}'. Use on, off, track, or toggle."
    st, _ = _api(
        "PUT",
        "/me/player/repeat",
        params={"state": mapped, "device_id": device_id},
    )
    if st == 403:
        return "Repeat needs Spotify Premium."
    if st not in (200, 202, 204):
        return f"Could not set repeat ({st})."
    label = {"off": "off", "context": "on", "track": "track"}.get(mapped, mapped)
    return f"Repeat {label}."


# ---------------------------------------------------------------------------
# SMTC / OS transport fallback (thin)
# ---------------------------------------------------------------------------

def _run_async(coro):
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        box: dict = {}

        def _runner():
            try:
                box["result"] = asyncio.run(coro)
            except Exception as e:
                box["error"] = e

        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        t.join(timeout=6)
        if "error" in box:
            raise box["error"]
        return box.get("result")
    return asyncio.run(coro)


def _smtc_command(command: str) -> bool:
    if sys.platform != "win32":
        return False
    try:
        from winrt.windows.media.control import (  # type: ignore
            GlobalSystemMediaTransportControlsSessionManager as SMTC,
        )

        async def _go():
            mgr = await SMTC.request_async()
            session = None
            for s in mgr.get_sessions():
                app = str(getattr(s, "source_app_user_model_id", "") or "").lower()
                if "spotify" in app:
                    session = s
                    break
            if not session:
                return False
            mapping = {
                "play": "try_play_async",
                "pause": "try_pause_async",
                "next": "try_skip_next_async",
                "previous": "try_skip_previous_async",
            }
            method = getattr(session, mapping.get(command, ""), None)
            if not callable(method):
                return False
            return bool(await method())

        return bool(_run_async(_go()))
    except Exception:
        return False


def _macos_transport(action: str) -> bool:
    verbs = {
        "next": "next track",
        "previous": "previous track",
        "play": "play",
        "pause": "pause",
    }
    verb = verbs.get(action)
    if not verb:
        return False
    try:
        r = subprocess.run(
            ["osascript", "-e", f'tell application "Spotify" to {verb}'],
            capture_output=True,
            timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


def _linux_transport(action: str) -> bool:
    verbs = {
        "next": "Next",
        "previous": "Previous",
        "play": "Play",
        "pause": "Pause",
    }
    verb = verbs.get(action)
    if not verb:
        return False
    try:
        r = subprocess.run(
            ["playerctl", "-p", "spotify", verb.lower()],
            capture_output=True,
            timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


def _transport_fallback(action: str) -> str | None:
    if sys.platform == "darwin":
        if _macos_transport(action):
            return f"Spotify {action} (macOS)."
        return None
    if sys.platform.startswith("linux"):
        if _linux_transport(action):
            return f"Spotify {action} (playerctl)."
        return None
    if _smtc_command(action):
        time.sleep(0.25)
        return f"Spotify {action} via system media controls."
    return None


# ---------------------------------------------------------------------------
# Play classifier + actions
# ---------------------------------------------------------------------------

def _play_liked(device_id: str) -> str:
    uid = _current_user_id()
    if uid:
        status, data = _player_play(
            device_id,
            {"context_uri": f"spotify:user:{uid}:collection"},
        )
        if status in (200, 202, 204):
            time.sleep(0.35)
            return f"Playing Liked Songs. {_proof_from_playback(_get_playback())}"
        if status == 403:
            return "Playing Liked Songs needs Spotify Premium."
        if status == 400:
            pass  # try URI fallback
        elif status not in (404,):
            msg = ""
            if isinstance(data, dict):
                msg = ((data.get("error") or {}).get("message") or "")
            if msg and "context" not in msg.lower():
                return f"Could not play Liked Songs ({status}): {msg}"

    _open_uri("spotify:collection:tracks")
    time.sleep(1.0)
    # Re-resolve / transfer then try context again
    did, err = _resolve_desktop_device(poll_s=3.0)
    device_id = did or device_id
    if uid:
        status, _ = _player_play(
            device_id,
            {"context_uri": f"spotify:user:{uid}:collection"},
        )
        if status in (200, 202, 204):
            time.sleep(0.35)
            return f"Playing Liked Songs. {_proof_from_playback(_get_playback())}"

    # Last resort: first page of saved tracks
    status, data = _api("GET", "/me/tracks", params={"limit": 50})
    if status == 200 and isinstance(data, dict):
        uris = [
            (it.get("track") or {}).get("uri")
            for it in (data.get("items") or [])
            if (it.get("track") or {}).get("uri")
        ]
        uris = [u for u in uris if u]
        if uris:
            st, _ = _player_play(device_id, {"uris": uris})
            if st in (200, 202, 204):
                return (
                    "Playing Liked Songs (first 50 only — full collection "
                    f"unavailable via API). {_proof_from_playback(_get_playback())}"
                )
            if st == 403:
                return "Playing Liked Songs needs Spotify Premium."

    return "Opened Liked Songs in Spotify, but could not start playback via API."


def _play_playlist(device_id: str, pl: dict) -> str:
    uri = pl.get("uri")
    name = pl.get("name") or "playlist"
    if not uri:
        return f"Playlist '{name}' has no URI."
    status, data = _player_play(device_id, {"context_uri": uri})
    if status == 403:
        return "Playing playlists needs Spotify Premium."
    if status == 404:
        _open_uri(uri)
        time.sleep(0.8)
        status, data = _player_play(device_id, {"context_uri": uri})
    if status in (200, 202, 204):
        time.sleep(0.35)
        return f"Playing playlist '{name}'. {_proof_from_playback(_get_playback())}"
    msg = ""
    if isinstance(data, dict):
        msg = ((data.get("error") or {}).get("message") or "")
    return f"Could not play playlist '{name}' ({status}){': ' + msg if msg else ''}."


def _play_track(device_id: str, query: str) -> str:
    track = _search_track(query)
    if not track:
        return f"No Spotify track found for '{query}'."
    uri = track.get("uri")
    name = track.get("name") or query
    artists = ", ".join(
        a.get("name", "") for a in (track.get("artists") or []) if a.get("name")
    )
    label = f"{name}" + (f" by {artists}" if artists else "")
    if not uri:
        return f"Found {label} but it has no URI."
    status, data = _player_play(device_id, {"uris": [uri]})
    if status == 403:
        return f"Playing tracks needs Spotify Premium. Found: {label}."
    if status == 404:
        _open_uri(uri)
        time.sleep(0.8)
        status, data = _player_play(device_id, {"uris": [uri]})
    if status in (200, 202, 204):
        time.sleep(0.35)
        return f"Playing {label}. {_proof_from_playback(_get_playback())}"
    msg = ""
    if isinstance(data, dict):
        msg = ((data.get("error") or {}).get("message") or "")
    return f"Could not play {label} ({status}){': ' + msg if msg else ''}."


def _resume(device_id: str) -> str:
    status, data = _api("PUT", "/me/player/play", params={"device_id": device_id}, body={})
    if status == 404:
        time.sleep(0.6)
        status, data = _api(
            "PUT", "/me/player/play", params={"device_id": device_id}, body={}, retry_401=False
        )
    if status == 403:
        return "Resume needs Spotify Premium."
    if status in (200, 202, 204):
        time.sleep(0.3)
        return f"Resumed. {_proof_from_playback(_get_playback())}"
    fb = _transport_fallback("play")
    if fb:
        return fb
    msg = ""
    if isinstance(data, dict):
        msg = ((data.get("error") or {}).get("message") or "")
    return f"Could not resume ({status}){': ' + msg if msg else ''}."


def _transport_api(action: str, device_id: str) -> str:
    endpoints = {
        "pause": ("PUT", "/me/player/pause"),
        "next": ("POST", "/me/player/next"),
        "previous": ("POST", "/me/player/previous"),
    }
    spec = endpoints.get(action)
    if not spec:
        return f"Unknown transport action: {action}"
    method, path = spec
    status, data = _api(method, path, params={"device_id": device_id})
    if status == 404:
        time.sleep(0.5)
        status, data = _api(method, path, params={"device_id": device_id}, retry_401=False)
    if status == 403:
        return f"{action.capitalize()} needs Spotify Premium."
    if status in (200, 202, 204):
        time.sleep(0.35)
        pb = _get_playback()
        if action == "pause":
            return f"Paused. {_proof_from_playback(pb)}"
        if action == "next":
            return f"Skipped. {_proof_from_playback(pb)}"
        if action == "previous":
            return f"Previous track. {_proof_from_playback(pb)}"
        return f"Spotify {action}. {_proof_from_playback(pb)}"

    fb = _transport_fallback(action)
    if fb:
        return fb
    msg = ""
    if isinstance(data, dict):
        msg = ((data.get("error") or {}).get("message") or "")
    return f"Could not {action} ({status}){': ' + msg if msg else ''}."


def _do_play(
    query: str,
    *,
    shuffle: str = "",
    repeat: str = "",
    force_liked: bool = False,
    force_playlist: bool = False,
) -> str:
    device_id, err = _resolve_desktop_device()
    if err or not device_id:
        return err or "No Spotify desktop device."

    q = (query or "").strip()

    if force_liked or (q and _is_liked_query(q)):
        result = _play_liked(device_id)
    elif not q:
        result = _resume(device_id)
    else:
        pl = _match_playlist(q)
        score = _playlist_score(q, pl.get("name") or "") if pl else 0.0
        if force_playlist:
            if not pl:
                return f"No playlist matching '{q}' in your library."
            result = _play_playlist(device_id, pl)
        elif pl and score >= 0.80:
            result = _play_playlist(device_id, pl)
        else:
            result = _play_track(device_id, q)

    # Compound shuffle/repeat on the same call (after play)
    fail_prefix = result.startswith("Could not") or result.startswith("AUTH")
    if not fail_prefix and "Premium" not in result:
        extras = []
        if shuffle:
            extras.append(_apply_shuffle(device_id, shuffle))
        if repeat:
            extras.append(_apply_repeat(device_id, repeat))
        if extras:
            result = result.rstrip(".") + ". " + " ".join(extras)
    return result


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------

def spotify_control(
    parameters: dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    raw_action = str(params.get("action", "play"))
    action = _normalize_action(raw_action)
    query = str(
        params.get("query")
        or params.get("song")
        or params.get("track")
        or params.get("name")
        or params.get("playlist")
        or ""
    ).strip()

    shuffle_opt = str(params.get("shuffle") or "").strip().lower()
    repeat_opt = str(params.get("repeat") or "").strip().lower()
    state = str(params.get("state") or "").strip().lower()

    raw_lower = raw_action.lower().replace(" ", "_").replace("-", "_")
    force_liked = raw_lower == "play_liked"
    force_playlist = raw_lower == "play_playlist"
    if force_liked and not query:
        query = "liked songs"

    if player:
        player.write_log(f"[spotify] {action} {query} shuffle={shuffle_opt} repeat={repeat_opt}")

    try:
        auth_err = _auth_status()
        if auth_err:
            if action in ("pause", "next", "previous") or (action == "play" and not query and not force_liked):
                fb = _transport_fallback("play" if action == "play" else action)
                if fb:
                    return f"{auth_err} (partial: {fb})"
            return auth_err

        if action == "shuffle":
            device_id, err = _resolve_desktop_device()
            if err or not device_id:
                return err or "No Spotify desktop device."
            return _apply_shuffle(device_id, state or shuffle_opt or "toggle")

        if action == "repeat":
            device_id, err = _resolve_desktop_device()
            if err or not device_id:
                return err or "No Spotify desktop device."
            return _apply_repeat(device_id, state or repeat_opt or "toggle")

        if action in ("pause", "next", "previous"):
            device_id, err = _resolve_desktop_device()
            if err or not device_id:
                fb = _transport_fallback(action)
                return fb or (err or "No Spotify desktop device.")
            return _transport_api(action, device_id)

        if action == "play":
            return _do_play(
                query,
                shuffle=shuffle_opt,
                repeat=repeat_opt,
                force_liked=force_liked,
                force_playlist=force_playlist,
            )

        return (
            f"Unknown Spotify action: '{action}'. "
            "Use play, pause, next, previous, shuffle, or repeat."
        )
    except Exception as e:
        return f"Spotify error: {e}"


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Athena Spotify controls")
    parser.add_argument(
        "--login",
        action="store_true",
        help="Run PKCE OAuth and save tokens to config/api_keys.json",
    )
    parser.add_argument("--action", default="", help="Test an action")
    parser.add_argument("--query", default="", help="Query for play")
    parser.add_argument("--shuffle", default="", help="on|off|toggle")
    parser.add_argument("--repeat", default="", help="on|off|track|toggle")
    args = parser.parse_args()

    if args.login:
        try:
            print(_run_oauth_flow(timeout=180.0, open_browser=True))
        except Exception as e:
            print(f"Login failed: {e}", file=sys.stderr)
            sys.exit(1)
        return

    if args.action:
        msg = spotify_control(
            parameters={
                "action": args.action,
                "query": args.query,
                "shuffle": args.shuffle,
                "repeat": args.repeat,
            }
        )
        print(msg)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
