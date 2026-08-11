# Athena Tools

## Applications
- `open_application` / `close_application` — friendly-name match, launch/verify

## Files
- `search_files`, `read_file`, `create_file`, `copy_file`, `move_file`, `rename_file`, `delete_file`, `get_file_info`, `list_files`
- Path guard blocks writes/deletes under Windows / Program Files

## System
- `get_system_status` — CPU/RAM/disk + Ollama/OpenClaw
- `list_processes`
- `shutdown_pc` / `restart_pc` / `sleep_pc` (confirmation required)

## Data engineering
- Docker / ClickHouse / Airflow / MySQL checks
- `check_data_stack`, `analyze_csv`
- See `docs/data_engineering.md`

## Development
- Git: `git_status`, `git_diff`, `git_log`, `create_branch`, `git_commit` (no push)
- Python: `run_python`, `run_tests`, `inspect_traceback`
- Projects: `create_project`, `read_project`, `write_code`
- Analysis: `analyze_csv`, `analyze_excel`, `profile_dataset`
- See `docs/development.md`

## Email
- Drafts + SMTP send; IMAP `search_inbox` / `read_email`
- See `docs/email.md`

## Execution
Plans run through `executor/plan_executor.py` with:
1. permissions
2. tool execution
3. verification
4. `core/task_manager.py` persistence under `data/sessions/`
