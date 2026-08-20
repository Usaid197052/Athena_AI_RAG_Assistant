import os
import re
import shutil
import platform
import subprocess
from pathlib import Path
from datetime import datetime

try:
    import send2trash
    _SEND2TRASH = True
except ImportError:
    _SEND2TRASH = False

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"
_clip: list[Path] = []


def _blocked_prefixes() -> list[Path]:
    roots: list[Path] = []
    if _OS == "Windows":
        windir = os.environ.get("WINDIR", r"C:\Windows")
        roots.extend([
            Path(windir),
            Path(os.environ.get("SYSTEMROOT", windir)),
            Path(r"C:\Program Files"),
            Path(r"C:\Program Files (x86)"),
            Path(r"C:\ProgramData"),
        ])
    elif _OS == "Darwin":
        roots.extend([Path("/System"), Path("/usr"), Path("/bin"), Path("/sbin")])
    else:
        roots.extend([Path("/usr"), Path("/bin"), Path("/sbin"), Path("/boot"), Path("/etc")])
    out = []
    for r in roots:
        try:
            out.append(r.resolve())
        except Exception:
            out.append(r)
    return out


_BLOCKED = _blocked_prefixes()


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _is_safe_path(target: Path, *, destructive: bool = False) -> bool:
    """Allow any local path. For destructive ops, block system dirs."""
    try:
        resolved = target.resolve(strict=False)
    except Exception:
        return False

    if not destructive:
        return True

    for blocked in _BLOCKED:
        if _is_under(resolved, blocked) or resolved == blocked:
            return False
    return True


def _get_desktop() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_DESKTOP_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Desktop"

def _get_downloads() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_DOWNLOAD_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Downloads"

def _get_documents() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_DOCUMENTS_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Documents"

def _get_pictures() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_PICTURES_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Pictures"

def _get_music() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_MUSIC_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Music"

def _get_videos() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_VIDEOS_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Videos"


def _windows_volumes() -> dict[str, Path]:
    """Map lowercase volume labels → drive roots (e.g. 'project data' → E:\\)."""
    if _OS != "Windows":
        return {}
    import ctypes
    import string
    get_vol = ctypes.windll.kernel32.GetVolumeInformationW
    get_type = ctypes.windll.kernel32.GetDriveTypeW
    out: dict[str, Path] = {}
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        if get_type(root) < 2:
            continue
        buf = ctypes.create_unicode_buffer(261)
        if get_vol(root, buf, 261, None, None, None, None, 0) and buf.value.strip():
            out[buf.value.strip().lower()] = Path(root)
    return out


def _resolve_path(raw: str) -> Path:
    shortcuts: dict[str, Path] = {
        "desktop":   _get_desktop(),
        "downloads": _get_downloads(),
        "documents": _get_documents(),
        "pictures":  _get_pictures(),
        "music":     _get_music(),
        "videos":    _get_videos(),
        "home":      Path.home(),
        "this pc":   Path("C:/") if _OS == "Windows" else Path("/"),
        "thispc":    Path("C:/") if _OS == "Windows" else Path("/"),
    }
    text = (raw or "").strip().strip('"').strip("'")
    lower = text.lower()
    if lower in shortcuts:
        return shortcuts[lower]

    # Drive aliases: "D:", "D drive", "d drive", "D:\\"
    m = re.match(r"^([a-zA-Z])\s*:?\s*(?:drive)?[/\\]?$", lower)
    if m and _OS == "Windows":
        letter = m.group(1).upper()
        return Path(f"{letter}:/")

    m2 = re.match(r"^([a-zA-Z]):[/\\]?$", text.strip())
    if m2 and _OS == "Windows":
        return Path(f"{m2.group(1).upper()}:/")

    # Volume labels: "Project Data", "Project Data drive", "DATA"
    if _OS == "Windows" and text and not re.match(r"^[a-zA-Z]:[\\/]", text):
        label = re.sub(r"[\s_\-]+drive$", "", lower).strip()
        label = re.sub(r"^(the|my)\s+", "", label).strip()
        vols = _windows_volumes()
        if label in vols:
            return vols[label]
        compact = label.replace(" ", "")
        for name, p in vols.items():
            if name.replace(" ", "") == compact:
                return p

    return Path(text).expanduser()


def _format_size(b: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


def _safe_trash(target: Path) -> str:
    if not _SEND2TRASH:
        return (
            "send2trash is not installed. "
            "Run: pip install send2trash — "
            "Permanent deletion is disabled for safety."
        )
    send2trash.send2trash(str(target))
    return f"Moved to Trash: {target.name}"


def open_path(path: str, name: str = "") -> str:
    """Open a file or folder in the system file manager / default app."""
    try:
        base = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target, destructive=False):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Path not found: {target}"

        if _OS == "Windows":
            os.startfile(str(target))  # type: ignore[attr-defined]
        elif _OS == "Darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
        return f"Opened: {target}"
    except Exception as e:
        return f"Could not open: {e}"


