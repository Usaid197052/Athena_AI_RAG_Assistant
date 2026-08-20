"""Load CSV / JSON / Parquet (and Excel/TSV) with pandas + numpy and show a table in the HUD panel."""

from __future__ import annotations

import html
import json
from pathlib import Path

_TABULAR_EXT = {
    ".csv", ".tsv", ".json", ".jsonl",
    ".parquet", ".pq",
    ".xlsx", ".xls", ".ods",
}

_MAX_LOAD_MB = 80
_MAX_PANEL_ROWS = 5000
_MAX_PANEL_COLS = 80


def _panel_on() -> bool:
    try:
        from memory.config_manager import get_content_panel_enabled
        return bool(get_content_panel_enabled())
    except Exception:
        return True


def _cell(val) -> str:
    try:
        import pandas as pd
        if val is None or (isinstance(val, float) and val != val) or pd.isna(val):
            return "—"
    except Exception:
        if val is None:
            return "—"
    s = str(val).replace("\n", " ").strip()
    if len(s) > 80:
        s = s[:77] + "…"
    return html.escape(s)


def _json_to_df(path: Path):
    import pandas as pd

    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    stripped = raw.lstrip()
    if path.suffix.lower() == ".jsonl" or (
        stripped.startswith("{") and "\n{" in raw[:4000]
    ):
        try:
            return pd.read_json(path, lines=True)
        except Exception:
            pass

    data = json.loads(raw)
    if isinstance(data, list):
        if not data:
            return pd.DataFrame()
        if all(not isinstance(x, (dict, list)) for x in data):
            return pd.DataFrame({"value": data})
        return pd.json_normalize(data, max_level=2)
    if isinstance(data, dict):
        for key in ("data", "records", "items", "results", "rows"):
            if isinstance(data.get(key), list):
                return pd.json_normalize(data[key], max_level=2)
        try:
            return pd.DataFrame(data)
        except Exception:
            return pd.json_normalize(data, max_level=2)
    return pd.DataFrame({"value": [data]})


def _load_frame(path: Path):
    import pandas as pd

    ext = path.suffix.lower()
    size_mb = path.stat().st_size / (1024 * 1024)
    truncated = False

    if ext in (".csv", ".tsv"):
        sep = "\t" if ext == ".tsv" else ","
        kwargs = {}
        if size_mb > _MAX_LOAD_MB:
            kwargs["nrows"] = 20_000
            truncated = True
        last_err = None
        df = None
        for enc in ("utf-8-sig", "utf-8", "utf-16", "cp1252", "latin-1"):
            try:
                df = pd.read_csv(path, sep=sep, encoding=enc, **kwargs)
                break
            except Exception as e:
                last_err = e
                df = None
        if df is None:
            raise RuntimeError(last_err)
        return df, truncated

    if ext in (".xlsx", ".xls", ".ods"):
        return pd.read_excel(path), truncated

    if ext in (".parquet", ".pq"):
        try:
            return pd.read_parquet(path), truncated
        except ImportError as e:
            raise RuntimeError(
                "Parquet support requires pyarrow. Run: pip install pyarrow"
            ) from e

    if ext in (".json", ".jsonl"):
        return _json_to_df(path), truncated

    raise ValueError(f"Unsupported tabular type: {ext}")


def _numpy_summary(df, max_cols: int = 8) -> str:
    import numpy as np

    num = df.select_dtypes(include=[np.number])
    if num.empty:
        return "No numeric columns."
    parts = []
    for col in list(num.columns)[:max_cols]:
        arr = pd_to_finite(num[col])
        if arr.size == 0:
            continue
        parts.append(
            f"{col}: n={int(arr.size)} mean={np.mean(arr):.4g} "
            f"std={np.std(arr):.4g} min={np.min(arr):.4g} max={np.max(arr):.4g}"
        )
    extra = f" (+{len(num.columns) - max_cols} more numeric)" if len(num.columns) > max_cols else ""
    return "; ".join(parts) + extra if parts else "No finite numeric values."


def pd_to_finite(series):
    import numpy as np

    arr = series.to_numpy(dtype=float, copy=False)
    return arr[np.isfinite(arr)]


