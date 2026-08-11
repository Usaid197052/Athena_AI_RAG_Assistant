from core.task_manager import TaskManager, TaskStatus


def test_create_and_complete_task(tmp_path):
    manager = TaskManager(storage_dir=tmp_path)
    plan = {
        "steps": [
            {
                "tool": "open_application",
                "arguments": {"application_name": "Notepad"},
                "description": "Open Notepad",
            }
        ]
    }
    task = manager.create_from_plan("Open Notepad", plan)
    assert task.status == TaskStatus.PENDING.value
    assert len(task.steps) == 1

    manager.mark_running(task)
    manager.mark_step(
        task,
        1,
        status=TaskStatus.COMPLETED.value,
        result="Notepad is open.",
        verified=True,
    )
    manager.complete(task, "done")

    loaded = manager.load(task.id)
    assert loaded is not None
    assert loaded.status == TaskStatus.COMPLETED.value
    assert "Open Notepad" in manager.status_summary(loaded)
