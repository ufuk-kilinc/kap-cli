# KAP CLI — Design Spec

**Date:** 2026-06-23
**Status:** Approved (design), pending implementation plan
**Repo:** `tuneup/kap-cli/` (standalone git repo, `main` branch)

---

## 1. Purpose

A Python command-line tool that lets the **research team** call every endpoint of the
**KAP Veri Yayın Servisi** REST API (MKK / Borsa İstanbul) directly, with one command per
endpoint. It must be **super easy to use** and **easy for researchers to read and modify**
(they will clone the repo and edit code).

This is a thin, faithful wrapper over the official MKK feed. It is **not** a re-implementation
of the higher-level "smart" logic that lives in the C# Tuni layer (financial-figures XBRL
parsing, FR-cluster discovery, RAG corpus, recency backward-scan, etc.). Those are explicitly
out of scope for v1.

The endpoint surface and auth contract are taken from the existing, live-verified C# client:
`tuneup-api/docs/kap-integration.md` and `tuneup-api/TuneUp.Integrations.Kap/IKapApiHttpClient.cs`.

---

## 2. Non-goals (v1)

- No financial-figures / XBRL parsing (`KapFinancialReportParser` parity).
- No FR-cluster discovery, recency backward-scan, or ticker→companyId resolution helpers.
- No persistence / DB / polling ingestion loop.
- No PDF **text extraction** (we download the raw PDF; we do not run PdfPig-equivalent OCR/extraction).
- No publishing to PyPI — distribution is clone + editable install.

---

## 3. Users & distribution

- **Audience:** internal research team. Mixed Python familiarity; must be able to read and edit code.
- **Distribution:** `git clone` the repo, then an **editable install** —
  `pip install -e .` (or `uv sync`) — which exposes a `kap` console command.
  Source edits take effect immediately, no reinstall.
- **Run:** `kap <command> [options]` from anywhere once installed.

---

## 4. Tech stack

| Concern | Choice | Why |
|---|---|---|
| CLI framework | **Typer** (on Click) | Type-hint-driven commands, auto `--help`, minimal boilerplate, easy to read/extend. |
| Terminal tables | **Rich** | Readable tables/output in the console. |
| HTTP | **httpx** (sync) | Modern client; sync is sufficient for a CLI. |
| Config | **pydantic-settings** | Typed config loaded from `.env`. |
| Tests | **pytest** + httpx mocking | Unit-test auth, client, render without hitting the live API. |
| Python | **3.11+** | Modern typing, `tomllib`, etc. |

Alternatives considered: Click+requests+tabulate (more boilerplate, no upside); argparse+stdlib
(zero deps but worst ergonomics — fights the "super easy" goal). Typer chosen.

---

## 5. Module layout

Small, single-purpose files:

```
kap-cli/
  pyproject.toml            # packaging; console_scripts: kap = kap.cli:app
  .env.example              # config template (committed)
  .env                      # real secrets (GITIGNORED)
  .gitignore
  README.md                 # install + usage + auth/IP-allowlist notes
  kap/
    __init__.py
    __main__.py             # python -m kap entry
    config.py               # pydantic-settings Settings from .env
    auth.py                 # token provider (mint, cache, refresh)
    client.py               # KapClient — one method per endpoint
    render.py               # output: table / json / csv; file or stdout
    cli.py                  # Typer app: 11 commands + global options
    errors.py               # KapApiError + friendly messages
  docs/
    superpowers/specs/2026-06-23-kap-cli-design.md   # this doc
  tests/
    test_auth.py
    test_client.py
    test_render.py
```

### 5.1 `config.py`
`pydantic-settings` `Settings`:
- `active_env`: `"test" | "production"` (default from `.env`; overridable by `--env`).
- Per-env: `test_base_url`, `test_api_key`, `prod_base_url`, `prod_api_key`.
- `token_refresh_skew_seconds` (default 60).
- Resolves `base_url` + `api_key` for the active env. Clear error if the active env's key is missing.

### 5.2 `auth.py` — token provider
- Mints JWT: `GET {base_url}/auth/generateToken?apiKey=<key>` → `{ "token": "<JWT>" }`.
- Sends token in `Authorization` header **RAW — no `Bearer` prefix** (Bearer → ER012).
- Parses the JWT `exp` claim; treats the token as expired `token_refresh_skew_seconds` early.
- **On-disk token cache** at `~/.kap/token-<env>.json` (mode 0600). Critical: each CLI
  invocation is a fresh process, so an in-memory cache alone would re-mint on every call.
  Cache stores token + expiry; reused across invocations until near expiry.
- Mint call uses a plain httpx client (no auth) to avoid recursion.

