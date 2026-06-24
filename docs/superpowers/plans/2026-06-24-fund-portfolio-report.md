# `fund-portfolio-report` Utility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `fund-portfolio-report <fund>` utility that returns a fund's Portföy Dağılım Raporu (latest by default; `--from/--to` YYYY-MM for a period range), with `--help` explaining the orchestration.

**Architecture:** New composite logic in `kap/utils.py` (period parsing, forward-paginating window enumerator that beats the 50-cap, and the finder); a new command in `kap/cli.py`'s Utilities panel. KapClient unchanged.

**Tech Stack:** Python 3.11+, Typer, Rich, pytest (mocked KapClient / Typer CliRunner).

## Global Constraints

- Python 3.11+. DRY, YAGNI, TDD.
- KapClient unchanged; composites live in `kap/utils.py`.
- PDR = `disclosureType == "FON"` disclosure under the fund's management company (`fundCompanyId`); confirmed by `subject.tr == "Portföy Dağılım Raporu"` AND `behalfFundCode == <fund>` in the detail. Report content = detail's `presentation`.
- `disclosures(index, company_id=X)` returns ≤50 of X's rows with index ≥ `index` in a ~36k forward window, OLDEST-first → MUST forward-paginate (step `cur` to `max(returned index)+1`) to avoid missing recent filings for a heavy filer.
- Date axis = report PERIOD ("2026 / 3.Ay" → `"2026-03"`), parsed from `summary.tr`. Periods compare lexicographically as `YYYY-MM`.
- Default (no range) → the single latest PDR (newest-first probe, stop at first match). `--from/--to` (YYYY-MM) → all matches with period in range.
- Bound the fan-out: `window=36000`, `max_windows=60`, `max_details=400`; set `truncated` + print a stderr note when a bound is hit.
- New command in `rich_help_panel=_UTIL_PANEL` with a `[magenta]composite[/magenta]` short_help; its docstring opens "Composite utility (not a single endpoint)." and explicitly explains the 4 steps (per user request).

---

## File Structure

```
kap/utils.py    # MODIFY — parse_report_period, _enumerate_window, find_fund_portfolio_reports, PortfolioReportResult
kap/cli.py      # MODIFY — fund-portfolio-report command (Utilities panel, explanatory --help, --from/--to)
tests/test_utils.py  # MODIFY — period parse, window pagination, finder (latest/range/truncated)
tests/test_cli.py    # MODIFY — command wiring (latest / not-found / bad-period)
README.md / docs/kap-cli-handoff.md  # MODIFY — Utilities table row
```

---

### Task 1: Period parsing + window enumerator (`kap/utils.py`)

**Files:**
- Modify: `kap/utils.py`
- Test: `tests/test_utils.py`

**Interfaces:**
- Consumes: `KapClient.disclosures(index, *, disclosure_class=None, company_id=None) -> list[dict]`; `JsonObj`.
- Produces:
  - `parse_report_period(detail: JsonObj) -> str | None`
  - `_enumerate_window(client, company_id, win_start: int, win_end: int) -> list[JsonObj]`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_utils.py`)

```python
from kap.utils import parse_report_period, _enumerate_window


def _fon(idx):
    return {"disclosureIndex": str(idx), "disclosureType": "FON"}


def test_parse_report_period_from_summary():
    detail = {"summary": {"tr": "2026 / 3.Ay Portföy Dağılım Raporu\n", "en": None}}
    assert parse_report_period(detail) == "2026-03"


def test_parse_report_period_none_on_garbage():
    assert parse_report_period({"summary": {"tr": "nope"}}) is None
    assert parse_report_period({}) is None


def test_enumerate_window_paginates_past_50_cap():
    # company has 60 rows (1..60); a single call caps at 50, so we must page to get all
    pages = {1: [_fon(i) for i in range(1, 51)], 51: [_fon(i) for i in range(51, 61)]}
    client = FakeClient(pages=pages)
    rows = _enumerate_window(client, "C", 1, 100)
    got = sorted(int(r["disclosureIndex"]) for r in rows)
    assert got == list(range(1, 61))  # nothing lost; 60 collected via 2 pages


def test_enumerate_window_excludes_beyond_win_end():
    pages = {1: [_fon(1), _fon(2), _fon(250)]}
    client = FakeClient(pages=pages)
    rows = _enumerate_window(client, "C", 1, 100)
    assert [int(r["disclosureIndex"]) for r in rows] == [1, 2]  # 250 > win_end dropped
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_utils.py -k "report_period or enumerate_window" -v`
Expected: FAIL with `ImportError: cannot import name 'parse_report_period'`.

- [ ] **Step 3: Implement** — append to `kap/utils.py` (add `import re` to the top imports)

```python
import re

