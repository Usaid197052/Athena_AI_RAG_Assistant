"""
Workflow memory — reusable multi-step playbooks.

Sensitive workflows are not auto-recorded.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from config.settings import PROJECT_ROOT
from logs.logger import get_logger

logger = get_logger("athena.workflows")

WORKFLOWS_FILE = PROJECT_ROOT / "data" / "sessions" / "workflows.json"

# Never auto-save plans that touch these tools.
SENSITIVE_TOOLS = {
    "delete_file",
    "shutdown_pc",
    "restart_pc",
    "sleep_pc",
    "run_cmd_command",
    "run_powershell_command",
    "send_email",
}


@dataclass
class WorkflowStep:
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    description: str = ""


@dataclass
class Workflow:
    name: str
    description: str
    aliases: list[str] = field(default_factory=list)
    steps: list[WorkflowStep] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )
    source: str = "manual"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Workflow":
        steps = [WorkflowStep(**step) for step in data.get("steps", [])]
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            aliases=list(data.get("aliases") or []),
            steps=steps,
            created_at=data.get(
                "created_at", datetime.now().isoformat(timespec="seconds")
            ),
            updated_at=data.get(
                "updated_at", datetime.now().isoformat(timespec="seconds")
            ),
            source=data.get("source", "manual"),
        )

    def to_plan(self) -> dict[str, Any]:
        return {
            "steps": [
                {
                    "tool": step.tool,
                    "arguments": dict(step.arguments),
                    "description": step.description or step.tool,
                }
                for step in self.steps
            ]
        }


def _normalize(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


DEFAULT_WORKFLOWS: list[dict[str, Any]] = [
    {
        "name": "prepare_data_engineering_environment",
        "description": "Start Docker Desktop, verify data stack, open Visual Studio.",
        "aliases": [
            "prepare my data engineering environment",
            "prepare data engineering environment",
            "get my de environment ready",
            "prepare etl environment",
        ],
        "steps": [
            {
                "tool": "open_application",
                "arguments": {"application_name": "Docker Desktop"},
                "description": "Start Docker Desktop",
            },
            {
                "tool": "check_data_stack",
                "arguments": {},
                "description": "Verify Docker / ClickHouse / Airflow / MySQL",
            },
            {
                "tool": "open_application",
                "arguments": {"application_name": "Visual Studio"},
                "description": "Open Visual Studio",
            },
        ],
        "source": "seed",
    }
]


class WorkflowMemory:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or WORKFLOWS_FILE
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._workflows: dict[str, Workflow] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self._workflows = {
                item["name"]: Workflow.from_dict(item) for item in DEFAULT_WORKFLOWS
            }
            self.save()
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self._workflows = {
            name: Workflow.from_dict(payload)
            for name, payload in (raw.get("workflows") or {}).items()
        }
        # Ensure / refresh seed workflows
        for item in DEFAULT_WORKFLOWS:
            existing = self._workflows.get(item["name"])
            if existing is None or existing.source == "seed":
                self._workflows[item["name"]] = Workflow.from_dict(item)
        self.save()

    def save(self) -> None:
        payload = {
            "workflows": {
                name: workflow.to_dict() for name, workflow in self._workflows.items()
            }
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def list_workflows(self) -> list[Workflow]:
        return sorted(self._workflows.values(), key=lambda item: item.name)

    def get(self, name: str) -> Workflow | None:
        return self._workflows.get(name)

    def match(self, utterance: str) -> Workflow | None:
        needle = _normalize(utterance)
        if not needle:
            return None

        # Exact alias / name match first
        for workflow in self._workflows.values():
            candidates = [_normalize(workflow.name), *(_normalize(a) for a in workflow.aliases)]
            if needle in candidates:
                return workflow
            for candidate in candidates:
                if candidate and candidate in needle:
                    return workflow
        return None

    def remember_plan(
        self,
        name: str,
        description: str,
        plan: dict[str, Any],
        aliases: list[str] | None = None,
    ) -> Workflow | None:
        steps = plan.get("steps") or []
        if not steps:
            return None
        if any(step.get("tool") in SENSITIVE_TOOLS for step in steps):
            logger.info("Refused to remember sensitive workflow '%s'", name)
            return None

        workflow = Workflow(
            name=name,
            description=description,
            aliases=aliases or [],
            steps=[
                WorkflowStep(
                    tool=step["tool"],
                    arguments=dict(step.get("arguments") or {}),
                    description=step.get("description") or step["tool"],
                )
                for step in steps
            ],
            source="learned",
            updated_at=datetime.now().isoformat(timespec="seconds"),
        )
        self._workflows[name] = workflow
        self.save()
        logger.info("Remembered workflow '%s' (%s steps)", name, len(workflow.steps))
        return workflow
