"""
Deterministic CSV profiling for Athena.

The LLM may summarize these numbers — it must not invent them.
"""

from __future__ import annotations

import csv
import statistics
from collections import Counter
from pathlib import Path

from security.path_guard import PathSecurityError, assert_safe_path


def analyze_csv(file_path: str, max_rows: int = 5000) -> str:
    try:
        path = assert_safe_path(file_path, operation="read", must_exist=True)
    except PathSecurityError as exc:
        return f"Error analyzing CSV: {exc}"

    if path.suffix.lower() not in {".csv", ".tsv", ".txt"}:
        # still allow if readable as csv
        pass

    delimiter = "," if path.suffix.lower() != ".tsv" else "\t"
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            if not reader.fieldnames:
                return f"CSV has no header row: {path}"

            columns = list(reader.fieldnames)
            rows: list[dict[str, str]] = []
            total = 0
            for row in reader:
                total += 1
                if len(rows) < max(1, int(max_rows)):
                    rows.append(row)
    except Exception as exc:
        return f"Error analyzing CSV: {exc}"

    return _profile_rows(columns, rows, path=path, total=total)


def profile_dataset(file_path: str) -> str:
    suffix = Path(str(file_path)).suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        return analyze_excel(file_path)
    return analyze_csv(file_path)


def _profile_rows(columns: list[str], rows: list[dict[str, str]], *, path: Path, total: int) -> str:
    if total == 0 or not columns:
        return f"Dataset is empty: {path}"

    missing = Counter()
    numeric_values: dict[str, list[float]] = {col: [] for col in columns}
    for row in rows:
        for col in columns:
            value = (row.get(col) or "").strip()
            if value == "":
                missing[col] += 1
                continue
            try:
                numeric_values[col].append(float(value.replace(",", "")))
            except ValueError:
                continue

    sample_n = len(rows)
    lines = [
        f"File: {path}",
        f"Rows scanned: {sample_n}"
        + (f" (file has at least {total})" if total > sample_n else f" (total {total})"),
        f"Columns ({len(columns)}): {', '.join(columns)}",
        "",
        "Missing values (in scanned rows):",
    ]
    for col in columns:
        pct = (missing[col] / sample_n) * 100 if sample_n else 0
        lines.append(f"- {col}: {missing[col]} ({pct:.1f}%)")

    lines.append("")
    lines.append("Numeric summary (scanned rows):")
    any_numeric = False
    for col, values in numeric_values.items():
        if len(values) < 2:
            continue
        any_numeric = True
        lines.append(
            f"- {col}: count={len(values)} min={min(values):.4g} "
            f"max={max(values):.4g} mean={statistics.fmean(values):.4g}"
        )
    if not any_numeric:
        lines.append("- (no numeric columns detected in scanned rows)")

    serialized = [tuple(row.get(col, "") for col in columns) for row in rows]
    unique = len(set(serialized))
    dup_pct = ((sample_n - unique) / sample_n) * 100 if sample_n else 0
    lines.append("")
    lines.append(f"Duplicate rows in sample: {sample_n - unique} ({dup_pct:.1f}%)")
    return "\n".join(lines)


def analyze_excel(file_path: str, sheet: str = "", max_rows: int = 5000) -> str:
    """
    Profile the first sheet (or named sheet) of an .xlsx workbook.

    Uses the standard library only (zip + XML). Legacy .xls is not supported.
    """
    import zipfile
    import xml.etree.ElementTree as ET

    try:
        path = assert_safe_path(file_path, operation="read", must_exist=True)
    except PathSecurityError as exc:
        return f"Error analyzing Excel: {exc}"

    if path.suffix.lower() not in {".xlsx", ".xlsm"}:
        if path.suffix.lower() == ".xls":
            return "Error: legacy .xls is not supported. Save as .xlsx or export CSV."
        return f"Error: not an Excel workbook: {path}"

    ns = {
        "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
    }

    try:
        with zipfile.ZipFile(path) as zf:
            shared: list[str] = []
            if "xl/sharedStrings.xml" in zf.namelist():
                root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                for si in root.findall("m:si", ns):
                    texts = [t.text or "" for t in si.findall(".//m:t", ns)]
                    shared.append("".join(texts))

            workbook = ET.fromstring(zf.read("xl/workbook.xml"))
            sheets = []
            for sh in workbook.findall("m:sheets/m:sheet", ns):
                sheets.append(
                    (
                        sh.attrib.get("name", "Sheet"),
                        sh.attrib.get(
                            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id",
                            "",
                        ),
                    )
                )
            if not sheets:
                return f"Error: workbook has no sheets: {path}"

            chosen = sheets[0]
            wanted = (sheet or "").strip().lower()
            if wanted:
                match = next((s for s in sheets if s[0].lower() == wanted), None)
                if match is None:
                    names = ", ".join(s[0] for s in sheets)
                    return f"Error: sheet '{sheet}' not found. Available: {names}"
                chosen = match

            rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
            target = None
            for rel in rels.findall("pr:Relationship", ns):
                if rel.attrib.get("Id") == chosen[1]:
                    target = rel.attrib.get("Target", "")
                    break
            if not target:
                return f"Error: could not resolve sheet path for '{chosen[0]}'."
            sheet_path = "xl/" + target.lstrip("/")
            if sheet_path.startswith("xl/xl/"):
                sheet_path = sheet_path[3:]

            sheet_root = ET.fromstring(zf.read(sheet_path))

            def cell_value(cell) -> str:
                ref_type = cell.attrib.get("t")
                v = cell.find("m:v", ns)
                if v is None or v.text is None:
                    return ""
                if ref_type == "s":
                    try:
                        return shared[int(v.text)]
                    except Exception:
                        return v.text
                return v.text

            rows_xml = sheet_root.findall("m:sheetData/m:row", ns)
            matrix: list[list[str]] = []
            for row in rows_xml:
                values = [cell_value(c) for c in row.findall("m:c", ns)]
                if any(values):
                    matrix.append(values)

            if not matrix:
                return f"Excel sheet '{chosen[0]}' is empty: {path}"

            width = max(len(r) for r in matrix)
            matrix = [r + [""] * (width - len(r)) for r in matrix]
            headers = [
                (h.strip() or f"column_{i+1}") for i, h in enumerate(matrix[0])
            ]
            data_rows = matrix[1:]
            total = len(data_rows)
            limit = max(1, int(max_rows))
            scanned = data_rows[:limit]
            dict_rows = [
                {headers[i]: row[i] for i in range(len(headers))} for row in scanned
            ]
            report = _profile_rows(headers, dict_rows, path=path, total=total)
            return f"Sheet: {chosen[0]}\n{report}"
    except KeyError as exc:
        return f"Error analyzing Excel (missing part): {exc}"
    except Exception as exc:
        return f"Error analyzing Excel: {exc}"
