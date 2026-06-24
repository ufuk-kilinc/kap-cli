# `--out <directory>` Auto-Naming — Design Spec

**Date:** 2026-06-24
**Status:** Approved (design), pending implementation plan
**Repo:** `tuneup/kap-cli/`

---

## 1. Purpose

When a user passes a **directory** to `--out` (e.g. `kap disclosures --index N --out C:\kap\api\output`),
the tool currently tries to write the directory as a file and fails with `[Errno 13] Permission denied`.
Instead, write a **sensibly-named file inside that directory** and tell the user where it went.

---

## 2. Behavior

- **Trigger:** only when `--out` resolves to a path that **already exists as a directory**. A normal
  `--out file.json` is unchanged; a typo'd/non-existent file path still behaves as today (treated as a
  file → a clean error if its parent is missing). We do NOT guess that a non-existent path means a dir.
- **Data commands** (table/json/csv via `output`): write `<command>.<ext>` into the dir — e.g.
  `kap disclosures --out C:\out` → `C:\out\disclosures.json`. `ext` = the resolved format
  (`json`/`csv`; a `table` result written to a file becomes `json`, matching today's behavior).
- **`download-attachment`**: drop the file into the dir under its existing default name
  (`<attachment-id>.pdf`).
- **`fund-portfolio-pdf`**: if its `--out` is a directory, treat it like `--out-dir` (write the
  server-named PDF inside).
- **Feedback:** when writing to a file, print `Saved to <path>` so there's no mystery (applies to the
  render path). The path printed is the **absolute, resolved path** (`Path.resolve()`) — a relative
  `--out`/`--out-dir` like `reports` otherwise leaves the user guessing which directory it landed in.
- **Absolute paths in all "Saved" lines:** the existing `download-attachment` and `fund-portfolio-pdf`
  "Saved …" prints are also updated to show the resolved absolute path (currently they echo the relative
  path as given, e.g. `Saved reports\BON_2026.04.pdf` — ambiguous).

---

## 3. Architecture

### 3.1 `kap/render.py`
- `output(data, fmt=None, out=None, default_stem="output")`:
  - Resolve format as today.
  - If `out is not None and out.is_dir()`: set `ext = "csv" if chosen == "csv" else "json"`, then
    `out = out / f"{default_stem}.{ext}"`.
  - Write as today. When `out is not None` (a file was written), print `Saved to {out.resolve()}`.
- The `default_stem` is the command name, supplied by the caller.
- All "Saved …" prints (here, `_save_bytes`, `fund_portfolio_pdf_cmd`) use `.resolve()` so the user
  always sees the absolute path, even for a relative `--out`/`--out-dir`.

### 3.2 `kap/cli.py`
- `_run(env, fmt, out, fn, *, decode=False, verbose=False, out_name="output")` — pass
  `default_stem=out_name` to `output`. Each command that calls `_run` passes its own name
  (`out_name="disclosures"`, `"members"`, …, and the utilities likewise). Commands that don't pass one
  fall back to `"output"`.
- `_save_bytes(...)`: if `out is not None and out.is_dir()` → `target = out / default_name` (else current
  behavior). Its existing `Saved N bytes to {target}` print then shows the resolved path.
- `fund_portfolio_pdf_cmd`: in the single-result branch, if `out is not None and out.is_dir()` → write
  `out / name` instead of `out`. (Multiple already uses `--out-dir`.)

No `KapClient` change.

---

## 4. Edge cases

- `out` is a dir but not writable → `OSError` still raised, caught by `_errors` → clean exit 1 (unchanged).
- A path that doesn't exist → treated as a file path (today's behavior); if its parent is missing the
  clean OSError stands. We only special-case an existing directory (unambiguous intent).
- `--format csv --out <dir>` → `<command>.csv`. `--format json`/default/table → `<command>.json`.

---

## 5. Testing

`tests/test_render.py`:
- `output([...], out=<tmp dir>, default_stem="disclosures")` writes `<dir>/disclosures.json` (json default)
  and the file contains the data.
- with `fmt="csv"` → `<dir>/disclosures.csv`.
- `output([...], out=<tmp file path>)` (existing tests) still writes exactly that file (no regression).

`tests/test_cli.py` (fake client):
- `kap members --out <tmp dir>` → exit 0, `<dir>/members.json` exists with the data, stdout mentions
  `Saved to`.
- `kap download-attachment abc --out <tmp dir>` → writes `<dir>/abc.pdf`.

(No live calls needed — directory handling is pure local I/O over mocked data.)

---

## 6. Non-goals

- No auto-`mkdir` of a non-existent `--out` path (only an existing dir triggers auto-naming).
- No timestamping / uniquification of filenames (a second run overwrites `<command>.json` — acceptable;
  the user can pass an explicit filename to keep multiple).
- No change to stdout output (no `--out`) behavior.

---

## 7. Deliverables

- `kap/render.py`: directory-aware `output` with `default_stem` + a `Saved to` line.
- `kap/cli.py`: `out_name` threaded through `_run` (+ each command), `_save_bytes` + `fund-portfolio-pdf`
  directory handling.
- Tests (render + cli).
- README/handoff note: "`--out` may be a directory — the tool writes `<command>.<ext>` into it."