def _table_html(df, title: str, subtitle: str) -> str:
    cols = list(df.columns)
    rows = df.itertuples(index=True, name=None)

    th = (
        '<th bgcolor="#3A2410"><font color="#C1502E" face="Courier New" size="2">#</font></th>'
        + "".join(
            f'<th bgcolor="#3A2410"><font color="#C1502E" face="Courier New" size="2">{html.escape(str(c))}</font></th>'
            for c in cols
        )
    )
    body_rows = []
    for i, tup in enumerate(rows):
        bg = "#120D09" if i % 2 == 0 else "#160F0A"
        idx = tup[0]
        vals = tup[1:]
        tds = (
            f'<td bgcolor="{bg}"><font color="#6B5C44" face="Courier New" size="2">{html.escape(str(idx))}</font></td>'
            + "".join(
                f'<td bgcolor="{bg}"><font color="#EDE3D0" face="Courier New" size="2">{_cell(v)}</font></td>'
                for v in vals
            )
        )
        body_rows.append(f"<tr>{tds}</tr>")

    table = (
        '<table border="0" cellspacing="0" cellpadding="4" style="white-space:nowrap;">'
        f"<tr>{th}</tr>"
        + "".join(body_rows)
        + "</table>"
    )
    return (
        "<html><body style=\"background-color:#080604; color:#EDE3D0;\">"
        f'<p><font color="#C1502E" face="Courier New" size="3"><b>{html.escape(title)}</b></font></p>'
        f'<p><font color="#A08060" face="Courier New" size="2">{html.escape(subtitle)}</font></p>'
        f"{table}"
        "</body></html>"
    )


