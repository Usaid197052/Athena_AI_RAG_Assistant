"""
Trading-only Athena. Separate process from main.py — no assistant tools, no AthenaLive.
Run: python trading_main.py
"""
import platform as _platform
import subprocess as _subprocess

if _platform.system() == "Windows":
    _OrigPopen = _subprocess.Popen

    class _Popen(_OrigPopen):
        def __init__(self, args, **kw):
            kw["creationflags"] = kw.get("creationflags", 0) | _subprocess.CREATE_NO_WINDOW
            kw.pop("startupinfo", None)
            super().__init__(args, **kw)

    _subprocess.Popen = _Popen

import asyncio
import json
import multiprocessing
import os
import re
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8", errors="replace")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8", errors="replace")

import sounddevice as sd
from google import genai
from google.genai import types

from ui import AthenaUI
from memory.config_manager import DEFAULT_ASSISTANT_NAME
from memory.memory_manager import get_response_language, reset_response_language
from actions.mt5_analysis import mt5_analysis, capture_chart_snapshot, CHART_ANALYSIS_PROMPT
from actions.trading_desk import (
    load_trading_config,
    refresh_hud,
    set_paused,
    trading_control,
    trading_desk,
    watch_tick,
)
from actions.web_search import web_search as web_search_action
from core.gemini_models import get_live_model
from core.permissions import evaluate_permission
from core.trading_logger import (
    get_logger as get_trading_logger,
    log_path as trading_log_path,
    set_hud_sink as set_trading_hud_sink,
    tlog,
)


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH = BASE_DIR / "core" / "prompt_trading.txt"
CHANNELS = 1
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 1024

_CTRL_RE = re.compile(r"<ctrl\d+>", re.IGNORECASE)


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are Athena trading desk. Speak BIAS BUY, SELL, or WAIT. "
            "Never invent fills. Never call share_screen. Never place orders yourself."
        )