_PERIOD_RE = re.compile(r"(\d{4})\s*/\s*(\d+)\s*\.?\s*Ay")
_PDR_SUBJECT = "Portföy Dağılım Raporu"


def parse_report_period(detail: JsonObj) -> str | None:
    """Extract the report period as 'YYYY-MM' from a disclosure detail's Turkish summary."""
    summary = detail.get("summary") if isinstance(detail, dict) else None
    text = summary.get("tr") if isinstance(summary, dict) else None
    if not isinstance(text, str):
        return None
    match = _PERIOD_RE.search(text)
    if not match:
        return None
    return f"{match.group(1)}-{int(match.group(2)):02d}"


def _enumerate_window(client: KapClient, company_id: str | int, win_start: int, win_end: int) -> list[JsonObj]:
    """All of a company's disclosure rows with win_start <= disclosureIndex <= win_end.

    Forward-paginates (cur -> max index + 1) so it isn't limited to the API's 50-row page cap.
    """
    cur = win_start
    rows: list[JsonObj] = []
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

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_utils.py -k "report_period or enumerate_window" -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add kap/utils.py tests/test_utils.py
git commit -m "feat: report-period parser + forward-paginating window enumerator"
```

---

### Task 2: The finder (`kap/utils.py`)

**Files:**
- Modify: `kap/utils.py`, `tests/test_utils.py`

**Interfaces:**
- Consumes: `parse_report_period`, `_enumerate_window` (Task 1); `KapClient.last_disclosure_index() -> int`, `KapClient.disclosure_detail(index, ...) -> dict | None`.
- Produces:
  - `PortfolioReportResult` dataclass: `items: list[JsonObj]`, `truncated: bool`, `details_fetched: int`.
  - `find_fund_portfolio_reports(client, fund_code: str, company_id: str | int, *, from_period: str | None = None, to_period: str | None = None, window: int = 36000, max_windows: int = 60, max_details: int = 400) -> PortfolioReportResult`
  - Each item: `{"disclosureIndex": int, "period": str | None, "fundCode", "fundTitle", "presentation"}`.

- [ ] **Step 1: Extend the test `FakeClient`** in `tests/test_utils.py` — add detail support (additive; existing tests unaffected). In `FakeClient.__init__` add a `details=None` parameter and store `self._details = details or {}`; add a method:

```python
    def disclosure_detail(self, index, file_type="data", sub_report=None):
        return self._details.get(int(index))
```

- [ ] **Step 2: Write the failing tests** (append to `tests/test_utils.py`)

```python
from kap.utils import PortfolioReportResult, find_fund_portfolio_reports


def _pdr_detail(idx, fund_code, period_text, fund_title="FUND"):
    return {
        "disclosureIndex": str(idx),
        "subject": {"tr": "Portföy Dağılım Raporu", "en": "Portfolio Allocation Report"},
        "summary": {"tr": f"{period_text} Portföy Dağılım Raporu\n"},
        "behalfFundCode": fund_code,
        "behalfFundTitle": fund_title,
        "presentation": [{"alloc": idx}],
    }


def _make_finder_client():
    # one window [0,100]; FON rows 30,60,90 (BON PDRs), 95 (CBD PDR), 99 (FON non-PDR)
    pages = {0: [_fon(30), _fon(60), _fon(90), _fon(95), _fon(99)]}
    details = {
        30: _pdr_detail(30, "BON", "2025 / 12.Ay"),
        60: _pdr_detail(60, "BON", "2026 / 2.Ay"),
        90: _pdr_detail(90, "BON", "2026 / 3.Ay"),
        95: _pdr_detail(95, "CBD", "2026 / 3.Ay"),
        99: {"disclosureIndex": "99", "subject": {"tr": "Komisyon Bilgileri"}, "behalfFundCode": "BON"},
    }
    return FakeClient(pages=pages, details=details, last=100)


def test_finder_latest_returns_newest_match_and_stops():
    client = _make_finder_client()
    result = find_fund_portfolio_reports(client, "BON", "C", window=1000)
    assert isinstance(result, PortfolioReportResult)
    assert [i["disclosureIndex"] for i in result.items] == [90]
    assert result.items[0]["period"] == "2026-03"
    assert result.truncated is False
    # newest-first probe: fetched 99, 95, 90 (stops at 90) — not the older 60/30
    assert result.details_fetched == 3


