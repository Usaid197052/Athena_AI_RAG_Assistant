"""
Airflow health / DAG inspection via the Airflow REST API when available.
"""

from __future__ import annotations

from typing import Any

import requests

from config.settings import get_settings


def _session() -> tuple[str, tuple[str, str] | None]:
    settings = get_settings()
    base = settings.airflow_url.rstrip("/")
    auth = None
    if settings.airflow_username:
        auth = (settings.airflow_username, settings.airflow_password)
    return base, auth


def check_airflow() -> str:
    base, auth = _session()
    try:
        response = requests.get(f"{base}/health", auth=auth, timeout=8)
    except requests.RequestException as exc:
        return f"Airflow unavailable: {exc}"

    if not response.ok:
        return f"Airflow health check failed: HTTP {response.status_code}"

    try:
        payload = response.json()
    except ValueError:
        return f"Airflow responded: {response.text[:200]}"

    parts = []
    for key in ("metadatabase", "scheduler", "triggerer", "dag_processor"):
        section = payload.get(key) or {}
        status = section.get("status") or section.get("healthy")
        if status is not None:
            parts.append(f"{key}={status}")
    detail = ", ".join(parts) if parts else str(payload)[:300]
    return f"Airflow online. {detail}"


def list_airflow_dags(limit: int = 20) -> str:
    base, auth = _session()
    try:
        response = requests.get(
            f"{base}/api/v1/dags",
            params={"limit": max(1, int(limit))},
            auth=auth,
            timeout=12,
        )
    except requests.RequestException as exc:
        return f"Error listing DAGs: {exc}"

    if response.status_code == 401:
        return "Error listing DAGs: unauthorized (check AIRFLOW_USERNAME/PASSWORD)."
    if not response.ok:
        return f"Error listing DAGs: HTTP {response.status_code} {response.text[:200]}"

    payload = response.json()
    dags = payload.get("dags") or []
    if not dags:
        return "No DAGs returned."

    lines = []
    for dag in dags[: max(1, int(limit))]:
        dag_id = dag.get("dag_id", "?")
        paused = dag.get("is_paused")
        lines.append(f"{dag_id}\tpaused={paused}")
    return "DAG_ID\tPAUSED\n" + "\n".join(lines)


def airflow_dag_runs(dag_id: str, limit: int = 5) -> str:
    base, auth = _session()
    dag = dag_id.strip()
    if not dag:
        return "Error: dag_id is required."
    try:
        response = requests.get(
            f"{base}/api/v1/dags/{dag}/dagRuns",
            params={"limit": max(1, int(limit)), "order_by": "-start_date"},
            auth=auth,
            timeout=12,
        )
    except requests.RequestException as exc:
        return f"Error fetching DAG runs: {exc}"

    if not response.ok:
        return f"Error fetching DAG runs: HTTP {response.status_code} {response.text[:200]}"

    runs = (response.json() or {}).get("dag_runs") or []
    if not runs:
        return f"No runs found for DAG '{dag}'."

    lines = []
    for run in runs:
        lines.append(
            f"{run.get('dag_run_id')}\t{run.get('state')}\t{run.get('start_date')}"
        )
    return "DAG_RUN_ID\tSTATE\tSTART\n" + "\n".join(lines)


def airflow_status_payload() -> dict[str, Any]:
    base, auth = _session()
    try:
        response = requests.get(f"{base}/health", auth=auth, timeout=5)
        return {
            "ok": response.ok,
            "endpoint": base,
            "status_code": response.status_code,
        }
    except requests.RequestException as exc:
        return {"ok": False, "endpoint": base, "error": str(exc)}