def show_dataframe(parameters: dict, player=None, speak=None) -> str:
    """
    Load a tabular file and render it in the HUD content panel.

    parameters:
        file_path : path to csv/json/parquet/excel (empty = caller should fill current upload)
        max_rows  : rows to show in the panel (default 80)
        max_cols  : columns to show in the panel (default 16)
        offset    : starting row index (0-based). Use to paginate or skip rows.
        tail      : if true, show the LAST max_rows rows instead of the first
        columns   : comma-separated column names to include (empty = all)
        sort_by   : column name to sort by before slicing
        sort_asc  : sort ascending (default true)
    """
    p = parameters or {}
    file_path = (p.get("file_path") or "").strip()
    if not file_path:
        return "No file path provided. Pass file_path or drop the file on the HUD first."

    path = Path(file_path)
    if not path.is_file():
        name = path.name
        for folder in (
            Path.home() / "Downloads" / "Athena Uploads",
            Path.home() / "Documents" / "Athena Uploads",
            Path(__file__).resolve().parent.parent / "uploads",
        ):
            cand = folder / name
            if cand.is_file():
                path = cand
                break
    if not path.exists() or not path.is_file():
        return f"File not found: {file_path}"

    ext = path.suffix.lower()
    if ext not in _TABULAR_EXT:
        return (
            f"'{path.name}' is not a tabular file. "
            "Supported: csv, tsv, json, jsonl, parquet, xlsx, xls."
        )

    try:
        import pandas as pd  # noqa: F401
        import numpy as np  # noqa: F401
    except ImportError:
        return "pandas and numpy are required. Run: pip install pandas numpy pyarrow openpyxl"

    if player:
        player.write_log(f"[DataFrame] {path.name}")

    try:
        df, truncated_load = _load_frame(path)
    except Exception as e:
        return f"Could not load {path.name} as a DataFrame: {e}"

    if df is None:
        return f"Could not load {path.name}."

    n_rows, n_cols = int(len(df)), int(len(df.columns))

    # ── sort ──────────────────────────────────────────────────────────────
    sort_by = (p.get("sort_by") or "").strip()
    if sort_by and sort_by in df.columns:
        sort_asc = p.get("sort_asc", True)
        if isinstance(sort_asc, str):
            sort_asc = sort_asc.lower() not in ("false", "0", "no", "desc")
        try:
            df = df.sort_values(sort_by, ascending=bool(sort_asc))
        except Exception:
            pass

    # ── column filter ─────────────────────────────────────────────────────
    col_filter = (p.get("columns") or "").strip()
    if col_filter:
        wanted = [c.strip() for c in col_filter.split(",") if c.strip()]
        valid = [c for c in wanted if c in df.columns]
        if valid:
            df = df[valid]
            n_cols = len(valid)

    # ── row limits (default: all rows/columns, scroll in panel) ─────────────
    show_all = p.get("all", False)
    if isinstance(show_all, str):
        show_all = show_all.lower() in ("true", "1", "yes")

    raw_max_rows = p.get("max_rows")
    raw_max_cols = p.get("max_cols")
    if raw_max_rows is None or raw_max_rows == "" or show_all:
        max_rows = min(n_rows, _MAX_PANEL_ROWS)
    else:
        try:
            max_rows = int(raw_max_rows)
        except Exception:
            max_rows = min(n_rows, _MAX_PANEL_ROWS)
    if raw_max_cols is None or raw_max_cols == "" or show_all:
        max_cols = min(n_cols, _MAX_PANEL_COLS)
    else:
        try:
            max_cols = int(raw_max_cols)
        except Exception:
            max_cols = min(n_cols, _MAX_PANEL_COLS)
    max_rows = max(1, min(max_rows, _MAX_PANEL_ROWS))
    max_cols = max(1, min(max_cols, _MAX_PANEL_COLS))

    # tail= overrides offset
    use_tail = p.get("tail", False)
    if isinstance(use_tail, str):
        use_tail = use_tail.lower() in ("true", "1", "yes")

    try:
        offset = int(p.get("offset") or 0)
    except Exception:
        offset = 0
    offset = max(0, min(offset, n_rows))

    if use_tail:
        view = df.iloc[-max_rows:, :max_cols]
    elif offset:
        view = df.iloc[offset : offset + max_rows, :max_cols]
    else:
        view = df.iloc[:max_rows, :max_cols]

    shown_r, shown_c = int(len(view)), int(len(view.columns))

    if use_tail:
        range_label = f"last {shown_r}"
    elif offset:
        range_label = f"rows {offset}–{offset + shown_r - 1}"
    elif shown_r >= n_rows and shown_c >= n_cols:
        range_label = "all"
    else:
        range_label = f"rows 0–{shown_r - 1}"

    missing = int(df.isna().sum().sum()) if n_rows else 0
    try:
        num_summary = _numpy_summary(df)
    except Exception:
        num_summary = "Numeric summary unavailable."

    subtitle_bits = [
        f"{n_rows:,} rows × {n_cols} columns",
        f"showing {range_label} ({shown_r} × {shown_c})",
        "scroll vertically / horizontally in panel",
    ]
    if truncated_load:
        subtitle_bits.append(f"file >{_MAX_LOAD_MB}MB — loaded first 20,000 rows")
    if missing:
        subtitle_bits.append(f"{missing:,} missing cells")
    subtitle = " · ".join(subtitle_bits)

    title = path.name
    header = (
        f"{title}\n{subtitle}\n"
        f"{'─' * min(72, len(subtitle) + 8)}\n"
    )
    table_text = view.to_string(index=True)
    display_text = header + table_text

    shown = False
    if player and hasattr(player, "show_content") and _panel_on():
        try:
            player.show_content(
                f"DATA — {title[:32]}", display_text, html=False, nowrap=True
            )
            shown = True
        except TypeError:
            try:
                player.show_content(f"DATA — {title[:32]}", display_text)
                shown = True
            except Exception:
                shown = False
        except Exception:
            shown = False

    cols = ", ".join(str(c) for c in df.columns[:24])
    if n_cols > 24:
        cols += f" … (+{n_cols - 24} more)"

    if shown:
        head = "DataFrame shown in the content panel."
    elif not _panel_on():
        head = (
            "Content panel is OFF (Settings → CONTENT PANEL). "
            "Table not displayed. Enable it and ask again."
        )
    else:
        head = "DataFrame loaded, but the content panel could not be opened."

    return (
        f"{head}\n"
        f"File: {path.name}\n"
        f"Shape: {n_rows} rows × {n_cols} columns "
        f"(panel shows {range_label}, {shown_c} columns).\n"
        f"Columns: {cols}\n"
        f"Numeric (numpy): {num_summary}\n"
        "Do not claim the panel opened unless this result starts with "
        "'DataFrame shown in the content panel'."
    )
