from core.mission import MissionManager, MissionStatus
from core.mission_planner import default_checklist_for, looks_like_mission
from core.mission_runner import should_use_mission_mode
from memory.workflow_memory import Workflow, WorkflowMemory, WorkflowStep


def test_looks_like_mission():
    assert looks_like_mission("Prepare my data engineering environment")
    assert looks_like_mission("Finish my ClickHouse ETL pipeline")
    assert not looks_like_mission("Open Notepad")


def test_default_checklist_for_etl():
    items = default_checklist_for("Prepare my ETL environment")
    assert len(items) >= 3


def test_mission_progress(tmp_path):
    manager = MissionManager(storage_dir=tmp_path)
    mission = manager.create(
        title="ETL Ready",
        goal="Prepare ETL",
        item_titles=["Check Docker", "Open VS", "Report"],
    )
    manager.mark_item(mission, 1, done=True, notes="ok")
    manager.mark_item(mission, 2, done=True)
    assert mission.progress_ratio() == 2 / 3
    summary = manager.status_summary(mission)
    assert "ETL Ready" in summary
    assert "[x] 1." in summary

    manager.mark_item(mission, 3, done=True)
    assert mission.status == MissionStatus.COMPLETED.value


def test_workflow_match_and_plan(tmp_path):
    path = tmp_path / "workflows.json"
    memory = WorkflowMemory(path=path)
    matched = memory.match("prepare my data engineering environment")
    assert matched is not None
    assert matched.name == "prepare_data_engineering_environment"
    plan = matched.to_plan()
    assert plan["steps"]
    assert plan["steps"][0]["tool"] == "open_application"


def test_workflow_refuses_sensitive_plans(tmp_path):
    memory = WorkflowMemory(path=tmp_path / "workflows.json")
    remembered = memory.remember_plan(
        name="danger",
        description="delete stuff",
        plan={
            "steps": [
                {
                    "tool": "delete_file",
                    "arguments": {"file_path": "x.txt"},
                    "description": "Delete",
                }
            ]
        },
    )
    assert remembered is None


def test_should_use_mission_mode_for_workflow(tmp_path):
    memory = WorkflowMemory(path=tmp_path / "workflows.json")
    assert should_use_mission_mode(
        "prepare my data engineering environment",
        memory,
    )


def test_remember_safe_plan(tmp_path):
    memory = WorkflowMemory(path=tmp_path / "workflows.json")
    wf = memory.remember_plan(
        name="open_tools",
        description="Open notepad then check status",
        plan={
            "steps": [
                {
                    "tool": "open_application",
                    "arguments": {"application_name": "Notepad"},
                    "description": "Open Notepad",
                },
                {
                    "tool": "get_system_status",
                    "arguments": {},
                    "description": "Status",
                },
            ]
        },
        aliases=["open tools"],
    )
    assert isinstance(wf, Workflow)
    assert memory.match("open tools") is not None
