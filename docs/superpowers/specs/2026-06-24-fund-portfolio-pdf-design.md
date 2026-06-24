# `fund-portfolio-pdf` Utility — Design Spec

**Date:** 2026-06-24
**Status:** Approved (design), pending implementation plan
**Repo:** `tuneup/kap-cli/`

---

## 1. Purpose

Add a `fund-portfolio-pdf <fund>` utility that **downloads the actual PDF** of a fund's Portföy Dağılım
Raporu (portfolio allocation report). It mirrors `fund-portfolio-report` (which returns the structured
`presentation` data) but saves the attached PDF instead. Composite utility in the "Utilities" panel.

Verified live: a recent PDR detail carries
`attachmentUrls: [{"url": ".../api/vyk/downloadAttachment/<id>", "fileName": "BON_2026.04.pdf"}]`, and the
existing `KapClient.download_attachment(id)` already returns the unwrapped PDF bytes. (Some older PDRs have
no attachment — handled.)

---

## 2. Behavior

- **No range → download the latest** PDR's PDF.
- **`--from YYYY-MM` / `--to YYYY-MM` → download each PDR's PDF in that period range.**
- Fund arg = code or name fragment (reuses `resolve_fund` + `resolve_one`; ambiguous/not-found → exit 1).
- **Output:**
  - Single report → `--out FILE`; if omitted, save as KAP's own filename (e.g. `BON_2026.04.pdf`) in the
    current directory.
  - Multiple reports → `--out-dir DIR` (default `.`), each saved under its server filename.
  - `--out` given while the result is multiple → `typer.BadParameter` ("use --out-dir for multiple reports").
  - Print `Saved <path> (<n> bytes)` per file.
- A report with **no attachment** → stderr note + skip. If nothing was downloaded → exit 1 with a clear message.

---

## 3. Architecture

Reuses the existing finder + the existing `download_attachment`. KapClient unchanged.

### 3.1 `kap/utils.py`
- **Extend `find_fund_portfolio_reports` items** to also carry the report's attachments: each item gains
  `"attachmentUrls": detail.get("attachmentUrls") or []`. Additive — existing item keys
  (`disclosureIndex/period/fundCode/fundTitle/presentation`) and tests are unaffected; `fund-portfolio-report`
  output simply gains an `attachmentUrls` field (useful: shows whether a PDF exists).
- New helper `attachment_id_from_url(url: str) -> str` → the last non-empty path segment
  (`url.rstrip("/").rsplit("/", 1)[-1]`). Used to feed `download_attachment`.

### 3.2 `kap/cli.py` — the command
`fund-portfolio-pdf <fund>` in `_UTIL_PANEL`, `[magenta]composite[/magenta]` short_help, with `--from`/`--to`
(YYYY-MM, validated like `fund-portfolio-report`), `--out PATH`, `--out-dir PATH`, `--env`, `--verbose`
(no `--format` — binary). Flow:
1. `resolve_one(resolve_fund(client, query), ...)` → fund.
2. `find_fund_portfolio_reports(client, fund["fundCode"], fund["fundCompanyId"], from_period=..., to_period=...)`.
3. If no items → friendly stderr + exit 1.
4. Build the download list: for each item, for each entry in its `attachmentUrls`, derive
   `(id = attachment_id_from_url(url), name = Path(fileName or f"{index}.pdf").name)` (use `.name` to strip
   any path components — defensive). Items with no attachments are noted on stderr and skipped.
5. If the download list is empty (reports found but none had a PDF) → stderr + exit 1.
6. If `--out` is set AND the list has >1 file → `typer.BadParameter`.
7. Resolve each target path: single + `--out` → that path; single + no `--out` → `./<name>`;
   multiple → `<out-dir or '.'>/<name>` (create the dir).
8. For each: `data = client.download_attachment(id)`; if `None` (not found) → stderr note + skip; else
   `target.write_bytes(data)` and print `Saved <target> (<len> bytes)`.
9. If `result.truncated` → the usual scan-bound stderr note.

Errors route through the existing `_errors` policy (KapError/ValueError/OSError → clean exit 1).

---

## 4. `--help` (clean numbered steps — required)

Short_help: `[magenta]composite[/magenta]  fund → download Portföy Dağılım Raporu PDF`.

Docstring opens "Composite utility (not a single endpoint)." then a **blank-line-separated numbered list**
(so rich renders each step on its own line, matching `fund-portfolio-report`):

```
What it does:

1. Resolve the fund to its management-company id — GET /api/vyk/funds

2. Find its Portföy Dağılım Raporu disclosure(s) (same scan as fund-portfolio-report)

3. Download each report's attached PDF — GET /api/vyk/downloadAttachment/{id}

No range downloads the latest report's PDF; --from/--to (YYYY-MM) download every report in that range.
Single report → --out FILE (defaults to KAP's own filename); multiple → --out-dir DIR.

Examples:

kap fund-portfolio-pdf BON

kap fund-portfolio-pdf BON --out latest.pdf

kap fund-portfolio-pdf BON --from 2026-01 --to 2026-06 --out-dir reports
```

---

## 5. Edge cases

- Report with empty/missing `attachmentUrls` → skipped with a stderr note; exit 1 only if NONE downloaded.
- `download_attachment` returns `None` (ER005) for a stale attachment id → stderr note + skip.
- Filename safety: always `Path(fileName).name` (strip directories); fall back to `<disclosureIndex>.pdf`
  when `fileName` is missing.
- `--from > --to` → `typer.BadParameter` (same as `fund-portfolio-report`).
- `--out` + multiple results → `typer.BadParameter`.

---

## 6. Testing

`tests/test_utils.py`:
- `attachment_id_from_url` returns the last path segment (with/without trailing slash).
- a `find_fund_portfolio_reports` item now includes `attachmentUrls` (extend the finder fixture's detail
  with an `attachmentUrls` and assert it surfaces on the item).

`tests/test_cli.py` (fake client; `find_fund_portfolio_reports` monkeypatched to canned items; fake
`download_attachment` returns bytes):
- single latest → writes the server filename (or `--out`) with the bytes (use `tmp_path`).
- `--out-dir` with two items → two files written under the dir.
- `--out` with two items → exit non-zero (BadParameter).
- report with no attachment → exit 1 with the "no PDF" message.
- not-found fund → exit 1.

Live verification (prod, allowlisted): `kap fund-portfolio-pdf BON` → saves `BON_2026.04.pdf`; confirm it
opens as a valid PDF (starts with `%PDF`).

---

## 7. Non-goals

- No PDF parsing/rendering — just save the bytes.
- No change to `KapClient` (uses existing `download_attachment`).
- No bulk download beyond the located PDR set.

---

## 8. Deliverables

- `kap/utils.py`: `attachmentUrls` on finder items + `attachment_id_from_url`.
- `kap/cli.py`: `fund-portfolio-pdf` command (Utilities panel, clean numbered-step `--help`).
- Tests (utils + cli); live-verified.
- README + handoff Utilities table row.
