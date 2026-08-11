import sounddevice as sd
from scipy.io.wavfile import write

from faster_whisper import WhisperModel

from voice.cuda_path import ensure_cuda_dll_path
from config import STT_DEVICE, STT_COMPUTE_TYPE, STT_MODEL_SIZE


SAMPLE_RATE = 16000
RECORD_SECONDS = 5


ensure_cuda_dll_path()


def _load_model():
    """
    Prefer GPU when configured; fall back to CPU int8 if CUDA fails.
    """

    try:

        print(
            f"Loading Whisper ({STT_MODEL_SIZE}) "
            f"on {STT_DEVICE}/{STT_COMPUTE_TYPE}..."
        )

        return WhisperModel(
            STT_MODEL_SIZE,
            device=STT_DEVICE,
            compute_type=STT_COMPUTE_TYPE
        )

    except Exception as error:

        print(
            f"GPU STT unavailable ({error}). "
            f"Falling back to CPU int8."
        )

        return WhisperModel(
            STT_MODEL_SIZE,
            device="cpu",
            compute_type="int8"
        )


model = _load_model()


def record_audio():

    print(
        "\nRecording... Speak now."
    )

    audio = sd.rec(
        int(RECORD_SECONDS * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16"
    )

    sd.wait()

    write(
        "recording.wav",
        SAMPLE_RATE,
        audio
    )

    print(
        "Recording complete."
    )

    return "recording.wav"


def transcribe_audio(audio_path):

    segments, info = model.transcribe(
        audio_path,
        language="en",
        vad_filter=True
    )

    text = ""

    for segment in segments:

        text += segment.text + " "

    return text.strip()


def record_seconds(seconds, output_path="wake_listening.wav"):
    """
    Records a short clip and returns the saved wav path.
    Used by STT-based wake word detection.
    """

    audio = sd.rec(
        int(seconds * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16"
    )

    sd.wait()

    write(
        output_path,
        SAMPLE_RATE,
        audio
    )

    return output_path
