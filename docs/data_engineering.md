# Athena Data Engineering Tools

Deterministic helpers — Athena does not ask the LLM to invent connection
commands at runtime.

## Tools

### Docker
- `check_docker`
- `list_containers`
- `docker_compose_ps` (`project_dir`)

### ClickHouse
- `check_clickhouse`
- `clickhouse_databases`
- `clickhouse_tables` (`database`)
- `clickhouse_query` (`sql`) — **read-only**; mutating SQL is blocked

### Airflow
- `check_airflow`
- `list_airflow_dags`
- `airflow_dag_runs` (`dag_id`)

### MySQL / MariaDB
- `check_mysql` — TCP port check

### Combined
- `check_data_stack`

## Analysis
- `analyze_csv` / `analyze_excel` / `profile_dataset`
- See `docs/data_engineering.md`

## Configuration (`.env`)

```text
CLICKHOUSE_HOST=http://127.0.0.1:8123
CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=
AIRFLOW_URL=http://127.0.0.1:8080
AIRFLOW_USERNAME=
AIRFLOW_PASSWORD=
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
```

## Example

> "Athena, check my data stack."
> "Athena, analyze the sales CSV on my desktop."