def list_files(path: str = "desktop", show_hidden: bool = False) -> str:
    try:
        target = _resolve_path(path)
        if not _is_safe_path(target, destructive=False):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Path not found: {target}"
        if not target.is_dir():
            return f"Not a directory: {target}"

        items = []
        for item in sorted(target.iterdir()):
            if not show_hidden and item.name.startswith("."):
                continue
            if item.is_dir():
                items.append(f"📁 {item.name}/")
            else:
                size = _format_size(item.stat().st_size)
                items.append(f"📄 {item.name} ({size})")

        if not items:
            return f"Directory is empty: {target.name}/"

        return f"Contents of {target}/ ({len(items)} items):\n" + "\n".join(items)

    except PermissionError:
        return f"Permission denied: {path}"
    except Exception as e:
        return f"Error listing files: {e}"


def create_file(path: str, name: str = "", content: str = "") -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target, destructive=True):
            return f"Access denied: {target}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"File created: {target.name}"
    except Exception as e:
        return f"Could not create file: {e}"


def create_folder(path: str, name: str = "") -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target, destructive=True):
            return f"Access denied: {target}"
        target.mkdir(parents=True, exist_ok=True)
        return f"Folder created: {target.name}"
    except Exception as e:
        return f"Could not create folder: {e}"


def delete_file(path: str, name: str = "") -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target, destructive=True):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Not found: {target.name}"

        protected = {
            _get_desktop(), _get_downloads(), _get_documents(),
            _get_pictures(), _get_music(), _get_videos(), Path.home()
        }
        resolved = target.resolve()
        if resolved in {p.resolve() for p in protected}:
            return f"Protected directory, cannot delete: {target.name}"
        if _OS == "Windows" and len(str(resolved).rstrip("\\/")) <= 2:
            return f"Protected drive root, cannot delete: {resolved}"

        return _safe_trash(target)

    except PermissionError:
        return f"Permission denied: {path}"
    except Exception as e:
        return f"Could not delete: {e}"


def move_file(path: str, name: str = "", destination: str = "") -> str:
    try:
        base   = _resolve_path(path)
        src    = (base / name) if name else base
        dst    = _resolve_path(destination) if destination else None

        if not src.exists():
            return f"Source not found: {src.name}"
        if dst is None:
            return "No destination specified."
        if not _is_safe_path(src, destructive=True):
            return f"Access denied (source): {src}"
        if not _is_safe_path(dst, destructive=True):
            return f"Access denied (destination): {dst}"

        if dst.exists() and dst.is_dir():
            dst = dst / src.name
        elif not dst.exists():
            if dst.suffix == "":
                return (
                    f"Destination not found: '{destination}'. "
                    f"Use a drive letter or the exact volume label of a connected drive."
                )
            dst.parent.mkdir(parents=True, exist_ok=True)

        shutil.move(str(src), str(dst))
        return f"Moved: {src.name} → {dst}"

    except Exception as e:
        return f"Could not move: {e}"


def _win_set_file_clipboard(paths: list[Path]) -> bool:
    if _OS != "Windows" or not paths:
        return False
    quoted = ", ".join("'" + str(p).replace("'", "''") + "'" for p in paths)
    try:
        r = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                f"Set-Clipboard -LiteralPath @({quoted})",
            ],
            capture_output=True, text=True, timeout=12,
        )
        return r.returncode == 0
    except Exception:
        return False


def clipboard_copy(src: Path) -> str:
    global _clip
    _clip = [src]
    win = _win_set_file_clipboard(_clip)
    extra = " Windows clipboard is ready (Ctrl+V in Explorer)." if win else ""
    return (
        f"Copied to clipboard: {src.name} ({src.parent}). "
        f"Call action=paste with destination (drive letter or volume name) "
        f"when ready.{extra}"
    )


def paste_file(destination: str = "") -> str:
    dest_raw = (destination or "").strip()
    if not _clip:
        return "Clipboard is empty. Copy a file first (action=copy without destination)."

    src = _clip[0]
    if not src.exists():
        return f"Clipboard source no longer exists: {src}"

    if not dest_raw:
        if _OS == "Windows":
            _win_set_file_clipboard(_clip)
            try:
                import pyautogui
                pyautogui.hotkey("ctrl", "v")
                return f"Pasted {src.name} into the active window (Ctrl+V)."
            except Exception as e:
                return (
                    f"Clipboard has {src.name}. Could not send Ctrl+V: {e}. "
                    f"Pass destination (e.g. 'E:' or 'Project Data')."
                )
        return "No destination specified. Pass destination as a path or volume name."

    return copy_file(str(src), destination=dest_raw)


