# Ticker & Fund Utilities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add composite "utility" commands (resolve a ticker/fund, fetch recency-correct disclosures) in a separate layer + a clearly-labeled "Utilities" help panel, distinct from the thin 1:1 API commands.

**Architecture:** A new `kap/utils.py` orchestrates `KapClient` calls (resolution over `members`/`funds`; a backward disclosure scan). `KapClient` stays the pure endpoint wrapper. `cli.py` gains 6 commands registered in a `rich_help_panel="Utilities"` panel.

**Tech Stack:** Python 3.11+, Typer, Rich, pytest (mocked KapClient / Typer CliRunner).

## Global Constraints

- Python 3.11+. DRY, YAGNI, TDD.
- `KapClient` is unchanged; composites live in `kap/utils.py`.
- Resolution: **exact code match first** (case-insensitive: `stockCode` for companies, `fundCode` for funds), **else partial name** (case-insensitive substring: `title` / `fundName`). Returns a **list**.
- `resolve_one(matches, ...)`: 0 matches → `ValueError`; >1 → `ValueError` listing matches; 1 → that match.
- companyId source = a member row's `id` (a **string** like "866"); funds use `fundId`, `fundCompanyId`, `fundCode`, `fundName`. Pass ids through to the client as-is (don't coerce).
- Backward scan: `window=36000`, `max_windows=30`, default `--limit 20`; dedupe by `disclosureIndex`; newest-first; set `truncated=True` if any window returns ≥50 rows.
- Utilities MUST read as distinct from core API: separate panel, a `[magenta]composite[/magenta]` tag in short_help (core rows use a yellow `GET …` endpoint), and each full `--help` opens with "Composite utility (not a single endpoint)." listing the endpoints it orchestrates.
- `fund-disclosures` depends on funds filing under `fundCompanyId` — **verify live**; drop the command before merge if unsupported.
- Utility commands accept the common options (`--env/--format/--out/--verbose`) and render via `render.output`.

---

## File Structure

```
kap/
  utils.py        # NEW — resolve_company, resolve_fund, resolve_one, scan_disclosures, ScanResult
  cli.py          # MODIFY — 6 utility commands in a Utilities panel + epilog note
tests/
  test_utils.py   # NEW — resolution + scan (mocked KapClient)
  test_cli.py     # MODIFY — CLI tests for the 6 commands (fake client)
README.md         # MODIFY — Utilities section
docs/kap-cli-handoff.md  # MODIFY — Utilities note
```

---

### Task 1: Resolution helpers (`kap/utils.py`)

**Files:**
- Create: `kap/utils.py`
- Test: `tests/test_utils.py`

**Interfaces:**
- Consumes: `KapClient.members() -> list[dict]`, `KapClient.funds() -> list[dict]`.
- Produces:
  - `resolve_company(client, query: str) -> list[dict]`
  - `resolve_fund(client, query: str) -> list[dict]`
  - `resolve_one(matches: list[dict], query: str, what: str, describe: Callable[[dict], str]) -> dict`

- [ ] **Step 1: Write the failing test** in `tests/test_utils.py`

