# KAP CLI — Project Handoff & Status

> **Read this first.** Canonical status + handoff for the `kap-cli` project. Last updated **2026-06-24**.
> Companion docs: design spec `docs/superpowers/specs/2026-06-23-kap-cli-design.md`, implementation plan
> `docs/superpowers/plans/2026-06-23-kap-cli.md`. Upstream API contract (the source of truth this wraps):
> `../tuneup-api/docs/kap-integration.md`.

---

## 0. TL;DR / current state (2026-06-23)

- **What:** a standalone **Python CLI (`kap`)** that exposes **every** endpoint of the KAP Veri Yayın
  Servisi REST API (MKK / Borsa İstanbul) as a subcommand, for the **research team** to call directly.
- **Where:** `C:\dev\source\tuneup\kap-cli` — its own git repo (NOT part of `tuneup-api`). Branch `main`.
- **Status:** **COMPLETE, merged to `main`, pushed to origin.** 76 tests passing.
  Built brainstorm → spec → plan → 6 TDD tasks (subagent-driven), each spec+quality reviewed, plus a
  final whole-branch Opus review. A background security review finding was fixed (atomic `0o600`
  token-cache write). Then a full **A+ hardening pass** (commit `1ed289e`): `KapResponseError` for
  2xx-but-malformed, guarded JSON decode, non-PDF download reject, single `_errors` policy (DRY + clean
  `OSError`), honest types (`JsonObj`/`RawResponse`/`TokenCache`/`Literal`s), Unix CSV, fail-fast
  `--format`/`--file-type`, strict `raw --query` — independent Opus verification verdict: **A+**.
- **Remote:** private `https://github.com/ufuk-kilinc/kap-cli` (`main` == origin).
- **LIVE-VERIFIED against PROD** (2026-06-24, allowlisted IP, real key in `~/.kap/.env`): all 11 core
  commands + the 6 utilities exercised against the real feed (e.g. `last-index` → 1619964, members 1124,
  funds 4452; `ticker-disclosures ASELS`, `fund-disclosures BON` return real data). The earlier "live
  smoke pending" item is DONE.

**Utilities layer (2026-06-24):** `kap/utils.py` adds composite commands (resolve-ticker/fund,
ticker-disclosures, ticker-financials, fund-info, fund-disclosures) shown in a separate
"Utilities" help panel. They resolve a ticker/fund (over members/funds, exact-code-then-partial-name)
and run the recency backward-scan. KapClient stays the thin 1:1 wrapper. fund-disclosures returns
disclosures filed under the fund's management company (fundCompanyId), covering all funds managed by
that company — this is how KAP files them, confirmed by live verification.
fund-portfolio-report resolves a fund → scans its management company's FON disclosures (forward-paginated
to beat the 50-row cap) → matches subject "Portföy Dağılım Raporu" + behalfFundCode; default latest,
--from/--to (YYYY-MM by report period) for a range.

---

## 1. Why this exists / scope

The research team needs to hit raw KAP endpoints ad hoc and pull data out (eyeball it, save JSON, export
CSV, download attachment PDFs). The C# `TuneUp.Integrations.Kap` client already encodes the (hard-won,
reverse-engineered) auth + endpoint contract, but it lives inside the .NET app and isn't a tool a
researcher can run. This CLI is a **thin, faithful Python re-implementation of that same contract**,
packaged as an easy command.

**In scope (v1, all built):** one command per the 11 KAP service methods + correctness handling.

**Utilities layer (added 2026-06-24, opt-in extension):** ticker→companyId / fund resolution and the
recency backward-scan ARE now provided — but as a deliberately *separate*, clearly-labeled composite
layer (`kap/utils.py` + a "Utilities" help panel), distinct from the thin 1:1 commands. See §0 + §6.