def test_finder_range_collects_in_period_window():
    client = _make_finder_client()
    result = find_fund_portfolio_reports(client, "BON", "C", from_period="2026-01", to_period="2026-12", window=1000)
    assert [i["disclosureIndex"] for i in result.items] == [90, 60]  # 30 is 2025-12, below from


def test_finder_excludes_other_fund_and_non_pdr():
    client = _make_finder_client()
    result = find_fund_portfolio_reports(client, "CBD", "C", window=1000)
    assert [i["disclosureIndex"] for i in result.items] == [95]


def test_finder_truncates_on_max_details():
    client = _make_finder_client()
    result = find_fund_portfolio_reports(client, "BON", "C", from_period="2000-01", to_period="2999-12", window=1000, max_details=1)
    assert result.truncated is True
```

- [ ] **Step 3: Run to verify it fails**

Run: `python -m pytest tests/test_utils.py -k finder -v`
Expected: FAIL with `ImportError: cannot import name 'find_fund_portfolio_reports'`.

- [ ] **Step 4: Implement** — append to `kap/utils.py`

```python
@dataclass
class PortfolioReportResult:
    items: list[JsonObj]
    truncated: bool
    details_fetched: int


def find_fund_portfolio_reports(
    client: KapClient,
    fund_code: str,
    company_id: str | int,
    *,
    from_period: str | None = None,
    to_period: str | None = None,
    window: int = 36000,
    max_windows: int = 60,
    max_details: int = 400,
) -> PortfolioReportResult:
    """Find a fund's Portföy Dağılım Raporu disclosure(s).

    Scans the management company's disclosures backward (newest window first), forward-paginating
    each window, and opens FON candidates newest-first to match subject + behalfFundCode. No range →
    the latest report (stops at first match); a range → all matches with period in [from, to].
    """
    target = str(fund_code).strip().upper()
    last = client.last_disclosure_index()
    range_mode = from_period is not None or to_period is not None
    items: list[JsonObj] = []
    seen: set[int] = set()
    details = 0
    truncated = False
    done = False
    win_end = last
    windows = 0

    while win_end >= 0 and windows < max_windows and not done:
        win_start = max(0, win_end - window)
        rows = _enumerate_window(client, company_id, win_start, win_end)
        fon = sorted(
            (r for r in rows if r.get("disclosureType") == "FON"),
            key=lambda r: int(r["disclosureIndex"]),
            reverse=True,
        )
        for row in fon:
            idx = int(row["disclosureIndex"])
            if idx in seen:
                continue
            if details >= max_details:
                truncated = done = True
                break
            detail = client.disclosure_detail(idx)
            details += 1
            if not detail:
                continue
            subject = detail.get("subject") if isinstance(detail, dict) else None
            subj_tr = subject.get("tr") if isinstance(subject, dict) else None
            if subj_tr != _PDR_SUBJECT:
                continue
            if str(detail.get("behalfFundCode") or "").strip().upper() != target:
                continue
            period = parse_report_period(detail)
            item: JsonObj = {
                "disclosureIndex": idx,
                "period": period,
                "fundCode": detail.get("behalfFundCode"),
                "fundTitle": detail.get("behalfFundTitle"),
                "presentation": detail.get("presentation"),
            }
            if not range_mode:
                return PortfolioReportResult(items=[item], truncated=False, details_fetched=details)
            if from_period is not None and period is not None and period < from_period:
                done = True
                break
            if to_period is not None and period is not None and period > to_period:
                continue  # newer than the range; keep scanning back
            if period is None:
                continue  # can't place an undated report in a range
            seen.add(idx)
            items.append(item)
        if win_start == 0:
            break
        win_end = win_start - 1
        windows += 1

    if windows >= max_windows and not done:
        truncated = True
    return PortfolioReportResult(items=items, truncated=truncated, details_fetched=details)
```

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest tests/test_utils.py -v`
Expected: PASS (all prior utils tests + 4 finder tests).

- [ ] **Step 6: Commit**

```bash
git add kap/utils.py tests/test_utils.py
git commit -m "feat: find_fund_portfolio_reports (latest + period range, newest-first)"
```

---

### Task 3: CLI command + live verification (`kap/cli.py`)

**Files:**
- Modify: `kap/cli.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `find_fund_portfolio_reports`, `PortfolioReportResult` (Task 2), `resolve_fund`, `resolve_one`, `_describe_fund`, `_errors`, `_make_client`, `validate_format`, `output`, `_err_console`, `_UTIL_PANEL`, option aliases.
- Produces: the `fund-portfolio-report` command.

- [ ] **Step 1: Add imports** to `kap/cli.py` — add `import re` to the top imports, and extend the utils import line to include the new names:

```python
from kap.utils import (
    PortfolioReportResult,
    find_fund_portfolio_reports,
    resolve_company,
    resolve_fund,
    resolve_one,
    scan_disclosures,
)
```

- [ ] **Step 2: Add the command** at the end of `kap/cli.py`

```python
_PERIOD_RE_CLI = re.compile(r"^\d{4}-\d{2}$")