```python
import pytest

from kap.utils import resolve_company, resolve_fund, resolve_one


class FakeClient:
    def __init__(self, members=None, funds=None, pages=None, last=0):
        self._members = members or []
        self._funds = funds or []
        self._pages = pages or {}
        self._last = last
        self.calls = []

    def members(self):
        return self._members

    def funds(self):
        return self._funds

    def last_disclosure_index(self):
        return self._last

    def disclosures(self, index, *, disclosure_type=None, disclosure_class=None, company_id=None):
        self.calls.append((index, disclosure_class, company_id))
        return self._pages.get(index, [])


_MEMBERS = [
    {"id": "866", "stockCode": "ASELS", "title": "ASELSAN ELEKTRONIK SANAYI VE TICARET A.S."},
    {"id": "1107", "stockCode": "THYAO", "title": "TURK HAVA YOLLARI A.O."},
    {"id": "200", "stockCode": "AKBNK", "title": "AKBANK T.A.S."},
]
_FUNDS = [
    {"fundId": 5758, "fundCode": "BON", "fundName": "A1 CAPITAL PORTFOY BORCLANMA ARACLARI FONU", "fundCompanyId": 700},
    {"fundId": 5815, "fundCode": "DGF", "fundName": "A1 CAPITAL PORTFOY DEGISKEN FON", "fundCompanyId": 700},
]


def test_resolve_company_exact_ticker_case_insensitive():
    out = resolve_company(FakeClient(members=_MEMBERS), "asels")
    assert len(out) == 1 and out[0]["id"] == "866"


def test_resolve_company_partial_name():
    out = resolve_company(FakeClient(members=_MEMBERS), "turk hava")
    assert [m["stockCode"] for m in out] == ["THYAO"]


def test_resolve_company_not_found_returns_empty():
    assert resolve_company(FakeClient(members=_MEMBERS), "ZZZZ") == []


def test_resolve_company_exact_beats_partial():
    # query equals a stockCode → only the exact row, even if it also appears in a title
    out = resolve_company(FakeClient(members=_MEMBERS), "AKBNK")
    assert len(out) == 1 and out[0]["stockCode"] == "AKBNK"


def test_resolve_fund_exact_code():
    out = resolve_fund(FakeClient(funds=_FUNDS), "bon")
    assert len(out) == 1 and out[0]["fundId"] == 5758


def test_resolve_fund_partial_name_multiple():
    out = resolve_fund(FakeClient(funds=_FUNDS), "A1 CAPITAL")
    assert {f["fundCode"] for f in out} == {"BON", "DGF"}


def test_resolve_one_single_returns_it():
    assert resolve_one([{"x": 1}], "q", "ticker", lambda m: "x")["x"] == 1


def test_resolve_one_zero_raises():
    with pytest.raises(ValueError, match="No ticker matching"):
        resolve_one([], "ZZZ", "ticker", lambda m: "x")


def test_resolve_one_multiple_raises_with_list():
    matches = [{"fundCode": "BON"}, {"fundCode": "DGF"}]
    with pytest.raises(ValueError, match="ambiguous"):
        resolve_one(matches, "A1", "fund", lambda f: f["fundCode"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_utils.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'kap.utils'`.

- [ ] **Step 3: Implement `kap/utils.py`**

```python
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from kap.client import JsonObj, KapClient


def resolve_company(client: KapClient, query: str) -> list[JsonObj]:
    """Resolve a stock ticker or company-name fragment to member rows.

    Exact stockCode match (case-insensitive) wins; otherwise a case-insensitive
    substring match on the company title. Returns all matches.
    """
    q = query.strip().upper()
    members = client.members()
    exact = [m for m in members if str(m.get("stockCode") or "").upper() == q]
    if exact:
        return exact
    return [m for m in members if q in str(m.get("title") or "").upper()]


def resolve_fund(client: KapClient, query: str) -> list[JsonObj]:
    """Resolve a fund code or fund-name fragment to fund rows.

    Exact fundCode match (case-insensitive) wins; otherwise a case-insensitive
    substring match on the fund name. Returns all matches.
    """
    q = query.strip().upper()
    funds = client.funds()
    exact = [f for f in funds if str(f.get("fundCode") or "").upper() == q]
    if exact:
        return exact
    return [f for f in funds if q in str(f.get("fundName") or "").upper()]


def resolve_one(matches: list[JsonObj], query: str, what: str, describe: Callable[[JsonObj], str]) -> JsonObj:
    """Return the single match, or raise ValueError for 0 (not found) / >1 (ambiguous)."""
    if not matches:
        raise ValueError(f"No {what} matching '{query}'.")
    if len(matches) > 1:
        shown = "; ".join(describe(m) for m in matches[:8])
        more = "" if len(matches) <= 8 else f" (+{len(matches) - 8} more)"
        raise ValueError(
            f"'{query}' is ambiguous — {len(matches)} {what} matches: {shown}{more}. "
            "Narrow it or use the exact code."
        )
    return matches[0]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_utils.py -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add kap/utils.py tests/test_utils.py
git commit -m "feat: ticker/fund resolution helpers (kap/utils.py)"
```

---

### Task 2: Backward disclosure scan (`kap/utils.py`)

**Files:**
- Modify: `kap/utils.py`
- Test: `tests/test_utils.py`

