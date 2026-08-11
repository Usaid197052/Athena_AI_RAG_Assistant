"""
Run missions by planning/executing each checklist item safely.
"""

from __future__ import annotations

from typing import Any, Callable

from core.mission import Mission, MissionManager, MissionStatus
from core.mission_planner import (
    build_mission_checklist,
    looks_like_mission,
    mission_title_from_goal,
)
from core.planner import create_plan
from core.task_manager import TaskManager
from executor.plan_executor import execute_plan
from logs.logger import get_logger
from memory.workflow_memory import WorkflowMemory
from monitoring.status_store import append_activity, write_status

logger = get_logger("athena.mission_runner")


class MissionRunner:
    def __init__(
        self,
        confirm_callback: Callable[[dict[str, Any]], bool] | None = None,
        missions: MissionManager | None = None,
        tasks: TaskManager | None = None,
        workflows: WorkflowMemory | None = None,
    ) -> None:
        self.confirm_callback = confirm_callback
        self.missions = missions or MissionManager()
        self.tasks = tasks or TaskManager()
        self.workflows = workflows or WorkflowMemory()

    def start_mission(self, goal: str) -> Mission:
        title = mission_title_from_goal(goal)
        items = build_mission_checklist(goal)
        mission = self.missions.create(title=title, goal=goal, item_titles=items)
        write_status(current_task=f"Mission: {title}")
        append_activity(f"Mission started: {title}", category="mission")
        return mission

    def run_mission(
        self,
        goal: str,
        *,
        planning_context: str = "",
        max_items: int = 5,
    ) -> dict[str, Any]:
        # Prefer a remembered workflow when the utterance matches one.
        workflow = self.workflows.match(goal)
        if workflow is not None:
            append_activity(
                f"Using remembered workflow: {workflow.name}",
                category="workflow",
            )
            plan = workflow.to_plan()
            outcome = execute_plan(
                plan,
                confirm_callback=self.confirm_callback,
                goal=goal,
                task_manager=self.tasks,
            )
            mission = self.missions.create(
                title=workflow.name,
                goal=goal,
                item_titles=[step.description or step.tool for step in workflow.steps],
            )
            if outcome.get("completed"):
                for item in mission.items:
                    self.missions.mark_item(mission, item.index, done=True)
            else:
                self.missions.fail(mission, outcome.get("summary") or "Workflow failed")
            return {
                "mode": "workflow",
                "workflow": workflow.name,
                "mission": mission.to_dict(),
                "outcome": outcome,
                "response": self._response_from_outcome(outcome, mission),
                "completed": bool(outcome.get("completed")),
            }

        mission = self.start_mission(goal)
        results: list[str] = []

        for item in mission.items[:max_items]:
            write_status(current_task=f"{mission.title} · {item.title}")
            append_activity(f"Mission step: {item.title}", category="mission")

            item_request = f"{item.title}. Context goal: {goal}"
            plan = create_plan(
                item_request,
                planning_context=planning_context,
            )
            if plan.get("error") or not plan.get("steps"):
                # Non-fatal for informational checklist items
                note = plan.get("error") or "No actionable tools for this item."
                self.missions.mark_item(mission, item.index, done=True, notes=note)
                results.append(f"{item.title}: skipped ({note})")
                continue

            outcome = execute_plan(
                plan,
                confirm_callback=self.confirm_callback,
                goal=item.title,
                task_manager=self.tasks,
            )
            if not outcome.get("completed"):
                self.missions.mark_item(
                    mission,
                    item.index,
                    done=False,
                    notes=outcome.get("summary"),
                )
                self.missions.fail(mission, outcome.get("summary") or "Step failed")
                return {
                    "mode": "mission",
                    "mission": mission.to_dict(),
                    "outcome": outcome,
                    "response": (
                        "Mission paused after a failed step.\n"
                        + self.missions.status_summary(mission)
                    ),
                    "completed": False,
                }

            note = None
            if outcome.get("results"):
                note = str(outcome["results"][-1])[:240]
            self.missions.mark_item(mission, item.index, done=True, notes=note)
            results.append(f"{item.title}: done")

        # Mark any remaining items beyond max_items as pending notes
        for item in mission.items[max_items:]:
            self.missions.mark_item(
                mission,
                item.index,
                done=False,
                notes="Deferred — ask me to continue the mission.",
            )

        if all(item.done for item in mission.items):
            mission.status = MissionStatus.COMPLETED.value
            mission.result = "Mission completed."
            self.missions.save(mission)

        summary = self.missions.status_summary(mission)
        append_activity(f"Mission update: {mission.status}", category="mission")
        return {
            "mode": "mission",
            "mission": mission.to_dict(),
            "results": results,
            "response": summary,
            "completed": mission.status == MissionStatus.COMPLETED.value,
        }

    def _workflow_name(self, goal: str) -> str:
        cleaned = "".join(ch if ch.isalnum() or ch in " _-" else " " for ch in goal.lower())
        cleaned = "_".join(cleaned.split())
        return (cleaned[:48] or "learned_workflow").strip("_")

    def _response_from_outcome(self, outcome: dict[str, Any], mission: Mission) -> str:
        if outcome.get("completed") and outcome.get("results"):
            return (
                str(outcome["results"][-1])
                + "\n\n"
                + self.missions.status_summary(mission)
            )
        return (
            "I stopped before finishing that.\n"
            + self.missions.status_summary(mission)
        )


def should_use_mission_mode(text: str, workflow_memory: WorkflowMemory | None = None) -> bool:
    memory = workflow_memory or WorkflowMemory()
    if memory.match(text) is not None:
        return True
    return looks_like_mission(text)
