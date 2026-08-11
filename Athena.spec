# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Athena (onedir).

Build:
  .\\.venv\\Scripts\\python.exe -m PyInstaller Athena.spec --noconfirm
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve()

hiddenimports = [
    "pydantic",
    "pydantic_settings",
    "dotenv",
    "yaml",
    "psutil",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    "pystray",
    "requests",
    "numpy",
    "ollama",
    "ui.tray",
    "ui.dashboard",
    "core.orchestrator",
    "tools.bootstrap",
    "tools.registry",
    "openclaw.client",
    "openclaw.executor",
    "openclaw.health",
    "monitoring.service",
    "monitoring.status_store",
    "security.permissions",
    "security.sanitizer",
    "scripts.health_check",
]

# Soft-collect optional heavy stacks when installed
for package in ("openwakeword", "faster_whisper", "piper", "sounddevice"):
    try:
        hiddenimports += collect_submodules(package)
    except Exception:
        pass

datas = []
for relative in (
    "config/permissions.yaml",
    ".env.example",
    "README.md",
):
    source = ROOT / relative
    if source.exists():
        datas.append((str(source), str(Path(relative).parent)))

# Include empty-ish data placeholders so onedir layout is clear
for folder in ("data/cache", "data/logs", "data/sessions", "data/application_registry"):
    target_dir = ROOT / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    keep = target_dir / ".keep"
    if not keep.exists():
        keep.write_text("", encoding="utf-8")
    datas.append((str(keep), folder))

a = Analysis(
    [str(ROOT / "app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "scipy.tests",
        "torch.testing",
    ],
    noarchive=False,
    optimize=0,
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
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "resources" / "athena.ico")
    if (ROOT / "resources" / "athena.ico").exists()
    else None,
    version=str(ROOT / "resources" / "version_info.txt")
    if (ROOT / "resources" / "version_info.txt").exists()
    else None,
)


coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Athena",
)
