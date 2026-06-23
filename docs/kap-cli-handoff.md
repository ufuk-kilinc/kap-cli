# KAP CLI — Project Handoff & Status

> **Read this first.** Canonical status + handoff for the `kap-cli` project. Last updated **2026-06-23**.
> Companion docs: design spec `docs/superpowers/specs/2026-06-23-kap-cli-design.md`, implementation plan
> `docs/superpowers/plans/2026-06-23-kap-cli.md`. Upstream API contract (the source of truth this wraps):
> `../tuneup-api/docs/kap-integration.md`.

---

## 0. TL;DR / current state (2026-06-23)

- **What:** a standalone **Python CLI (`kap`)** that exposes **every** endpoint of the KAP Veri Yayın
  Servisi REST API (MKK / Borsa İstanbul) as a subcommand, for the **research team** to call directly.
- **Where:** `C:\dev\source\tuneup\kap-cli` — its own git repo (NOT part of `tuneup-api`). Branch `main`.
- **Status:** **COMPLETE and merged to `main`** (merge commit `a61a307`). 52 tests passing.
  Built brainstorm → spec → plan → 6 TDD tasks (subagent-driven), each spec+quality reviewed, plus a
  final whole-branch Opus review (verdict: **ready to merge**). A background security review finding was
  fixed (atomic `0o600` token-cache write).
- **No git remote yet** — local-only. Push to GitHub when ready (see §9).
- **NOT yet run against the live KAP API.** All logic is unit-tested against the documented contract via
  mocked HTTP (`respx`). A first **live smoke** from an allowlisted IP with a real key is the #1 open task
  (see §8).

---

## 1. Why this exists / scope

The research team needs to hit raw KAP endpoints ad hoc and pull data out (eyeball it, save JSON, export
CSV, download attachment PDFs). The C# `TuneUp.Integrations.Kap` client already encodes the (hard-won,
reverse-engineered) auth + endpoint contract, but it lives inside the .NET app and isn't a tool a
researcher can run. This CLI is a **thin, faithful Python re-implementation of that same contract**,
packaged as an easy command.

**In scope (v1, all built):** one command per the 11 KAP service methods + correctness handling.

**Explicitly OUT of scope (non-goals):** the "smart" business logic that lives in the C# Tuni layer —
no financial-figures XBRL parsing, no FR-cluster discovery, no ticker→companyId resolution, no recency
backward-scan, no PDF *text* extraction (we download the raw PDF; we don't OCR/extract), no DB/persistence/
polling. If a researcher needs those, they're the C# `TuneUp.Domain` assistant tools' job. Keep this thin.

---

## 2. How to install & run (researcher-facing — also in README.md)

```bash
git clone <repo-url> kap-cli          # no remote yet; for now it's the local folder
cd kap-cli
pip install -e .                       # editable: edit the code, changes apply with no reinstall
cp .env.example .env                   # then fill in the API key(s)
```
Requires **Python 3.11+**. `pip install -e ".[dev]"` also installs test deps (pytest, respx).

Configure `.env`:
```bash
KAP_ACTIVE_ENV=test                    # or: production
KAP_TEST_API_KEY=<test-key>
KAP_PROD_API_KEY=<prod-key>
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

- **52 unit tests passing**, pristine output (no warnings). Coverage: config resolution, error-envelope
  parsing (+ empty-message edge), token mint/exp/skew/disk-reuse-across-instances/invalidate, all client
  endpoints incl. raw-auth-header assertion + retry-once over ER004/006/012 + ER005→empty/None + attachment
  envelope strip + connectivity error, render table/json/csv + format inference + ISO-8859-9 decode, CLI
  commands incl. post-command options + errors-on-stderr (not stdout) + clean config-error exit.
- **Manual smokes** (no key set): `kap --help` clean under cp1252; `kap members --format json` →
  clean `Error: Missing API key…` on stderr, exit 1, no traceback; `--verbose` adds a traceback.
- **Reviews:** every task spec+quality reviewed by a fresh subagent (2 fix rounds on the CLI task);
  final Opus whole-branch review → **ready to merge, no Critical/blocking-Important**.

---

## 8. OPEN / next steps (in priority order)

1. **Live smoke against real KAP (BLOCKER for "it actually works").** Needs (a) a real test or prod API
   key in `.env`, and (b) an **allowlisted egress IP** (dev IP `46.197.97.199` was allowlisted for the C#
   work — confirm this machine's egress matches, else open an MKK ticket). Run: `kap last-index`,
   `kap members --format json | head`, a `kap disclosure-detail <id>`, and a `kap download-attachment <id>
   --out test.pdf` (verify the PDF opens). Watch for: real error-envelope shapes, `lastDisclosureIndex`
   JSON key casing, `disclosureDetail` body field actually being `htmlMessages[].tr/en` (the decode target).
2. **Git remote + push** (see §9) — currently local-only.
3. **Distribute to the team** — share the clone+`pip install -e .`+`.env` steps; confirm each researcher
   is on an allowlisted network.
4. **Deferred minors** (none block; sweep if desired): `_extract_pdf` silently returns bytes when no `%PDF`
   marker (add a stderr warning); `last_disclosure_index` parse-guard uses `KapApiError(200,…)` (cosmetic);
   `to_csv([])` → degenerate empty CSV; `decode_disclosure_bodies` mutates input in place; remove unused
   `import pytest` in `tests/test_auth.py`; add tests for `fund_detail`/`member_securities`/
   `blocked_disclosures` path construction + the Rich-table output path.
5. **Possible future (only if asked):** a `--raw`/no-decode flag on `disclosure-detail`; pagination helper
   for `disclosures` (server returns 50 from an index); column selection for table/csv. All YAGNI until
   the team asks.

---

## 9. Pushing to a remote (when ready)

No remote configured. To put it on GitHub:
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
