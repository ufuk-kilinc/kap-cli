# Ticker & Fund Utilities — Design Spec

**Date:** 2026-06-24
**Status:** Approved (design), pending implementation plan
**Repo:** `tuneup/kap-cli/` (branch TBD at implementation)

---

## 1. Purpose

Add a small family of **utility commands** to `kap-cli` that resolve a human-friendly
identifier (a stock ticker or a fund code/name) and orchestrate the multi-call workflows the
thin 1:1 endpoint commands can't do on their own — chiefly **recency-correct disclosures for an
entity**. These are explicitly *composites*: each calls more than one KAP endpoint, so they are
kept separate from the raw endpoint commands and labeled as such in help.

This is a deliberate, opt-in extension beyond the original "thin wrapper only" scope (the
"smart" logic that otherwise lives in the C# Tuni layer), done with clear separation.

---

## 2. Architecture

New layer **`kap/utils.py`** that takes a `KapClient` and orchestrates calls. `KapClient` stays
the pure 1:1 endpoint wrapper (unchanged). The CLI utility commands call `kap/utils.py`.

```
kap/
  utils.py        # NEW — resolution + backward-scan composites over a KapClient
  cli.py          # MODIFY — add 6 utility commands in a "Utilities" help panel
tests/
  test_utils.py   # NEW — resolution + scan logic (mocked KapClient)
  test_cli.py     # MODIFY — CLI tests for the new commands (fake client)
```

Rationale: keeps the thin client uncluttered; composites are independently testable; mirrors the
conceptual thin-vs-composite separation the help surfaces.

---

## 3. Resolution (pure, low-risk)

Resolve a query to one or more entities, over the (per-invocation) `members` / `funds` lists.

**`resolve_company(client, query) -> list[CompanyMatch]`**
- Fetch `client.members()`.
- **Exact ticker first:** rows where `stockCode.upper() == query.upper()`.
- **Else partial name:** rows where `query.upper()` is a substring of `title.upper()`.
- Returns all matches as dicts: `{ "companyId": id, "stockCode": ..., "title": ... }`.

**`resolve_fund(client, query) -> list[FundMatch]`**
- Fetch `client.funds()`.
- **Exact code first:** rows where `fundCode.upper() == query.upper()`.
- **Else partial name:** rows where `query.upper()` is a substring of `fundName.upper()`.
- Returns all matches as dicts: `{ "fundId": ..., "fundCode": ..., "fundName": ..., "fundCompanyId": ... }`.

Fund codes can collide and partial-name can match many, so resolution returns a **list**.

**Single-entity requirement (for composites):** a helper `resolve_one(matches, what)` raises a
`ValueError` when there are **0 matches** ("no <ticker/fund> matching '<query>'") or **>1**
("'<query>' is ambiguous — N matches: <short list>; narrow it or use the exact code"). The
`resolve-*` discovery commands themselves do NOT require uniqueness (they list all matches).

In-memory only; each command invocation fetches `members`/`funds` once (no disk cache — YAGNI).

---

## 4. Backward disclosure scan (the recency correctness)

The thin `disclosures` endpoint scans a bounded **~36,000-index window forward** from `--index`
and caps at **50** (oldest-first within the window). This helper walks backward from
`last-index` to collect an entity's recent disclosures, newest-first.

**`scan_disclosures(client, company_id, limit, disclosure_class=None, *, window=36000, max_windows=30) -> ScanResult`**

```
last = client.last_disclosure_index()
found: dict[int, dict] = {}          # keyed by disclosureIndex (dedupe)
truncated = False
start = max(0, last - window)
windows = 0
while len(found) < limit and windows < max_windows:
    page = client.disclosures(start, disclosure_class=disclosure_class, company_id=company_id)
    if len(page) >= 50:
        truncated = True            # a window hit the 50-cap → may be incomplete
    for d in page:
        found[int(d["disclosureIndex"])] = d
    if start == 0:
        break
    start = max(0, start - window)
    windows += 1
ordered = sorted(found.values(), key=lambda d: int(d["disclosureIndex"]), reverse=True)
return ScanResult(items=ordered[:limit], truncated=truncated, windows=windows)
```

- Windows tile backward `[last-36k, last]`, `[last-72k, last-36k]`, … Dedupe handles overlap.
- `max_windows=30` (~1.08M indices back) bounds runtime; `limit` short-circuits early.
- **Truncation is surfaced, not hidden:** if any window returned 50 rows the command prints a
  one-line stderr note ("some windows hit the 50-result cap; very active filers may be
  incomplete — raise --limit or query a tighter range").

Provenance note: the `disclosures` `companyId` filter echoes the requested id into each row, so
results are trusted as belonging to that company (consistent with the thin command's behavior).

---

## 5. The 6 utility commands (in a "Utilities" help panel)

All accept the common options (`--format/--out/--env/--verbose`) and render via `render.output`.
Each is registered with `rich_help_panel="Utilities"` and a short help labeling it a composite.

| Command | Arg / opts | Orchestration | Output |
|---|---|---|---|
| `resolve-ticker <query>` | ticker or name fragment | `GET /members` → match | list of `{companyId, stockCode, title}` |
| `resolve-fund <query>` | code or name fragment | `GET /funds` → match | list of `{fundId, fundCode, fundName, fundCompanyId}` |
| `ticker-disclosures <query>` | `--limit` (default 20) | resolve_one(company) → `scan_disclosures(companyId)` | list of disclosures, newest-first |
| `ticker-financials <query>` | `--limit` (default 20) | resolve_one(company) → `scan_disclosures(companyId, disclosure_class="FR")` | list of FR disclosures |
| `fund-info <query>` | — | resolve_one(fund) → `GET /fundDetail/{fundId}` | fund detail sections |
| `fund-disclosures <query>` | `--limit` (default 20) | resolve_one(fund) → `scan_disclosures(fundCompanyId)` | list of disclosures, newest-first |

- `--limit` validated `>= 1`.
- Composite resolution errors (`ValueError` from `resolve_one`) surface as the standard clean
  stderr `Error:` + exit 1 (via the existing `_errors` policy).
- ⚠️ **`fund-disclosures` depends on funds filing disclosures under `fundCompanyId`.** This must
  be **verified live during implementation**. If the feed doesn't support it (empty/wrong
  results), drop the command before merge and note it.

---

## 6. Help / separation — utilities MUST read as distinct from the core API

The help must make unmistakably clear that these are convenience utilities, **not** core 1:1
KAP API commands:

- **Separate panel.** New commands carry `rich_help_panel="Utilities"`, so `kap --help` renders a
  distinct panel — titled to read as **"Utilities (convenience — not raw API endpoints)"** —
  below the core **Commands** panel.
- **Distinct visual language.** The core Commands panel shows a single yellow `GET /api/vyk/...`
  endpoint per row. Utilities deliberately do NOT show a single endpoint; their `short_help`
  leads with a `[magenta]composite[/magenta]` tag plus a plain-language summary
  (e.g. `[magenta]composite[/magenta]  ticker → recent disclosures (newest first)`). The magenta
  "composite" tag is the at-a-glance signal that the row is a multi-call utility, not an endpoint.
- **Self-describing detail.** Each command's full `--help` opens by stating it is a composite
  convenience and then lists the endpoints it orchestrates (so the reader knows exactly what runs
  under the hood), plus a worked example — e.g. *"Composite utility (not a single endpoint).
  Resolves the ticker via GET /api/vyk/members, then pages GET /api/vyk/disclosures backward from
  the latest index. Example: kap ticker-disclosures ASELS --limit 20."*
- The top-level app `help`/epilog notes the two groups: core commands = one KAP endpoint each;
  Utilities = multi-call convenience built on them.

---

## 7. Testing

`tests/test_utils.py` (mocked `KapClient`):
- `resolve_company`: exact ticker, case-insensitive, partial-name, not-found (→ []), multiple.
- `resolve_fund`: exact code, partial-name, collision (multiple), not-found.
- `resolve_one`: 0 → ValueError; >1 → ValueError (message lists matches); 1 → the match.
- `scan_disclosures`: collects to limit, dedupes overlapping windows, newest-first ordering,
  respects `max_windows`, passes `disclosure_class` through, sets `truncated` when a window
  returns 50.

`tests/test_cli.py` (fake client): each new command exits 0, calls the right orchestration, and
ambiguous/not-found resolution exits 1 with a message.

Live verification during implementation (real prod, allowlisted IP): `resolve-ticker ASELS`,
`ticker-disclosures ASELS`, `ticker-financials ASELS`, `resolve-fund`, `fund-info`, and
critically `fund-disclosures` (confirm `fundCompanyId` yields real disclosures).

---

## 8. Non-goals

- No disk caching of members/funds (per-invocation fetch is fine at these sizes).
- No fuzzy/ranked search — substring match only.
- No `--ticker`/`--fund` option bolted onto the thin `disclosures` command (kept separate as
  utilities, per the separation goal).
- No attachment-bulk download utility.

---

## 9. Deliverables

- `kap/utils.py` + the 6 commands in `cli.py` under a Utilities panel.
- Passing `test_utils.py` + extended `test_cli.py`.
- Live-verified against prod; `fund-disclosures` confirmed or dropped.
- README + handoff doc updated with a "Utilities" section.
