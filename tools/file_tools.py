"""
Athena file tools with path safety and verification-friendly messages.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from security.path_guard import PathSecurityError, assert_safe_path, validate_destination


def create_file(file_path):
    try:
        path = assert_safe_path(file_path, operation="create")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
        return f"File created: {path}"
    except PathSecurityError as e:
        return f"Error creating file: {e}"
    except Exception as e:
        return f"Error creating file: {e}"


def read_file(file_path):
    try:
        path = assert_safe_path(file_path, operation="read", must_exist=True)
        if not path.is_file():
            return f"Error reading file: Not a file: {path}"
        return path.read_text(encoding="utf-8")
    except PathSecurityError as e:
        return f"Error reading file: {e}"
    except Exception as e:
        return f"Error reading file: {e}"


def list_files(folder_path):
    try:
        folder = assert_safe_path(folder_path, operation="read", must_exist=True)
        if not folder.is_dir():
            return f"Error listing files: Not a folder: {folder}"
        files = sorted(item.name for item in folder.iterdir())
        return "\n".join(files) if files else "(empty folder)"
    except PathSecurityError as e:
        return f"Error listing files: {e}"
    except Exception as e:
        return f"Error listing files: {e}"


def delete_file(file_path):
    try:
        path = assert_safe_path(file_path, operation="delete", must_exist=True)
        if not path.is_file():
            return f"Error deleting file: Not a file: {path}"
        path.unlink()
        return f"File deleted: {path}"
    except PathSecurityError as e:
        return f"Error deleting file: {e}"
    except Exception as e:
        return f"Error deleting file: {e}"


def rename_file(old_name, new_name):
    try:
        source = assert_safe_path(old_name, operation="delete", must_exist=True)
        destination = validate_destination(new_name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
        return f"Renamed '{source}' to '{destination}'"
    except PathSecurityError as e:
        return f"Error renaming file: {e}"
    except Exception as e:
        return f"Error renaming file: {e}"


def move_file(source_path, destination_path):
    try:
        source = assert_safe_path(source_path, operation="delete", must_exist=True)
        destination = validate_destination(destination_path)
        if destination.exists() and destination.is_dir():
            destination = destination / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        return f"Moved '{source}' to '{destination}'"
    except PathSecurityError as e:
        return f"Error moving file: {e}"
    except Exception as e:
        return f"Error moving file: {e}"


def copy_file(source_path, destination_path):
    try:
        source = assert_safe_path(source_path, operation="read", must_exist=True)
        destination = validate_destination(destination_path)
        if destination.exists() and destination.is_dir():
            destination = destination / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(source), str(destination))
        return f"Copied '{source}' to '{destination}'"
    except PathSecurityError as e:
        return f"Error copying file: {e}"
    except Exception as e:
        return f"Error copying file: {e}"


def search_files(
    folder_path,
    pattern="*",
    extension=None,
    min_size_mb=None,
):
    """
    Search for files under a folder.

    extension: optional like ".csv" or "csv"
    min_size_mb: optional minimum size filter
    """
    try:
        root = assert_safe_path(folder_path, operation="read", must_exist=True)
        if not root.is_dir():
            return f"Error searching files: Not a folder: {root}"

        glob_pattern = pattern or "*"
        matches: list[Path] = []
        for path in root.rglob(glob_pattern):
            if not path.is_file():
                continue
            if extension:
                ext = extension if str(extension).startswith(".") else f".{extension}"
                if path.suffix.lower() != ext.lower():
                    continue
            if min_size_mb is not None:
                try:
                    size_mb = path.stat().st_size / (1024 * 1024)
                except OSError:
                    continue
                if size_mb < float(min_size_mb):
                    continue
            matches.append(path)

        if not matches:
            return "No matching files found."

        # Cap listing for voice/UI friendliness
        lines = [str(p) for p in sorted(matches)[:100]]
        extra = len(matches) - len(lines)
        text = "\n".join(lines)
        if extra > 0:
            text += f"\n... and {extra} more"
        return text
    except PathSecurityError as e:
        return f"Error searching files: {e}"
    except Exception as e:
        return f"Error searching files: {e}"


def get_file_info(file_path):
    try:
        path = assert_safe_path(file_path, operation="read", must_exist=True)
        stat = path.stat()
        return (
            f"path={path}\n"
            f"size_bytes={stat.st_size}\n"
            f"is_file={path.is_file()}\n"
            f"is_dir={path.is_dir()}"
        )
    except PathSecurityError as e:
        return f"Error getting file info: {e}"
    except Exception as e:
        return f"Error getting file info: {e}"
