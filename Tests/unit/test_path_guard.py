import pytest

from security.path_guard import PathSecurityError, assert_safe_path


def test_normalize_user_path(tmp_path):
    target = tmp_path / "notes.txt"
    target.write_text("hi", encoding="utf-8")
    resolved = assert_safe_path(target, operation="read", must_exist=True)
    assert resolved.exists()


def test_blocks_windows_system32_delete():
    with pytest.raises(PathSecurityError):
        assert_safe_path(r"C:\Windows\System32\drivers\etc\hosts", operation="delete")


def test_blocks_program_files_write():
    with pytest.raises(PathSecurityError):
        assert_safe_path(r"C:\Program Files\Athena\hack.exe", operation="create")
