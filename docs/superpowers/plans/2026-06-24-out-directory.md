# `--out <directory>` Auto-Naming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When `--out` points at an existing directory, write a sensibly-named file into it (instead of `[Errno 13]`), and make every "Saved" line print the absolute path.

**Architecture:** `render.output` gains directory-detection + a `default_stem` (the command name) + a `Saved to <abs>` line; `cli` threads each command's name as `out_name` and applies the same directory handling to the byte-saving paths.

**Tech Stack:** Python 3.11+, Typer, Rich, pytest.

## Global Constraints

- Python 3.11+. DRY, YAGNI, TDD.
- Auto-naming triggers ONLY when `--out` is an **existing directory** (`Path.is_dir()`); a normal `--out file.ext` is unchanged; a non-existent path stays a file path.
- Data export filename in a dir = `<command>.<ext>`, `ext = "csv" if resolved-format=="csv" else "json"`.
- `download-attachment` / `fund-portfolio-pdf` write their existing default/server filename into the dir.
- All "Saved …" prints show `Path.resolve()` (absolute) — relative `--out`/`--out-dir` was ambiguous.
- No `KapClient` change; no auto-`mkdir` of a non-existent `--out`; no change to stdout (no-`--out`) behavior.

---

## File Structure

```
kap/render.py    # MODIFY — output(): dir-detection + default_stem + "Saved to <abs>"
kap/cli.py       # MODIFY — thread out_name through _run/_render_scan/fund-portfolio-report;
                 #          _save_bytes + fund-portfolio-pdf dir handling; .resolve() in Saved lines
tests/test_render.py  # MODIFY — dir auto-naming (json/csv), file path unchanged
tests/test_cli.py     # MODIFY — `members --out <dir>`, `download-attachment --out <dir>`
README.md / docs/kap-cli-handoff.md  # MODIFY — note --out accepts a directory
```

---

### Task 1: `render.output` directory-aware writing

**Files:**
- Modify: `kap/render.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Produces: `output(data, fmt=None, out=None, default_stem="output") -> None` — when `out` is an existing
  dir, writes `<out>/<default_stem>.<ext>`; prints `Saved to <abs>` whenever a file is written.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_render.py`)

```python
def test_output_to_directory_auto_names_json(tmp_path):
    output([{"a": 1}], out=tmp_path, default_stem="disclosures")
    saved = tmp_path / "disclosures.json"
    assert json.loads(saved.read_text(encoding="utf-8")) == [{"a": 1}]


def test_output_to_directory_csv_ext(tmp_path):
    output([{"a": 1}], fmt="csv", out=tmp_path, default_stem="members")
    assert (tmp_path / "members.csv").exists()


def test_output_to_directory_prints_saved_path(tmp_path, capsys):
    output([{"a": 1}], out=tmp_path, default_stem="funds")
    assert "Saved to" in capsys.readouterr().out


def test_output_to_explicit_file_unchanged(tmp_path):
    target = tmp_path / "x.json"
    output([{"a": 1}], out=target)
    assert json.loads(target.read_text(encoding="utf-8")) == [{"a": 1}]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_render.py -k "directory" -v`
Expected: FAIL — `output()` got an unexpected keyword `default_stem` (and no dir handling).

- [ ] **Step 3: Implement** — replace the `output` function in `kap/render.py`

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_render.py -v`
Expected: PASS (all prior render tests + 4 new). (`test_output_scalar_to_stdout` still passes — `out is None`, so no "Saved to" line.)

- [ ] **Step 5: Commit**

```bash
git add kap/render.py tests/test_render.py
git commit -m "feat: output() writes into a directory --out and prints the saved path"
```

---

### Task 2: CLI wiring (thread name; bytes/pdf dir handling; absolute Saved lines)

**Files:**
- Modify: `kap/cli.py`, `tests/test_cli.py`, `README.md`, `docs/kap-cli-handoff.md`

**Interfaces:**
- Consumes: `output(..., default_stem=...)` (Task 1).
- Produces: `_run(..., out_name="output")`, `_render_scan(fmt, out, result, out_name="output")`; directory
  handling in `_save_bytes` and `fund_portfolio_pdf_cmd`; absolute "Saved" lines.

- [ ] **Step 1: Thread `out_name` into `_run`** — change the signature and the `output` call:

```python
def _run(
    env: Optional[str],
    fmt: Optional[str],
    out: Optional[Path],
    fn: Callable[[KapClient], Any],
    *,
    decode: bool = False,
    verbose: bool = False,
    out_name: str = "output",
) -> None:
    with _errors(verbose):
        validate_format(fmt)
        with _make_client(env) as client:
            data = fn(client)
        if decode and isinstance(data, dict):
            data = decode_disclosure_bodies(data)
        output(data, fmt=fmt, out=out, default_stem=out_name)
```

- [ ] **Step 2: Thread `out_name` into `_render_scan`**:

```python
def _render_scan(fmt: Optional[str], out: Optional[Path], result: ScanResult, out_name: str = "output") -> None:
    if result.truncated:
        _err_console.print(
            "[yellow]Note:[/yellow] some windows hit the 50-result cap; very active filers may be "
            "incomplete — raise --limit."
        )
    output(result.items, fmt=fmt, out=out, default_stem=out_name)
