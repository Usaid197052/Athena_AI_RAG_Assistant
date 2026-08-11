"""
Athena configuration via environment + defaults.

Secrets belong in .env (never committed). Non-secret defaults
can also be overridden with ATHENA_* / OLLAMA_* env vars.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    assistant_name: str = Field(default="Athena", alias="ATHENA_NAME")
    athena_version: str = Field(default="0.1.0", alias="ATHENA_VERSION")

    ollama_host: str = Field(
        default="http://127.0.0.1:11434",
        alias="OLLAMA_HOST",
    )
    ollama_model: str = Field(default="qwen3.5:9b", alias="OLLAMA_MODEL")
    embedding_model: str = Field(
        default="nomic-embed-text",
        alias="EMBEDDING_MODEL",
    )

    rag_endpoint: str = Field(default="", alias="RAG_ENDPOINT")
    openclaw_endpoint: str = Field(
        default="http://127.0.0.1:18789",
        alias="OPENCLAW_ENDPOINT",
    )
    openclaw_enabled: bool = Field(default=False, alias="OPENCLAW_ENABLED")
    openclaw_token: str = Field(
        default="",
        alias="OPENCLAW_GATEWAY_TOKEN",
    )

    wake_word: str = Field(default="hey athena", alias="WAKE_WORD")
    tts_enabled: bool = Field(default=True, alias="TTS_ENABLED")
    stt_enabled: bool = Field(default=True, alias="STT_ENABLED")

    idle_timeout: int = Field(default=300, alias="IDLE_TIMEOUT_SECONDS")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        alias="LOG_LEVEL",
    )

    confirmation_policy: str = Field(
        default="confirm_medium_high",
        alias="CONFIRMATION_POLICY",
    )
    auto_execute_low_risk: bool = Field(
        default=True,
        alias="AUTO_EXECUTE_LOW_RISK",
    )
    confirm_medium_risk: bool = Field(
        # False during migration so existing medium tools behave as before.
        # Set CONFIRM_MEDIUM_RISK=true for stricter Athena policy.
        default=False,
        alias="CONFIRM_MEDIUM_RISK",
    )
    confirm_high_risk: bool = Field(
        default=True,
        alias="CONFIRM_HIGH_RISK",
    )

    stt_model_size: str = Field(default="small", alias="STT_MODEL_SIZE")
    stt_device: str = Field(default="cuda", alias="STT_DEVICE")
    stt_compute_type: str = Field(default="float16", alias="STT_COMPUTE_TYPE")

    wake_listen_seconds: float = Field(default=2.0, alias="WAKE_LISTEN_SECONDS")
    wake_word_threshold: float = Field(default=0.85, alias="WAKE_WORD_THRESHOLD")
    wake_word_cooldown_seconds: float = Field(
        default=3.0,
        alias="WAKE_WORD_COOLDOWN_SECONDS",
    )

    @property
    def project_root(self) -> Path:
        return PROJECT_ROOT

    @property
    def log_file(self) -> Path:
        return PROJECT_ROOT / "logs" / "athena.log"

    @property
    def permissions_file(self) -> Path:
        return PROJECT_ROOT / "config" / "permissions.yaml"

    @property
    def application_registry_dir(self) -> Path:
        return PROJECT_ROOT / "data" / "application_registry"

    @property
    def application_registry_file(self) -> Path:
        return self.application_registry_dir / "apps.json"

    @property
    def custom_wake_model(self) -> Path:
        return PROJECT_ROOT / "voice" / "models" / "hey_athena.onnx"

    @property
    def wake_phrases(self) -> tuple[str, ...]:
        return (
            "hey athena",
            "hi athena",
            "okay athena",
            "ok athena",
            "athena",
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