**Interfaces:**
- Consumes: `KapClient.last_disclosure_index() -> int`, `KapClient.disclosures(index, *, disclosure_class=None, company_id=None) -> list[dict]`.
- Produces:
  - `ScanResult` dataclass: `items: list[dict]`, `truncated: bool`, `windows: int`.
  - `scan_disclosures(client, company_id: str | int, limit: int, disclosure_class: str | None = None, *, window: int = 36000, max_windows: int = 30) -> ScanResult`

- [ ] **Step 1: Write the failing test** (append to `tests/test_utils.py`)

```python
from kap.utils import ScanResult, scan_disclosures


def _d(idx):
    return {"disclosureIndex": str(idx), "title": f"d{idx}"}


def test_scan_collects_newest_first_to_limit():
    # window=50, last=200 → starts 150, 100, 50, 0
    pages = {150: [_d(180), _d(160)], 100: [_d(120)], 50: [_d(70)], 0: [_d(10)]}
    client = FakeClient(pages=pages, last=200)
    result = scan_disclosures(client, "C", limit=3, window=50, max_windows=10)
    assert isinstance(result, ScanResult)
    assert [d["disclosureIndex"] for d in result.items] == ["180", "160", "120"]
    assert result.truncated is False


def test_scan_dedupes_overlapping_windows():
    pages = {150: [_d(180)], 100: [_d(180), _d(120)]}
    client = FakeClient(pages=pages, last=200)
    result = scan_disclosures(client, "C", limit=10, window=50, max_windows=2)
    idxs = [d["disclosureIndex"] for d in result.items]
    assert idxs == ["180", "120"]  # 180 not duplicated


def test_scan_passes_disclosure_class_and_company_id():
    client = FakeClient(pages={0: [_d(1)]}, last=10)
    scan_disclosures(client, "866", limit=5, disclosure_class="FR", window=50)
    assert client.calls[0] == (0, "FR", "866")


def test_scan_respects_max_windows():
    client = FakeClient(pages={}, last=10_000)
    scan_disclosures(client, "C", limit=99, window=100, max_windows=3)
    assert len(client.calls) == 3


def test_scan_sets_truncated_when_window_returns_50():
    client = FakeClient(pages={0: [_d(i) for i in range(50)]}, last=10)
    result = scan_disclosures(client, "C", limit=5, window=50)
    assert result.truncated is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_utils.py -k scan -v`
Expected: FAIL with `ImportError: cannot import name 'ScanResult'`.

- [ ] **Step 3: Implement** — append to `kap/utils.py`

```python
@dataclass
class ScanResult:
    items: list[JsonObj]
    truncated: bool
    windows: int


def scan_disclosures(
    client: KapClient,
    company_id: str | int,
    limit: int,
    disclosure_class: str | None = None,
    *,
    window: int = 36000,
    max_windows: int = 30,
) -> ScanResult:
    """Collect an entity's most recent disclosures by walking BACKWARD from the latest index.

    The disclosures endpoint scans a bounded ~36k-index window forward from a start index and
    caps at 50; this tiles windows backward from last-index, deduping by disclosureIndex, until
    `limit` are gathered (or `max_windows` is reached). Returns newest-first.
    """
    last = client.last_disclosure_index()
    found: dict[int, JsonObj] = {}
    truncated = False
    start = max(0, last - window)
    windows = 0
    while len(found) < limit and windows < max_windows:
        page = client.disclosures(start, disclosure_class=disclosure_class, company_id=company_id)
        if len(page) >= 50:
            truncated = True
        for item in page:
            try:
                idx = int(item["disclosureIndex"])
            except (KeyError, TypeError, ValueError):
                continue
            found[idx] = item
        windows += 1
        if start == 0:
            break
        start = max(0, start - window)
    ordered = [item for _, item in sorted(found.items(), key=lambda kv: kv[0], reverse=True)]
    return ScanResult(items=ordered[:limit], truncated=truncated, windows=windows)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_utils.py -v`
Expected: PASS (14 tests total).

- [ ] **Step 5: Commit**

```bash
git add kap/utils.py tests/test_utils.py
git commit -m "feat: backward disclosure scan with dedupe + truncation flag"
```

---

