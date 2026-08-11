# Athena Voice

Flow:

```text
Wake word → Record → STT → Athena Core → Tools → TTS
```

## Components

- `voice/wake_word.py` — lightweight wake detection
- `voice/speech_to_text.py` — Faster-Whisper
- `voice/text_to_speech.py` — Piper TTS

## Config

```text
WAKE_WORD=hey athena
TTS_ENABLED=true
STT_ENABLED=true
STT_MODEL_SIZE=small
STT_DEVICE=cuda
```

Ollama stays off until a request needs it (see `core/ollama_manager.py`).
