# KAP CLI — Project Memory & Handoff

> **Read this first.** This is the canonical, checked-in memory for `kap-cli`: what it is, how to run
> it, the hard-won KAP domain knowledge, the full command reference, the architecture, and the progress
> log. It travels with the repo so anyone who clones it (research team or a future developer) has the
> whole picture. **Last updated 2026-06-24** (`main` @ `b6aace8`).
>
> Companion docs: `README.md` (quickstart), `docs/superpowers/specs|plans/*` (per-feature design/plans),
> and the upstream API contract this wraps: `../tuneup-api/docs/kap-integration.md`.

---

## 0. TL;DR / current status

- **What:** a standalone **Python CLI (`kap`)** giving the **research team** direct, easy access to the
  **KAP Veri Yayın Servisi** REST API (MKK / Borsa İstanbul) — every endpoint as a command, plus a few
  convenience "utilities".
- **Where:** `C:\dev\source\tuneup\kap-cli` — its **own git repo** (NOT part of `tuneup-api`).
- **Remote:** private GitHub `https://github.com/ufuk-kilinc/kap-cli` (`main` == origin).
- **Status:** **COMPLETE, live-verified against PROD, in active use.** 11 core commands + 7 utilities;
  **116 tests passing**; A+/A code-review verdicts across the build. Live-verified with a real key from
  an allowlisted IP (e.g. `last-index` → 1619964; members 1124; funds 4452; `fund-portfolio-report BON`
  → the 2026-04 report).
- **How it was built:** brainstorm → spec → plan → subagent-driven TDD, each task spec+quality reviewed,
  each feature closed by an Opus whole-branch review. Three shipped increments: core CLI (+A+ hardening),
  ticker/fund utilities, fund-portfolio-report.

---

## 1. What this is & who it's for

The research team needs to pull KAP data ad hoc — eyeball it, save JSON/CSV, grab attachment PDFs. The
authoritative auth + endpoint contract already lives in the C# `TuneUp.Integrations.Kap` client, but
that's locked inside the .NET app. **This CLI is a thin, faithful Python re-implementation of that same
contract**, packaged as a command anyone can run.

- **Core commands** = one-to-one with the 11 KAP service endpoints (no business logic).
- **Utilities** = a *separate, clearly-labeled* layer of multi-call conveniences (resolve a ticker/fund,
  recency-correct disclosures, portfolio report). Shown in their own "Utilities" panel in `--help`.