def copy_file(path: str, name: str = "", destination: str = "") -> str:
    try:
        base = _resolve_path(path)
        src  = (base / name) if name else base
        dest_raw = (destination or "").strip()

        if not src.exists():
            return f"Source not found: {src}"

        if not dest_raw:
            if not _is_safe_path(src, destructive=False):
                return f"Access denied (source): {src}"
            return clipboard_copy(src)

        dst = _resolve_path(dest_raw)
        if not _is_safe_path(src, destructive=False):
            return f"Access denied (source): {src}"
        if not _is_safe_path(dst, destructive=True):
            return f"Access denied (destination): {dst}"

        if dst.exists() and dst.is_dir():
            dst = dst / src.name
        elif not dst.exists():
            # Do not create a misnamed file from a volume label / folder name
            if dst.suffix == "":
                return (
                    f"Destination not found: '{dest_raw}'. "
                    f"Use a drive letter (E:) or the exact volume label of a connected drive."
                )
            dst.parent.mkdir(parents=True, exist_ok=True)
        else:
            # exists as a file — overwrite that path
            pass

        if src.is_dir():
            if dst.exists():
                return f"Destination already exists: {dst}"
            shutil.copytree(str(src), str(dst))
        else:
            shutil.copy2(str(src), str(dst))

        return f"Copied: {src.name} → {dst}"

    except Exception as e:
        return f"Could not copy: {e}"


def rename_file(path: str, name: str = "", new_name: str = "") -> str:
    try:
        base     = _resolve_path(path)
        target   = (base / name) if name else base
        if not _is_safe_path(target, destructive=True):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Not found: {target.name}"
        if not new_name:
            return "No new name provided."

        new_path = target.parent / new_name
        if new_path.exists():
            return f"A file named '{new_name}' already exists here."

        target.rename(new_path)
        return f"Renamed: {target.name} → {new_name}"

    except Exception as e:
        return f"Could not rename: {e}"


def read_file(path: str, name: str = "", max_chars: int = 4000) -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target, destructive=False):
            return f"Access denied: {target}"
        if not target.exists():
            return f"File not found: {target.name}"
        if not target.is_file():
            return f"Not a file: {target.name}"

        content = target.read_text(encoding="utf-8", errors="ignore")
        if len(content) > max_chars:
            content = content[:max_chars] + f"\n\n[Truncated — {len(content)} total chars]"
        return content

    except Exception as e:
        return f"Could not read file: {e}"


def write_file(path: str, name: str = "", content: str = "",
               append: bool = False) -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target, destructive=True):
            return f"Access denied: {target}"
        target.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with open(target, mode, encoding="utf-8") as f:
            f.write(content)
        action = "Appended to" if append else "Written to"
        return f"{action}: {target.name}"
    except Exception as e:
        return f"Could not write file: {e}"


def find_files(name: str = "", extension: str = "",
               path: str = "home", max_results: int = 20) -> str:
    try:
        search_path = _resolve_path(path)
        if not _is_safe_path(search_path, destructive=False):
            return f"Access denied: {search_path}"
        if not search_path.exists():
            return f"Search path not found: {path}"

        results    = []
        dir_count  = 0
        max_dirs   = 500

        for item in search_path.rglob("*"):
            if item.is_dir():
                dir_count += 1
                if dir_count > max_dirs:
                    break
                continue
            if not item.is_file():
                continue
            if extension and item.suffix.lower() != extension.lower():
                continue
            if name and name.lower() not in item.name.lower():
                continue
            size = _format_size(item.stat().st_size)
            results.append(f"📄 {item.name} ({size}) — {item.parent}")
            if len(results) >= max_results:
                break

        if not results:
            query = name or extension or "files"
            return f"No {query} found in {search_path.name}/"

        return f"Found {len(results)} file(s):\n" + "\n".join(results)

    except Exception as e:
        return f"Search error: {e}"


def get_largest_files(path: str = "downloads", count: int = 10) -> str:
    count = min(count, 50)
    try:
        search_path = _resolve_path(path)
        if not _is_safe_path(search_path, destructive=False):
            return f"Access denied: {search_path}"
        if not search_path.exists():
            return f"Path not found: {path}"

        files = []
        for item in search_path.rglob("*"):
            if item.is_file():
                try:
                    files.append((item.stat().st_size, item))
                except Exception:
                    continue

        files.sort(reverse=True)
        top = files[:count]

        if not top:
            return "No files found."

        lines = [f"Top {len(top)} largest files in {search_path.name}/:"]
        for size, f in top:
            lines.append(f"  {_format_size(size):>10}  {f.name}  ({f.parent})")

        return "\n".join(lines)

    except Exception as e:
        return f"Error: {e}"


