# Athena Development Tools

Deterministic helpers for local software work. Athena never invents raw
shell git/python commands for these flows — tools wrap known-safe operations.

**Push is intentionally not exposed.** Commits stay local until the user
pushes manually or a future high-risk tool is explicitly enabled.

## Tools

### Git
- `git_status` (`path`) — short status + branch
- `git_diff` (`path`, `staged`) — diffstat
- `git_log` (`path`, `limit`) — recent commits
- `create_branch` (`branch_name`, `path`) — local checkout -b
- `git_commit` (`message`, `path`, `add_all`) — local commit only (**HIGH**, confirmation)

Blocked: `--force`, `--hard`, delete flags, and any push path.

### Python
- `run_python` (`script_path`, `args`) — run a script; reports exit code
- `run_tests` (`path`, `pattern`) — pytest preferred, unittest fallback
- `inspect_traceback` (`text` or `file_path`) — summarize a traceback

### Projects
- `create_project` (`name`, `parent_dir`, `kind`) — scaffold (default `python`)
- `read_project` (`path`) — markers + shallow tree
- `write_code` (`file_path`, `content`, `overwrite`) — path-guarded write

## Recommended flow for code changes

```text
read_project
  ↓
write_code
  ↓
run_tests
  ↓
git_status / git_diff
  ↓
git_commit (with confirmation)
```

## Risk

| Tool | Risk |
|------|------|
| git_status / git_diff / git_log / read_project / inspect_traceback | LOW |
| create_branch / create_project / write_code / run_python / run_tests | MEDIUM |
| git_commit | HIGH |

## Contributor notes

Branch: `athena-rearchitecture`

```powershell
.venv\Scripts\python.exe -m pytest Tests/unit -q
```

New tools: implement under `tools/`, register in `tools/bootstrap.py`, declare risk in `config/permissions.yaml`.
