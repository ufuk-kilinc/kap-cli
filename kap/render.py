from __future__ import annotations

import base64
import csv
import io
import json
import re
from pathlib import Path
from typing import Any, Literal

from rich.console import Console
from rich.table import Table

Format = Literal["table", "json", "csv"]
_FORMATS: tuple[Format, ...] = ("table", "json", "csv")

_console = Console()
_STYLE_SCRIPT = re.compile(r"<(style|script)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _is_scalar(data: Any) -> bool:
    return not isinstance(data, (dict, list))


def validate_format(fmt: str | None) -> None:
    """Raise ValueError if an explicit format isn't one we support (lets the CLI fail fast)."""
    if fmt is not None and fmt.lower() not in _FORMATS:
        raise ValueError(f"Unknown format '{fmt}' (use one of: {', '.join(_FORMATS)}).")


def resolve_format(fmt: str | None, out: Path | None, data: Any) -> Format:
    validate_format(fmt)
    if fmt:
        return fmt.lower()  # type: ignore[return-value]
    if out is not None:
        suffix = out.suffix.lower()
        if suffix == ".csv":
            return "csv"
        if suffix == ".json":
            return "json"
    # default: nested dict isn't table-able → json; everything else → table
    if isinstance(data, dict):
        return "json"
    return "table"


def to_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _as_rows(data: Any) -> list[dict]:
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        rows = []
        for item in data:
            if isinstance(item, dict):
                rows.append(item)
            else:
                rows.append({"value": item})
        return rows
    return [{"value": data}]


def _cell(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return "" if value is None else str(value)


def _columns(rows: list[dict]) -> list[str]:
    cols: list[str] = []
    for row in rows:
        for key in row:
            if key not in cols:
                cols.append(key)
    return cols


def to_csv(data: Any) -> str:
    rows = _as_rows(data)
    cols = _columns(rows)
    buf = io.StringIO()
    # lineterminator="\n": avoid csv's default \r\n, which doubles to \r\n\n when
    # the CSV is printed to stdout. File writes stay newline-clean too.
    writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({c: _cell(row.get(c)) for c in cols})
    return buf.getvalue()


def decode_disclosure_bodies(detail: Any) -> Any:
    """Decode a disclosure detail's base64 ``htmlMessages`` bodies into readable text.

    Adds a ``<lang>_text`` field next to each ``tr``/``en`` body. KAP encodes these
    as base64 ISO-8859-9 XHTML, so that's the assumed encoding. **Mutates ``detail``
    in place** (and returns it). On a base64 failure, sets ``<lang>_text`` to ``None``
    so "couldn't decode" is distinguishable from "field absent".
    """
    if not isinstance(detail, dict):
        return detail
    messages = detail.get("htmlMessages")
    if isinstance(messages, list):
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            for lang in ("tr", "en"):
                encoded = msg.get(lang)
                if isinstance(encoded, str) and encoded:
                    try:
                        raw = base64.b64decode(encoded).decode("iso-8859-9", errors="replace")
                        msg[f"{lang}_text"] = _strip_html(raw)
                    except (ValueError, TypeError):
                        msg[f"{lang}_text"] = None
    return detail


def _strip_html(html: str) -> str:
    text = _STYLE_SCRIPT.sub(" ", html)
    text = _TAGS.sub(" ", text)
    return _WS.sub(" ", text).strip()


def _write_text(text: str, out: Path | None) -> None:
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    else:
        print(text)


def _print_table(rows: list[dict], out: Path | None) -> None:
    if out is not None:
        # tables aren't meant for files; fall back to JSON-on-disk
        _write_text(to_json(rows), out)
        return
    if not rows:
        _console.print("[dim](no rows)[/dim]")
        return
    cols = _columns(rows)
    table = Table(show_lines=False)
    for col in cols:
        table.add_column(col, overflow="fold")
    for row in rows:
        table.add_row(*[_cell(row.get(c)) for c in cols])
    _console.print(table)


def output(data: Any, fmt: str | None = None, out: Path | None = None, default_stem: str = "output") -> None:
    chosen = resolve_format(fmt, out, data)
    if out is not None and out.is_dir():
        ext = "csv" if chosen == "csv" else "json"
        out = out / f"{default_stem}.{ext}"
    if chosen == "json":
        _write_text(to_json(data), out)
    elif chosen == "csv":
        _write_text(to_csv(data), out)
    else:  # table
        if _is_scalar(data):
            _write_text(str(data), out)
        elif isinstance(data, dict):
            _write_text(to_json(data), out)  # nested → json even if table requested
        else:
            _print_table(_as_rows(data), out)
    if out is not None:
        print(f"Saved to {out.resolve()}")