def get_disk_usage(path: str = "home") -> str:
    try:
        target = _resolve_path(path)
        usage  = shutil.disk_usage(target)
        pct    = usage.used / usage.total * 100
        return (
            f"Disk usage ({target}):\n"
            f"  Total : {_format_size(usage.total)}\n"
            f"  Used  : {_format_size(usage.used)} ({pct:.1f}%)\n"
            f"  Free  : {_format_size(usage.free)}"
        )
    except Exception as e:
        return f"Could not get disk usage: {e}"


def organize_desktop() -> str:
    type_map = {
        "Images":    {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".heic"},
        "Documents": {".pdf", ".doc", ".docx", ".txt", ".xls", ".xlsx",
                      ".ppt", ".pptx", ".csv", ".odt", ".ods", ".odp"},
        "Videos":    {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v"},
        "Music":     {".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"},
        "Archives":  {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
        "Code":      {".py", ".js", ".ts", ".html", ".css", ".json", ".xml",
                      ".cpp", ".java", ".cs", ".go", ".rs", ".sh"},
    }

    desktop = _get_desktop()
    moved, skipped = [], []

    try:
        for item in desktop.iterdir():
            if item.is_dir() or item.name.startswith("."):
                continue
            if item.name in {k for k in type_map}:
                continue

            ext        = item.suffix.lower()
            target_dir = desktop / "Others"
            for folder, exts in type_map.items():
                if ext in exts:
                    target_dir = desktop / folder
                    break

            target_dir.mkdir(exist_ok=True)
            new_path = target_dir / item.name

            if new_path.exists():
                skipped.append(item.name)
                continue

            shutil.move(str(item), str(new_path))
            moved.append(f"{item.name} → {target_dir.name}/")

        result = f"Desktop organized: {len(moved)} files moved."
        if moved:
            preview = moved[:8]
            result += "\n" + "\n".join(preview)
            if len(moved) > 8:
                result += f"\n... and {len(moved) - 8} more."
        if skipped:
            result += f"\n{len(skipped)} file(s) skipped (name conflict)."
        return result

    except Exception as e:
        return f"Could not organize desktop: {e}"


def get_file_info(path: str, name: str = "") -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target, destructive=False):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Not found: {target.name}"

        stat = target.stat()
        info = {
            "Name":      target.name,
            "Type":      "Folder" if target.is_dir() else "File",
            "Size":      _format_size(stat.st_size),
            "Location":  str(target.parent),
            "Created":   datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M"),
            "Modified":  datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "Extension": target.suffix or "—",
        }
        return "\n".join(f"  {k}: {v}" for k, v in info.items())

    except Exception as e:
        return f"Could not get file info: {e}"


def file_controller(
    parameters: dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    action = params.get("action", "").lower().strip()
    path   = params.get("path", "desktop")
    name   = params.get("name", "")

    if player:
        player.write_log(f"[file] {action} {name or path}")

    try:
        if action == "list":
            return list_files(path)

        elif action == "open":
            return open_path(path, name=name)

        elif action == "create_file":
            return create_file(path, name=name, content=params.get("content", ""))

        elif action == "create_folder":
            return create_folder(path, name=name)

        elif action == "delete":
            return delete_file(path, name=name)

        elif action == "move":
            return move_file(path, name=name, destination=params.get("destination", ""))

        elif action == "copy":
            return copy_file(path, name=name, destination=params.get("destination", ""))

        elif action == "paste":
            dest = str(params.get("destination") or "").strip()
            if not dest and path and str(path).lower() not in ("desktop", ""):
                dest = path
            return paste_file(destination=dest)

        elif action == "rename":
            return rename_file(path, name=name, new_name=params.get("new_name", ""))

        elif action == "read":
            return read_file(path, name=name)

        elif action == "write":
            return write_file(
                path, name=name,
                content=params.get("content", ""),
                append=params.get("append", False)
            )

        elif action == "find":
            return find_files(
                name=name or params.get("name", ""),
                extension=params.get("extension", ""),
                path=path,
                max_results=min(int(params.get("max_results", 20)), 50),
            )

        elif action == "largest":
            return get_largest_files(
                path=path,
                count=int(params.get("count", 10)),
            )

        elif action == "disk_usage":
            return get_disk_usage(path)

        elif action == "organize_desktop":
            return organize_desktop()

        elif action == "info":
            return get_file_info(path, name=name)

        else:
            return f"Unknown action: '{action}'"

    except Exception as e:
        return f"File controller error ({action}): {e}"