### Task 3: Utility CLI commands + Utilities panel (`kap/cli.py`)

**Files:**
- Modify: `kap/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `kap.utils.resolve_company`, `resolve_fund`, `resolve_one`, `scan_disclosures` (Tasks 1–2); existing `_errors`, `_make_client`, `validate_format`, `output`, `_err_console`, option aliases `EnvOpt/FormatOpt/OutOpt/VerboseOpt`.
- Produces: 6 commands — `resolve-ticker`, `resolve-fund`, `ticker-disclosures`, `ticker-financials`, `fund-info`, `fund-disclosures` — all with `rich_help_panel` set to the Utilities panel.

- [ ] **Step 1: Add the import** to `kap/cli.py` (after the existing `from kap.render import ...` line)

```python
from kap.utils import resolve_company, resolve_fund, resolve_one, scan_disclosures
```

- [ ] **Step 2: Add the Utilities panel constant + helpers** (after `_err_console = Console(stderr=True)`)

```python
_UTIL_PANEL = "Utilities (convenience — not raw API endpoints)"


def _describe_company(m: dict) -> str:
    return f"{m.get('stockCode')} — {m.get('title')}"


def _describe_fund(f: dict) -> str:
    return f"{f.get('fundCode')} — {f.get('fundName')}"


def _render_scan(fmt, out, result) -> None:
    if result.truncated:
        _err_console.print(
            "[yellow]Note:[/yellow] some windows hit the 50-result cap; very active filers may be "
            "incomplete — raise --limit."
        )
    output(result.items, fmt=fmt, out=out)
```

- [ ] **Step 3: Add a note to the epilog** — in `_EPILOG`, append one final line (change the last string fragment)

Find the last line of `_EPILOG`:
```python
    "[cyan]-o/--out[/cyan] PATH, [cyan]--env[/cyan] \\[test|production], [cyan]-v/--verbose[/cyan]."
```
Replace it with:
```python
    "[cyan]-o/--out[/cyan] PATH, [cyan]--env[/cyan] \\[test|production], [cyan]-v/--verbose[/cyan].\n\n"
    "Core [bold]Commands[/bold] call one KAP endpoint each; [magenta]Utilities[/magenta] are "
    "multi-call convenience built on them."
```

- [ ] **Step 4: Add the 6 commands** at the end of `kap/cli.py`

```python
_TICKER_ARG = Annotated[str, typer.Argument(help="Stock ticker (e.g. ASELS) or a company-name fragment.")]
_FUND_ARG = Annotated[str, typer.Argument(help="Fund code (e.g. BON) or a fund-name fragment.")]
_LIMIT_OPT = Annotated[int, typer.Option("--limit", min=1, help="Max disclosures, newest first.")]


@app.command(
    "resolve-ticker",
    rich_help_panel=_UTIL_PANEL,
    short_help="[magenta]composite[/magenta]  ticker/name → companyId",
)
def resolve_ticker_cmd(
    query: _TICKER_ARG, env: EnvOpt = None, fmt: FormatOpt = None, out: OutOpt = None, verbose: VerboseOpt = False
):
    """Composite utility (not a single endpoint). Resolve a stock ticker or company-name
    fragment to its companyId + title.

    Calls GET /api/vyk/members and matches stockCode (exact) or title (substring).

    Example: kap resolve-ticker ASELS
    """
    with _errors(verbose):
        validate_format(fmt)
        with _make_client(env) as client:
            matches = resolve_company(client, query)
        output(matches, fmt=fmt, out=out)


@app.command(
    "resolve-fund",
    rich_help_panel=_UTIL_PANEL,
    short_help="[magenta]composite[/magenta]  fund code/name → fundId",
)
def resolve_fund_cmd(
    query: _FUND_ARG, env: EnvOpt = None, fmt: FormatOpt = None, out: OutOpt = None, verbose: VerboseOpt = False
):
    """Composite utility (not a single endpoint). Resolve a fund code or fund-name fragment to
    its fundId + name.

    Calls GET /api/vyk/funds and matches fundCode (exact) or fundName (substring).

    Example: kap resolve-fund BON
    """
    with _errors(verbose):
        validate_format(fmt)
        with _make_client(env) as client:
            matches = resolve_fund(client, query)
        output(matches, fmt=fmt, out=out)


