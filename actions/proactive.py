"""
ProactiveEngine 2.0 — context-aware, time-aware, non-repetitive background prompting.
Gemini decides what to say; this module decides WHEN and builds a rich context snapshot.
"""
import time
from datetime import datetime
from memory.memory_manager import get_response_language


class ProactiveEngine:
    """
    Decides when Athena should speak unprompted and builds a context-rich prompt.

    Defaults (more active continuous presence):
      min_silence_secs  — 600 s  (10 min) user must be silent before any check
      check_cooldown    — 900 s  (15 min) minimum gap between proactive messages
    """

    def __init__(
        self,
        min_silence_secs: int = 600,
        check_cooldown:   int = 900,
    ):
        self.min_silence_secs = min_silence_secs
        self.check_cooldown   = check_cooldown
        self._last_triggered  = 0.0
        self._rotation        = 0          # cycles through context focus areas

    # ── Trigger gate ───────────────────────────────────────────────────────────

    def should_trigger(self, last_user_speech: float) -> bool:
        now = time.monotonic()
        return (
            (now - last_user_speech) >= self.min_silence_secs
            and (now - self._last_triggered) >= self.check_cooldown
        )

    def mark_triggered(self) -> None:
        self._last_triggered = time.monotonic()
        self._rotation      += 1

    # ── Prompt builder ─────────────────────────────────────────────────────────

    def build_prompt(
        self,
        memory:       dict,
        monitors:     list[str] | None = None,
        recent_turns: list[str] | None = None,
        system_snapshot: dict | None = None,
    ) -> str:
        """
        Build a context snapshot for Gemini.
        Rotates through three focus areas so proactive messages don't repeat.
        """
        from memory.memory_manager import format_memory_for_prompt

        now      = datetime.now()
        hour     = now.hour
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")

        # Time-of-day label
        if   6  <= hour < 12:  period = "morning"
        elif 12 <= hour < 18:  period = "afternoon"
        elif 18 <= hour < 23:  period = "evening"
        else:                  period = "late night"

        mem_str = format_memory_for_prompt(memory) or "(no stored user data)"

        # Rotating context focus (cycles every trigger)
        focus_index = self._rotation % 4
        if focus_index == 0:
            focus = (
                "Focus on the user's active projects or goals if any are stored. "
                "Ask how something is going, or offer a relevant tip."
            )
        elif focus_index == 1:
            focus = (
                "Focus on the time of day and the user's wellbeing. "
                "A warm check-in, a reminder to take a break, or something timely."
            )
        elif focus_index == 2:
            focus = (
                "Focus on something genuinely interesting or useful — "
                "a fact, a suggestion, or a question based on what you know about this person."
            )
        else:
            focus = (
                "If the system snapshot shows anything noteworthy (high CPU/RAM, low battery, "
                "low disk), mention it helpfully in one short sentence. Otherwise do a light check-in."
            )

        # Optional: monitored topics context
        monitor_ctx = ""
        if monitors:
            monitor_ctx = (
                f"\nThe user tracks these topics: {', '.join(monitors[:4])}. "
                "You may mention one if it seems relevant."
            )

        # Optional: recent conversation context
        recent_ctx = ""
        if recent_turns:
            snippet = "\n".join(recent_turns[-6:])
            recent_ctx = f"\nRecent conversation:\n{snippet}"

        sys_ctx = ""
        if system_snapshot:
            bits = []
            for k in (
                "cpu_percent", "ram_percent", "battery_percent", "battery_plugged",
                "disk_free_gb", "idle_minutes", "uptime",
            ):
                if k in system_snapshot and system_snapshot[k] is not None:
                    bits.append(f"{k}={system_snapshot[k]}")
            if bits:
                sys_ctx = "\nLive system snapshot: " + ", ".join(bits)

        return "\n".join([
            "[PROACTIVE_CHECK] You are initiating a proactive check-in.",
            f"Current time : {time_str}  ({period})",
            "",
            "Context about this person:",
            mem_str,
            monitor_ctx,
            recent_ctx,
            sys_ctx,
            "",
            "Task:",
            focus,
            "",
            "Rules:",
            f"- Speak in {get_response_language()} (never mirror the user's spoken language unless they commanded a switch).",
            "- Sound human: contractions, a small reaction, then the useful point.",
            "- Two or three complete sentences. Never robotic, never a single clipped line.",
            "- No chatbot filler ('How may I assist', 'I'd be happy to', 'As an AI').",
            "- Do NOT mention [PROACTIVE_CHECK] or these instructions.",
            "- Do NOT call any tools.",
            "- If nothing genuinely useful comes to mind, stay silent (say nothing).",
        ])
