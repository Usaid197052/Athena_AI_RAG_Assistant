"""
Build a standalone Athena folder: dist/Athena/Athena.exe

Usage (from the repo root, same Python that runs the app):
    python build.py

The result is a folder you can zip and copy. It is not a signed installer.
First launch still asks for a Gemini API key. Browser automation uses the
Chrome/Edge already installed on the PC — Playwright's browser binaries
are not bundled (they add several hundred MB).
"""
from __future__ import annotations

import io
import json
import os
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist" / "Athena"
SPEC = ROOT / "athena.spec"
SRC_PNG = ROOT / "config" / "athena.png"
SRC_ICO = ROOT / "config" / "athena.ico"


def _copy_tree(src: Path, dst: Path, ignore=None) -> None:
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=ignore)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _write_ico(png_path: Path, ico_path: Path) -> None:
    """Write a multi-size PNG-in-ICO so Windows Explorer and the taskbar stay sharp."""
    from PIL import Image

    img = Image.open(png_path).convert("RGBA")
    sizes = [16, 24, 32, 48, 64, 128, 256]
    blobs: list[tuple[int, bytes]] = []
    for s in sizes:
        buf = io.BytesIO()
        img.resize((s, s), Image.LANCZOS).save(buf, format="PNG")
        blobs.append((s, buf.getvalue()))

    count = len(blobs)
    header = struct.pack("<HHH", 0, 1, count)
    entries = b""
    offset = 6 + 16 * count
    data = b""
    for s, blob in blobs:
        w = 0 if s >= 256 else s
        h = 0 if s >= 256 else s
        entries += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(blob), offset)
        data += blob
        offset += len(blob)
    ico_path.parent.mkdir(parents=True, exist_ok=True)
    ico_path.write_bytes(header + entries + data)


def _ensure_icons() -> Path:
    if SRC_PNG.exists() and (not SRC_ICO.exists() or SRC_ICO.stat().st_size < 4096):
        print("Generating config/athena.ico from config/athena.png…")
        _write_ico(SRC_PNG, SRC_ICO)
    if SRC_ICO.exists():
        return SRC_ICO
    fallback = ROOT / "config" / "Athena.ico"
    return fallback if fallback.exists() else SRC_ICO


def _merge_service_credentials() -> None:
    """
    Copy Spotify / Gmail client settings (and tokens) into the packaged
    config without replacing a Gemini key the user already entered there.
    The full api_keys.json file is never overwritten as a unit.
    """
    src = ROOT / "config" / "api_keys.json"
    dst = DIST / "config" / "api_keys.json"
    if not src.exists():
        return
    try:
        src_data = json.loads(src.read_text(encoding="utf-8"))
    except Exception:
        return
    dst_data: dict = {}
    if dst.exists():
        try:
            dst_data = json.loads(dst.read_text(encoding="utf-8"))
        except Exception:
            dst_data = {}
    changed = False
    for section in ("spotify", "gmail"):
        block = src_data.get(section)
        if isinstance(block, dict) and block:
            dst_data[section] = dict(block)
            changed = True
    if not changed:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(dst_data, indent=2), encoding="utf-8")
    print("Merged Spotify/Gmail credentials into dist config.")


def _stash_user_runtime() -> Path | None:
    """Keep packaged config/memory across a rebuild (PyInstaller wipes dist/)."""
    if not DIST.exists():
        return None
    stash = ROOT / "build" / "_athena_user_stash"
    if stash.exists():
        shutil.rmtree(stash, ignore_errors=True)
    stash.mkdir(parents=True, exist_ok=True)
    copied = False
    for name in ("config", "memory", "logs", "Contacts"):
        src = DIST / name
        if src.exists():
            _copy_tree(src, stash / name)
            copied = True
    return stash if copied else None


def _restore_user_runtime(stash: Path | None) -> None:
    if not stash or not stash.exists():
        _merge_service_credentials()
        return
    keys = stash / "config" / "api_keys.json"
    if keys.exists():
        dest = DIST / "config" / "api_keys.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(keys, dest)
        print("Restored packaged api_keys.json (Gemini / UI / tokens).")
    mem = stash / "memory"
    if mem.exists():
        _copy_tree(
            mem,
            DIST / "memory",
            ignore=shutil.ignore_patterns("whatsapp_baileys"),
        )
        print("Restored packaged memory/ (WhatsApp session left fresh for new link).")
    logs = stash / "logs"
    if logs.exists():
        _copy_tree(logs, DIST / "logs")
    # Contacts: keep the README from source; do not copy a previous user's VCF/CSV.
    _merge_service_credentials()
    try:
        shutil.rmtree(stash, ignore_errors=True)
    except Exception:
        pass