```

- [ ] **Step 3: Pass each command's name** at its call site. Add `out_name="<name>"` to every `_run(...)`
  call and `_render_scan(...)` call, and `default_stem="..."` to the direct `output(...)` in
  `fund_portfolio_report_cmd`. Exact mapping (command → name):

  - `last_index` → `_run(..., out_name="last-index")`
  - `disclosures` → `out_name="disclosures"`
  - `disclosure_detail` → `out_name="disclosure-detail"`
  - `members` → `out_name="members"`
  - `funds` → `out_name="funds"`
  - `fund_detail` → `out_name="fund-detail"`
  - `member_securities` → `out_name="member-securities"`
  - `blocked_disclosures` → `out_name="blocked-disclosures"`
  - `ca_event_status` → `out_name="ca-event-status"`
  - `raw` → `out_name="raw"`
  - `resolve_ticker_cmd` → `out_name="resolve-ticker"`
  - `resolve_fund_cmd` → `out_name="resolve-fund"`
  - `ticker_disclosures_cmd` → `_render_scan(fmt, out, result, out_name="ticker-disclosures")`
  - `ticker_financials_cmd` → `_render_scan(fmt, out, result, out_name="ticker-financials")`
  - `fund_disclosures_cmd` → `_render_scan(fmt, out, result, out_name="fund-disclosures")`
  - `fund_info_cmd` → `_run(..., out_name="fund-info")`
  - `fund_portfolio_report_cmd` → its `output(result.items, fmt=fmt, out=out)` becomes
    `output(result.items, fmt=fmt, out=out, default_stem="fund-portfolio-report")`

  Example for `members`:
  ```python
  _run(env, fmt, out, lambda c: c.members(), verbose=verbose, out_name="members")
  ```

- [ ] **Step 4: Directory handling + absolute path in `_save_bytes`** — replace its tail:

```python
        if out is not None and out.is_dir():
            target = out / default_name
        else:
            target = out or Path(default_name)
        target.write_bytes(data)
        print(f"Saved {len(data)} bytes to {target.resolve()}")
```

- [ ] **Step 5: `fund-portfolio-pdf` — accept a directory `--out`; absolute Saved line.** Right after the
  `with _make_client(env) as client:` resolves `fund`/`result` (or at the top of the command body before
  building downloads), normalize a directory `--out` into `out_dir`:

```python
    # an existing-directory --out behaves like --out-dir
    if out is not None and out.is_dir():
        out_dir = out_dir if out_dir is not None else out
        out = None
```
  Place that line just before the `if out is not None and len(downloads) > 1:` guard (so the guard and
  single/multiple routing see the normalized values). And change the per-file save print to:
```python
                print(f"Saved {target.resolve()} ({len(data)} bytes)")
```

- [ ] **Step 6: Write CLI tests** (append to `tests/test_cli.py`)

```python
def test_members_out_directory_auto_names(fake_client, tmp_path):
    result = runner.invoke(cli.app, ["members", "--out", str(tmp_path)])
    assert result.exit_code == 0
    saved = tmp_path / "members.json"
    assert saved.exists()
    import json as _json
    assert _json.loads(saved.read_text(encoding="utf-8")) == [{"id": "1", "stockCode": "ACM", "title": "ACME"}]
    assert "Saved to" in result.stdout


def test_download_attachment_out_directory(fake_client, tmp_path):
    result = runner.invoke(cli.app, ["download-attachment", "abc", "--out", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "abc.pdf").read_bytes() == b"%PDF-1.7 bytes"
```

(The fake `members()` returns `[{"id": "1", "stockCode": "ACM", "title": "ACME"}]`; `download_attachment`
returns `b"%PDF-1.7 bytes"` with default name `<id>.pdf`.)

- [ ] **Step 7: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS (all prior + Task 1 render tests + 2 new CLI tests).

- [ ] **Step 8: Manual smoke**

Run: `python -m kap members --out . 2>&1 | tail -1`
Expected: `Saved to <abs>\members.json` (writes `members.json` into the current dir; clean, no Errno 13).
(Needs a key+IP for real data, but the directory-write path + message are exercised either way — a
no-key run will show the clean config error instead, which also confirms no crash.)

- [ ] **Step 9: Docs**

- `README.md` (Common-options table, `--out` row): append " — may be a directory; the tool writes
  `<command>.<ext>` (or the attachment/PDF's own filename) into it and prints the saved path."
- `docs/kap-cli-handoff.md` §2 (the common-options line): add the same note.

- [ ] **Step 10: Commit**

```bash
git add kap/cli.py tests/test_cli.py README.md docs/kap-cli-handoff.md
git commit -m "feat: --out accepts a directory (auto-named file); absolute Saved paths"
```

---

## Self-Review

**Spec coverage** (against `2026-06-24-out-directory-design.md`):
- §2 dir trigger (existing dir only) + `<command>.<ext>` + download-attachment/pdf default names + `Saved to`/absolute → Tasks 1 & 2. ✓
- §3.1 `output(default_stem)` + dir-detection + resolve() print → Task 1. ✓
- §3.2 `_run` out_name threading + `_save_bytes` + `fund-portfolio-pdf` dir handling + resolve() prints → Task 2. ✓
- §5 testing (render dir json/csv + explicit-file-unchanged; cli members-dir + attachment-dir) → Tasks 1 & 2. ✓
- §6 non-goals (no auto-mkdir of non-existent; no stdout change) → honored (only `is_dir()` triggers). ✓
- §7 docs → Task 2 Step 9. ✓

**Placeholder scan:** none — all steps carry real code/commands.

**Type consistency:** `output(data, fmt, out, default_stem="output")` (Task 1) is called with `default_stem=`/`out_name`-derived value from `_run`/`_render_scan`/`fund_portfolio_report_cmd` (Task 2). `_render_scan` signature gains `out_name` and all three scan callers pass it. `_save_bytes`/`fund_portfolio_pdf_cmd` use `out.is_dir()` + `.resolve()` consistently. No new types. ✓
```