@app.command(
    "ticker-disclosures",
    rich_help_panel=_UTIL_PANEL,
    short_help="[magenta]composite[/magenta]  ticker → recent disclosures (newest first)",
)
def ticker_disclosures_cmd(
    query: _TICKER_ARG,
    limit: _LIMIT_OPT = 20,
    env: EnvOpt = None,
    fmt: FormatOpt = None,
    out: OutOpt = None,
    verbose: VerboseOpt = False,
):
    """Composite utility (not a single endpoint). Recent disclosures for a ticker, newest first.

    Resolves the ticker via GET /api/vyk/members, then pages GET /api/vyk/disclosures backward
    from the latest index until --limit are collected.

    Example: kap ticker-disclosures ASELS --limit 20
    """
    with _errors(verbose):
        validate_format(fmt)
        with _make_client(env) as client:
            company = resolve_one(resolve_company(client, query), query, "ticker", _describe_company)
            result = scan_disclosures(client, company["id"], limit)
        _render_scan(fmt, out, result)


@app.command(
    "ticker-financials",
    rich_help_panel=_UTIL_PANEL,
    short_help="[magenta]composite[/magenta]  ticker → recent FR filings (newest first)",
)
def ticker_financials_cmd(
    query: _TICKER_ARG,
    limit: _LIMIT_OPT = 20,
    env: EnvOpt = None,
    fmt: FormatOpt = None,
    out: OutOpt = None,
    verbose: VerboseOpt = False,
):
    """Composite utility (not a single endpoint). Recent financial-report (FR-class) filings for
    a ticker, newest first.

    Resolves the ticker via GET /api/vyk/members, then pages GET /api/vyk/disclosures?disclosureClass=FR
    backward from the latest index until --limit are collected.

    Example: kap ticker-financials ASELS
    """
    with _errors(verbose):
        validate_format(fmt)
        with _make_client(env) as client:
            company = resolve_one(resolve_company(client, query), query, "ticker", _describe_company)
            result = scan_disclosures(client, company["id"], limit, disclosure_class="FR")
        _render_scan(fmt, out, result)


@app.command(
    "fund-info",
    rich_help_panel=_UTIL_PANEL,
    short_help="[magenta]composite[/magenta]  fund code/name → fund detail",
)
def fund_info_cmd(
    query: _FUND_ARG, env: EnvOpt = None, fmt: FormatOpt = None, out: OutOpt = None, verbose: VerboseOpt = False
):
    """Composite utility (not a single endpoint). General-info sections for a fund, by code or name.

    Resolves the fund via GET /api/vyk/funds, then calls GET /api/vyk/fundDetail/{id}.

    Example: kap fund-info BON
    """
    with _errors(verbose):
        validate_format(fmt)
        with _make_client(env) as client:
            fund = resolve_one(resolve_fund(client, query), query, "fund", _describe_fund)
            data = client.fund_detail(fund["fundId"])
        output(data, fmt=fmt, out=out)


@app.command(
    "fund-disclosures",
    rich_help_panel=_UTIL_PANEL,
    short_help="[magenta]composite[/magenta]  fund → recent disclosures (newest first)",
)
def fund_disclosures_cmd(
    query: _FUND_ARG,
    limit: _LIMIT_OPT = 20,
    env: EnvOpt = None,
    fmt: FormatOpt = None,
    out: OutOpt = None,
    verbose: VerboseOpt = False,
):
    """Composite utility (not a single endpoint). Recent disclosures for a fund, newest first.

    Resolves the fund via GET /api/vyk/funds, then pages GET /api/vyk/disclosures backward by the
    fund's company id (fundCompanyId).

    Example: kap fund-disclosures BON --limit 20
    """
    with _errors(verbose):
        validate_format(fmt)
        with _make_client(env) as client:
            fund = resolve_one(resolve_fund(client, query), query, "fund", _describe_fund)
            result = scan_disclosures(client, fund["fundCompanyId"], limit)
        _render_scan(fmt, out, result)
