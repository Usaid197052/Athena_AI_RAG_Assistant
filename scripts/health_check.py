"""Athena health check for local dependencies."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests

from config import ASSISTANT_NAME
from config.settings import get_settings
from core.ollama_manager import OllamaManager
from openclaw.health import health_report
from rag.client import RagClient


def _ok(flag: bool) -> str:
    return "OK" if flag else "FAIL"


def main() -> int:
    settings = get_settings()
    print(f"{ASSISTANT_NAME} Health Check")
    print("-" * 20)

    python_ok = sys.version_info[:2] >= (3, 12)
    print(f"Python       {_ok(python_ok)}  {sys.version.split()[0]}")

    ollama = OllamaManager()
    ollama_ok = ollama.is_running()
    print(f"Ollama       {_ok(ollama_ok)}  {settings.ollama_host}")

    rag_status = RagClient().status()
    rag_ok = bool(rag_status.get("ok"))
    rag_detail = (
        f"{rag_status.get('chunks', 0)} chunks"
        if rag_ok
        else rag_status.get("error", "down")
    )
    print(f"RAG          {_ok(rag_ok)}  {rag_detail}")

    claw = health_report()
    claw_ok = bool(claw.get("ok"))
    if not claw.get("enabled"):
        claw_note = "disabled"
    elif not claw.get("token_configured"):
        claw_note = "enabled, token missing"
        claw_ok = False
    else:
        claw_note = "connected" if claw_ok else claw.get("reason", "down")
    print(f"OpenClaw     {_ok(claw_ok)}  {claw_note}")

    mic_ok = shutil.which("ffmpeg") is not None or True  # sounddevice may still work
    try:
        import sounddevice  # noqa: F401

        mic_ok = True
    except Exception:
        mic_ok = False
    print(f"Microphone   {_ok(mic_ok)}")

    tts_model = ROOT / "voice" / "models" / "en_US-lessac-medium.onnx"
    print(f"TTS          {_ok(tts_model.exists())}")

    apps = settings.application_registry_file
    apps_ok = apps.exists()
    count = 0
    if apps_ok:
        import json

        try:
            count = len(json.loads(apps.read_text(encoding="utf-8")))
        except Exception:
            apps_ok = False
    print(f"Applications {_ok(apps_ok)}  {count} indexed" if apps_ok else f"Applications {_ok(False)}  run scripts/scan_apps.py")

    try:
        from tools.data_engineering.docker import check_docker
        from tools.data_engineering.clickhouse import clickhouse_status_payload
        from tools.data_engineering.airflow import airflow_status_payload

        docker_msg = check_docker()
        docker_ok = "online" in docker_msg.lower()
        print(f"Docker       {_ok(docker_ok)}  {docker_msg[:60]}")
        ch = clickhouse_status_payload()
        print(f"ClickHouse   {_ok(bool(ch.get('ok')))}  {ch.get('endpoint')}")
        af = airflow_status_payload()
        print(f"Airflow      {_ok(bool(af.get('ok')))}  {af.get('endpoint')}")
    except Exception as exc:
        print(f"Data stack   FAIL  {exc}")

    # Optional: confirm model tag exists when Ollama is up
    if ollama_ok:
        try:
            tags = requests.get(f"{settings.ollama_host.rstrip('/')}/api/tags", timeout=3).json()
            names = {m.get("name") for m in tags.get("models", [])}
            model_ok = settings.ollama_model in names or any(
                settings.ollama_model in n for n in names
            )
            print(f"Model        {_ok(model_ok)}  {settings.ollama_model}")
        except Exception as exc:
            print(f"Model        FAIL  {exc}")

    return 0 if python_ok and ollama_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
