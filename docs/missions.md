# Athena Missions & Workflows

## Mission Mode

High-level goals become a checklist mission:

```text
Hey Athena, prepare my data engineering environment.
```

Athena:
1. Matches a remembered workflow when possible
2. Otherwise builds a mission checklist
3. Executes each item through the normal plan → permission → verify loop
4. Persists progress under `data/sessions/missions/`

Ask **"status"** or **"mission status"** for the checklist.

## Workflow Memory

Stored in `data/sessions/workflows.json`.

Seeded workflow:
- `prepare_data_engineering_environment`

Successful multi-step plans can be remembered automatically when they do **not** include sensitive tools (delete/shutdown/shell/email).

## Tools

- `list_workflows`
- `run_workflow`
- `mission_status`

## Modules

- `core/mission.py`
- `core/mission_planner.py`
- `core/mission_runner.py`
- `memory/workflow_memory.py`
- `tools/mission_tools.py`