**Out of scope** (lives in the C# Tuni layer, not here): financial-figures XBRL parsing, FR-cluster
discovery, PDF *text* extraction (we download the raw PDF; we don't OCR), DB/persistence/polling.

---

## 2. Install, PATH, configure (research-team quickstart)

```bash
git clone https://github.com/ufuk-kilinc/kap-cli.git
cd kap-cli
pip install -e .                      # editable: edit code, changes apply with no reinstall
mkdir %USERPROFILE%\.kap & copy .env.example %USERPROFILE%\.kap\.env   # then put your key in it
```
Requires **Python 3.11+**. (`pip install -e ".[dev]"` also installs the test deps.)

**Put `kap` on PATH** so it runs from any directory: add the user Scripts dir to your User PATH —
`%USERPROFILE%\AppData\Roaming\Python\Python3xx\Scripts` (Windows). New terminals pick it up. Until then,
`python -m kap ...` always works.

**Configure `~/.kap/.env`** (Windows: `%USERPROFILE%\.kap\.env`) — read from ANY directory:
```bash
KAP_ACTIVE_ENV=production              # or: test
KAP_PROD_API_KEY=<prod-key>
KAP_TEST_API_KEY=<test-key>
```
- ⚠️ **A `.env` in the current directory is deliberately NOT read** (security: an untrusted folder could
  ship a `.env` that redirects `KAP_*_BASE_URL` and exfiltrate your key). Config = `~/.kap/.env` + real
  env vars (which override). Override per-call with `--env test|production`.
- ⚠️ **You must be on an allowlisted egress IP** (see §5) or calls hang then fail with a connectivity hint.

**Common options** go AFTER the command (e.g. `kap members --format json`): `-f/--format table|json|csv`,
`-o/--out PATH` (format inferred from extension), `--env`, `-v/--verbose` (traceback on error).

---

## 3. Core commands (11) — one KAP endpoint each

| Command | Endpoint | Notes |
|---|---|---|
| `last-index` | `GET /api/vyk/lastDisclosureIndex` | the newest disclosure id market-wide; a polling cursor |
| `disclosures --index N` | `GET /api/vyk/disclosures` | 50 from N onward; `--type/--class/--company-id` filters |
| `disclosure-detail <index>` | `GET /api/vyk/disclosureDetail/{id}` | `--file-type data|html` (**html** for the readable body), `--sub-report` |
| `download-attachment <id>` | `GET /api/vyk/downloadAttachment/{id}` | writes a PDF; Java-envelope auto-unwrapped |
| `members` | `GET /api/vyk/members` | all companies (id, title, stockCode, …) |
| `funds` | `GET /api/vyk/funds` | all funds (fundId, fundCode, fundName, fundCompanyId, …) |
| `fund-detail <id>` | `GET /api/vyk/fundDetail/{id}` | general-info sections (polymorphic) |
| `member-securities` | `GET /api/vyk/memberSecurities` | ISIN-level securities |
| `blocked-disclosures` | `GET /api/vyk/blockedDisclosures` | disclosures blocked from access |
| `ca-event-status <ref-ids…>` | `GET /api/vyk/caEventStatus?processRefId=…` | corporate-action process status |
| `raw <path>` | any relative path | diagnostic passthrough (no retry / no error-mapping); `--query k=v` |

`kap --help` shows these in a **Commands** panel with the endpoint (yellow) on each line; each
`kap <cmd> --help` states the endpoint, the inputs, and an example.

---

## 4. Utilities (7) — composites, NOT raw endpoints

Shown in a separate **"Utilities (convenience — not raw API endpoints)"** panel with a magenta
`composite` tag. Each resolves a ticker/fund and orchestrates several calls.

| Utility | What it does | Orchestrates |
|---|---|---|
| `resolve-ticker <q>` | ticker or company-name → companyId + title | `members` |
| `resolve-fund <q>` | fund code or name → fundId + name | `funds` |
| `ticker-disclosures <q> [--limit N]` | a ticker's recent disclosures, newest-first | resolve + paged `disclosures` |
| `ticker-financials <q> [--limit N]` | a ticker's recent FR (financial-report) filings | resolve + paged `disclosures?disclosureClass=FR` |
| `fund-info <q>` | a fund's general-info sections | resolve + `fundDetail/{id}` |
| `fund-disclosures <q> [--limit N]` | a fund's **management-company** disclosures (covers all its funds) | resolve + paged `disclosures` (by `fundCompanyId`) |
| `fund-portfolio-report <q> [--from YYYY-MM --to YYYY-MM]` | a fund's **Portföy Dağılım Raporu** (latest, or all in a period range) | resolve + forward-paginated FON scan + `disclosureDetail` |

Resolution: exact code (case-insensitive; handles comma-joined codes like `"AKM, AKMEN"`) first, else
partial-name substring; results deduped. For commands needing one entity, an ambiguous/not-found query
exits 1 with a clear message.

**Worked recipes**
- Recent disclosures for a ticker: `kap ticker-disclosures ASELS --limit 20`
- A fund's latest portfolio allocation: `kap fund-portfolio-report BON`
- A fund's allocations over a range: `kap fund-portfolio-report BON --from 2026-01 --to 2026-06`

---

## 5. KAP domain knowledge & gotchas (the high-value memory)

These were reverse-engineered/verified live. Trust them over the MKK docs (which are incomplete/misleading).

**Auth**
- Token exchange, not a static key: `GET {base}/auth/generateToken?apiKey=<key>` → `{"token":"<JWT>"}`.
- Send the token in `Authorization` **RAW — no `Bearer`** (Bearer → error `ER012`).
- Token TTL: **prod 24h / test ≈104 days** (read from the JWT `exp`). The CLI **disk-caches** it at
  `~/.kap/token-<env>.json` (atomic, 0600) so repeated invocations reuse it.
- Hosts: test `https://vykapipreprod.mkk.com.tr`, prod `https://kapdatafeed.kap.org.tr`; services under
  `/api/vyk/`, `generateToken` under `/auth/`.

**Errors**
- Errors are **non-2xx** with a JSON envelope `{"code":"ERxxx","message":"..."}`. `ER005` = not found
  (→ empty/None); `ER004/006/012` = token issues (the client invalidates + retries once); others raise.

**IP allowlist** ⚠️
- MKK **IP-allowlists** the API. A non-allowlisted source IP isn't rejected with 401 — packets are
  silently dropped → **TCP timeout**. The CLI turns that into a clear connectivity hint. If calls hang,
  suspect a VPN/egress change or that the IP isn't allowlisted (ticket: `kapdestek@mkk.com.tr`).

**Data shapes & traps (learned live)**
- `members` `id` (the companyId) is a **string** ("866"). `stockCode` is often **comma-joined**
  ("AKM, AKMEN"), and member rows can be **exact-duplicated** — the resolvers split + dedupe.
- `disclosures` LIST rows expose only `disclosureIndex/disclosureType/disclosureClass/title(=sender)/
  companyId` — **NOT** the subject or which fund. To know what a disclosure *is*, you must open its detail.
- `disclosures(index, company_id)` returns **≤50 rows, OLDEST-first, within a ~36k forward window**. For
  a heavy filer (e.g. a fund management company) a single call near `last-index` returns the *oldest* 50
  of that window and **misses the newest** → to get recent items, **forward-paginate** (step the start to
  `max(returned index)+1`) or step back in windows. This is why the utilities exist.
- `disclosure-detail` default `--file-type data` returns `subject`/`summary` (as `{tr,en}` dicts),
  `flatData`, `link`, `attachmentUrls`, `presentation` — **no `htmlMessages`**. The readable base64 body
  only appears under **`--file-type html`** (decoded ISO-8859-9). FON html bodies can mojibake; the
  structured `presentation` (data form) is the clean source for fund reports.
- `downloadAttachment` lies `Content-Type: application/pdf` but the body is a **Java-serialized `byte[]`
  envelope** (`0xAC 0xED…`, real `%PDF` at ~offset 27). The client strips to the `%PDF` marker; a body
  with no `%PDF` is rejected (not silently saved).
- **Fund disclosures** (incl. the Portföy Dağılım Raporu) are filed under the fund's **management
  company** (`fundCompanyId`), not the fund itself — one per fund per period. The PDR specifically is a
  `disclosureType=FON` disclosure with `subject.tr == "Portföy Dağılım Raporu"` and a `behalfFundCode`
  naming the fund; its content is the detail's `presentation`. Report period (e.g. "2026 / 3.Ay") is in
  `summary.tr`.
- Numeric ids appear both quoted and unquoted across services — treat ids as strings / parse defensively.

---

## 6. Architecture / module map

Layered, small single-purpose files under `kap/`. KapClient is the only thing that talks to the API;
utilities orchestrate it; the CLI is a thin presentation layer.

| File | Responsibility |
|---|---|
| `config.py` | `pydantic-settings` `Settings` (prefix `KAP_`, reads `~/.kap/.env`) → `ResolvedConfig`. `load_config(env)`. `ValueError` on missing key / unknown env. |
| `errors.py` | `KapError` base; `KapApiError` (non-2xx envelope, `is_token_error`/`is_not_found`, `from_body`); `KapResponseError` (2xx-but-malformed); `KapConnectivityError`. |
| `auth.py` | `TokenProvider` — mints JWT, parses `exp` (no sig check), **disk-caches** atomically (0600), re-mints within skew. `parse_jwt_expiry`. |
| `client.py` | `KapClient` — one method per endpoint; `_send`/`_get`/`_get_list`/`_json` share raw-token auth + retry-once + connectivity + JSON-guard; `%PDF` unwrap; `RawResponse`/`JsonObj` types. **Thin 1:1 wrapper — keep it that way.** |
| `render.py` | `output(data, fmt, out)` (table/json/csv, format inference + validation), `to_json`/`to_csv`, `decode_disclosure_bodies` (base64→ISO-8859-9, strip style/script). |
| `utils.py` | **Composite layer**: `resolve_company`/`resolve_fund`/`resolve_one`, `scan_disclosures` (backward window scan, truncation flag), `_enumerate_window` (forward pagination, beats the 50-cap), `find_fund_portfolio_reports` + `parse_report_period`. |
| `cli.py` | Typer app; 11 core commands + 7 utilities; shared `Annotated` option aliases; `_make_client(env)`; `_errors` context-manager (one error policy: clean stderr + exit 1, traceback only with `-v`); forces UTF-8 stdout/stderr at import (Windows/cp1252-safe). |
| `__main__.py` | `python -m kap` entry. |

Pure Python; no JS/other stack. Tests mirror modules in `tests/` (pytest + `respx` HTTP mocking + Typer
`CliRunner`). Errors (`KapError`/`ValueError`/`OSError`) → red message on **stderr**, exit 1.

---

## 7. Testing

`python -m pytest` (install dev deps: `pip install -e ".[dev]"`). **116 tests**, pristine output. They
assert real behavior at real boundaries — HTTP via respx, disk via tmp_path, CLI via CliRunner — not
mock-theater. Covered: auth (mint/exp/skew/disk-reuse/retry), all endpoints (raw-auth-header, ER005→
empty, non-PDF reject, envelope strip), render (table/json/csv/decode/validation), the utilities
(resolution incl. comma-codes/dedupe, backward scan, forward-pagination past the 50-cap, period parse,
PDR latest/range), and CLI wiring (errors-on-stderr, fail-fast validation, exit codes).

There are **no JS unit tests** (pure-Python project). Live-verify network behavior manually from an
allowlisted IP.

---

## 8. Progress log

- **2026-06-23 — Core CLI shipped.** 11 commands, token auth + disk cache, attachment unwrap,
  table/json/csv, README; subagent TDD + final review. Then an **A+ hardening pass** (`1ed289e`):
  `KapResponseError` + guarded JSON, non-PDF reject, single `_errors` policy, honest types/`Literal`s,
  Unix CSV, fail-fast `--format`/`--file-type`, strict `raw --query`. Pushed to a new private GitHub repo.
- **2026-06-24 — Live-verified against PROD** (allowlisted IP, real key). Config moved to `~/.kap/.env`
  (cwd `.env` dropped for security); `kap` put on User PATH; help redesigned (3-col Commands panel,
  width-aware, colored).
- **2026-06-24 — Utilities layer** (`8a75e8e`): resolve-ticker/fund, ticker-disclosures,
  ticker-financials, fund-info, fund-disclosures — separate "Utilities" panel; live-shape bugs
  (comma-codes, duplicate members) caught by review and fixed.
- **2026-06-24 — `fund-portfolio-report`** (`b6aace8`): a fund's Portföy Dağılım Raporu via forward-
  paginated FON scan (so "latest" is the true latest, not a stale window) + subject/behalfFundCode match;
  default latest, `--from/--to` period range; explanatory `--help`.

Per-feature specs/plans + reviews are under `docs/superpowers/`. SDD scratch (briefs/reports/diffs) is in
`.superpowers/` (gitignored).

---

## 9. Open items / future (only if asked)

- **Distribute to the team:** share §2; confirm each researcher is on an allowlisted network.
- **PDF research-team guide** (a printable how-to) — drafted-but-not-built; ask if wanted.
- **Possible enhancements (YAGNI until requested):** make `disclosure-detail` default to `--file-type
  html` (or auto-fall-back when the body is absent); flatten the `presentation` allocation structure into
  tidy rows; a `--limit`/pagination helper on raw `disclosures`; fix the FON html-body mojibake (likely a
  UTF-8-vs-ISO-8859-9 mismatch for fund bodies).

---

## 10. How to extend

- **Add a core command** (1:1 with a new endpoint): add the typed method to `KapClient`, register the URL
  in `_ENDPOINTS`, add a `@app.command(...)` using `_help(name, summary)` for the yellow-endpoint short
  help + a docstring (endpoint + inputs + example), route through `_run`/`output`. Add client + CLI tests.
- **Add a utility** (composite): put orchestration in `utils.py` (take a `KapClient`, return a small
  dataclass/dicts), add a `@app.command(rich_help_panel=_UTIL_PANEL, short_help="[magenta]composite[/magenta] …")`
  whose docstring opens "Composite utility (not a single endpoint)." and lists the endpoints it calls.
  Keep `KapClient` thin — do NOT add composite logic to it.
- Always TDD; keep help honest about what each command/utility actually does.

---

## 11. Contacts & references

- **MKK / KAP support** (IP allowlist, access, spec): `kapdestek@mkk.com.tr`.
- **Upstream contract** (authoritative source this mirrors): `../tuneup-api/docs/kap-integration.md`.
- **Repo:** `https://github.com/ufuk-kilinc/kap-cli` (private).
