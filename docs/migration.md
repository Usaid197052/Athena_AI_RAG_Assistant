# Athena Migration Notes

## Rename

Product name: **Athena** (formerly Jarvis).

Filesystem path may remain `D:\Projects\Jarvis` until a deliberate folder rename.

## Strategy

1. Keep existing modules working.
2. Add new packages (`core/`, `openclaw/`, `security/`, `tools/applications/`) alongside old code.
3. Bridge old `tools/tool_registry.py` to the new registry.
4. Remove compatibility aliases only after tests pass.

## Branch

`athena-rearchitecture`

## Status

- Stages A–I complete at build-order/module level
- Production polish: prompt-injection sanitizer, version check, V1 smoke script
- Email: drafts/send + IMAP `search_inbox` / `read_email`
- Analysis: `analyze_csv` + `analyze_excel`
- UX: Owl's Vigil dashboard + live phase phrases
- OpenClaw: live gateway auth OK; enable gateway `browser` tool for full delegation
- Packaging: standalone onedir at `dist/Athena/Athena.exe`
- Next: live voice e2e (`Hey Athena, open Notepad`); enable OpenClaw browser policy
