"""Run CMD or PowerShell commands (high-risk — requires HUD confirmation).

On Windows, commands that need Administrator (or as_admin=true) trigger a UAC
prompt via ShellExecuteW runas so the packaged app can elevate without
running Athena itself as admin.
"""

from __future__ import annotations

import os
import platform
import subprocess
import tempfile
import time
from pathlib import Path

_OS = platform.system()
_MAX_OUT = 4000

if _OS == "Windows":
    _WIN_HIDE: dict = {"creationflags": subprocess.CREATE_NO_WINDOW}
else:
    _WIN_HIDE: dict = {}

_ADMIN_HINTS = (
    "bcdedit",
    "diskpart",
    "dism ",
    "dism.exe",
    "sfc ",
    "sfc.exe",
    "chkdsk",
    "format ",
    "netsh advfirewall",
    "netsh interface",
    "netsh wlan set",
    "netsh wlan add",
    "powercfg -h",
    "powercfg /h",
    "sc config",
    "sc.exe config",
    "sc start",
    "sc stop",
    "sc create",
    "sc delete",
    "reg add hklm",
    "reg delete hklm",
    "reg add hkcr",
    "reg delete hkcr",
    "shutdown /s",
    "shutdown /r",
    "shutdown.exe",
    "net user ",
    "net localgroup",
    "pnputil",
    "devcon",
    "takeown ",
    "icacls ",
    "wevtutil",
)


def _truthy(val) -> bool:
    if isinstance(val, bool):
        return val
    s = str(val or "").strip().lower()
    return s in ("1", "true", "yes", "on", "admin", "elevated")


def _needs_admin(command: str, explicit: bool) -> bool:
    if explicit:
        return True
    c = f" {command.lower()} "
    return any(h in c or command.lower().startswith(h.strip()) for h in _ADMIN_HINTS)


def _is_admin() -> bool:
    if _OS != "Windows":
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _run_elevated_windows(command: str, shell: str, timeout: int) -> str:
    """UAC-elevate a command, capture stdout/stderr via a temp file."""
    import ctypes

    stamp = f"{os.getpid()}_{int(time.time() * 1000)}"
    tmp = Path(tempfile.gettempdir())
    out_path = tmp / f"athena_shell_{stamp}.txt"
    bat_path = tmp / f"athena_shell_{stamp}.bat"
    marker = "ATHENA_EXIT="

    if shell in ("powershell", "pwsh", "ps"):
        ps1_path = tmp / f"athena_shell_{stamp}.ps1"
        ps1_path.write_text(
            command + "\n",
            encoding="utf-8",
        )
        inner = (
            f'powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass '
            f'-File "{ps1_path}" > "{out_path}" 2>&1\r\n'
            f'echo {marker}%ERRORLEVEL%>> "{out_path}"\r\n'
        )
    else:
        inner = (
            f'cmd.exe /c {command} > "{out_path}" 2>&1\r\n'
            f'echo {marker}%ERRORLEVEL%>> "{out_path}"\r\n'
        )

    bat_path.write_text("@echo off\r\n" + inner, encoding="mbcs", errors="replace")

    rc = int(
        ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            "cmd.exe",
            f'/c "{bat_path}"',
            None,
            0,  # SW_HIDE
        )
    )
    if rc <= 32:
        return (
            "Administrator approval was declined or elevation failed "
            f"(code {rc}). Approve the Windows UAC prompt to run this command."
        )

    deadline = time.monotonic() + max(timeout, 15) + 90
    text = ""
    exit_code = None
    while time.monotonic() < deadline:
        if out_path.exists():
            try:
                raw = out_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                raw = out_path.read_text(encoding="mbcs", errors="replace")
            if marker in raw:
                body, _, tail = raw.rpartition(marker)
                text = body.strip()
                try:
                    exit_code = int(tail.strip().split()[0])
                except Exception:
                    exit_code = 0
                break
        time.sleep(0.25)
    else:
        return "Elevated command timed out waiting for output (UAC may still be open)."

    for p in (out_path, bat_path, tmp / f"athena_shell_{stamp}.ps1"):
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass

    if not text:
        text = f"(exit {exit_code}, no output)"
    if len(text) > _MAX_OUT:
        text = text[:_MAX_OUT] + "\n…[truncated]"
    if exit_code not in (0, None):
        text = f"{text}\n(exit {exit_code})"
    return text


def _run_normal(command: str, shell: str, timeout: int):
    if shell in ("powershell", "pwsh", "ps"):
        if _OS != "Windows":
            return None, "PowerShell is only available on Windows."
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=timeout,
            **_WIN_HIDE,
        )
        return result, None
    if shell in ("cmd", "command", "bat"):
        if _OS != "Windows":
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=timeout,
            )
        else:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                timeout=timeout, **_WIN_HIDE,
            )
        return result, None
    result = subprocess.run(
        command, shell=True, capture_output=True, text=True, timeout=timeout,
        **(_WIN_HIDE if _OS == "Windows" else {}),
    )
    return result, None


def shell_command(
    parameters: dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    command = str(params.get("command", "")).strip()
    shell = str(params.get("shell", "cmd")).lower().strip()
    timeout = min(int(params.get("timeout", 30) or 30), 120)
    as_admin = _truthy(params.get("as_admin") or params.get("elevated") or params.get("admin"))

    if not command:
        return "No command provided."

    elevate = _OS == "Windows" and _needs_admin(command, as_admin) and not _is_admin()

    if player:
        tag = "admin " if elevate or (_OS == "Windows" and _is_admin() and _needs_admin(command, as_admin)) else ""
        player.write_log(f"[shell] {tag}{shell}: {command[:80]}")

    try:
        if elevate:
            if player:
                player.write_log("[shell] Requesting Administrator (UAC)…")
            return _run_elevated_windows(command, shell, timeout)

        result, err = _run_normal(command, shell, timeout)
        if err:
            return err

        out = (result.stdout or "").strip()
        err_txt = (result.stderr or "").strip()
        text = out if out else err_txt
        if not text:
            text = f"(exit {result.returncode}, no output)"
        if len(text) > _MAX_OUT:
            text = text[:_MAX_OUT] + "\n…[truncated]"
        if result.returncode != 0 and out:
            text = f"{text}\n(exit {result.returncode})"
            if err_txt:
                text += f"\n{err_txt[:1000]}"
        return text

    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s."
    except Exception as e:
        return f"Shell error: {e}"