**Still OUT of scope (non-goals):** the heavier "smart" logic in the C# Tuni layer — financial-figures
XBRL parsing, FR-cluster discovery, PDF *text* extraction (we download the raw PDF; we don't OCR/extract),
DB/persistence/polling. If a researcher needs those, they're the C# `TuneUp.Domain` assistant tools' job.

---

## 2. How to install & run (researcher-facing — also in README.md)

```bash
git clone https://github.com/ufuk-kilinc/kap-cli.git
cd kap-cli
pip install -e .                       # editable: edit the code, changes apply with no reinstall
mkdir %USERPROFILE%\.kap & copy .env.example %USERPROFILE%\.kap\.env   # then fill in the key
```
Requires **Python 3.11+**. `pip install -e ".[dev]"` also installs test deps (pytest, respx).
To run `kap` from any directory, add the user Scripts dir to PATH
(`%USERPROFILE%\AppData\Roaming\Python\Python3xx\Scripts` on Windows).

Configure **`~/.kap/.env`** (Windows: `%USERPROFILE%\.kap\.env`) — read from ANY directory; a cwd
`.env` is deliberately NOT read (security: an untrusted dir mustn't redirect the API host). Real env
vars override.
```bash
KAP_ACTIVE_ENV=production               # or: test
KAP_PROD_API_KEY=<prod-key>
KAP_TEST_API_KEY=<test-key>
```

Run:
```bash
kap last-index
kap members
kap members --format json
kap members --out members.csv          # format inferred from extension
kap disclosures --index 1000000 --class FR --company-id 42
kap disclosure-detail 1234567          # base64 bodies decoded to readable text
kap download-attachment <attachment-id> --out report.pdf
kap fund-detail 5900
kap ca-event-status 111 222
kap raw api/vyk/members --query foo=bar
```

**Common options go AFTER the command** (`kap members --format json`, not `kap --format json members`):
`--env test|production`, `-f/--format table|json|csv`, `-o/--out PATH`, `-v/--verbose` (adds a traceback
on error). `download-attachment` takes `--out`/`--env`/`--verbose` (no `--format` — it's binary).

---

## 3. Architecture / module map

Layered, small single-purpose files under `kap/`:

| File | Responsibility |
|---|---|
| `config.py` | `pydantic-settings` `Settings` (env prefix `KAP_`, reads `.env`) → `ResolvedConfig(env, base_url, api_key, token_refresh_skew_seconds)`. `load_config(env_override)`. Raises `ValueError` for missing key / unknown env. |
| `errors.py` | `KapError` (base), `KapApiError(status_code, code, message)` with `from_body()` + `is_token_error`/`is_not_found`, `KapConnectivityError`. |
| `auth.py` | `TokenProvider` — mints JWT, parses `exp` (no signature check), **disk-caches** token at `~/.kap/token-<env>.json`, re-mints within skew. `parse_jwt_expiry()`. |
| `client.py` | `KapClient` — one method per endpoint, `_send`/`_get`/`_get_list` share auth+retry+connectivity. Attachment `%PDF` unwrap. |
| `render.py` | `output(data, fmt, out)`; `resolve_format`, `to_json`, `to_csv`, `decode_disclosure_bodies` (base64→ISO-8859-9, strip `<style>`/`<script>`). |
| `cli.py` | Typer app; 11 commands; shared `Annotated` option aliases; `_make_client(env)`; `_run`/`_save_bytes` lifecycle helpers; forces UTF-8 stdout/stderr at import. |
| `__main__.py` | `python -m kap` entry. |

Tests mirror modules in `tests/` (pytest + `respx` for HTTP mocking + Typer `CliRunner`).
**No JS/other stack** — pure Python.

Data flow: `cli` → `load_config` → `KapClient(config)` (lazily builds `TokenProvider`) → endpoint method
→ `render.output`. Errors (`KapError` or `ValueError`) → red message on **stderr**, exit 1, traceback only
with `-v`.

---

## 4. The 11 commands ↔ endpoints

| Command | Endpoint | Notes |
|---|---|---|
| `last-index` | `GET /api/vyk/lastDisclosureIndex` | scalar; polling cursor |
| `disclosures` | `GET /api/vyk/disclosures` | `--index` required; `--type/--class/--company-id` |
| `disclosure-detail <index>` | `GET /api/vyk/disclosureDetail/{id}` | `--file-type data\|html`, `--sub-report`; bodies decoded |
| `download-attachment <id>` | `GET /api/vyk/downloadAttachment/{id}` | writes PDF; Java-envelope unwrapped |
| `members` | `GET /api/vyk/members` | ~1047 on test |
| `funds` | `GET /api/vyk/funds` | ~2074 on test |
| `fund-detail <id>` | `GET /api/vyk/fundDetail/{id}` | polymorphic sections (raw JSON) |
| `member-securities` | `GET /api/vyk/memberSecurities` | ISIN-level |
| `blocked-disclosures` | `GET /api/vyk/blockedDisclosures` | |
| `ca-event-status <ref-ids…>` | `GET /api/vyk/caEventStatus?processRefId=…` | variadic ids |
| `raw <path>` | any relative path | `--query k=v` repeatable; diagnostic passthrough (no retry/no error-map) |

---

## 5. Auth & upstream contract (reverse-engineered — DO NOT "fix")

Mirrors the C# client. The MKK docs are incomplete/misleading; trust this:

- **Token exchange:** `GET {base}/auth/generateToken?apiKey=<key>` → `{"token":"<JWT>"}`.
- Token sent in `Authorization` header **RAW — NO `Bearer`** (Bearer → `ER012`).
- Token TTL: **prod 24h / test ≈104 days** (parsed from JWT `exp`).
- All service paths under `/api/vyk/`; `generateToken` under `/auth/`.
- **Errors are non-2xx** with a JSON envelope `{"code":"ERxxx","message":"..."}`:
  - `ER005` = not found → mapped to empty list / `None`.
  - `ER004`/`ER006`/`ER012` = token error → invalidate cache, re-mint, retry **once**, then raise.
  - other `ER` → raise `KapApiError`.
- **IP-allowlisted by MKK** — a non-allowlisted source IP is **silently dropped** (TCP timeout, not 401).
  The client turns connect timeout/error into a `KapConnectivityError` with an allowlist hint.
- **`downloadAttachment`** Content-Type lies `application/pdf`; the body is a **Java-serialized `byte[]`
  envelope** (`0xAC 0xED…`, real `%PDF` at ~offset 27). Client strips to the `%PDF` marker.
- Hosts: test `https://vykapipreprod.mkk.com.tr`, prod `https://kapdatafeed.kap.org.tr`.
- API keys are **secrets** → `.env` is gitignored; only `.env.example` is committed. **Contact for
  allowlist/keys:** `kapdestek@mkk.com.tr`.

---

## 6. Decisions & deviations from the plan (intentional, review-approved)

- **Per-command options, not a global callback.** The plan put `--env/--format/--out/--verbose` on a Typer
  `@app.callback()` (which only works *before* the command). That contradicted the README's natural
  `kap members --format json` usage and crashed `--help`. Changed to per-command options via shared
  `Annotated` aliases. ✔ improvement, README+tests consistent.
- **Force UTF-8 stdout/stderr at import** (`cli.py`). The research team is on Windows/Turkish (cp1252);
  without this, `kap --help` and any Turkish data output raise `UnicodeEncodeError`. Reconfigure is guarded.
- **Catch `ValueError` (not just `KapError`)** in the CLI run helpers, so config errors (missing key /
  unknown env) and client input guards exit cleanly with a message instead of a traceback.
- **On-disk token cache** (`auth.py`). Each CLI invocation is a fresh process, so an in-memory cache would
  re-mint on every call. Cache written atomically with `os.open(..., 0o600)` (security-review hardened;
  mode ignored on Windows).
- **`raw` is a deliberate passthrough** — no token retry, no error mapping; returns status/body for
  inspection. Documented in its docstring.

---

## 7. Verification done

- **103 unit tests passing** (incl. the utilities layer: resolution exact/partial/comma-joined-code/
  dedupe/ambiguous + backward-scan ordering/dedupe/truncation/edge), pristine output. Coverage: config
  resolution, error-envelope
  parsing (+ empty-message edge), token mint/exp/skew/disk-reuse-across-instances/invalidate + mint
  failure/non-JSON/no-token, all client endpoints incl. raw-auth-header assertion + retry-once over
  ER004/006/012 + ER005→empty/None + attachment envelope strip + **non-PDF reject** + **non-JSON-2xx
  reject** + path construction (fund_detail/member_securities/blocked) + `file_type` forwarding +
  connectivity error, render table/json/csv + format inference + validation + ISO-8859-9 decode +
  base64-fail→None + Unix CSV, CLI commands incl. post-command options + **errors-on-stderr (proven not
  stdout)** + clean config-error/OSError exit + fail-fast `--format`/`--file-type` + strict `raw --query`.
- **Manual smokes** (no key set): `kap --help` clean under cp1252; `kap members --format json` →
  clean `Error: Missing API key…` on stderr, exit 1, no traceback; `--verbose` adds a traceback.
- **Reviews:** every task spec+quality reviewed by a fresh subagent (2 fix rounds on the CLI task);
  final Opus whole-branch review → **ready to merge, no Critical/blocking-Important**.

---

## 8. OPEN / next steps (in priority order)

1. **Live smoke — DONE (2026-06-24, prod, allowlisted IP).** All commands verified against the real feed.
   **Key data-shape findings from the live run (important):**
   - `disclosure-detail` default `--file-type data` returns `subject`/`summary`/`flatData`/`link`/
     `attachmentUrls` (subject/summary are `{tr,en}` dicts) — there is **NO `htmlMessages`**. The readable
     base64 body the decode targets only appears under **`--file-type html`**. So for readable text use
     `kap disclosure-detail <id> --file-type html`. (Possible follow-up: default detail to `html`, or
     auto-fall-back when the body is absent.)
   - members `id` (companyId) is a **string**; `stockCode` is often **comma-joined** ("AKM, AKMEN") and
     rows can be **exact-duplicated** — the utilities handle both (split + dedupe).
   - `fund-disclosures` works via `fundCompanyId` (management-company scope — all that company's funds).
2. **Distribute to the team** — share the clone+`pip install -e .`+`.env` steps; confirm each researcher
   is on an allowlisted network.
3. **Possible future (only if asked):** a `--raw`/no-decode flag on `disclosure-detail`; pagination helper
   for `disclosures` (server returns 50 from an index); column selection for table/csv. All YAGNI until
   the team asks.

> The review "deferred minors" (non-PDF passthrough, `KapApiError(200,…)`, empty-CSV, base64-fail
> handling, missing path/forwarding tests, etc.) were all **resolved in the A+ hardening pass** (`1ed289e`)
> — see §0. Git remote + push: **done**.

---

## 9. Remote

Already on GitHub (private): `https://github.com/ufuk-kilinc/kap-cli`, `main` == origin. For reference,
the repo was created with:
```bash
cd C:\dev\source\tuneup\kap-cli
gh repo create <org>/kap-cli --private --source . --remote origin --push   # or set-url to an existing repo
```
Then update the clone URL in `README.md` §Install. Ask the user for the org/visibility first.

---

## 10. Git history (branch already merged + deleted)

Merged to `main` via `a61a307` (`--no-ff`). The 11 implementation commits (feature branch
`feat/kap-cli-implementation`, now deleted) in order: scaffold/config `61f9d38`, errors `ef9f27d` +
`998c51c`, auth `0951837` + security `6546fdc`, client `02a8127` + `3695a99`, render `2703d41`,
cli+README `b32287a` + `0d8304f` + `16c5cc9`. SDD progress ledger + per-task briefs/reports/diffs are
under `.superpowers/sdd/` (gitignored scratch).