### 5.3 `client.py` — `KapClient`
- One method per endpoint (see §6). All service paths under `/api/vyk/`.
- Attaches the cached token; on a token error (ER004/ER006/ER012) invalidates cache, re-mints,
  retries **once**.
- `ER005` ("not found") → empty list / `None` (matches C# behavior).
- Other ER codes (ER001/002/003) → raise `KapApiError` with the code + message.
- **`download_attachment`**: response Content-Type lies `application/pdf` but the body is a
  **Java-serialized `byte[]` envelope** (`0xAC 0xED…`, real `%PDF` at ~offset 27). Strip to the
  `%PDF` marker before returning bytes.
- **TCP connect timeout** → friendly hint: likely not on an allowlisted IP / VPN changing egress
  (MKK silently drops non-allowlisted IPs; contact `kapdestek@mkk.com.tr`).

### 5.4 `render.py` — output
- Formats: `table` (Rich), `json`, `csv`.
- Selection: explicit `--format/-f`, else inferred from `--out` extension (`.json`/`.csv`),
  else default `table` to terminal.
- Lists of flat records → table/csv rows.
- Scalars (e.g. `last-index`) → plain print.
- Deeply-nested responses (`disclosure-detail`, `fund-detail`) → **JSON by default** (not
  table-able); `--format table` shows top-level fields only.
- **Decodes base64 ISO-8859-9 disclosure bodies** (`htmlMessages[].tr/en`) into readable text
  when rendering detail, so output is human-readable rather than base64 blobs.
- `--out PATH` writes to file; otherwise stdout.

### 5.5 `cli.py` — Typer app
Global options (apply to all commands): `--env [test|production]`, `--format/-f [table|json|csv]`,
`--out/-o PATH`, `--verbose`.

---

## 6. Commands (1:1 with the 11 endpoints)

| Command | Endpoint | Args / options | Output |
|---|---|---|---|
| `last-index` | `GET /lastDisclosureIndex` | — | scalar |
| `disclosures` | `GET /disclosures` | `--index` (req), `--type`, `--class`, `--company-id` | list |
| `disclosure-detail <index>` | `GET /disclosureDetail/{id}` | `--file-type [data\|html]` (default data), `--sub-report` | nested (JSON), bodies decoded |
| `download-attachment <attachment-id>` | `GET /downloadAttachment/{id}` | `--out PATH` (default `<id>.pdf`) | PDF file (envelope-unwrapped) |
| `members` | `GET /members` | — | list (~1047 on test) |
| `funds` | `GET /funds` | — | list (~2074 on test) |
| `fund-detail <fund-id>` | `GET /fundDetail/{id}` | — | nested (JSON) |
| `member-securities` | `GET /memberSecurities` | — | list (ISIN-level) |
| `blocked-disclosures` | `GET /blockedDisclosures` | — | list |
| `ca-event-status <ref-ids…>` | `GET /caEventStatus?processRefId=…` | one or more ref ids | list |
| `raw <path>` | any relative path | `--query k=v` (repeatable) | raw JSON probe |

`raw` wraps the C# `GetRawAsync` exploration probe — useful for researchers inspecting
un-modeled responses.

---

## 7. Auth & environment facts (from the C# integration)

- **Token exchange**, not a static key header. Token sent **raw** in `Authorization`.
- Token TTL: **prod = 24h**, **test ≈ 104 days**.
- Hosts: test `https://vykapipreprod.mkk.com.tr`, prod `https://kapdatafeed.kap.org.tr`.
- All services under `/api/vyk/`; `generateToken` under `/auth/`.
- **IP-allowlisted by MKK** — non-allowlisted IPs are silently dropped (TCP timeout, not 401).
  Researchers must run from an allowlisted network/egress IP.
- API keys are **secrets** — `.env` is gitignored; `.env.example` documents the keys.

---

## 8. Testing

pytest with mocked httpx (no live API in CI):
- `test_auth.py`: token mint, raw-Authorization header (no Bearer), `exp` parsing + skew,
  disk cache write/reuse/expiry.
- `test_client.py`: per-endpoint URL/params, retry-once on token error, ER005→empty/None,
  other ER→raise, `download_attachment` envelope unwrap to `%PDF`.
- `test_render.py`: table/json/csv rendering, format inference from `--out` extension,
  base64 ISO-8859-9 body decode, scalar vs list vs nested handling.

---

## 9. Deliverables

- Working `kap` CLI with all 11 commands.
- `.env.example`, `.gitignore`, `README.md` (install, usage examples, auth + IP-allowlist notes).
- Passing pytest suite.
- Committed to the new `kap-cli` git repo.
