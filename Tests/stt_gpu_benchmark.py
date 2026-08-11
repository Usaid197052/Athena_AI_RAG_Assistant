"""
Benchmark faster-whisper STT on CPU vs GPU.

Creates a short speech sample with Piper, then times transcription
on both devices.

Run: python -m Tests.stt_gpu_benchmark
"""

import os
import site
import time
import wave
from pathlib import Path

# Ensure pip-installed CUDA 12 DLLs are discoverable on Windows.
_extra_bins = []

for _sp in site.getsitepackages():
    for _rel in (
        "nvidia/cublas/bin",
        "nvidia/cudnn/bin",
        "nvidia/cuda_nvrtc/bin",
    ):
        _bin = Path(_sp) / _rel
        if _bin.exists():
            _extra_bins.append(str(_bin))

if _extra_bins:
    os.environ["PATH"] = os.pathsep.join(
        _extra_bins + [os.environ.get("PATH", "")]
    )

import ctranslate2
from faster_whisper import WhisperModel
from piper.voice import PiperVoice


SAMPLE_PATH = Path("Tests/stt_benchmark_sample.wav")
MODEL_SIZE = "small"

PIPER_MODEL = (
    Path("voice/models/en_US-lessac-medium.onnx")
)

PIPER_CONFIG = (
    Path("voice/models/en_US-lessac-medium.onnx.json")
)

TEST_TEXT = (
    "Hey Athena, open notepad and create a file called notes. "
    "Then tell me what processes are running on this computer."
)


def make_speech_sample():

    print("Generating speech sample with Piper...")

    voice = PiperVoice.load(
        str(PIPER_MODEL),
        config_path=str(PIPER_CONFIG)
    )

    with wave.open(str(SAMPLE_PATH), "wb") as wav_file:
        voice.synthesize_wav(TEST_TEXT, wav_file)

    duration = (
        SAMPLE_PATH.stat().st_size
    )

    print(f"Sample saved: {SAMPLE_PATH}")

    return SAMPLE_PATH


def benchmark(device, compute_type, runs=3):

    print(f"\n=== {device.upper()} ({compute_type}) ===")

    load_start = time.perf_counter()

    model = WhisperModel(
        MODEL_SIZE,
        device=device,
        compute_type=compute_type
    )

    load_time = time.perf_counter() - load_start

    print(f"Model load: {load_time:.2f}s")

    # Warmup
    list(model.transcribe(str(SAMPLE_PATH), language="en"))

    times = []
    text = ""

    for i in range(runs):

        start = time.perf_counter()

        segments, info = model.transcribe(
            str(SAMPLE_PATH),
            language="en",
            vad_filter=True
        )

        text = " ".join(
            segment.text.strip()
            for segment in segments
        ).strip()

        elapsed = time.perf_counter() - start

        times.append(elapsed)

        print(f"  Run {i + 1}: {elapsed:.2f}s")

    avg = sum(times) / len(times)

    print(f"Average: {avg:.2f}s")
    print(f"Transcript: {text}")

    # Free GPU / model memory between tests
    del model

    return {
        "device": device,
        "compute_type": compute_type,
        "load_s": load_time,
        "avg_s": avg,
        "runs": times,
        "text": text
    }


def main():

    print("STT CPU vs GPU benchmark")
    print(f"GPU devices (ctranslate2): {ctranslate2.get_cuda_device_count()}")

    if not SAMPLE_PATH.exists():
        make_speech_sample()
    else:
        print(f"Using existing sample: {SAMPLE_PATH}")

    results = []

    results.append(
        benchmark("cpu", "int8")
    )

    try:
        results.append(
            benchmark("cuda", "float16")
        )
    except Exception as e:
        print(f"\nGPU float16 failed: {e}")

        try:
            results.append(
                benchmark("cuda", "int8")
            )
        except Exception as e2:
            print(f"GPU int8 also failed: {e2}")

    print("\n========== COMPARISON ==========")

    for result in results:
        print(
            f"{result['device']:5} | "
            f"{result['compute_type']:8} | "
            f"load {result['load_s']:.2f}s | "
            f"transcribe avg {result['avg_s']:.2f}s"
        )

    if len(results) >= 2:

        cpu = results[0]["avg_s"]
        gpu = results[1]["avg_s"]

        if gpu > 0:
            print(
                f"\nSpeedup: {cpu / gpu:.2f}x faster on GPU"
            )
            print(
                f"Time saved per transcription: "
                f"{cpu - gpu:.2f}s"
            )


if __name__ == "__main__":
    main()