```

- [ ] **Step 5: Write CLI tests** — replace the `_FakeClient` in `tests/test_cli.py` and add tests

In `tests/test_cli.py`, update `_FakeClient.members` and add `funds`/`last_disclosure_index` data so the utilities resolve. Replace the existing `members` method and add the new ones:

```python
    def members(self):
        return [
            {"id": "1", "stockCode": "ACM", "title": "ACME"},
            {"id": "2", "stockCode": "ACB", "title": "ACME BETA"},
        ]

    def funds(self):
        return [{"fundId": 5900, "fundCode": "BON", "fundName": "TEST FON", "fundCompanyId": 700}]

    def last_disclosure_index(self):
        return 999

    def disclosures(self, index, *, disclosure_type=None, disclosure_class=None, company_id=None):
        self.calls.append(("disclosures", index, disclosure_class, company_id))
        return [{"disclosureIndex": str(index)}]
```

(Keep the existing `disclosure_detail`, `download_attachment`, `ca_event_status`, `fund_detail`, `raw`, `close`, `__enter__`, `__exit__`, and the unchanged `fund_detail` returning `[{"section": "general"}]`.) Note: `test_members_json` asserts `'"title": "ACME"'` — keep a member titled exactly `ACME`.

Then append these tests:

```python
def test_resolve_ticker_lists_matches(fake_client):
    result = runner.invoke(cli.app, ["resolve-ticker", "ACM"])
    assert result.exit_code == 0
    assert "ACM" in result.stdout


def test_resolve_fund_lists_matches(fake_client):
    result = runner.invoke(cli.app, ["resolve-fund", "BON", "--format", "json"])
    assert result.exit_code == 0
    assert '"fundId": 5900' in result.stdout


def test_ticker_disclosures_scans_by_company_id(fake_client):
    result = runner.invoke(cli.app, ["ticker-disclosures", "ACM", "--limit", "5"])
    assert result.exit_code == 0
    # resolved ACM → id "1"; scan called disclosures with that company_id
    assert any(c[0] == "disclosures" and c[3] == "1" for c in fake_client.calls)


def test_ticker_financials_filters_fr(fake_client):
    result = runner.invoke(cli.app, ["ticker-financials", "ACM"])
    assert result.exit_code == 0
    assert any(c[0] == "disclosures" and c[2] == "FR" for c in fake_client.calls)


def test_fund_info_resolves_and_details(fake_client):
    result = runner.invoke(cli.app, ["fund-info", "BON"])
    assert result.exit_code == 0
    assert "general" in result.stdout


def test_fund_disclosures_scans_by_fund_company_id(fake_client):
    result = runner.invoke(cli.app, ["fund-disclosures", "BON"])
    assert result.exit_code == 0
    assert any(c[0] == "disclosures" and c[3] == 700 for c in fake_client.calls)


def test_ambiguous_ticker_exits_with_message(fake_client):
    # "ACME" is not an exact stockCode, matches both titles → ambiguous
    result = runner.invoke(cli.app, ["ticker-disclosures", "ACME"])
    assert result.exit_code == 1
    assert "ambiguous" in result.stderr


def test_unknown_ticker_exits_with_message(fake_client):
    result = runner.invoke(cli.app, ["ticker-disclosures", "ZZZZ"])
    assert result.exit_code == 1
    assert "No ticker matching" in result.stderr
```

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS (all prior + 8 new CLI tests + 14 utils tests).

- [ ] **Step 7: Verify the Utilities panel renders**

Run: `COLUMNS=140 python -m kap --help`
Expected: a separate panel titled "Utilities (convenience — not raw API endpoints)" listing the 6 commands, each with a magenta `composite` tag; the core Commands panel still shows yellow `GET …` endpoints.

- [ ] **Step 8: Live verification (prod, allowlisted IP; `~/.kap/.env` has the prod key)**

Run each and confirm real data (not an error):
```bash
python -m kap resolve-ticker ASELS
python -m kap ticker-disclosures ASELS --limit 5
python -m kap ticker-financials ASELS --limit 5
python -m kap resolve-fund BON
python -m kap fund-info BON
python -m kap fund-disclosures BON --limit 5
```
**Decision gate for `fund-disclosures`:** if it returns real disclosures, keep it. If it returns empty/wrong data (funds don't file under `fundCompanyId`), REMOVE the `fund-disclosures` command + its two tests and note it in the report. Record the live results (counts) in the report either way.

- [ ] **Step 9: Commit**

```bash
git add kap/cli.py tests/test_cli.py
git commit -m "feat: ticker/fund utility commands in a Utilities panel"
```

---

### Task 4: Docs (README + handoff)

**Files:**
- Modify: `README.md`, `docs/kap-cli-handoff.md`

**Interfaces:** none (documentation).

- [ ] **Step 1: Add a Utilities section to `README.md`** (after the existing "Commands ↔ endpoints" table)

```markdown
## Utilities (convenience — not raw API endpoints)

