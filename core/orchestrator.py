"""
Athena core orchestrator.

Coordinates input → (optional RAG) → LLM/tool planning → permissions
→ execution → verification → response. Does not launch apps itself.
"""

from __future__ import annotations

from typing import Any, Callable

from core.context import ContextEngine
from core.mission import MissionManager
from core.mission_runner import MissionRunner, should_use_mission_mode
from core.planner import create_plan
from core.task_manager import TaskManager
from logs.logger import get_logger, log_request, log_result
from memory.session import get_session, note_tool_result
from memory.workflow_memory import WorkflowMemory
from monitoring.status_store import set_ux_phase
from rag.memory_manager import MemoryManager
from security.audit import audit_event
from security.permissions import evaluate_permission
from tools.registry import get_registry

logger = get_logger("athena.orchestrator")


class Orchestrator:
    def __init__(
        self,
        confirm_callback: Callable[[dict[str, Any]], bool] | None = None,
    ) -> None:
        self.confirm_callback = confirm_callback
        self.registry = get_registry()
        self.memory = MemoryManager()
        self.context_engine = ContextEngine(self.memory)
        self.tasks = TaskManager()
        self.missions = MissionManager()
        self.workflows = WorkflowMemory()
        self.mission_runner = MissionRunner(
            confirm_callback=confirm_callback,
            missions=self.missions,
            tasks=self.tasks,
            workflows=self.workflows,
        )

    def handle_text(self, user_text: str) -> dict[str, Any]:
        """
        High-level entry for a single user utterance/request.
        """
        from brain.intent_router import classify_intent
        from brain.chat import chat_with_athena
        from executor.plan_executor import execute_plan

        normalized = user_text.lower().strip()
        if normalized in {
            "status",
            "task status",
            "mission status",
            "what's the status",
            "what is the status",
        }:
            mission_summary = self.missions.status_summary()
            task_summary = self.tasks.status_summary()
            if mission_summary != "No active mission.":
                summary = mission_summary
            else:
                summary = task_summary
            self.memory.remember_exchange(user_text, summary)
            return {
                "mode": "status",
                "response": summary,
                "completed": True,
            }

        if normalized in {"list workflows", "show workflows", "what workflows do you know"}:
            lines = [
                f"- {wf.name}: {wf.description}"
                for wf in self.workflows.list_workflows()
            ]
            response = "Workflows:\n" + "\n".join(lines) if lines else "No workflows yet."
            self.memory.remember_exchange(user_text, response)
            return {"mode": "workflows", "response": response, "completed": True}

        log_request(user_text)
        set_ux_phase("Thinking...", "Understanding request")
        context = self.context_engine.build(user_text)
        if context.get("rag_hits"):
            set_ux_phase("Searching memory...", f"{len(context['rag_hits'])} hits")
        intent = classify_intent(user_text)
        logger.info("Intent: %s | rag_hits=%s", intent, len(context["rag_hits"]))

        get_session().update(current_task=user_text[:200])

        if intent.get("intent") == "chat" and not should_use_mission_mode(
            user_text, self.workflows
        ):
            set_ux_phase("Thinking...", "Composing response")
            if context["rag_context"]:
                response = chat_with_athena(
                    user_text,
                    extra_context=context["rag_context"],
                )
            else:
                response = chat_with_athena(user_text)
            log_result(response)
            return {
                "mode": "chat",
                "response": response,
                "completed": True,
                "context": context,
            }

        # Mission / remembered workflow path for larger goals
        if should_use_mission_mode(user_text, self.workflows):
            set_ux_phase("Planning...", "Mission mode")
            result = self.mission_runner.run_mission(
                user_text,
                planning_context=context["planning_context"],
            )
            self.memory.remember_exchange(user_text, result["response"])
            log_result(result["response"])
            return {
                **result,
                "context": context,
            }

        set_ux_phase("Planning...", "Building action steps")
        plan = create_plan(
            user_text,
            planning_context=context["planning_context"],
        )
        if plan.get("error") or not plan.get("steps"):
            message = "I could not work out how to do that."
            if context["rag_context"] and plan.get("error"):
                message = (
                    "I found related memory, but I could not build a safe action plan."
                )
            log_result(plan.get("error") or "Empty plan")
            self.memory.remember_exchange(user_text, message)
            return {
                "mode": "action",
                "response": message,
                "completed": False,
                "plan": plan,
                "context": context,
            }

        first = (plan.get("steps") or [{}])[0]
        set_ux_phase(
            first.get("description") or f"Running {first.get('tool', 'tool')}...",
            f"{len(plan.get('steps') or [])} step(s)",
        )
        outcome = execute_plan(
            plan,
            confirm_callback=self.confirm_callback,
            goal=user_text,
            task_manager=self.tasks,
        )

        # Remember short successful non-sensitive plans as workflows when useful
        if outcome.get("completed") and len(plan.get("steps") or []) >= 2:
            self.workflows.remember_plan(
                name=self.mission_runner._workflow_name(user_text),
                description=user_text,
                plan=plan,
                aliases=[user_text.lower()],
            )

        summary = outcome.get("summary", "")
        if outcome.get("completed") and outcome.get("results"):
            response = str(outcome["results"][-1])
        elif outcome.get("task_status"):
            response = (
                "I stopped before finishing that.\n"
                + str(outcome.get("task_status"))
            )
        else:
            response = "I stopped before finishing that."

        set_ux_phase(
            "Task completed." if outcome.get("completed") else "Task incomplete.",
            summary[:160],
        )
        self.memory.remember_exchange(user_text, response)
        log_result(summary)
        return {
            "mode": "action",
            "response": response,
            "completed": outcome.get("completed", False),
            "plan": plan,
            "outcome": outcome,
            "context": context,
            "task_id": outcome.get("task_id"),
        }

    def run_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        user_request: str | None = None,
    ) -> str:
        arguments = arguments or {}
        decision = evaluate_permission(tool_name)

        if not decision.allowed:
            audit_event(
                user_request,
                tool_name,
                arguments,
                decision.risk_level.value,
                "denied",
                "blocked",
            )
            return decision.reason

        if decision.requires_confirmation:
            approved = False
            if self.confirm_callback:
                approved = self.confirm_callback(
                    {
                        "tool": tool_name,
                        "arguments": arguments,
                        "description": tool_name,
                    }
                )
            if not approved:
                audit_event(
                    user_request,
                    tool_name,
                    arguments,
                    decision.risk_level.value,
                    "rejected",
                    "user declined",
                )
                return f"Confirmation required for '{tool_name}'."

        result = self.registry.execute(tool_name, arguments)
        note_tool_result(tool_name, arguments, result.message)
        audit_event(
            user_request,
            tool_name,
            arguments,
            decision.risk_level.value,
            "automatic" if not decision.requires_confirmation else "confirmed",
            result.message,
            verification=(
                "success"
                if result.verified
                else "failed"
                if result.verified is False
                else None
            ),
            error=None if result.success else result.message,
        )
        return str(result)
