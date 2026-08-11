"""
Ollama lifecycle helpers for Athena.

Start/check/request/shutdown. Heavy models should not stay loaded
during long idle periods.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from typing import Any

import requests

from config.settings import get_settings
from logs.logger import get_logger

logger = get_logger("athena.ollama")


class OllamaManager:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._process: subprocess.Popen | None = None

    @property
    def host(self) -> str:
        return self.settings.ollama_host.rstrip("/")

    def is_running(self) -> bool:
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=2)
            return response.ok
        except requests.RequestException:
            return False

    def start(self) -> bool:
        if self.is_running():
            return True

        binary = shutil.which("ollama")
        if not binary:
            logger.error("Ollama binary not found on PATH")
            return False

        try:
            self._process = subprocess.Popen(
                [binary, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for _ in range(20):
                if self.is_running():
                    logger.info("Ollama started")
                    return True
                time.sleep(0.5)
        except Exception as exc:
            logger.error("Failed to start Ollama: %s", exc)
        return False

    def ensure_ready(self) -> bool:
        return self.is_running() or self.start()

    def chat(self, prompt: str, model: str | None = None) -> str:
        if not self.ensure_ready():
            raise RuntimeError("Ollama is unavailable")

        model = model or self.settings.ollama_model
        response = requests.post(
            f"{self.host}/api/chat",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            },
            timeout=120,
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        return payload.get("message", {}).get("content", "")

    def shutdown(self) -> None:
        # Prefer stopping the model to free VRAM; leave daemon if system-managed.
        try:
            requests.post(
                f"{self.host}/api/generate",
                json={
                    "model": self.settings.ollama_model,
                    "keep_alive": 0,
                    "prompt": "",
                },
                timeout=10,
            )
            logger.info("Requested Ollama model unload")
        except requests.RequestException as exc:
            logger.debug("Model unload skipped: %s", exc)