These wrap several endpoint calls into one. Unlike the core commands, they don't map to a single
KAP endpoint — they resolve a ticker/fund and orchestrate the right calls.

| Utility | What it does | Orchestrates |
|---|---|---|
| `resolve-ticker <q>` | ticker or company-name → companyId + title | `GET /members` |
| `resolve-fund <q>` | fund code or name → fundId + name | `GET /funds` |
| `ticker-disclosures <q> [--limit N]` | recent disclosures for a ticker, newest first | resolve + paged `GET /disclosures` |
| `ticker-financials <q> [--limit N]` | recent FR filings for a ticker | resolve + paged `GET /disclosures?disclosureClass=FR` |
| `fund-info <q>` | fund general-info sections | resolve + `GET /fundDetail/{id}` |
| `fund-disclosures <q> [--limit N]` | recent disclosures for a fund | resolve + paged `GET /disclosures` (by fundCompanyId) |

```bash
kap resolve-ticker ASELS
kap ticker-disclosures ASELS --limit 20
kap resolve-fund BON
kap fund-info BON
```

> Disclosure utilities page backward from the latest index to return genuinely recent filings
> (the raw `disclosures` command only scans a bounded window forward).
```

(If `fund-disclosures` was dropped in Task 3, omit its row and any mention.)

- [ ] **Step 2: Add a Utilities note to `docs/kap-cli-handoff.md`** — under §0 or a new short section:

```markdown
**Utilities layer (2026-06-24):** `kap/utils.py` adds composite commands (resolve-ticker/fund,
ticker-disclosures, ticker-financials, fund-info, fund-disclosures) shown in a separate
"Utilities" help panel. They resolve a ticker/fund (over members/funds, exact-code-then-partial-name)
and run the recency backward-scan. KapClient stays the thin 1:1 wrapper. (fund-disclosures kept/dropped
per live verification — see commit.)
```

- [ ] **Step 3: Commit**

```bash
git add README.md docs/kap-cli-handoff.md
git commit -m "docs: document the ticker/fund utilities"
```

---

## Self-Review

**Spec coverage** (against `2026-06-24-ticker-fund-utilities-design.md`):
- §2 architecture (kap/utils.py layer, KapClient unchanged) → Tasks 1–2. ✓
- §3 resolution (exact-then-partial, list, resolve_one 0/>1) → Task 1. ✓
- §4 backward scan (window/max_windows/limit, dedupe, newest-first, truncated) → Task 2. ✓
- §5 the 6 commands + --limit≥1 + clean errors + fund-disclosures live gate → Task 3 (Steps 4, 8). ✓
- §6 help separation (Utilities panel, magenta composite tag, composite docstrings, epilog note) → Task 3 (Steps 2,3,4,7). ✓
- §7 testing (utils + cli) → Tasks 1,2,3. ✓ Live verification → Task 3 Step 8. ✓
- §9 deliverables (README + handoff) → Task 4. ✓

**Placeholder scan:** none — all steps carry real code/commands. (The only conditional is the fund-disclosures live gate, which is an explicit decision step, not a placeholder.)

**Type consistency:** `resolve_company/resolve_fund -> list[JsonObj]`; `resolve_one(matches, query, what, describe)` used in Task 3 with `_describe_company`/`_describe_fund`. `scan_disclosures(client, company_id, limit, disclosure_class=None, *, window, max_windows) -> ScanResult(items, truncated, windows)` consumed by `_render_scan` and the commands. companyId from `company["id"]` (str), fund from `fund["fundId"]`/`fund["fundCompanyId"]`. `JsonObj` imported from `kap.client`. Consistent across tasks. ✓
