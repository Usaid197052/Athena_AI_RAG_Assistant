"""
Combined data-stack health snapshot.
"""

from __future__ import annotations

from tools.data_engineering.airflow import check_airflow
from tools.data_engineering.clickhouse import check_clickhouse
from tools.data_engineering.docker import check_docker
from tools.data_engineering.mysql import check_mysql


def check_data_stack() -> str:
    return "\n".join(
        [
            "Data stack status",
            "-----------------",
            f"Docker:     {check_docker()}",
            f"ClickHouse: {check_clickhouse()}",
            f"Airflow:    {check_airflow()}",
            f"MySQL:      {check_mysql()}",
        ]
    )
