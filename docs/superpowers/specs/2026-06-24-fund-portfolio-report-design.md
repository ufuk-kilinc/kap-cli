# `fund-portfolio-report` Utility — Design Spec

**Date:** 2026-06-24
**Status:** Approved (design), pending implementation plan
**Repo:** `tuneup/kap-cli/`

---

## 1. Purpose

Add a `fund-portfolio-report` utility command that returns a fund's **Portföy Dağılım Raporu**
(Portfolio Allocation Report) by its fund code/name, hiding the multi-step hunt the raw API
requires. It is a composite (sibling to the existing fund utilities), shown in the "Utilities"
help panel, and its `--help` explicitly explains what it orchestrates (per the user's request).

Background (verified live): the PDR is filed as a `disclosureType=FON` disclosure under the fund's
**management company** (`fundCompanyId`), one per fund per period. The disclosures *list* exposes
only `disclosureIndex/disclosureType/disclosureClass/title(=sender)/companyId` — NOT the subject or
which fund — so each FON candidate must be opened (`disclosureDetail`) to confirm
`subject.tr == "Portföy Dağılım Raporu"` and `behalfFundCode == <fund>`. The report content is the
detail's `presentation` field.

---

## 2. Behavior

- **No date range → the single latest** PDR for the fund.
- **`--from YYYY-MM` / `--to YYYY-MM` → all PDRs whose report PERIOD falls in [from, to]** (inclusive).
  Either bound optional: `--from` alone = that period → now; `--to` alone = oldest scanned → that
  period. The date axis is the **report period** (parsed from the disclosure, e.g. "2026 / 3.Ay" →
  `2026-03`), not the filing timestamp.
- Fund argument accepts a fund code or name fragment (reuses `resolve_fund` + `resolve_one`; ambiguous
  / not-found → clean `ValueError` → exit 1).

---

## 3. Architecture

New orchestration in **`kap/utils.py`**; new command in **`kap/cli.py`** (Utilities panel). KapClient
unchanged.

### 3.0 The enumeration gotcha (why this is more than a simple backward scan)

`disclosures(index, company_id=X)` returns up to **50** of X's disclosures with `disclosureIndex >= index`
**within a ~36k forward window, OLDEST-first**. A fund's management company is a **heavy filer**, so any
36k window holds far more than 50 of its disclosures — meaning a single call near `last-index` returns the
*oldest* 50 of that window and **misses the newest** (incl. the latest PDR). The naive "step back a tile,
take 50" approach would therefore return a stale report as "latest". The fix is **forward pagination
within a window**: page from a start index, advancing the start to `max(returned index)+1` until the
window is exhausted (`len(page) < 50` or the next index passes the window end). That enumerates *all* of
X's disclosures in the window without loss; for a company that's a few hundred per window → a handful of
list calls.

### 3.1 `kap/utils.py` additions
- `parse_report_period(detail: JsonObj) -> str | None` — `"YYYY-MM"` from the PDR detail. Source:
  `summary.tr` matched by `(\d{4})\s*/\s*(\d+)\s*\.?\s*Ay` → `f"{yyyy}-{mm:02d}"`. `None` if unparseable.

- `_enumerate_window(client, company_id, win_start, win_end) -> list[JsonObj]` — all of the company's
  disclosure rows with `win_start <= disclosureIndex <= win_end`, via forward pagination:
  ```
  cur = win_start; rows = []
  while cur <= win_end:
      page = client.disclosures(cur, company_id=company_id)
      page = [r for r in page if int(r["disclosureIndex"]) <= win_end]
      if not page:
          break
      rows.extend(page)
      hi = max(int(r["disclosureIndex"]) for r in page)
      if len(page) < 50 or hi <= cur:
          break
      cur = hi + 1
  return rows
  ```

- `find_fund_portfolio_reports(client, fund_code, company_id, *, from_period=None, to_period=None, window=36000, max_windows=60, max_details=400) -> PortfolioReportResult`
  - `last = client.last_disclosure_index()`. Scan windows from the top backward:
    `win_end = last`, `win_start = max(0, win_end - window)`, then on each hop `win_end = win_start - 1`,
    `win_start = max(0, win_end - window)`. Stop after `max_windows` or when `win_end < 0`.
  - Per window: `rows = _enumerate_window(...)`; keep `disclosureType == "FON"`; sort those **DESC by
    index** (newest-first).
  - For each FON row newest-first: `detail = client.disclosure_detail(index)` (count toward
    `max_details`); a **match** = `subject.tr == "Portföy Dağılım Raporu"` AND
    `str(behalfFundCode).upper() == fund_code.upper()`. For a match, `period = parse_report_period`.
  - **No range:** return the **first match** (newest) and stop.
  - **Range:** append matches whose `period` is within `[from_period, to_period]` (string compare,
    inclusive; `None`-period matches are included only when no range bound excludes them — i.e. skipped
    when a bound is set). Stop when a match's `period` is **`< from_period`** (we've scanned past the
    range) or a bound (`max_windows`/`max_details`) is hit.
  - Dedupe by `disclosureIndex`. `truncated=True` if a bound was hit before natural completion.
