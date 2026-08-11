"""
Central Athena configuration.

Existing modules import constants from here. New code should prefer
`from config.settings import get_settings`.
"""

from config.settings import PROJECT_ROOT, get_settings

_settings = get_settings()

ASSISTANT_NAME = _settings.assistant_name
ATHENA_VERSION = _settings.athena_version

CUSTOM_WAKE_MODEL = _settings.custom_wake_model
WAKE_PHRASES = _settings.wake_phrases
WAKE_LISTEN_SECONDS = _settings.wake_listen_seconds
WAKE_WORD_THRESHOLD = _settings.wake_word_threshold
WAKE_WORD_COOLDOWN_SECONDS = _settings.wake_word_cooldown_seconds

OLLAMA_MODEL = _settings.ollama_model
EMBEDDING_MODEL = _settings.embedding_model
OLLAMA_HOST = _settings.ollama_host

STT_MODEL_SIZE = _settings.stt_model_size
STT_DEVICE = _settings.stt_device
STT_COMPUTE_TYPE = _settings.stt_compute_type

LOG_FILE = _settings.log_file
