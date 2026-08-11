from pathlib import Path
import sys

from scripts import backup as backup_mod


def test_backup_creates_manifest(tmp_path, monkeypatch):
    dest = tmp_path / "backups"
    monkeypatch.setattr(
        backup_mod,
        "INCLUDE",
        [".env.example", "config/permissions.yaml"],
    )

    argv = sys.argv
    try:
        sys.argv = ["backup.py", "--dest", str(dest)]
        assert backup_mod.main() == 0
    finally:
        sys.argv = argv

    backups = list(dest.glob("athena_backup_*"))
    assert backups
    assert (backups[0] / "backup_manifest.json").exists()
