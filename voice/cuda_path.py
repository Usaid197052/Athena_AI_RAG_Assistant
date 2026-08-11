"""
Adds pip-installed NVIDIA CUDA DLL folders to PATH on Windows
so faster-whisper / ctranslate2 can load cublas and cudnn.
"""

import os
import site
from pathlib import Path


def ensure_cuda_dll_path():

    bins = []

    for site_packages in site.getsitepackages():

        for relative in (
            "nvidia/cublas/bin",
            "nvidia/cudnn/bin",
            "nvidia/cuda_nvrtc/bin",
        ):

            path = Path(site_packages) / relative

            if path.exists():
                bins.append(str(path))

    if not bins:
        return

    current = os.environ.get("PATH", "")

    missing = [
        path
        for path in bins
        if path.lower() not in current.lower()
    ]

    if missing:
        os.environ["PATH"] = os.pathsep.join(
            missing + [current]
        )