def _clean_transcript(text: str) -> str:
    text = _CTRL_RE.sub("", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return text.strip()


def classify_exit_intent(text: str) -> str | None:
    raw = (text or "").strip().lower()
    if not raw:
        return None
    compact = re.sub(r"[\s'_]+", "", raw)
    cleaned = re.sub(r"\s+", " ", raw)
    if any(x in cleaned for x in (
        "the computer", "the pc", "the laptop", "my computer", "my pc",
        "this computer", "this pc",
    )):
        return None
    if re.search(r"\b(pc|computer|laptop|desktop)\b", cleaned):
        return None
    if any(p in compact for p in (
        "shutdownyourself", "quitathena", "exitathena", "shutdowncompletely",
        "athenashutdown", "shutyourself",
    )):
        return "shutdown"
    if any(p in cleaned for p in (
        "quit athena", "shut down completely", "shut yourself down", "shutdown",
    )):
        return "shutdown"
    if re.search(r"shut\s*down", cleaned) or "shutdown" in compact:
        return "shutdown"
    return None


TOOL_DECLARATIONS = [
    {
        "name": "trading_desk",
        "description": (
            "Run the trading desk on a symbol: TA + FA + session hours + news blackout + risk. "
            "If BIAS is BUY or SELL and every gate passes, the executor places a demo market order "
            "with SL and TP. You never place the order yourself. "
            "Speak BIAS and FILLED/CLOSED/BLOCKED/WAIT exactly as returned. Never invent a fill."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "symbol": {"type": "STRING", "description": "MT5 symbol e.g. EURUSD (default from config)"},
                "timeframe": {"type": "STRING", "description": "M1 | M5 | M15 | M30 | H1 | H4 | D1 (default config)"},
            },
            "required": [],
        },
    },
    {
        "name": "mt5_analysis",
        "description": (
            "Read-only MetaTrader 5 analysis. Never places orders. "
            "quote / ta / analyze / fa / status / snapshot. "
            "After ta or analyze you MUST speak BIAS BUY|SELL|WAIT. "
            "snapshot = one still of the MT5 window. NEVER share_screen."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "status | quote | ta | analyze | fa | snapshot (default: analyze)",
                },
                "symbol": {"type": "STRING", "description": "EURUSD, XAUUSD, ..."},
                "timeframe": {"type": "STRING", "description": "M1 | M5 | M15 | M30 | H1 | H4 | D1"},
                "fundamentals": {"type": "BOOLEAN", "description": "With analyze, also fetch news"},
                "text": {"type": "STRING", "description": "Question about the chart (snapshot)"},
            },
            "required": [],
        },
    },
    {
        "name": "trading_control",
        "description": (
            "Desk controls. status = P&L and positions. "
            "pause = stop the auto watch-loop. resume = start it. "
            "flatten = close only Athena magic-number positions."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "status | pause | resume | flatten",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "web_search",
        "description": "Web or news search for extra event context. Prefer mode=news for prints.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Search query"},
                "mode": {"type": "STRING", "description": "search | news | research"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "sleep_assistant",
        "description": (
            "Hide the HUD, pause auto-trade, keep the process in the tray. "
            "Not a PC sleep and not a full quit."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "shutdown_athena",
        "description": (
            "Quit this trading process. Pauses auto-trade. Not the PC. "
            "Call for quit Athena / shut down completely."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
]


class SleepRequested(Exception):
    """Tear down the Gemini TaskGroup when the HUD sleeps."""


class TradingLive:
    def __init__(self, ui: AthenaUI):
        self.ui = ui
        self._asst_name = DEFAULT_ASSISTANT_NAME
        self.session = None
        self.audio_in_queue = None
        self.out_queue = None
        self._loop = None
        self._is_speaking = False
        self._speaking_lock = threading.Lock()
        self._pending_vision = None
        self._vision_last_time = 0.0
        self._vision_busy = False
        self._interrupted = False
        self._shutdown_started = False
        self._hold_mic = False
        self._last_model_audio = 0.0
        reset_response_language()
        self.ui.on_text_command = self._on_text_command
        self.ui.on_interrupt = self.interrupt
        self.ui.on_sleep_requested = self.request_sleep
        self.ui.on_wake_requested = self.request_wake
        self.ui.on_quit_requested = self.request_quit
        self.ui.on_api_config_saved = self.request_reconnect
        self.ui.on_trading_control = self._on_trading_hud
        self._hud_sleeping = False
        self._sleep_request: asyncio.Event | None = None
        self._wake_event: asyncio.Event | None = None
        self._reconnect_needed = False
        self._wake_listener = None
        self._pending_wake_greeting = False
        get_trading_logger()
        _orig_write = self.ui.write_log

        def _logged_write(text: str):
            _orig_write(text)
            try:
                tlog(text, "info")
            except Exception:
                pass

        self.ui.write_log = _logged_write  # type: ignore[method-assign]
        set_trading_hud_sink(self.ui.write_log)
        tlog(f"Trading logger ready → {trading_log_path()}")
        self._turn_done_event: asyncio.Event | None = None
        self._session_log: list[str] = []
        self._conn_backoff = 3
        try:
            refresh_hud(self.ui)
        except Exception as e:
            tlog(f"initial HUD: {e}", "warning")

    def request_sleep(self) -> None:
        if self._hud_sleeping:
            return
        self._hud_sleeping = True
        try:
            set_paused(True, persist=False)
        except Exception:
            pass
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
        was = self._hud_sleeping
        self._hud_sleeping = False
        self._hold_mic = False
        try:
            set_paused(False, persist=False)
        except Exception:
            pass
        try:
            self.ui.show_from_tray()
        except Exception:
            pass
        if was:
            self._pending_wake_greeting = True
            self.ui.set_state("THINKING")
        if self._loop and self._wake_event is not None:
            self._loop.call_soon_threadsafe(self._wake_event.set)

    def request_quit(self) -> None:
        self.ui.write_log("SYS: Quit requested from tray.")
        try:
            self._stop_wake_listener()
        except Exception:
            pass
        os._exit(0)

    def _begin_shutdown(self) -> None:
        if getattr(self, "_shutdown_started", False):
            return
        self._shutdown_started = True
        self._hold_mic = True
        try:
            set_paused(True, persist=False)
        except Exception:
            pass
        self.ui.write_log("SYS: Shutdown requested.")

        async def _do_shutdown():
            try:
                await asyncio.wait_for(self._wait_for_farewell_speech(), timeout=8.0)
            except Exception:
                pass
            await asyncio.sleep(0.25)
            try:
                self._stop_wake_listener()
            except Exception:
                pass
            tlog("SYS: Trading shutdown complete.")
            os._exit(0)

        if self._loop:
            self._loop.call_soon_threadsafe(lambda: asyncio.create_task(_do_shutdown()))
        else:
            asyncio.create_task(_do_shutdown())

    def request_reconnect(self) -> None:
        self._reconnect_needed = True
        try:
            self.ui.write_log("SYS: Reconnecting with saved API key / voice model…")
            self.ui.set_state("THINKING")
        except Exception:
            pass
        if self._loop and self._sleep_request is not None:
            self._loop.call_soon_threadsafe(self._sleep_request.set)
        elif self._loop and self._wake_event is not None:
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
        try:
            if isinstance(exc, BaseExceptionGroup):
                return any(TradingLive._is_sleep_exc(e) for e in exc.exceptions)
        except NameError:
            pass
        return "SLEEP_REQUESTED" in str(exc)

    async def _sleep_watcher(self):
        assert self._sleep_request is not None
        await self._sleep_request.wait()
        raise SleepRequested("SLEEP_REQUESTED")

    def _on_text_command(self, text: str):
        if not self._loop:
            return
        exit_kind = classify_exit_intent(text)
        if exit_kind == "shutdown":
            self._begin_shutdown()
            return
        if not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True,
            ),
            self._loop,
        )

    def _on_trading_hud(self, action: str) -> None:
        if not self._loop:
            trading_control({"action": action}, player=self.ui)
            return
        asyncio.run_coroutine_threadsafe(self._hud_control(action), self._loop)

    async def _hud_control(self, action: str) -> None:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: trading_control({"action": action}, player=self.ui)
        )
        self.ui.write_log(f"SYS: {str(result)[:240]}")
        if self.session and action in ("pause", "resume", "flatten"):
            try:
                await self.session.send_client_content(
                    turns={"parts": [{
                        "text": (
                            f"[DESK] HUD {action}: {result}\n"
                            "Say this outcome briefly. Do not call a tool."
                        )
                    }]},
                    turn_complete=True,
                )
            except Exception:
                pass

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
        recent = (time.monotonic() - self._last_model_audio) < 1.4
        return queued or speaking or recent

    async def _wait_for_farewell_speech(self, timeout: float = 36.0) -> None:
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
        quiet_needed = 1.5
        quiet_start = None
        while time.monotonic() < end_deadline:
            if self._speech_busy():
                quiet_start = None
            else:
                if quiet_start is None:
                    quiet_start = time.monotonic()
                elif time.monotonic() - quiet_start >= quiet_needed:
                    return
            await asyncio.sleep(0.05)

    def interrupt(self) -> None:
        if getattr(self, "_shutdown_started", False) or self._hold_mic:
            return
        self._interrupted = True
        q = self.audio_in_queue
        if q:
            while True:
                try:
                    q.get_nowait()
                except Exception:
                    break
        self.set_speaking(False)
        if self._turn_done_event:
            self._turn_done_event.clear()
        self.ui.write_log("SYS: Interrupted — listening...")

    def _build_config(self) -> types.LiveConnectConfig:
        try:
            _cfg = json.loads(open(API_CONFIG_PATH, encoding="utf-8").read())
            self._asst_name = (_cfg.get("assistant_name") or DEFAULT_ASSISTANT_NAME).strip()
            _user_name = (_cfg.get("user_name") or "").strip()
        except Exception:
            self._asst_name = DEFAULT_ASSISTANT_NAME
            _user_name = ""

        sys_prompt = _load_system_prompt()
        now = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
        _addr = (
            f'ADDRESS: Always call the user \'{_user_name}\' and say "sir".'
            if _user_name else
            'ADDRESS: Always address the user as "sir".'
        )
        identity_ctx = (
            f"[IDENTITY]\n"
            f"Your name is {self._asst_name}. You are a woman — the trading desk, not the general assistant. "
            f"Always refer to yourself as {self._asst_name}. Never call yourself Jarvis.\n"
            f"{_addr}\n"
            f"RESPONSE LANGUAGE: Default English. Currently speaking {get_response_language()}.\n"
            f"You never call order_send. Speak BIAS and actual FILLED/CLOSED/BLOCKED only.\n\n"
        )
        time_ctx = (
            f"[CURRENT DATE & TIME]\nRight now it is: {time_str}\n\n"
        )
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join([time_ctx, identity_ctx, sys_prompt]),
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
        print(f"[TRADE] 🔧 {name}  {args}")
        tlog(f"TOOL {name} {args}")
        self.ui.set_state("THINKING")

        decision = evaluate_permission(name, args)
        if not decision.allowed:
            msg = decision.reason or "Action denied."
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(id=fc.id, name=name, response={"result": msg})

        loop = asyncio.get_event_loop()
        result = "Done."
        try:
            if name == "trading_desk":
                r = await loop.run_in_executor(
                    None, lambda: trading_desk(parameters=args, player=self.ui)
                )
                result = r or "Desk failed."
            elif name == "trading_control":
                r = await loop.run_in_executor(
                    None, lambda: trading_control(parameters=args, player=self.ui)
                )
                result = r or "Control failed."
            elif name == "mt5_analysis":
                _mt5_act = str(args.get("action") or "analyze").strip().lower().replace("-", "_")
                if _mt5_act == "snapshot":
                    _now = time.monotonic()
                    if self._vision_busy or (_now - self._vision_last_time) < 4.0:
                        result = (
                            "A chart snapshot is still being processed. "
                            "Do not call mt5_analysis snapshot again."
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
                            result = f"Chart snapshot failed: {e}."
                        else:
                            user_q = str(
                                args.get("text") or args.get("question") or "Analyze this chart."
                            ).strip()
                            prompt = (
                                f"{CHART_ANALYSIS_PROMPT}\n{note}\n"
                                f"User request: {user_q}"
                            )
                            self._pending_vision = (img_b, mime_t, prompt)
                            result = (
                                f"[VISION_ACTIVE] Chart captured ({note}). "
                                f"Immediately say ONE short sentence in {get_response_language()}, "
                                "telling them you are looking at the chart. "
                                "Do not guess content. Never call share_screen."
                            )
                else:
                    r = await loop.run_in_executor(
                        None, lambda: mt5_analysis(parameters=args, player=self.ui)
                    )
                    result = r or "MT5 analysis failed."
            elif name == "web_search":
                r = await loop.run_in_executor(
                    None, lambda: web_search_action(parameters=args, player=self.ui)
                )
                result = r or "Done."
            elif name == "sleep_assistant":
                if getattr(self, "_shutdown_started", False):
                    result = "Shutdown already in progress."
                else:
                    self._hold_mic = True
                    self.ui.write_log("SYS: Sleep requested — auto-trade paused.")

                    async def _do_sleep():
                        await self._wait_for_farewell_speech()
                        await asyncio.sleep(0.35)
                        self.request_sleep()

                    asyncio.create_task(_do_sleep())
                    result = (
                        f"Going to sleep. Auto-trade paused. "
                        f"Say Hey {self.ui.assistant_name} or use the tray to wake me."
                    )
            elif name in ("shutdown_athena", "shutdown_Athena"):
                self._begin_shutdown()
                result = "Shutting down the trading desk. Goodbye, sir."
            else:
                result = (
                    f"Unknown tool: {name}. This is trading-only Athena. "
                    "Use trading_desk, mt5_analysis, trading_control, or web_search."
                )
        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            tlog(result, "error")

        if not self.ui.muted:
            self.ui.set_state("LISTENING")
        return types.FunctionResponse(id=fc.id, name=name, response={"result": result})

    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            await self.session.send_realtime_input(media=msg)

    async def _listen_audio(self):
        print("[TRADE] Mic started")
        loop = asyncio.get_event_loop()

        def callback(indata, frames, time_info, status):
            with self._speaking_lock:
                speaking = self._is_speaking
            if (
                not speaking
                and not self._hold_mic
                and not getattr(self, "_shutdown_started", False)
                and not self.ui.muted
            ):
                loop.call_soon_threadsafe(
                    self.out_queue.put_nowait,
                    {"data": indata.tobytes(), "mime_type": "audio/pcm"},
                )

        try:
            with sd.InputStream(
                samplerate=SEND_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                callback=callback,
            ):
                while True:
                    await asyncio.sleep(0.1)
        except Exception as e:
            print(f"[TRADE] Mic: {e}")
            raise

    async def _receive_audio(self):
        out_buf, in_buf = [], []
        try:
            while True:
                async for response in self.session.receive():
                    if response.data:
                        if self._interrupted:
                            pass
                        else:
                            self._last_model_audio = time.monotonic()
                            if self._turn_done_event and self._turn_done_event.is_set():
                                self._turn_done_event.clear()
                            _audio_data = response.data
                            _SLICE = 2400
                            for _i in range(0, len(_audio_data), _SLICE):
                                self.audio_in_queue.put_nowait(_audio_data[_i:_i + _SLICE])

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
                                in_buf.append(txt)

                        if sc.turn_complete:
                            if self._turn_done_event:
                                self._turn_done_event.set()
                            if self._interrupted:
                                self._interrupted = False
                                in_buf, out_buf = [], []
                                continue
                            full_in = " ".join(in_buf).strip()
                            if full_in:
                                self.ui.write_log(f"You: {full_in}")
                                self._session_log.append(f"User: {full_in}")
                                if classify_exit_intent(full_in) == "shutdown":
                                    self._begin_shutdown()
                            in_buf = []
                            full_out = " ".join(out_buf).strip()
                            if full_out:
                                self.ui.write_log(f"{self._asst_name}: {full_out}")
                                self._session_log.append(f"{self._asst_name}: {full_out}")
                                lo = full_out.lower()
                                if not getattr(self, "_shutdown_started", False) and (
                                    "shutting down completely" in lo
                                    or "i am shutting down" in lo
                                ):
                                    self._begin_shutdown()
                            out_buf = []

                            if self._pending_vision and self.session:
                                import base64 as _b64
                                img_b, mime_t, question = self._pending_vision
                                self._pending_vision = None
                                b64 = _b64.b64encode(img_b).decode("ascii")
                                await self.session.send_client_content(
                                    turns={"parts": [
                                        {"inline_data": {"mime_type": mime_t, "data": b64}},
                                        {"text": question},
                                    ]},
                                    turn_complete=True,
                                )
                                self._vision_busy = False

                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
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
                print("[TRADE] Gemini Live connection dropped — will reconnect.")
                self.ui.write_log("SYS: Connection dropped. Reconnecting…")
            else:
                print(f"[TRADE] Recv: {e}")
                traceback.print_exc()
            raise

    async def _play_audio(self):
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
                    chunk = await asyncio.wait_for(self.audio_in_queue.get(), timeout=0.1)
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
                batch = bytearray(chunk)
                while len(batch) < 9600:
                    try:
                        batch.extend(self.audio_in_queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break
                try:
                    await asyncio.to_thread(stream.write, bytes(batch))
                except Exception:
                    pass
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    async def _watch_loop(self):
        cfg = load_trading_config()
        interval = max(8, int(cfg.get("watch_interval_sec") or 20))
        tlog(f"WATCH loop started interval={interval}s symbols={cfg.get('symbols')} tf={cfg.get('timeframe')}")
        while True:
            if not (self._hud_sleeping or getattr(self, "_shutdown_started", False)):
                try:
                    cards = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: watch_tick(self.ui)
                    )
                except Exception as e:
                    tlog(f"watch_tick: {e}", "error")
                    cards = []
                if cards and self.session:
                    for card in cards:
                        try:
                            await self.session.send_client_content(
                                turns={"parts": [{
                                    "text": (
                                        "[DESK] Auto watch-loop result (do not re-run trading_desk "
                                        "for this bar unless asked):\n"
                                        f"{card}\n"
                                        "Speak FILLED, CLOSED, or BLOCKED exactly. Never invent a fill."
                                    )
                                }]},
                                turn_complete=True,
                            )
                        except Exception as e:
                            tlog(f"watch announce: {e}", "warning")
            await asyncio.sleep(interval)

    async def run(self):
        self._loop = asyncio.get_event_loop()
        self._sleep_request = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._wake_event.set()

        while True:
            if self._hud_sleeping:
                self.ui.set_state("SLEEPING")
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
                print("[TRADE] Connecting...")
                self.ui.set_state("THINKING")
                config = self._build_config()
                client = genai.Client(
                    api_key=_get_api_key(),
                    http_options={"api_version": "v1beta"},
                )
                async with (
                    client.aio.live.connect(model=get_live_model(), config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session = session
                    self.audio_in_queue = asyncio.Queue()
                    self.out_queue = asyncio.Queue(maxsize=200)
                    self._turn_done_event = asyncio.Event()
                    self._pending_vision = None
                    self._vision_busy = False
                    self._interrupted = False
                    if self._hud_sleeping:
                        if self._sleep_request is not None:
                            self._sleep_request.set()
                    elif self._sleep_request is not None:
                        self._sleep_request.clear()

                    print("[TRADE] Connected.")
                    self.ui.set_state("LISTENING")
                    self.ui.write_log(f"SYS: {self._asst_name} trading desk online.")
                    try:
                        refresh_hud(self.ui)
                    except Exception:
                        pass

                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())
                    tg.create_task(self._sleep_watcher())
                    tg.create_task(self._watch_loop())

                    if self._pending_wake_greeting:
                        self._pending_wake_greeting = False
                        try:
                            await session.send_client_content(
                                turns={"parts": [{
                                    "text": (
                                        "[SYSTEM] You just woke from sleep. Auto-trade follows config. "
                                        "Say you are back on the desk, briefly."
                                    )
                                }]},
                                turn_complete=True,
                            )
                        except Exception:
                            pass

            except KeyboardInterrupt:
                raise
            except SystemExit:
                raise
            except BaseException as e:
                if self._is_sleep_exc(e):
                    exited_for_sleep = True
                    if self._reconnect_needed:
                        print("[TRADE] Reconnecting after API/model change.")
                        self._reconnect_needed = False
                        if self._sleep_request is not None:
                            self._sleep_request.clear()
                    else:
                        print("[TRADE] Sleep requested — pausing Gemini.")
                else:
                    err_str = str(e)
                    _transient = (
                        "1011" in err_str
                        or "Internal error occurred" in err_str
                        or "ConnectionClosed" in err_str
                        or "ConnectionClosed" in type(e).__name__
                    )
                    if _transient:
                        print("[TRADE] Gemini Live server error — reconnecting.")
                        self.ui.write_log("SYS: Connection dropped. Reconnecting…")
                        self._conn_backoff = 3
                    else:
                        print(f"[TRADE] Error ({type(e).__name__}): {e}")
                        traceback.print_exc()
                    if "API key not valid" in err_str or "1007" in err_str:
                        self.ui.write_log("ERR: API key invalid — please re-enter your key.")
                        self.ui.set_state("SLEEPING")
                        self.ui.prompt_reconfig()
                        while not self.ui._win._ready:
                            await asyncio.sleep(1)
                        continue
                    is_net_err = any(k in err_str for k in (
                        "TimeoutError", "timed out", "getaddrinfo", "CancelledError",
                        "ConnectionRefusedError", "Cannot connect",
                    ))
                    if is_net_err:
                        self._conn_backoff = min(getattr(self, "_conn_backoff", 3) * 2, 60)
                        self.ui.write_log(
                            f"NET: Could not connect — retry in {self._conn_backoff}s."
                        )
                    else:
                        self._conn_backoff = 3
            finally:
                self.session = None

            self.set_speaking(False)
            if getattr(self, "_shutdown_started", False):
                return
            if self._hud_sleeping or exited_for_sleep:
                continue
            self.ui.set_state("SLEEPING")
            delay = getattr(self, "_conn_backoff", 3)
            print(f"[TRADE] Reconnecting in {delay}s...")
            await asyncio.sleep(delay)


def main():
    if getattr(sys, "frozen", False):
        os.chdir(BASE_DIR)
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "Athena.Trading"
                )
            except Exception:
                pass

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
    ui = AthenaUI(str(face) if face else "face.png", trading_mode=True)

    def runner():
        ui.wait_for_api_key()
        live = TradingLive(ui)
        try:
            asyncio.run(live.run())
        except KeyboardInterrupt:
            print("\nShutting down trading desk...")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
