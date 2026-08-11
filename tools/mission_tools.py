"""
Tools for missions and remembered workflows.
"""

from __future__ import annotations

from core.mission import MissionManager
from memory.workflow_memory import WorkflowMemory
from tools.base import RiskLevel, Tool, ToolResult


class ListWorkflowsTool(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="list_workflows",
            description="List remembered Athena workflows.",
            risk_level=RiskLevel.LOW,
            input_schema={"type": "object", "properties": {}, "required": []},
        )

    def execute(self, arguments):
        workflows = WorkflowMemory().list_workflows()
        if not workflows:
            return ToolResult(success=True, message="No workflows stored yet.")
        lines = [
            f"- {wf.name}: {wf.description} ({len(wf.steps)} steps)"
            for wf in workflows
        ]
        return ToolResult(success=True, message="Workflows:\n" + "\n".join(lines))


class MissionStatusTool(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="mission_status",
            description="Show the active mission checklist and progress.",
            risk_level=RiskLevel.LOW,
            input_schema={"type": "object", "properties": {}, "required": []},
        )

    def execute(self, arguments):
        summary = MissionManager().status_summary()
        return ToolResult(success=True, message=summary)


class RunWorkflowTool(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="run_workflow",
            description=(
                "Run a remembered workflow by name "
                "(e.g. prepare_data_engineering_environment)."
            ),
            risk_level=RiskLevel.MEDIUM,
            input_schema={
                "type": "object",
                "properties": {
                    "workflow_name": {
                        "type": "string",
                        "description": "Workflow name or alias",
                    }
                },
                "required": ["workflow_name"],
            },
        )

    def execute(self, arguments):
        name = str(arguments.get("workflow_name", "")).strip()
        memory = WorkflowMemory()
        workflow = memory.get(name) or memory.match(name)
        if workflow is None:
            return ToolResult(
                success=False,
                message=f"No workflow matching '{name}'.",
            )

        from executor.plan_executor import execute_plan

        outcome = execute_plan(workflow.to_plan(), goal=workflow.name)
        if outcome.get("completed"):
            return ToolResult(
                success=True,
                message=(
                    f"Workflow '{workflow.name}' completed.\n"
                    + str(outcome.get("summary") or "")
                ),
                data=outcome,
            )
        return ToolResult(
            success=False,
            message=(
                f"Workflow '{workflow.name}' did not finish.\n"
                + str(outcome.get("summary") or "")
            ),
            data=outcome,
        )