@app.command(
    "fund-portfolio-report",
    rich_help_panel=_UTIL_PANEL,
    short_help="[magenta]composite[/magenta]  fund → Portföy Dağılım Raporu",
)
def fund_portfolio_report_cmd(
    query: _FUND_ARG,
    from_period: Annotated[Optional[str], typer.Option("--from", help="Start report period, YYYY-MM.")] = None,
    to_period: Annotated[Optional[str], typer.Option("--to", help="End report period, YYYY-MM.")] = None,
    env: EnvOpt = None,
    fmt: FormatOpt = None,
    out: OutOpt = None,
    verbose: VerboseOpt = False,
):
    """Composite utility (not a single endpoint). A fund's Portföy Dağılım Raporu (portfolio allocation report).

    What it does: (1) resolves the fund to its management-company id via GET /api/vyk/funds; (2) reads the
    latest index via GET /api/vyk/lastDisclosureIndex; (3) scans that company's disclosures backward
    (GET /api/vyk/disclosures, forward-paginated per window so recent filings aren't missed), keeping
    disclosureType=FON; (4) opens each candidate (GET /api/vyk/disclosureDetail) and keeps those whose
    subject is "Portföy Dağılım Raporu" for THIS fund. No range returns the latest report; --from/--to
    (YYYY-MM, by report period) return all in that range. Note: this fans out into many detail calls, so a
    wide range can be slow.

    Example: kap fund-portfolio-report BON
    Example: kap fund-portfolio-report BON --from 2026-01 --to 2026-06
    """
    for label, value in (("--from", from_period), ("--to", to_period)):
        if value is not None and not _PERIOD_RE_CLI.match(value):
            raise typer.BadParameter(f"{label} must be YYYY-MM, got '{value}'")
    if from_period and to_period and from_period > to_period:
        raise typer.BadParameter(f"--from ({from_period}) is after --to ({to_period})")
    with _errors(verbose):
        validate_format(fmt)
        with _make_client(env) as client:
            fund = resolve_one(resolve_fund(client, query), query, "fund", _describe_fund)
            result = find_fund_portfolio_reports(
                client, fund["fundCode"], fund["fundCompanyId"],
                from_period=from_period, to_period=to_period,
            )
        if not result.items:
            _err_console.print(
                f"[yellow]No Portföy Dağılım Raporu found for '{query}' in the scanned range.[/yellow]"
            )
            raise typer.Exit(code=1)
        if result.truncated:
            _err_console.print(
                "[yellow]Note:[/yellow] scan bound hit (max windows/details); results may be "
                "incomplete — narrow the --from/--to range."
            )
        output(result.items, fmt=fmt, out=out)
```

- [ ] **Step 3: Write CLI tests** — append to `tests/test_cli.py` (add `PortfolioReportResult` to the existing `from kap.utils import ...`, or add `from kap.utils import PortfolioReportResult`)

```python
from kap.utils import PortfolioReportResult


def test_fund_portfolio_report_returns_latest(fake_client, monkeypatch):
    monkeypatch.setattr(
        cli, "find_fund_portfolio_reports",
        lambda *a, **k: PortfolioReportResult(
            items=[{"disclosureIndex": 90, "period": "2026-03", "fundCode": "BON",
                    "fundTitle": "T", "presentation": [{"alloc": 1}]}],
            truncated=False, details_fetched=3),
    )
    result = runner.invoke(cli.app, ["fund-portfolio-report", "BON", "--format", "json"])
    assert result.exit_code == 0
    assert '"disclosureIndex": 90' in result.stdout


def test_fund_portfolio_report_not_found_exits_1(fake_client, monkeypatch):
    monkeypatch.setattr(
        cli, "find_fund_portfolio_reports",
        lambda *a, **k: PortfolioReportResult(items=[], truncated=False, details_fetched=0),
    )
    result = runner.invoke(cli.app, ["fund-portfolio-report", "BON"])
    assert result.exit_code == 1
    assert "No Portföy Dağılım Raporu" in result.stderr


def test_fund_portfolio_report_bad_period_format(fake_client):
    result = runner.invoke(cli.app, ["fund-portfolio-report", "BON", "--from", "2026-1"])
    assert result.exit_code != 0
    assert "YYYY-MM" in (result.stderr + result.stdout)
