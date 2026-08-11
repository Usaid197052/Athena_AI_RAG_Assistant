# Athena ↔ OpenClaw

OpenClaw is an **execution provider**, not Athena's brain.

```text
LLM → Tool → Permission → OpenClaw (or local fallback) → Windows
```

## Configure

In `.env`:

```text
OPENCLAW_ENABLED=true
OPENCLAW_ENDPOINT=http://127.0.0.1:18789
OPENCLAW_GATEWAY_TOKEN=your-gateway-token
```

Token maps to OpenClaw `gateway.auth.token` / `OPENCLAW_GATEWAY_TOKEN`.

## API used by Athena

`POST /tools/invoke` with bearer auth (official Tools Invoke API).

## What stays local

Gateway HTTP **denies** `exec` / `spawn` / `shell` by default.

Therefore Athena keeps:

- application launch/close
- file tools
- system tools

on the local deterministic tool layer.

## What can use OpenClaw

When enabled and healthy:

- `search_web`
- `open_url`

These adapt to OpenClaw `browser` tool calls. If OpenClaw is down, Athena falls back to the local browser.

## Modules

- `openclaw/client.py` — health + invoke
- `openclaw/adapters.py` — Athena action → OpenClaw tool mapping
- `openclaw/executor.py` — launch local + optional OpenClaw delegation
- `openclaw/health.py` — status for dashboard/health check
- `openclaw/stub_server.py` — local stub for tests

## Check

```powershell
python scripts\health_check.py
```
