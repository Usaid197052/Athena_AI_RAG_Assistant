"""
Athena Mission Mode — high-level goals with checklist progress.
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

logger = get_logger("athena.missions")

MISSIONS_DIR = PROJECT_ROOT / "data" / "sessions" / "missions"


class MissionStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


@dataclass
class MissionItem:
    index: int
    title: str
    done: bool = False
    notes: str | None = None
    tool_hint: str | None = None


@dataclass
class Mission:
    id: str
    title: str
    goal: str
    status: str = MissionStatus.PENDING.value
    items: list[MissionItem] = field(default_factory=list)
    current_item: int = 1
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

    def progress_ratio(self) -> float:
        if not self.items:
            return 0.0
        return sum(1 for item in self.items if item.done) / len(self.items)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Mission":
        items = [MissionItem(**item) for item in data.get("items", [])]
        return cls(
            id=data["id"],
            title=data.get("title", ""),
            goal=data.get("goal", ""),
            status=data.get("status", MissionStatus.PENDING.value),
            items=items,
            current_item=int(data.get("current_item", 1)),
            created_at=data.get(
                "created_at", datetime.now().isoformat(timespec="seconds")
            ),
            updated_at=data.get(
                "updated_at", datetime.now().isoformat(timespec="seconds")
            ),
            error=data.get("error"),
            result=data.get("result"),
        )


class MissionManager:
    def __init__(self, storage_dir: Path | None = None) -> None:
        self.storage_dir = storage_dir or MISSIONS_DIR
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._active: Mission | None = None

    @property
    def active(self) -> Mission | None:
        return self._active

    def create(
        self,
        title: str,
        goal: str,
        item_titles: list[str],
    ) -> Mission:
        items = [
            MissionItem(index=index, title=title_text)
            for index, title_text in enumerate(item_titles, start=1)
        ]
        mission = Mission(
            id=str(uuid.uuid4()),
            title=title,
            goal=goal,
            status=MissionStatus.RUNNING.value,
            items=items,
            current_item=1 if items else 0,
        )
        self._active = mission
        self.save(mission)
        logger.info("Created mission %s (%s items)", mission.id, len(items))
        return mission

    def mark_item(
        self,
        mission: Mission,
        index: int,
        *,
        done: bool,
        notes: str | None = None,
    ) -> None:
        for item in mission.items:
            if item.index == index:
                item.done = done
                item.notes = notes
                break
        mission.current_item = index
        if all(item.done for item in mission.items):
            mission.status = MissionStatus.COMPLETED.value
            mission.result = "All mission items completed."
        else:
            mission.status = MissionStatus.RUNNING.value
        mission.touch()
        self.save(mission)

    def fail(self, mission: Mission, error: str) -> None:
        mission.status = MissionStatus.FAILED.value
        mission.error = error
        mission.touch()
        self.save(mission)

    def cancel(self, mission: Mission, reason: str) -> None:
        mission.status = MissionStatus.CANCELLED.value
        mission.error = reason
        mission.touch()
        self.save(mission)

    def save(self, mission: Mission) -> Path:
        path = self.storage_dir / f"mission_{mission.id}.json"
        path.write_text(json.dumps(mission.to_dict(), indent=2), encoding="utf-8")
        # pointer to latest active mission
        (self.storage_dir / "active.json").write_text(
            json.dumps({"id": mission.id}),
            encoding="utf-8",
        )
        return path

    def load(self, mission_id: str) -> Mission | None:
        path = self.storage_dir / f"mission_{mission_id}.json"
        if not path.exists():
            return None
        mission = Mission.from_dict(json.loads(path.read_text(encoding="utf-8")))
        self._active = mission
        return mission

    def load_active(self) -> Mission | None:
        pointer = self.storage_dir / "active.json"
        if not pointer.exists():
            return self._active
        try:
            mission_id = json.loads(pointer.read_text(encoding="utf-8")).get("id")
        except Exception:
            return self._active
        if not mission_id:
            return self._active
        return self.load(str(mission_id))

    def status_summary(self, mission: Mission | None = None) -> str:
        mission = mission or self._active or self.load_active()
        if mission is None:
            return "No active mission."

        pct = int(mission.progress_ratio() * 100)
        bar_filled = pct // 10
        bar = "#" * bar_filled + "-" * (10 - bar_filled)
        lines = [
            f"MISSION: {mission.title}",
            f"Goal: {mission.goal}",
            f"Status: {mission.status}  [{bar}] {pct}%",
            "",
        ]
        for item in mission.items:
            mark = "[x]" if item.done else "[ ]"
            lines.append(f"{mark} {item.index}. {item.title}")
            if item.notes:
                lines.append(f"    note: {item.notes}")
        if mission.error:
            lines.append(f"Error: {mission.error}")
        return "\n".join(lines)
