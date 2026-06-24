# `fund-portfolio-pdf` Utility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `fund-portfolio-pdf <fund>` utility that downloads a fund's Portföy Dağılım Raporu PDF(s) — latest by default, or all in a `--from/--to` period range.

**Architecture:** Reuse `find_fund_portfolio_reports` (extended to surface each report's `attachmentUrls`) + the existing `KapClient.download_attachment` (Java-envelope→`%PDF` unwrap). New command in `cli.py`'s Utilities panel; no KapClient change.

**Tech Stack:** Python 3.11+, Typer, Rich, pytest (mocked KapClient / Typer CliRunner).

## Global Constraints

- Python 3.11+. DRY, YAGNI, TDD.
- KapClient unchanged; reuse `download_attachment(id) -> bytes | None`.
- The PDR detail carries `attachmentUrls: [{"url": ".../downloadAttachment/<id>", "fileName": "BON_2026.04.pdf"}]` (some older PDRs have none). The attachment id = last path segment of `url`.
- Default (no range) → download the latest report's PDF; `--from/--to` (YYYY-MM, validated) → every report in the range.
- Output: single → `--out FILE` (default = KAP's own filename in the current dir); multiple → `--out-dir DIR` (default `.`), each under its server filename. `--out` + multiple → `typer.BadParameter`. Filenames are always `Path(name).name` (strip dir components); fall back to `<disclosureIndex>.pdf`.
- A report with no attachment → stderr note + skip; if nothing downloaded → exit 1. Print `Saved <path> (<n> bytes)` per file.
- New command in `rich_help_panel=_UTIL_PANEL` with `[magenta]composite[/magenta]` short_help; docstring opens "Composite utility (not a single endpoint)." with the steps as a **blank-line-separated numbered list** (each step on its own line, matching `fund-portfolio-report`).

---

## File Structure

```
kap/utils.py    # MODIFY — add attachmentUrls to finder items; add attachment_id_from_url
kap/cli.py      # MODIFY — fund-portfolio-pdf command (Utilities panel, numbered-step --help)
tests/test_utils.py  # MODIFY — attachment_id_from_url; attachmentUrls surfaces on items
tests/test_cli.py    # MODIFY — download wiring (single/--out/--out-dir/no-attachment/not-found)
README.md / docs/kap-cli-handoff.md  # MODIFY — Utilities table row
```

---

### Task 1: utils — attachments on items + id helper

**Files:**
- Modify: `kap/utils.py`, `tests/test_utils.py`

**Interfaces:**
- Consumes: existing `find_fund_portfolio_reports`, `FakeClient`.
- Produces:
  - `attachment_id_from_url(url: str) -> str` (last non-empty path segment).
  - `find_fund_portfolio_reports` items now also include `"attachmentUrls": list` (the detail's, or `[]`).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_utils.py`)

```python
from kap.utils import attachment_id_from_url


def test_attachment_id_from_url():
    assert attachment_id_from_url("https://h/api/vyk/downloadAttachment/ABC123") == "ABC123"
    assert attachment_id_from_url("https://h/api/vyk/downloadAttachment/ABC123/") == "ABC123"


def test_finder_item_includes_attachment_urls():
    atts = [{"url": "https://h/api/vyk/downloadAttachment/AID", "fileName": "BON_2026.03.pdf"}]
    detail = _pdr_detail(90, "BON", "2026 / 3.Ay")
    detail["attachmentUrls"] = atts
    client = FakeClient(pages={0: [_fon(90)]}, details={90: detail}, last=100)
    result = find_fund_portfolio_reports(client, "BON", "C", window=1000)
    assert result.items[0]["attachmentUrls"] == atts
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_utils.py -k "attachment" -v`
Expected: FAIL with `ImportError: cannot import name 'attachment_id_from_url'` (and the item-key test failing once the import exists).

- [ ] **Step 3: Implement** in `kap/utils.py`

Add the helper near the other module-level helpers (e.g. above `_enumerate_window`):
```python
def attachment_id_from_url(url: str) -> str:
    """The attachment id is the last non-empty path segment of an attachmentUrls[].url."""
    return url.rstrip("/").rsplit("/", 1)[-1]
```

In `find_fund_portfolio_reports`, add `attachmentUrls` to the item dict (the `detail` is already in hand):
```python
            item: JsonObj = {
                "disclosureIndex": idx,
                "period": period,
                "fundCode": detail.get("behalfFundCode"),
                "fundTitle": detail.get("behalfFundTitle"),
                "attachmentUrls": detail.get("attachmentUrls") or [],
                "presentation": detail.get("presentation"),
            }
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_utils.py -v`
Expected: PASS (all prior utils tests + 2 new).

- [ ] **Step 5: Commit**

```bash
git add kap/utils.py tests/test_utils.py
git commit -m "feat: surface attachmentUrls on portfolio-report items + id-from-url helper"
```

---

### Task 2: CLI command + live verification

**Files:**
- Modify: `kap/cli.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `attachment_id_from_url`, `find_fund_portfolio_reports` (Task 1); `resolve_fund`/`resolve_one`/`_describe_fund`, `_errors`, `_make_client`, `_err_console`, `_PERIOD_RE_CLI`, `_FUND_ARG`, `EnvOpt/OutOpt/VerboseOpt`, `KapClient.download_attachment`.
- Produces: the `fund-portfolio-pdf` command.

- [ ] **Step 1: Extend the utils import** in `kap/cli.py` — add `attachment_id_from_url` to the `from kap.utils import (...)` block.

- [ ] **Step 2: Add the command** at the end of `kap/cli.py`

```python
@app.command(
    "fund-portfolio-pdf",
    rich_help_panel=_UTIL_PANEL,
    short_help="[magenta]composite[/magenta]  fund → download Portföy Dağılım Raporu PDF",
)
def fund_portfolio_pdf_cmd(
    query: _FUND_ARG,
    from_period: Annotated[Optional[str], typer.Option("--from", help="Start report period, YYYY-MM.")] = None,
    to_period: Annotated[Optional[str], typer.Option("--to", help="End report period, YYYY-MM.")] = None,
    out: OutOpt = None,
    out_dir: Annotated[Optional[Path], typer.Option("--out-dir", help="Directory for the PDF(s).")] = None,
    env: EnvOpt = None,
    verbose: VerboseOpt = False,
):
    """Composite utility (not a single endpoint). Download a fund's Portföy Dağılım Raporu (portfolio allocation report) PDF.

    What it does:

    1. Resolve the fund to its management-company id — GET /api/vyk/funds

    2. Find its Portföy Dağılım Raporu disclosure(s) — same scan as fund-portfolio-report

    3. Download each report's attached PDF — GET /api/vyk/downloadAttachment/{id}

    No range downloads the latest report's PDF; --from/--to (YYYY-MM) download every report in that range. Single report → --out FILE (defaults to KAP's own filename); multiple → --out-dir DIR.

    Examples:

    kap fund-portfolio-pdf BON

    kap fund-portfolio-pdf BON --out latest.pdf

    kap fund-portfolio-pdf BON --from 2026-01 --to 2026-06 --out-dir reports
    """
    for label, value in (("--from", from_period), ("--to", to_period)):
        if value is not None and not _PERIOD_RE_CLI.match(value):
            raise typer.BadParameter(f"{label} must be YYYY-MM, got '{value}'")
    if from_period is not None and to_period is not None and from_period > to_period:
        raise typer.BadParameter(f"--from ({from_period}) is after --to ({to_period})")

    with _errors(verbose):
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

            downloads: list[tuple[str, str]] = []  # (attachment_id, filename)
            for item in result.items:
                atts = item.get("attachmentUrls") or []
                if not atts:
                    label = item.get("period") or item["disclosureIndex"]
                    _err_console.print(f"[yellow]Note:[/yellow] {label} has no PDF attachment — skipped.")
                    continue
                for att in atts:
                    url = att.get("url")
                    if not url:
                        continue
                    name = Path(att.get("fileName") or f"{item['disclosureIndex']}.pdf").name
                    downloads.append((attachment_id_from_url(url), name))

            if not downloads:
                _err_console.print(f"[yellow]No PDF attachments found for '{query}'.[/yellow]")
                raise typer.Exit(code=1)
            if out is not None and len(downloads) > 1:
                raise typer.BadParameter("multiple reports matched — use --out-dir instead of --out")
            if result.truncated:
                _err_console.print(
                    "[yellow]Note:[/yellow] scan bound hit; results may be incomplete — narrow --from/--to."
                )

            single = len(downloads) == 1
            saved = 0
            for att_id, name in downloads:
                if single and out is not None:
                    target = out
                else:
                    base = out_dir if out_dir is not None else Path(".")
                    base.mkdir(parents=True, exist_ok=True)
                    target = base / name
                data = client.download_attachment(att_id)
                if data is None:
                    _err_console.print(f"[yellow]Note:[/yellow] attachment {att_id} not found — skipped.")
                    continue
                target.write_bytes(data)
                print(f"Saved {target} ({len(data)} bytes)")
                saved += 1
            if saved == 0:
                raise typer.Exit(code=1)
```

- [ ] **Step 3: Write CLI tests** — append to `tests/test_cli.py`. The existing `_FakeClient.download_attachment` already returns `b"%PDF-1.7 bytes"`. Add:

```python
def _pdf_result(items):
    return PortfolioReportResult(items=items, truncated=False, details_fetched=len(items))


def _report(idx, period, name="BON_%s.pdf", atts=True):
    fn = name % period if "%s" in name else name
    return {
        "disclosureIndex": idx, "period": period, "fundCode": "BON", "fundTitle": "T",
        "attachmentUrls": [{"url": f"https://h/api/vyk/downloadAttachment/AID{idx}", "fileName": fn}] if atts else [],
        "presentation": [],
    }


def test_fund_portfolio_pdf_single_to_out_dir(fake_client, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "find_fund_portfolio_reports", lambda *a, **k: _pdf_result([_report(90, "2026-04")]))
    result = runner.invoke(cli.app, ["fund-portfolio-pdf", "BON", "--out-dir", str(tmp_path)])
    assert result.exit_code == 0
    saved = tmp_path / "BON_2026-04.pdf"
    assert saved.read_bytes() == b"%PDF-1.7 bytes"


def test_fund_portfolio_pdf_single_to_out_file(fake_client, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "find_fund_portfolio_reports", lambda *a, **k: _pdf_result([_report(90, "2026-04")]))
    target = tmp_path / "latest.pdf"
    result = runner.invoke(cli.app, ["fund-portfolio-pdf", "BON", "--out", str(target)])
    assert result.exit_code == 0
    assert target.read_bytes() == b"%PDF-1.7 bytes"


def test_fund_portfolio_pdf_multiple_to_out_dir(fake_client, monkeypatch, tmp_path):
    monkeypatch.setattr(
        cli, "find_fund_portfolio_reports",
        lambda *a, **k: _pdf_result([_report(90, "2026-04"), _report(60, "2026-03")]),
    )
    result = runner.invoke(cli.app, ["fund-portfolio-pdf", "BON", "--out-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "BON_2026-04.pdf").exists() and (tmp_path / "BON_2026-03.pdf").exists()


def test_fund_portfolio_pdf_out_with_multiple_rejected(fake_client, monkeypatch, tmp_path):
    monkeypatch.setattr(
        cli, "find_fund_portfolio_reports",
        lambda *a, **k: _pdf_result([_report(90, "2026-04"), _report(60, "2026-03")]),
    )
    result = runner.invoke(cli.app, ["fund-portfolio-pdf", "BON", "--out", str(tmp_path / "x.pdf")])
    assert result.exit_code != 0
    assert "out-dir" in (result.stderr + result.stdout)


def test_fund_portfolio_pdf_no_attachment_exits_1(fake_client, monkeypatch):
    monkeypatch.setattr(cli, "find_fund_portfolio_reports", lambda *a, **k: _pdf_result([_report(90, "2026-04", atts=False)]))
    result = runner.invoke(cli.app, ["fund-portfolio-pdf", "BON"])
    assert result.exit_code == 1
    assert "No PDF attachments" in result.stderr


def test_fund_portfolio_pdf_not_found_exits_1(fake_client, monkeypatch):
    monkeypatch.setattr(cli, "find_fund_portfolio_reports", lambda *a, **k: _pdf_result([]))
    result = runner.invoke(cli.app, ["fund-portfolio-pdf", "BON"])
    assert result.exit_code == 1
    assert "No Portföy Dağılım Raporu" in result.stderr
```

(Ensure `PortfolioReportResult` is imported in `tests/test_cli.py` — it already is from the prior feature; if not, add `from kap.utils import PortfolioReportResult`.)

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS (all prior + Task 1 utils tests + 6 new CLI tests).

- [ ] **Step 5: Verify help (numbered steps + Utilities panel)**

Run: `COLUMNS=150 python -m kap fund-portfolio-pdf --help`
Expected: docstring shows the 3 numbered steps **each on its own line** + the examples; `--from/--to/--out/--out-dir` listed.
Run: `COLUMNS=150 python -m kap --help` → `fund-portfolio-pdf` in the Utilities panel with the magenta `composite` tag.

- [ ] **Step 6: Live verification (prod, allowlisted IP; `~/.kap/.env` has the prod key)**

```bash
python -m kap fund-portfolio-pdf BON --out-dir _smoke
```
Confirm a `BON_*.pdf` is written under `_smoke/` and is a real PDF (first bytes `%PDF`):
```bash
python - <<'PY'
import glob
f = sorted(glob.glob("_smoke/BON_*.pdf"))[-1]
print(f, "starts with %PDF:", open(f, "rb").read(4) == b"%PDF")
PY
```
Record the filename + the `%PDF` check in your report. (`_smoke/` and `*.pdf` are gitignored.)

- [ ] **Step 7: Commit**

```bash
git add kap/cli.py tests/test_cli.py
git commit -m "feat: fund-portfolio-pdf command (download the report PDF)"
```

---

### Task 3: Docs

**Files:**
- Modify: `README.md`, `docs/kap-cli-handoff.md`

- [ ] **Step 1: Add a README Utilities-table row** (in `README.md`, after the `fund-portfolio-report` row):

```markdown
| `fund-portfolio-pdf <q> [--from/--to] [--out/--out-dir]` | download a fund's Portföy Dağılım Raporu **PDF** (latest, or all in a range) | resolve + find report(s) + `GET /downloadAttachment` |
```

And after the Utilities usage block, add:
```markdown
```bash
kap fund-portfolio-pdf BON                              # latest report PDF → KAP's own filename
kap fund-portfolio-pdf BON --from 2026-01 --to 2026-06 --out-dir reports
```
```

- [ ] **Step 2: Update `docs/kap-cli-handoff.md`** — in §4 (Utilities table) add a `fund-portfolio-pdf` row mirroring the README, and in the §0 Utilities paragraph append: "`fund-portfolio-pdf` downloads the report's attached PDF (reusing the finder's `attachmentUrls` + `download-attachment`'s %PDF unwrap)."

- [ ] **Step 3: Commit**

```bash
git add README.md docs/kap-cli-handoff.md
git commit -m "docs: document fund-portfolio-pdf utility"
```

---

## Self-Review

**Spec coverage** (against `2026-06-24-fund-portfolio-pdf-design.md`):
- §3.1 attachmentUrls on items + `attachment_id_from_url` → Task 1. ✓
- §3.2 command flow (resolve → find → build downloads → out/out-dir → save) → Task 2. ✓
- §2 behavior (latest default; range; out vs out-dir; --out+multiple reject) → Task 2. ✓
- §4 numbered-step `--help` → Task 2 Step 2 docstring + Step 5 check. ✓
- §5 edge cases (no attachment skip; ER005 None skip; filename `.name`; from>to) → Task 2. ✓
- §6 testing (utils + cli) + live verify → Tasks 1, 2 (Step 6). ✓
- §8 docs → Task 3. ✓

**Placeholder scan:** none — all steps have real code/commands.

**Type consistency:** `attachment_id_from_url(url) -> str` and the item's `attachmentUrls` key are produced in Task 1 and consumed in Task 2. The command uses `fund["fundCode"]`/`fund["fundCompanyId"]`, `result.items`/`result.truncated` (from `PortfolioReportResult`), `client.download_attachment(id) -> bytes | None`, and `_PERIOD_RE_CLI` — all already defined in the codebase. CLI tests reuse the existing `_FakeClient.download_attachment` (returns `b"%PDF-1.7 bytes"`) and `PortfolioReportResult`. ✓
