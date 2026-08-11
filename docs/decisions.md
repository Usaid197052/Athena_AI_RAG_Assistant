# Architecture Decisions

## ADR-001: Keep filesystem folder name for now

**Decision:** Do not rename `D:\Projects\Jarvis` during Stage A.

**Why:** Avoids breaking IDE solutions, absolute paths in docs/tests, and backup references. Product-facing name is Athena.

## ADR-002: Qwen3.5:9b as initial model

**Decision:** Use installed `qwen3.5:9b` (guide target: ~9.5B class).

**Why:** Already local; sufficient for intent + tool calling when paired with deterministic tools and RAG.

## ADR-003: OpenClaw optional with local fallback

**Decision:** OpenClaw client is required in the architecture, but launch falls back to local `subprocess` when OpenClaw is unavailable.

**Why:** OpenClaw is not yet installed; milestone must still open apps.

## ADR-005: PATH scanning uses an allowlist

**Decision:** Do not index every `.exe` on PATH.

**Why:** Full PATH dumps hundreds of system utilities and hurts matching quality.
Athena indexes Start Menu + known app locations + a small PATH allowlist.

