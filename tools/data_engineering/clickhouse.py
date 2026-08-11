"""
ClickHouse helpers via HTTP interface.

Uses deterministic requests — Athena never asks the LLM to invent
connection strings at execution time.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

import requests

from config.settings import get_settings


def _base_url() -> str:
    settings = get_settings()
    host = settings.clickhouse_host.rstrip("/")
    return host


def _auth() -> tuple[str, str] | None:
    settings = get_settings()
    user = settings.clickhouse_user
    password = settings.clickhouse_password
    if user:
        return user, password
    return None


def _query(sql: str, timeout: float = 15.0) -> tuple[bool, str]:
    url = f"{_base_url()}/"
    params = {"query": sql}
    try:
        response = requests.get(
            url,
            params=params,
            auth=_auth(),
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return False, str(exc)

    if not response.ok:
        return False, response.text[:500] or f"HTTP {response.status_code}"
    return True, response.text.strip()


def check_clickhouse() -> str:
    ok, output = _query("SELECT version()")
    if not ok:
        return f"ClickHouse unavailable: {output}"
    return f"ClickHouse online. Version: {output}"


def clickhouse_databases() -> str:
    ok, output = _query("SHOW DATABASES")
    if not ok:
        return f"Error listing databases: {output}"
    dbs = [line for line in output.splitlines() if line.strip()]
    return "Databases:\n" + "\n".join(dbs) if dbs else "No databases returned."


def clickhouse_tables(database: str = "default") -> str:
    db = database.replace("`", "")
    ok, output = _query(f"SHOW TABLES FROM `{db}`")
    if not ok:
        return f"Error listing tables: {output}"
    tables = [line for line in output.splitlines() if line.strip()]
    if not tables:
        return f"No tables in database '{db}'."
    return f"Tables in {db}:\n" + "\n".join(tables)


def clickhouse_query(sql: str, max_rows: int = 50) -> str:
    """
    Run a read-oriented SQL query. Blocks obvious mutating statements.
    """
    text = sql.strip().rstrip(";")
    lower = text.lower()
    first = lower.split(None, 1)[0] if lower else ""
    banned_starts = {
        "drop",
        "truncate",
        "alter",
        "insert",
        "delete",
        "rename",
        "attach",
        "detach",
        "grant",
        "revoke",
        "optimize",
    }
    if first in banned_starts or first == "system":
        return (
            "Error: mutating ClickHouse statements are blocked. "
            "Use a dedicated write tool after explicit approval."
        )

    limited = text
    if lower.startswith("select") and " limit " not in lower:
        limited = f"{text} LIMIT {max(1, int(max_rows))}"

    ok, output = _query(limited)
    if not ok:
        return f"Error running query: {output}"
    if not output:
        return "(empty result)"
    lines = output.splitlines()
    if len(lines) > max_rows:
        return "\n".join(lines[:max_rows]) + f"\n... truncated ({len(lines)} lines)"
    return output


def clickhouse_status_payload() -> dict[str, Any]:
    ok, version = _query("SELECT version()")
    return {
        "ok": ok,
        "endpoint": _base_url(),
        "version": version if ok else None,
        "error": None if ok else version,
    }
