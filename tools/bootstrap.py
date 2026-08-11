"""
Assemble the Athena tool registry (new + legacy wrappers).
"""

from __future__ import annotations

from tools.applications.closer import CloseApplicationTool
from tools.applications.launcher import OpenApplicationTool, open_application
from tools.base import FunctionTool, RiskLevel
from tools.registry import ToolRegistry


def _wrap_open(name: str, friendly: str):
    def _runner() -> str:
        return str(open_application(friendly))

    return FunctionTool(
        name=name,
        description=f"Open {friendly}. Prefer open_application when possible.",
        func=_runner,
        risk_level=RiskLevel.LOW,
        input_schema={"type": "object", "properties": {}, "required": []},
    )


def _safe_register(registry: ToolRegistry, import_fn, builder) -> None:
    try:
        module_bits = import_fn()
        for tool in builder(module_bits):
            registry.register(tool)
    except Exception:
        # Optional subsystems (RAG/vision) may be missing deps in some envs.
        pass


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(OpenApplicationTool())
    registry.register(CloseApplicationTool())

    try:
        from tools.browser.browser_tools import OpenUrlTool, SearchWebTool

        registry.register(OpenUrlTool())
        registry.register(SearchWebTool())
    except Exception:
        pass

    try:
        from tools.mission_tools import (
            ListWorkflowsTool,
            MissionStatusTool,
            RunWorkflowTool,
        )

        registry.register(ListWorkflowsTool())
        registry.register(MissionStatusTool())
        registry.register(RunWorkflowTool())
    except Exception:
        pass

    try:
        from tools.communication.email import (
            draft_email,
            list_email_drafts,
            read_email,
            read_email_draft,
            search_email_drafts,
            search_inbox,
            send_email,
        )

        for tool in (
            FunctionTool(
                "draft_email",
                "Create an email draft (does not send)",
                draft_email,
                RiskLevel.MEDIUM,
            ),
            FunctionTool(
                "list_email_drafts",
                "List local email drafts",
                list_email_drafts,
                RiskLevel.LOW,
            ),
            FunctionTool(
                "read_email_draft",
                "Read a local email draft by id",
                read_email_draft,
                RiskLevel.LOW,
            ),
            FunctionTool(
                "search_email_drafts",
                "Search local email drafts",
                search_email_drafts,
                RiskLevel.LOW,
            ),
            FunctionTool(
                "search_inbox",
                "Search IMAP inbox (SUBJECT/FROM); configure IMAP_* in .env",
                search_inbox,
                RiskLevel.LOW,
            ),
            FunctionTool(
                "read_email",
                "Read one IMAP message by id from search_inbox",
                read_email,
                RiskLevel.LOW,
            ),
            FunctionTool(
                "send_email",
                "Send an email via SMTP (requires confirmation)",
                send_email,
                RiskLevel.HIGH,
                True,
            ),
        ):
            registry.register(tool)
    except Exception:
        pass

    try:
        from tools.analysis.csv_tools import analyze_csv, analyze_excel, profile_dataset
        from tools.data_engineering.airflow import (
            airflow_dag_runs,
            check_airflow,
            list_airflow_dags,
        )
        from tools.data_engineering.clickhouse import (
            check_clickhouse,
            clickhouse_databases,
            clickhouse_query,
            clickhouse_tables,
        )
        from tools.data_engineering.docker import (
            check_docker,
            docker_compose_ps,
            list_containers,
        )
        from tools.data_engineering.mysql import check_mysql
        from tools.data_engineering.stack import check_data_stack

        for tool in (
            FunctionTool("check_docker", "Check Docker engine status", check_docker, RiskLevel.LOW),
            FunctionTool(
                "list_containers",
                "List Docker containers",
                list_containers,
                RiskLevel.LOW,
            ),
            FunctionTool(
                "docker_compose_ps",
                "Show docker compose service status for a project directory",
                docker_compose_ps,
                RiskLevel.LOW,
            ),
            FunctionTool(
                "check_clickhouse",
                "Check ClickHouse availability",
                check_clickhouse,
                RiskLevel.LOW,
            ),
            FunctionTool(
                "clickhouse_databases",
                "List ClickHouse databases",
                clickhouse_databases,
                RiskLevel.LOW,
            ),
            FunctionTool(
                "clickhouse_tables",
                "List tables in a ClickHouse database",
                clickhouse_tables,
                RiskLevel.LOW,
            ),
            FunctionTool(
                "clickhouse_query",
                "Run a read-only ClickHouse SQL query",
                clickhouse_query,
                RiskLevel.MEDIUM,
            ),
            FunctionTool("check_airflow", "Check Airflow health", check_airflow, RiskLevel.LOW),
            FunctionTool(
                "list_airflow_dags",
                "List Airflow DAGs",
                list_airflow_dags,
                RiskLevel.LOW,
            ),
            FunctionTool(
                "airflow_dag_runs",
                "Show recent Airflow DAG runs",
                airflow_dag_runs,
                RiskLevel.LOW,
            ),
            FunctionTool(
                "check_mysql",
                "Check MySQL/MariaDB port availability",
                check_mysql,
                RiskLevel.LOW,
            ),
            FunctionTool(
                "check_data_stack",
                "Check Docker, ClickHouse, Airflow and MySQL together",
                check_data_stack,
                RiskLevel.LOW,
            ),
            FunctionTool(
                "analyze_csv",
                "Profile a CSV file with deterministic statistics",
                analyze_csv,
                RiskLevel.LOW,
            ),
            FunctionTool(
                "analyze_excel",
                "Profile an Excel .xlsx sheet with deterministic statistics",
                analyze_excel,
                RiskLevel.LOW,
            ),
            FunctionTool(
                "profile_dataset",
                "Profile CSV or Excel depending on file extension",
                profile_dataset,
                RiskLevel.LOW,
            ),
        ):
            registry.register(tool)
    except Exception:
        pass

    try:
        from tools.development.git_tools import (
            create_branch,
            git_commit,
            git_diff,
            git_log,
            git_status,
        )
        from tools.development.project_tools import create_project, read_project, write_code
        from tools.development.python_tools import inspect_traceback, run_python, run_tests

        for tool in (
            FunctionTool(
                "git_status",
                "Show git status for a repository path",
                git_status,
                RiskLevel.LOW,
            ),
            FunctionTool(
                "git_diff",
                "Show git diff summary (optionally staged)",
                git_diff,
                RiskLevel.LOW,
            ),
            FunctionTool(
                "git_log",
                "Show recent git commits",
                git_log,
                RiskLevel.LOW,
            ),
            FunctionTool(
                "create_branch",
                "Create and check out a new local git branch",
                create_branch,
                RiskLevel.MEDIUM,
            ),
            FunctionTool(
                "git_commit",
                "Create a local git commit (never pushes)",
                git_commit,
                RiskLevel.HIGH,
                True,
            ),
            FunctionTool(
                "run_python",
                "Run a Python script and return output with exit code",
                run_python,
                RiskLevel.MEDIUM,
            ),
            FunctionTool(
                "run_tests",
                "Run pytest (or unittest) for a project/path",
                run_tests,
                RiskLevel.MEDIUM,
            ),
            FunctionTool(
                "inspect_traceback",
                "Summarize a Python traceback from text or a log file",
                inspect_traceback,
                RiskLevel.LOW,
            ),
            FunctionTool(
                "create_project",
                "Scaffold a new project directory",
                create_project,
                RiskLevel.MEDIUM,
            ),
            FunctionTool(
                "read_project",
                "Summarize a project directory structure",
                read_project,
                RiskLevel.LOW,
            ),
            FunctionTool(
                "write_code",
                "Write source code to a file (path-guarded)",
                write_code,
                RiskLevel.MEDIUM,
            ),
        ):
            registry.register(tool)
    except Exception:
        pass

    for name, friendly in (
        ("open_visual_studio", "Visual Studio"),
        ("open_notepad", "Notepad"),
        ("open_calculator", "Calculator"),
        ("open_cmd", "Command Prompt"),
        ("open_powershell", "Windows PowerShell"),
    ):
        registry.register(_wrap_open(name, friendly))

    from tools.file_tools import (
        copy_file,
        create_file,
        delete_file,
        get_file_info,
        list_files,
        move_file,
        read_file,
        rename_file,
        search_files,
    )
    from tools.system_status import get_system_status, list_processes
    from tools.system_tools import restart_pc, shutdown_pc, sleep_pc
    from tools.terminal_tools import (
        run_cmd_command,
        run_powershell_command,
        run_python_script,
    )

    for tool in (
        FunctionTool("create_file", "Create a file", create_file, RiskLevel.MEDIUM),
        FunctionTool("read_file", "Read a file", read_file, RiskLevel.LOW),
        FunctionTool("list_files", "List files in a folder", list_files, RiskLevel.LOW),
        FunctionTool(
            "search_files",
            "Search for files under a folder with optional extension/size filters",
            search_files,
            RiskLevel.LOW,
        ),
        FunctionTool("get_file_info", "Get file metadata", get_file_info, RiskLevel.LOW),
        FunctionTool("delete_file", "Delete a file", delete_file, RiskLevel.HIGH, True),
        FunctionTool("rename_file", "Rename a file", rename_file, RiskLevel.MEDIUM),
        FunctionTool("move_file", "Move a file", move_file, RiskLevel.MEDIUM),
        FunctionTool("copy_file", "Copy a file", copy_file, RiskLevel.MEDIUM),
        FunctionTool(
            "get_system_status",
            "Report CPU, RAM, disk, Ollama and OpenClaw status",
            get_system_status,
            RiskLevel.LOW,
        ),
        FunctionTool(
            "list_processes",
            "List top processes by memory usage",
            list_processes,
            RiskLevel.LOW,
        ),
        FunctionTool(
            "run_python_script",
            "Run a Python script",
            run_python_script,
            RiskLevel.MEDIUM,
        ),
        FunctionTool(
            "run_cmd_command",
            "Run a CMD command",
            run_cmd_command,
            RiskLevel.MEDIUM,
        ),
        FunctionTool(
            "run_powershell_command",
            "Run a PowerShell command",
            run_powershell_command,
            RiskLevel.MEDIUM,
        ),
        FunctionTool("shutdown_pc", "Shut down the PC", shutdown_pc, RiskLevel.HIGH, True),
        FunctionTool("restart_pc", "Restart the PC", restart_pc, RiskLevel.HIGH, True),
        FunctionTool("sleep_pc", "Put the PC to sleep", sleep_pc, RiskLevel.HIGH, True),
    ):
        registry.register(tool)

    def _import_rag():
        from rag.search import (
            ingest_document,
            list_ingested_documents,
            query_documents,
        )

        return ingest_document, query_documents, list_ingested_documents

    def _build_rag(bits):
        ingest_document, query_documents, list_ingested_documents = bits
        return [
            FunctionTool(
                "ingest_document",
                "Ingest a document into RAG",
                ingest_document,
                RiskLevel.MEDIUM,
            ),
            FunctionTool(
                "query_documents",
                "Query RAG documents",
                query_documents,
                RiskLevel.LOW,
            ),
            FunctionTool(
                "list_ingested_documents",
                "List ingested documents",
                list_ingested_documents,
                RiskLevel.LOW,
            ),
        ]

    def _import_vision():
        from vision.ocr import read_screen
        from vision.screenshot import take_screenshot
        from vision.ui_automation import (
            click_at,
            click_text,
            find_on_screen,
            press_key,
            scroll_screen,
            type_text,
        )

        return (
            take_screenshot,
            read_screen,
            find_on_screen,
            click_text,
            click_at,
            type_text,
            press_key,
            scroll_screen,
        )

    def _build_vision(bits):
        (
            take_screenshot,
            read_screen,
            find_on_screen,
            click_text,
            click_at,
            type_text,
            press_key,
            scroll_screen,
        ) = bits
        return [
            FunctionTool("take_screenshot", "Capture the screen", take_screenshot, RiskLevel.LOW),
            FunctionTool("read_screen", "OCR the screen", read_screen, RiskLevel.LOW),
            FunctionTool(
                "find_on_screen",
                "Find on-screen text via OCR and return coordinates (no click)",
                find_on_screen,
                RiskLevel.LOW,
            ),
            FunctionTool("click_text", "Click on-screen text", click_text, RiskLevel.MEDIUM, True),
            FunctionTool(
                "click_at",
                "Click absolute screen coordinates from find_on_screen",
                click_at,
                RiskLevel.MEDIUM,
                True,
            ),
            FunctionTool(
                "type_text",
                "Type text via UI automation",
                type_text,
                RiskLevel.MEDIUM,
                True,
            ),
            FunctionTool("press_key", "Press a keyboard key", press_key, RiskLevel.MEDIUM, True),
            FunctionTool(
                "scroll_screen",
                "Scroll the active window (positive=up, negative=down)",
                scroll_screen,
                RiskLevel.MEDIUM,
                True,
            ),
        ]

    _safe_register(registry, _import_rag, _build_rag)
    _safe_register(registry, _import_vision, _build_vision)

    return registry