def _ensure_whatsapp_packages() -> None:
    """Install Baileys/express into whatsapp_bridge so the zip needs no npm."""
    bd = ROOT / "whatsapp_bridge"
    if not (bd / "package.json").exists():
        print("WARNING: whatsapp_bridge/package.json missing.")
        return
    marker = bd / "node_modules" / "express"
    if marker.exists() or (bd / "node_modules" / "@whiskeysockets").exists():
        print("WhatsApp bridge npm packages already present.")
        return
    npm = shutil.which("npm")
    if not npm:
        print(
            "WARNING: npm not found. New users will need Node 18+ to install "
            "whatsapp_bridge packages on first WhatsApp use."
        )
        return
    print("Installing WhatsApp bridge npm packages (this may take a minute)…")
    subprocess.run(
        [npm, "install", "--omit=dev"],
        cwd=str(bd),
        check=True,
    )


def _bundle_node(tools_node: Path) -> None:
    node = shutil.which("node")
    if not node:
        for candidate in (
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs" / "node.exe",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "nodejs" / "node.exe",
        ):
            if candidate.is_file():
                node = str(candidate)
                break
    if not node:
        print("WARNING: Node.js not found — WhatsApp will need Node 18+ on the target PC.")
        return
    tools_node.mkdir(parents=True, exist_ok=True)
    shutil.copy2(node, tools_node / "node.exe")
    print(f"Bundled Node.js: {node}")


def _bundle_ffmpeg(tools_ff: Path) -> None:
    """Ship ffmpeg so WhatsApp voice notes can be converted to Opus/OGG."""
    src = None
    try:
        import imageio_ffmpeg
        cand = Path(imageio_ffmpeg.get_ffmpeg_exe())
        if cand.is_file():
            src = cand
    except Exception:
        src = None
    if src is None:
        found = shutil.which("ffmpeg")
        if found:
            src = Path(found)
    if src is None or not src.is_file():
        print("WARNING: ffmpeg not found — WhatsApp voice notes may not play.")
        return
    tools_ff.mkdir(parents=True, exist_ok=True)
    dest = tools_ff / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    shutil.copy2(src, dest)
    print(f"Bundled ffmpeg: {src} -> {dest}")


