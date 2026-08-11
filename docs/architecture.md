# Athena Architecture

## Principle

**Athena thinks, tools act, OpenClaw executes, RAG remembers, Whisper hears, TTS speaks.**

The LLM never directly controls Windows. It produces structured tool calls that pass through permissions, deterministic tools, optional OpenClaw execution, and verification.

## Layers

```text
Voice / Text / Tray
        ↓
Athena Core (orchestrator, context, planner)
        ↓
RAG / Ollama / System state
        ↓
Action planner → Permission check → Tool registry
        ↓
Applications / Files / Browser / Dev / Data / Communication
        ↓
OpenClaw (or local fallback executor)
        ↓
Windows
```

## Initial model

`qwen3.5:9b` via Ollama. Application paths are resolved by deterministic discovery — never by the LLM.

## First milestone

> "Hey Athena, open Visual Studio."

Wake → STT → tool call `open_application` → match → launch → verify → speak.
