"""
OpenClaw Gateway HTTP client.

Uses the official Tools Invoke API:
  POST {endpoint}/tools/invoke
  Authorization: Bearer <OPENCLAW_GATEWAY_TOKEN>

Athena's permission layer must approve actions before anything is sent here.
"""

from __future__ import annotations

from typing import Any

import requests

from config.settings import get_settings
from logs.logger import get_logger

logger = get_logger("athena.openclaw")


class OpenClawClient:
    def __init__(
        self,
        endpoint: str | None = None,
        token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        settings = get_settings()
        self.endpoint = (endpoint or settings.openclaw_endpoint).rstrip("/")
        self.timeout = timeout
        self.enabled = settings.openclaw_enabled
        self.token = token if token is not None else settings.openclaw_token

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def health(self) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "reason": "OpenClaw disabled in settings"}

        # Prefer a lightweight probe; Gateway may not expose /health on all builds.
        try:
            response = requests.get(
                f"{self.endpoint}/health",
                headers=self._headers(),
                timeout=min(self.timeout, 5),
            )
            if response.ok:
                return {
                    "ok": True,
                    "status_code": response.status_code,
                    "body": response.text[:500],
                    "probe": "health",
                }
        except requests.RequestException:
            pass

        # Fallback: invoke a read-only tool. 404 means gateway is up but tool denied.
        try:
            response = requests.post(
                f"{self.endpoint}/tools/invoke",
                headers=self._headers(),
                json={"tool": "sessions_list", "args": {}},
                timeout=min(self.timeout, 5),
            )
            if response.status_code in {200, 401, 403, 404}:
                return {
                    "ok": response.status_code != 401,
                    "status_code": response.status_code,
                    "body": response.text[:500],
                    "probe": "tools/invoke",
                    "reason": None
                    if response.status_code != 401
                    else "Unauthorized — check OPENCLAW_GATEWAY_TOKEN",
                }
            return {
                "ok": False,
                "status_code": response.status_code,
                "body": response.text[:500],
                "probe": "tools/invoke",
            }
        except requests.RequestException as exc:
            return {"ok": False, "reason": str(exc), "probe": "tools/invoke"}

    def invoke(
        self,
        tool: str,
        args: dict[str, Any] | None = None,
        action: str | None = None,
        session_key: str = "main",
    ) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("OpenClaw is disabled")

        payload: dict[str, Any] = {
            "tool": tool,
            "args": args or {},
            "sessionKey": session_key,
        }
        if action:
            payload["action"] = action

        response = requests.post(
            f"{self.endpoint}/tools/invoke",
            headers=self._headers(),
            json=payload,
            timeout=self.timeout,
        )

        try:
            body = response.json()
        except ValueError:
            body = {"raw": response.text}

        if response.status_code == 200:
            return {
                "ok": True,
                "status_code": 200,
                "result": body.get("result", body),
                "raw": body,
            }

        error = body.get("error") if isinstance(body, dict) else None
        message = None
        if isinstance(error, dict):
            message = error.get("message")
        elif isinstance(error, str):
            message = error

        return {
            "ok": False,
            "status_code": response.status_code,
            "error": message or response.text[:500],
            "raw": body,
        }

    def execute(self, action: dict[str, Any]) -> dict[str, Any]:
        """
        Backward-compatible wrapper around invoke().

        Accepts:
          {"tool": "...", "args": {...}}
        or legacy:
          {"action": "launch", "target": "..."}
        """
        if "tool" in action:
            return self.invoke(
                tool=str(action["tool"]),
                args=action.get("args") or action.get("arguments") or {},
                action=action.get("action_name"),
                session_key=str(
                    action.get("sessionKey")
                    or action.get("session_key")
                    or "main"
                ),
            )

        if action.get("action") == "launch":
            return self.invoke(
                tool="exec",
                args={
                    "command": action.get("target"),
                    "display_name": action.get("display_name"),
                },
            )

        raise ValueError("OpenClaw execute() requires a tool name or launch action")
