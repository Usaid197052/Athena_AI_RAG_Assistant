"""
Mission planning helpers — checklist generation for high-level goals.
"""

from __future__ import annotations

import re
from typing import Any

from brain.ollama_client import ask_athena
from brain.planner import extract_json
from brain.prompt_manager import PERSONA


MISSION_TRIGGERS = (
    "mission",
    "finish my",
    "get my",
    "prepare my",
    "make ready",
    "ready for production",
    "end to end",
    "end-to-end",
)


def looks_like_mission(text: str) -> bool:
    lower = text.lower()
    if any(trigger in lower for trigger in MISSION_TRIGGERS):
        return True
    # Longer multi-clause goals
    return len(lower.split()) >= 8 and any(
        word in lower for word in ("pipeline", "environment", "project", "deploy")
    )


def default_checklist_for(goal: str) -> list[str]:
    lower = goal.lower()
    if "data engineering" in lower or "etl" in lower or "clickhouse" in lower:
        return [
            "Check system / Docker readiness",
            "Open Visual Studio",
            "Locate project context",
            "Review environment status",
            "Summarize readiness",
        ]
    if "production" in lower:
        return [
            "Inspect project",
            "Run checks",
            "Validate configuration",
            "Validate connectivity",
            "Generate readiness report",
        ]
    return [
        "Understand the goal",
        "Inspect current state",
        "Perform required actions",
        "Verify results",
        "Report outcome",
    ]


def build_mission_checklist(goal: str) -> list[str]:
    prompt = f"""
{PERSONA}

Create a short mission checklist for this goal.
Return ONLY JSON:
{{"title": "...", "items": ["...", "..."]}}

Rules:
- 3 to 7 items
- Each item is a short concrete action
- No tools names unless necessary
- No markdown

Goal:
{goal}
"""
    try:
        response = ask_athena(prompt)
        data = extract_json(response)
        items = data.get("items") or []
        cleaned = [str(item).strip() for item in items if str(item).strip()]
        if 3 <= len(cleaned) <= 7:
            return cleaned
    except Exception:
        pass
    return default_checklist_for(goal)


def mission_title_from_goal(goal: str) -> str:
    text = re.sub(r"\s+", " ", goal.strip())
    if len(text) <= 60:
        return text[0].upper() + text[1:] if text else "Mission"
    return text[:57].rstrip() + "..."
