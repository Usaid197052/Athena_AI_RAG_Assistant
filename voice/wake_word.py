import time
import re

import sounddevice as sd
import numpy as np

from config import (
    ASSISTANT_NAME,
    CUSTOM_WAKE_MODEL,
    WAKE_PHRASES,
    WAKE_LISTEN_SECONDS,
    WAKE_WORD_THRESHOLD,
    WAKE_WORD_COOLDOWN_SECONDS
)

from logs.logger import (
    log_wakeword
)


SAMPLE_RATE = 16000
CHUNK_SIZE = 1280

DETECTION_THRESHOLD = WAKE_WORD_THRESHOLD

COOLDOWN_SECONDS = WAKE_WORD_COOLDOWN_SECONDS


LAST_TTS_TIME = 0

# Lazy-loaded only if a custom ONNX wake model is present.
_oww_model = None
_oww_label = None


def pause_wake_word(seconds=5):

    global LAST_TTS_TIME

    LAST_TTS_TIME = (
        time.time() + seconds
    )


def _normalize(text):

    text = text.lower().strip()

    text = re.sub(r"[^\w\s]", " ", text)

    return re.sub(r"\s+", " ", text).strip()


def contains_wake_phrase(text):
    """
    Returns True if transcribed speech contains a wake phrase.
    """

    normalized = _normalize(text)

    if not normalized:
        return False

    for phrase in WAKE_PHRASES:

        if phrase in normalized:
            return True

    return False


def _wait_with_onnx():
    """
    Fast wake detection using a custom hey_athena.onnx model.
    """

    global _oww_model, _oww_label

    from openwakeword.model import Model

    print("Loading Athena OpenWakeWord model...")

    _oww_label = CUSTOM_WAKE_MODEL.stem

    _oww_model = Model(
        wakeword_models=[str(CUSTOM_WAKE_MODEL)],
        inference_framework="onnx"
    )

    print(
        f"Wake word model loaded. Say 'Hey {ASSISTANT_NAME}'."
    )

    last_detection = 0
    detected = False

    def audio_callback(indata, frames, time_info, status):

        nonlocal detected
        nonlocal last_detection

        if status:
            return

        if time.time() < LAST_TTS_TIME:
            return

        audio = indata.flatten().astype(np.int16)

        predictions = _oww_model.predict(audio)

        score = 0

        if _oww_label in predictions:
            score = predictions[_oww_label]
        elif predictions:
            score = max(predictions.values())

        if score > 0.3:
            print(f"Wake score: {score:.2f}")

        now = time.time()

        if (
            score > DETECTION_THRESHOLD
            and now - last_detection > COOLDOWN_SECONDS
        ):

            print(f"\nWake word detected ({score:.2f})")

            log_wakeword(score, model_name=_oww_label)

            last_detection = now
            detected = True

    with sd.InputStream(
        channels=1,
        samplerate=SAMPLE_RATE,
        dtype="int16",
        blocksize=CHUNK_SIZE,
        callback=audio_callback
    ):

        while not detected:
            time.sleep(0.1)


def _wait_with_stt():
    """
    Wake detection by listening for spoken 'Hey Athena' via Whisper.
    No custom wake-word training required.
    """

    from voice.speech_to_text import (
        record_seconds,
        transcribe_audio
    )

    print(
        f"Listening for wake word via speech recognition. "
        f"Say 'Hey {ASSISTANT_NAME}'."
    )

    while True:

        if time.time() < LAST_TTS_TIME:
            time.sleep(0.1)
            continue

        wav_path = record_seconds(WAKE_LISTEN_SECONDS)

        text = transcribe_audio(wav_path)

        if text:
            print(f"Heard: {text}")

        if contains_wake_phrase(text):

            print(f"\nWake word detected: {text}")

            log_wakeword(1.0, model_name="stt_hey_athena")

            return


def wait_for_wake_word():

    print(
        f"\nListening for wake word "
        f"('Hey {ASSISTANT_NAME}')..."
    )

    if CUSTOM_WAKE_MODEL.exists():
        _wait_with_onnx()
    else:
        _wait_with_stt()
