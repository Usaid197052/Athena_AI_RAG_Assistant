"""
Athena multi-step task manager.

Tracks goals, steps, and resumable status across plan execution.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from config.settings import PROJECT_ROOT
from logs.logger import get_logger

logger = get_logger("athena.tasks")

TASKS_DIR = PROJECT_ROOT / "data" / "sessions"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_FOR_PERMISSION = "WAITING_FOR_PERMISSION"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


@dataclass
class TaskStep:
    index: int
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    status: str = TaskStatus.PENDING.value
    result: str | None = None
    verified: bool | None = None
    error: str | None = None


@dataclass
class Task:
    id: str
    goal: str
    status: str = TaskStatus.PENDING.value
    steps: list[TaskStep] = field(default_factory=list)
    current_step: int = 0
    created_at: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )
    error: str | None = None
    result: str | None = None

    def touch(self) -> None:
        self.updated_at = datetime.now().isoformat(timespec="seconds")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        steps = [TaskStep(**step) for step in data.get("steps", [])]
        return cls(
            id=data["id"],
            goal=data.get("goal", ""),
            status=data.get("status", TaskStatus.PENDING.value),
            steps=steps,
            current_step=int(data.get("current_step", 0)),
            created_at=data.get("created_at", datetime.now().isoformat(timespec="seconds")),
            updated_at=data.get("updated_at", datetime.now().isoformat(timespec="seconds")),
            error=data.get("error"),
            result=data.get("result"),
        )


class TaskManager:
    def __init__(self, storage_dir: Path | None = None) -> None:
        self.storage_dir = storage_dir or TASKS_DIR
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._active: Task | None = None

    @property
    def active(self) -> Task | None:
        return self._active

    def create_from_plan(self, goal: str, plan: dict[str, Any]) -> Task:
        steps = [
            TaskStep(
                index=index,
                tool=step.get("tool", ""),
                arguments=dict(step.get("arguments") or {}),
                description=step.get("description") or step.get("tool", ""),
            )
            for index, step in enumerate(plan.get("steps") or [], start=1)
        ]
        task = Task(
            id=str(uuid.uuid4()),
            goal=goal,
            status=TaskStatus.PENDING.value,
            steps=steps,
            current_step=1 if steps else 0,
        )
        self._active = task
        self.save(task)
        logger.info("Created task %s with %s steps", task.id, len(steps))
        return task

    def mark_running(self, task: Task) -> None:
        task.status = TaskStatus.RUNNING.value
        task.touch()
        self.save(task)

    def mark_waiting(self, task: Task) -> None:
        task.status = TaskStatus.WAITING_FOR_PERMISSION.value
        task.touch()
        self.save(task)

    def mark_step(
        self,
        task: Task,
        index: int,
        *,
        status: str,
        result: str | None = None,
        verified: bool | None = None,
        error: str | None = None,
    ) -> None:
        for step in task.steps:
            if step.index == index:
                step.status = status
                step.result = result
                step.verified = verified
                step.error = error
                break
        task.current_step = index
        task.touch()
        self.save(task)

    def complete(self, task: Task, result: str) -> None:
        task.status = TaskStatus.COMPLETED.value
        task.result = result
        task.error = None
        task.touch()
        self.save(task)

    def fail(self, task: Task, error: str) -> None:
        task.status = TaskStatus.FAILED.value
        task.error = error
        task.touch()
        self.save(task)

    def cancel(self, task: Task, reason: str) -> None:
        task.status = TaskStatus.CANCELLED.value
        task.error = reason
        task.touch()
        self.save(task)

    def save(self, task: Task) -> Path:
        path = self.storage_dir / f"task_{task.id}.json"
        path.write_text(json.dumps(task.to_dict(), indent=2), encoding="utf-8")
        return path

    def load(self, task_id: str) -> Task | None:
        path = self.storage_dir / f"task_{task_id}.json"
        if not path.exists():
            return None
        task = Task.from_dict(json.loads(path.read_text(encoding="utf-8")))
        self._active = task
        return task

    def status_summary(self, task: Task | None = None) -> str:
        task = task or self._active
        if task is None:
            return "No active task."

        lines = [
            f"Task: {task.goal}",
            f"Status: {task.status}",
            f"Progress: {task.current_step}/{len(task.steps)}",
        ]
        for step in task.steps:
            mark = {
                TaskStatus.COMPLETED.value: "[x]",
                TaskStatus.FAILED.value: "[!]",
                TaskStatus.CANCELLED.value: "[-]",
                TaskStatus.RUNNING.value: "[>]",
                TaskStatus.WAITING_FOR_PERMISSION.value: "[?]",
            }.get(step.status, "[ ]")
            lines.append(f"{mark} {step.index}. {step.description or step.tool}")
        if task.error:
            lines.append(f"Error: {task.error}")
        return "\n".join(lines)
