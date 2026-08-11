"""Risk classification for Athena tools."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from config.settings import get_settings
from tools.base import RiskLevel


DEFAULT_RISK: dict[str, list[str]] = {
    "low": [
        "open_application",
        "close_application",
        "open_visual_studio",
        "open_notepad",
        "open_calculator",
        "open_cmd",
        "open_powershell",
        "search_files",
        "search_web",
        "open_url",
        "list_workflows",
        "mission_status",
        "check_docker",
        "list_containers",
        "docker_compose_ps",
        "check_clickhouse",
        "clickhouse_databases",
        "clickhouse_tables",
        "check_airflow",
        "list_airflow_dags",
        "airflow_dag_runs",
        "check_mysql",
        "check_data_stack",
        "analyze_csv",
        "analyze_excel",
        "profile_dataset",
        "list_email_drafts",
        "read_email_draft",
        "search_email_drafts",
        "search_inbox",
        "read_email",
        "read_file",
        "list_files",
        "get_file_info",
        "get_system_status",
        "list_processes",
        "query_documents",
        "list_ingested_documents",
        "take_screenshot",
        "read_screen",
        "find_on_screen",
        "git_status",
        "git_diff",
        "git_log",
        "inspect_traceback",
        "read_project",
    ],
    "medium": [
        "create_file",
        "write_file",
        "copy_file",
        "move_file",
        "rename_file",
        "run_workflow",
        "clickhouse_query",
        "draft_email",
        "run_python_script",
        "run_python",
        "run_tests",
        "create_branch",
        "create_project",
        "write_code",
        "run_cmd_command",
        "run_powershell_command",
        "ingest_document",
        "click_text",
        "click_at",
        "type_text",
        "press_key",
        "scroll_screen",
    ],
    "high": [
        "delete_file",
        "send_email",
        "git_commit",
        "shutdown_pc",
        "restart_pc",
        "sleep_pc",
    ],
    "critical": [],
}


@lru_cache
def _risk_map() -> dict[str, RiskLevel]:
    settings = get_settings()
    data: dict[str, Any] = {}
    path: Path = settings.permissions_file
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        data = loaded.get("risk", {}) or {}

    mapping: dict[str, RiskLevel] = {}
    for level_name, level in (
        ("low", RiskLevel.LOW),
        ("medium", RiskLevel.MEDIUM),
        ("high", RiskLevel.HIGH),
        ("critical", RiskLevel.CRITICAL),
    ):
        names = data.get(level_name) or DEFAULT_RISK.get(level_name, [])
        for name in names:
            mapping[str(name)] = level
    return mapping


def classify_risk(tool_name: str) -> RiskLevel:
    return _risk_map().get(tool_name, RiskLevel.MEDIUM)


def reset_risk_cache() -> None:
    _risk_map.cache_clear()
