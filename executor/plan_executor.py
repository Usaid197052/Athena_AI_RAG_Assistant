"""
Plan executor with task tracking, permissions, and verification.
"""

from __future__ import annotations

import re

from core.event_bus import get_event_bus
from core.task_manager import TaskManager, TaskStatus
from core.verification import verify_tool_result
from executor.action_executor import execute_action
from logs.logger import log_action, log_result
from memory.session import note_tool_result
from monitoring.status_store import set_ux_phase
from permissions.permissions import requires_confirmation


PLACEHOLDER_PATTERN = re.compile(r"\{\{step_(\d+)\}\}")


def resolve_placeholders(value, results):
    if isinstance(value, str):

        def substitute(match):
            step_number = int(match.group(1))
            if 1 <= step_number <= len(results):
                return str(results[step_number - 1])
            return match.group(0)

        return PLACEHOLDER_PATTERN.sub(substitute, value)

    if isinstance(value, dict):
        return {
            key: resolve_placeholders(item, results)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [resolve_placeholders(item, results) for item in value]

    return value


def execute_plan(
    plan,
    confirm_callback=None,
    on_step=None,
    goal: str | None = None,
    task_manager: TaskManager | None = None,
):
    """
    Executes plan steps in order with verification.

    Returns:
    {
        "completed": bool,
        "results": [str, ...],
        "summary": str,
        "task_id": str | None,
        "verifications": [dict, ...]
    }
    """

    steps = plan.get("steps", [])
    manager = task_manager or TaskManager()
    task = manager.create_from_plan(goal or "Untitled plan", plan)
    manager.mark_running(task)
    bus = get_event_bus()

    results = []
    lines = []
    verifications = []

    for index, step in enumerate(steps, start=1):
        tool_name = step["tool"]
        arguments = resolve_placeholders(step.get("arguments", {}), results)
        description = step.get("description") or tool_name
        set_ux_phase(
            f"{description}...",
            f"Step {index}/{len(steps)}",
            current_task=f"{goal or 'Plan'} · {description}",
        )

        if on_step:
            on_step(index, len(steps), step)

        if requires_confirmation(tool_name):
            manager.mark_waiting(task)
            set_ux_phase("Waiting for confirmation...", description)
            approved = confirm_callback(step) if confirm_callback else False
            if not approved:
                message = f"Plan cancelled at step {index} ({tool_name})."
                manager.cancel(task, message)
                manager.mark_step(
                    task,
                    index,
                    status=TaskStatus.CANCELLED.value,
                    error=message,
                )
                log_result(message)
                bus.publish(
                    "TASK_CANCELLED",
                    {"task_id": task.id, "step": index, "tool": tool_name},
                )
                return {
                    "completed": False,
                    "results": results,
                    "summary": message,
                    "task_id": task.id,
                    "verifications": verifications,
                    "task_status": manager.status_summary(task),
                }
            manager.mark_running(task)
            set_ux_phase(f"{description}...", f"Step {index}/{len(steps)}")

        log_action(tool_name, arguments)
        manager.mark_step(task, index, status=TaskStatus.RUNNING.value)

        result = execute_action(tool_name, arguments)
        note_tool_result(tool_name, arguments, str(result))

        verified_ok, verify_message = verify_tool_result(
            tool_name,
            arguments,
            result,
        )
        verifications.append(
            {
                "step": index,
                "tool": tool_name,
                "ok": verified_ok,
                "message": verify_message,
            }
        )

        result_text = str(result)
        if not verified_ok:
            fail_message = (
                f"Step {index} ({tool_name}) verification failed: {verify_message}"
            )
            manager.mark_step(
                task,
                index,
                status=TaskStatus.FAILED.value,
                result=result_text,
                verified=False,
                error=fail_message,
            )
            manager.fail(task, fail_message)
            log_result(fail_message)
            bus.publish(
                "TASK_FAILED",
                {
                    "task_id": task.id,
                    "step": index,
                    "tool": tool_name,
                    "reason": verify_message,
                },
            )
            lines.append(
                f"Step {index}: {step.get('description', tool_name)} -> {result_text}"
            )
            lines.append(f"Verification failed: {verify_message}")
            return {
                "completed": False,
                "results": results + [result_text],
                "summary": "\n".join(lines),
                "task_id": task.id,
                "verifications": verifications,
                "task_status": manager.status_summary(task),
            }

        manager.mark_step(
            task,
            index,
            status=TaskStatus.COMPLETED.value,
            result=result_text,
            verified=True,
        )
        results.append(result_text)
        log_result(result_text)
        description = step.get("description", tool_name)
        lines.append(f"Step {index}: {description} -> {result_text}")
        lines.append(f"Verified: {verify_message}")

    summary = "\n".join(lines)
    manager.complete(task, summary)
    bus.publish("TASK_COMPLETED", {"task_id": task.id, "goal": task.goal})

    return {
        "completed": True,
        "results": results,
        "summary": summary,
        "task_id": task.id,
        "verifications": verifications,
        "task_status": manager.status_summary(task),
    }