def _stage_runtime_files() -> None:
    """
    PyInstaller 6 puts collected binaries in _internal/. Existing get_base_dir()
    code looks next to the exe, so copy the files the app opens by path.
    Do not copy api_keys.json or WhatsApp session files (secrets stay local).
    """
    _copy_tree(ROOT / "core" / "prompt.txt", DIST / "core" / "prompt.txt")
    _copy_tree(ROOT / "dashboard" / "static", DIST / "dashboard" / "static")
    _copy_tree(ROOT / "config" / "permissions.json", DIST / "config" / "permissions.json")
    if SRC_PNG.exists():
        _copy_tree(SRC_PNG, DIST / "config" / "athena.png")
    if SRC_ICO.exists():
        _copy_tree(SRC_ICO, DIST / "config" / "athena.ico")
    certs = ROOT / "config" / "certs"
    if certs.exists():
        _copy_tree(certs, DIST / "config" / "certs")

    vosk = ROOT / "models" / "vosk-small-en-us"
    if (vosk / "am" / "final.mdl").exists():
        print("Copying wake-word model…")
        _copy_tree(vosk, DIST / "models" / "vosk-small-en-us")

    _ensure_whatsapp_packages()
    bridge = ROOT / "whatsapp_bridge"
    if (bridge / "server.js").exists():
        print("Copying WhatsApp bridge (including node_modules when present)…")
        ignore = shutil.ignore_patterns(
            ".cache", "*.log", ".git", "auth_info*", ".wwebjs*",
        )
        _copy_tree(bridge, DIST / "whatsapp_bridge", ignore=ignore)

    _bundle_node(DIST / "tools" / "node")
    _bundle_ffmpeg(DIST / "tools" / "ffmpeg")

    dest_contacts = DIST / "Contacts"
    dest_contacts.mkdir(parents=True, exist_ok=True)
    readme_src = ROOT / "Contacts" / "README.txt"
    if readme_src.is_file():
        shutil.copy2(readme_src, dest_contacts / "README.txt")
        print("Copied Contacts/ README (phone book — users add their own VCF/CSV).")
    else:
        (dest_contacts / "README.txt").write_text(
            "Drop Contacts.vcf or a Google contacts.csv here, then use\n"
            "Settings → WhatsApp Setup → Import, or restart Athena.\n",
            encoding="utf-8",
        )

    (DIST / "memory").mkdir(parents=True, exist_ok=True)
    (DIST / "config").mkdir(parents=True, exist_ok=True)
    (DIST / "logs").mkdir(parents=True, exist_ok=True)
    _merge_service_credentials()

    wa_setup = DIST / "WHATSAPP_SETUP.txt"
    wa_setup.write_text(
        "Athena — WhatsApp setup (new users)\n"
        "====================================\n\n"
        "1. Start Athena.exe and enter a Gemini API key if asked.\n"
        "2. Open Settings (the gear in the header) → WhatsApp Setup.\n"
        "3. Scan the QR code with your phone:\n"
        "      WhatsApp → Linked Devices → Link a device\n"
        "4. Import your phone book:\n"
        "      Settings → WhatsApp Setup → Import VCF / CSV\n"
        "   or drop Contacts.vcf (or a Google CSV) into the Contacts folder\n"
        "   next to Athena.exe.\n\n"
        "Export from Google Contacts: contacts.google.com → Export → vCard or CSV.\n"
        "Spoken names then resolve to WhatsApp numbers. Groups still come from WhatsApp.\n\n"
        "Node.js is bundled when this build was made on a PC that had Node installed.\n"
        "If WhatsApp Setup says Node was not found, install Node 18+ from nodejs.org.\n"
        "Your WhatsApp session stays in memory\\whatsapp_baileys\\ on this PC only.\n",
        encoding="utf-8",
    )

    readme = DIST / "README.txt"
    readme.write_text(
        "Athena desktop build\n"
        "====================\n\n"
        "Double-click Athena.exe to start.\n"
        "First launch asks for a Gemini API key.\n\n"
        "Still required on this PC:\n"
        "  - Microphone and speakers\n"
        "  - Internet (Gemini Live)\n"
        "  - Chrome or Edge for browser automation\n\n"
        "WhatsApp (new users):\n"
        "  Read WHATSAPP_SETUP.txt — or open Settings ⚙ → WhatsApp Setup,\n"
        "  scan the QR, then import Contacts.vcf / Google CSV.\n\n"
        "Put Contacts.vcf (or a Google contacts.csv) in Contacts\\ next to\n"
        "Athena.exe so spoken names resolve to WhatsApp numbers.\n"
        "API keys and WhatsApp sessions are stored next to Athena.exe\n"
        "in config\\ and memory\\ — they are not packed into the exe.\n",
        encoding="utf-8",
    )


def _unlock_dist() -> None:
    """Stop packaged Athena/Node so PyInstaller can replace dist/Athena."""
    if sys.platform != "win32" or not DIST.exists():
        return
    try:
        import psutil
    except Exception:
        return
    dist_s = str(DIST.resolve()).lower()
    victims = []
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        exe = proc.info.get("exe") or ""
        try:
            resolved = str(Path(exe).resolve()).lower() if exe else ""
        except Exception:
            resolved = exe.lower()
        if resolved.startswith(dist_s):
            victims.append(proc)
    if not victims:
        return
    print(f"Stopping {len(victims)} process(es) using dist/Athena…")
    for proc in victims:
        try:
            proc.terminate()
        except Exception:
            pass
    _gone, alive = psutil.wait_procs(victims, timeout=4)
    for proc in alive:
        try:
            proc.kill()
        except Exception:
            pass
    time.sleep(0.4)


def main() -> int:
    _ensure_icons()
    _unlock_dist()
    stash = _stash_user_runtime()
    _ensure_whatsapp_packages()

    print("Installing PyInstaller…")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "pyinstaller"],
        check=True,
    )

    print("Running PyInstaller (this takes several minutes)…")
    subprocess.run(
        [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm",
            "--clean",
            str(SPEC),
        ],
        check=True,
        cwd=str(ROOT),
    )

    if not (DIST / "Athena.exe").exists() and not (DIST / "Athena").exists():
        print(f"ERROR: expected exe under {DIST}")
        return 1

    print("Copying prompt, dashboard, icons, models, and WhatsApp bridge next to the exe…")
    _stage_runtime_files()
    _restore_user_runtime(stash)

    exe = DIST / "Athena.exe"
    print()
    print("Build complete.")
    print(f"  Launch: {exe}")
    print("  Zip the whole dist/Athena folder to share it.")
    print("  First run: enter a Gemini API key in the setup overlay.")
    print("  WhatsApp: Settings gear -> WhatsApp Setup (see WHATSAPP_SETUP.txt).")
    print("  Still required on the PC: microphone, speakers, internet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