- `PortfolioReportResult` dataclass: `items: list[JsonObj]`, `truncated: bool`, `details_fetched: int`.
  Each item: `{ "disclosureIndex", "period", "fundCode", "fundTitle", "presentation" }`.

Note: `"YYYY-MM"` strings compare correctly lexicographically. The newest-first probe means the
common "latest" case fetches only a handful of details (it hits the most recent PDR batch first).

### 3.2 `kap/cli.py` — the command
`fund-portfolio-report <fund>` with `--from`/`--to` (str, `YYYY-MM`) + the common options; in the
`_UTIL_PANEL`; `[magenta]composite[/magenta]` short_help. Orchestration:
1. `validate_format(fmt)`; resolve fund via `resolve_one(resolve_fund(client, query), query, "fund", _describe_fund)`.
2. `find_fund_portfolio_reports(client, fund["fundCode"], fund["fundCompanyId"], from_period=..., to_period=...)`.
3. If no items → friendly `_err_console` message + exit 1 ("No Portföy Dağılım Raporu found for <fund> ...").
4. If `result.truncated` → stderr note (scan bound hit; widen/raise or narrow the range).
5. `output(result.items, fmt=fmt, out=out)`.

`--from`/`--to` format validated (`YYYY-MM`); bad format → `typer.BadParameter`.

---

## 4. The `--help` page (explicit, per user request)

Short_help (Utilities panel): `[magenta]composite[/magenta]  fund → Portföy Dağılım Raporu`.

Full docstring opens "Composite utility (not a single endpoint)." then plainly explains the steps:

> Finds a fund's Portföy Dağılım Raporu (portfolio allocation report). Steps: (1) resolve the fund to
> its management-company id via GET /api/vyk/funds; (2) read the latest index via
> GET /api/vyk/lastDisclosureIndex; (3) scan that company's disclosures backward
> (GET /api/vyk/disclosures), keeping disclosureType=FON; (4) open each candidate
> (GET /api/vyk/disclosureDetail) and keep those whose subject is "Portföy Dağılım Raporu" for this
> fund. No range → the latest report; --from/--to (YYYY-MM) → all reports in that period range.
> Note: this fans out into many detail calls, so a wide range can be slow.
>
> Example: kap fund-portfolio-report BON
> Example: kap fund-portfolio-report BON --from 2026-01 --to 2026-06

---

## 5. Edge cases / bounding

- `max_windows=60` (~2.16M indices back) and `max_details=400` cap the fan-out; surfaced via
  `truncated` + a stderr note so the user knows results may be incomplete.
- A fund whose code never matches any `behalfFundCode` → no items → exit 1 with a clear message.
- `parse_report_period` returns `None` → in range mode the item is still returned (period shown as
  null) but cannot be range-filtered; documented. In latest mode period is best-effort.
- `from_period > to_period` → `typer.BadParameter`.

---

## 6. Testing

`tests/test_utils.py` (mocked client returning list rows + per-index details):
- `_enumerate_window` paginates past the 50-cap: a window with >50 company rows is fully collected via
  forward stepping (assert all returned, and that it advanced `cur` to max+1, not lost the newest).
- latest-only returns the single **newest** matching PDR (highest index) and stops early (few detail
  fetches) — including the case where the newest tile has >50 rows so the naive approach would miss it.
- range collects only PDRs with period in [from, to]; excludes a same-company PDR for a *different*
  fund (behalfFundCode mismatch) and a non-PDR FON (wrong subject).
- `parse_report_period` parses "2026 / 3.Ay" → "2026-03"; returns None on garbage.
- early-stop when a match's period drops below `from_period`.
- `truncated` set when `max_details` cap is hit.

`tests/test_cli.py` (fake client): command exits 0 and returns the latest; `--from/--to` filters;
bad `--from` format → non-zero; not-found fund → exit 1.

Live verification (prod, allowlisted): `kap fund-portfolio-report BON` (latest), and a small range
`--from 2026-01 --to 2026-03` returns the expected periods.

---

## 7. Non-goals

- No parsing/flattening of the `presentation` XBRL-style structure into tidy rows (return it as-is;
  YAGNI — a future enhancement if the team wants a flat allocation table).
- No caching of details across invocations.
- No new core endpoint (uses existing client methods only).

---

## 8. Deliverables

- `kap/utils.py`: `parse_report_period`, `find_fund_portfolio_reports`, `PortfolioReportResult`.
- `kap/cli.py`: `fund-portfolio-report` command (Utilities panel, explanatory `--help`).
- Tests (utils + cli); live-verified.
- README + handoff Utilities table updated with the new command.
