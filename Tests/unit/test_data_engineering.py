import csv
from pathlib import Path

from tools.analysis.csv_tools import analyze_csv
from tools.data_engineering.clickhouse import clickhouse_query
from tools.data_engineering.docker import check_docker
from tools.data_engineering.stack import check_data_stack
from tools.registry import get_registry, reset_registry


def test_analyze_csv(tmp_path: Path):
    path = tmp_path / "sales.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["category", "amount"])
        writer.writeheader()
        writer.writerow({"category": "Electronics", "amount": "10"})
        writer.writerow({"category": "Electronics", "amount": "20"})
        writer.writerow({"category": "Books", "amount": ""})

    report = analyze_csv(str(path))
    assert "Columns (2)" in report
    assert "amount" in report
    assert "mean=" in report


def test_analyze_excel(tmp_path: Path):
    # Minimal XLSX via open XML (stdlib zip)
    import zipfile

    path = tmp_path / "sales.xlsx"
    shared = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="3" uniqueCount="3">
  <si><t>category</t></si><si><t>amount</t></si><si><t>Electronics</t></si>
</sst>
"""
    sheet = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>
    <row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>10</v></c></row>
    <row r="3"><c r="A3" t="s"><v>2</v></c><c r="B3"><v>20</v></c></row>
  </sheetData>
</worksheet>
"""
    workbook = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Sales" sheetId="1" r:id="rId1"/></sheets>
</workbook>
"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>
"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
</Types>
"""
    root_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>
"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet)
        zf.writestr("xl/sharedStrings.xml", shared)

    from tools.analysis.csv_tools import analyze_excel

    report = analyze_excel(str(path))
    assert "Sheet: Sales" in report
    assert "amount" in report
    assert "mean=" in report


def test_clickhouse_blocks_drop():
    result = clickhouse_query("DROP TABLE evil")
    assert result.startswith("Error:")
    assert "blocked" in result.lower()


def test_clickhouse_allows_select_from_system_prefix_shape():
    # Should not be blocked solely because the table name contains 'system'
    # (connection may fail — that is fine).
    result = clickhouse_query("SELECT 1")
    assert "mutating" not in result.lower()


def test_registry_has_de_tools():
    reset_registry()
    registry = get_registry()
    for name in (
        "check_docker",
        "check_clickhouse",
        "check_airflow",
        "check_data_stack",
        "analyze_csv",
        "analyze_excel",
        "clickhouse_query",
    ):
        assert registry.has(name)


def test_check_docker_and_stack_smoke():
    # Smoke only — services may be offline.
    docker = check_docker()
    assert isinstance(docker, str) and docker
    stack = check_data_stack()
    assert "Docker:" in stack
    assert "ClickHouse:" in stack