```

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS (all prior + Task 1/2 utils tests + 3 new CLI tests).

- [ ] **Step 5: Verify help renders the explanation + Utilities panel**

Run: `COLUMNS=140 python -m kap fund-portfolio-report --help`
Expected: docstring shows the numbered "What it does" steps + both examples; `--from`/`--to` options listed.
Run: `COLUMNS=140 python -m kap --help` → `fund-portfolio-report` appears in the Utilities panel with the magenta `composite` tag.

- [ ] **Step 6: Live verification (prod, allowlisted IP; `~/.kap/.env` has the prod key)**

```bash
python -m kap fund-portfolio-report BON                       # latest PDR (one item, has 'presentation')
python -m kap fund-portfolio-report BON --from 2026-01 --to 2026-03   # the in-range periods
```
Confirm the latest returns one item with a `period` and non-empty `presentation`, and the range returns the expected months (e.g. 2026-03, 2026-02, 2026-01 if present). Record the periods/indices returned in your report. (A range scan may take several seconds — expected.)

- [ ] **Step 7: Commit**

```bash
git add kap/cli.py tests/test_cli.py
git commit -m "feat: fund-portfolio-report command (Utilities panel, explanatory --help)"
```

---

### Task 4: Docs

**Files:**
- Modify: `README.md`, `docs/kap-cli-handoff.md`

- [ ] **Step 1: Add a row to the README Utilities table** (in `README.md`, the "Utilities (convenience — not raw API endpoints)" table) — insert after the `fund-disclosures` row:

```markdown
| `fund-portfolio-report <q> [--from YYYY-MM --to YYYY-MM]` | a fund's Portföy Dağılım Raporu (latest, or all in a period range) | resolve + scan FON disclosures + `GET /disclosureDetail` |
```

And after the usage code block, add:

```markdown
```bash
kap fund-portfolio-report BON                      # latest portfolio allocation report
kap fund-portfolio-report BON --from 2026-01 --to 2026-06
```
> `fund-portfolio-report` opens many disclosure details (the list doesn't expose subject/fund), so a
> wide period range can be slow; the latest-only call is quick.
```

- [ ] **Step 2: Add a line to `docs/kap-cli-handoff.md`** — in the §0 "Utilities layer" paragraph, append:

```markdown
fund-portfolio-report resolves a fund → scans its management company's FON disclosures (forward-paginated
to beat the 50-row cap) → matches subject "Portföy Dağılım Raporu" + behalfFundCode; default latest,
--from/--to (YYYY-MM by report period) for a range.
```

- [ ] **Step 3: Commit**

```bash
git add README.md docs/kap-cli-handoff.md
git commit -m "docs: document fund-portfolio-report utility"
```

---

## Self-Review

**Spec coverage** (against `2026-06-24-fund-portfolio-report-design.md`):
- §3.0 forward-pagination gotcha → Task 1 `_enumerate_window` + the >50-cap test. ✓
- §3.1 `parse_report_period` → Task 1; `find_fund_portfolio_reports` + `PortfolioReportResult` → Task 2. ✓
- §3.2 CLI command (resolve → find → not-found exit 1 → truncation note → output) → Task 3. ✓
- §2 behavior (latest default; `--from/--to` range; fund code/name) → Task 2 logic + Task 3 options. ✓
- §4 explanatory `--help` (composite, 4 steps, examples) → Task 3 Step 2 docstring + Step 5 check. ✓
- §5 bounding (`max_windows`/`max_details`, truncated, bad `--from`>`--to`, period None) → Task 2 + Task 3 validation. ✓
- §6 testing → Tasks 1–3; live verify → Task 3 Step 6. ✓
- §8 deliverables (docs) → Task 4. ✓

**Placeholder scan:** none — every step has real code/commands. The live-verify is a concrete decision/record step, not a placeholder.

**Type consistency:** `parse_report_period(detail) -> str | None`, `_enumerate_window(client, company_id, win_start, win_end) -> list[JsonObj]`, `find_fund_portfolio_reports(client, fund_code, company_id, *, from_period, to_period, window, max_windows, max_details) -> PortfolioReportResult(items, truncated, details_fetched)` consistent across Tasks 1–3. CLI uses `fund["fundCode"]`/`fund["fundCompanyId"]` (from `resolve_fund`, matching the live `funds` shape) and `_describe_fund`/`resolve_one` from the existing utilities. `_PDR_SUBJECT`/`_PERIOD_RE` defined once in Task 1, reused in Task 2. ✓
```
