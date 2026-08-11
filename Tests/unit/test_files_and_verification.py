from core.verification import verify_tool_result
from tools.file_tools import create_file, delete_file, search_files


def test_verify_create_and_delete(tmp_path):
    path = tmp_path / "athena_verify.txt"
    created = create_file(str(path))
    assert "File created" in created
    ok, message = verify_tool_result(
        "create_file",
        {"file_path": str(path)},
        created,
    )
    assert ok is True
    assert path.exists()

    deleted = delete_file(str(path))
    ok, message = verify_tool_result(
        "delete_file",
        {"file_path": str(path)},
        deleted,
    )
    assert ok is True
    assert not path.exists()


def test_search_files_extension(tmp_path):
    (tmp_path / "a.csv").write_text("1,2\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("hi", encoding="utf-8")
    result = search_files(str(tmp_path), extension="csv")
    assert "a.csv" in result
    assert "b.txt" not in result


def test_verify_rejects_error_strings():
    ok, _ = verify_tool_result("read_file", {"file_path": "x"}, "Error reading file: missing")
    assert ok is False
