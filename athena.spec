# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Athena — Windows onedir desktop build."""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

try:
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )
except Exception:  # non-Windows build host
    VSVersionInfo = None  # type: ignore

ROOT = Path(SPECPATH)

datas, binaries, hiddenimports = [], [], []

_PACKAGES = [
    "PyQt6",
    "sounddevice",
    "_sounddevice_data",
    "cv2",
    "numpy",
    "google.genai",
    "google.generativeai",
    "fastapi",
    "starlette",
    "uvicorn",
    "pydantic",
    "cryptography",
    "PIL",
    "qrcode",
    "mss",
    "psutil",
    "playwright",
    "duckduckgo_search",
    "ddgs",
    "pandas",
    "openpyxl",
    "pyarrow",
    "comtypes",
    "pycaw",
    "multipart",
    "websockets",
    "httptools",
    "anyio",
    "h11",
    "sniffio",
    "watchfiles",
    "yaml",
    "vosk",
    "winrt",
    "edge_tts",
    "aiohttp",
    "tabulate",
    "imageio_ffmpeg",
]

for pkg in _PACKAGES:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        hiddenimports.append(pkg)

for pkg in ("actions", "core", "memory", "dashboard", "config"):
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception:
        hiddenimports.append(pkg)

hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "google.genai.types",
    "win32timezone",
    "win32com",
    "win32com.client",
    "pythoncom",
    "pywintypes",
    "pyautogui",
    "pyscreeze",
    "mouseinfo",
    "pygetwindow",
    "pyperclip",
    "send2trash",
    "youtube_transcript_api",
    "pptx",
    "bs4",
    "requests",
    "pywinauto",
    "win10toast",
    "vosk",
    "winrt.windows.foundation",
    "winrt.windows.media.control",
    "winrt.windows.ui.notifications",
    "winrt.windows.ui.notifications.management",
    "actions.whatsapp_contacts_book",
    "actions.whatsapp_bridge_client",
    "actions.whatsapp_control",
    "actions.whatsapp_watch",
    "edge_tts",
    "aiohttp",
    "aiohttp.client",
    "aiohttp.web",
    "certifi",
    "miniaudio",
    "tabulate",
    "imageio_ffmpeg",
    "yarl",
    "multidict",
    "frozenlist",
    "aiosignal",
    "aiohappyeyeballs",
    "propcache",
    "attrs",
]

_ICON = ROOT / "config" / "athena.ico"
if not _ICON.exists():
    _ICON = ROOT / "config" / "Athena.ico"

version_info = None
if VSVersionInfo is not None:
    version_info = VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=(1, 0, 0, 0),
            prodvers=(1, 0, 0, 0),
            mask=0x3F,
            flags=0x0,
            OS=0x40004,
            fileType=0x1,
            subtype=0x0,
            date=(0, 0),
        ),
        kids=[
            StringFileInfo(
                [
                    StringTable(
                        "040904B0",
                        [
                            StringStruct("CompanyName", "Athena"),
                            StringStruct("FileDescription", "Athena AI Assistant"),
                            StringStruct("FileVersion", "1.0.0"),
                            StringStruct("InternalName", "Athena"),
                            StringStruct("OriginalFilename", "Athena.exe"),
                            StringStruct("ProductName", "Athena"),
                            StringStruct("ProductVersion", "1.0.0"),
                        ],
                    )
                ]
            ),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(ROOT / "pyi_rth_athena.py")],
    excludes=[
        "torch",
        "tensorflow",
        "matplotlib",
        "scipy",
        "IPython",
        "notebook",
        "pytest",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Athena",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=str(_ICON) if _ICON.exists() else None,
    version=version_info,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Athena",
)
