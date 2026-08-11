"""
Minimal local OpenClaw Gateway stub for Athena tests.

Implements:
  GET  /health
  POST /tools/invoke
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any


class _Handler(BaseHTTPRequestHandler):
    token: str = "test-token"
    server_version = "AthenaOpenClawStub/0.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _auth_ok(self) -> bool:
        auth = self.headers.get("Authorization", "")
        return auth == f"Bearer {self.token}"

    def _send(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/health"):
            self._send(200, {"ok": True, "service": "openclaw-stub"})
            return
        self._send(404, {"ok": False, "error": {"message": "not found"}})

    def do_POST(self) -> None:  # noqa: N802
        if not self.path.startswith("/tools/invoke"):
            self._send(404, {"ok": False, "error": {"message": "not found"}})
            return
        if not self._auth_ok():
            self._send(401, {"ok": False, "error": {"message": "unauthorized"}})
            return

        payload = self._read_json()
        tool = payload.get("tool") or payload.get("name")
        if tool in {"exec", "spawn", "shell"}:
            self._send(
                404,
                {
                    "ok": False,
                    "error": {
                        "type": "denied",
                        "message": f"Tool '{tool}' is denied over HTTP",
                    },
                },
            )
            return
        if tool == "sessions_list":
            self._send(200, {"ok": True, "result": {"sessions": []}})
            return
        if tool == "browser":
            self._send(
                200,
                {
                    "ok": True,
                    "result": {
                        "opened": True,
                        "args": payload.get("args") or {},
                    },
                },
            )
            return
        self._send(
            404,
            {"ok": False, "error": {"message": f"Tool '{tool}' not available"}},
        )


class OpenClawStubServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 0, token: str = "test-token") -> None:
        self.token = token
        handler = type("BoundHandler", (_Handler,), {"token": token})
        self.httpd = ThreadingHTTPServer((host, port), handler)
        self.thread = Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def endpoint(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> str:
        self.thread.start()
        return self.endpoint

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
