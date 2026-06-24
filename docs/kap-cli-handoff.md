# KAP CLI — Coding-Agent Handoff & Project Memory

> **Read this first — you are (probably) a coding agent.** This is the canonical, checked-in technical
> memory for `kap-cli`, written **for Claude Code (or any coding agent) extending this project**. The
> explicit goal of this starter project: *a researcher clones it, opens it in Claude Code, and the agent —
> primed by this doc — builds new utilities for their research with zero guesswork.* So this doc is
> deliberately deep and precise: exact signatures, exact data shapes, exact extension recipes that match
> the existing patterns one-for-one.
>
> **Audience split:** THIS doc is for developers/agents. A separate, gentler human guide for
> non-developers is planned at `docs/getting-started.*` (not yet written — see §13 Open items); do not
> assume it exists. `README.md` is the user-facing quickstart.
>
> **Last updated 2026-06-24** — `main` @ `66b695e`. **134 tests passing** (`python -m pytest`).
> **11 core commands + 8 utilities.**
>
> Companion material in-repo: `README.md` (quickstart), `docs/superpowers/specs/*` + `docs/superpowers/plans/*`
> (per-feature design/plans — context only). Upstream API contract this mirrors:
> `../tuneup-api/docs/kap-integration.md` (the authoritative C# `TuneUp.Integrations.Kap` reverse-engineering).

---

## 0. TL;DR / current status

- **What:** a standalone **Python 3.11+ CLI (`kap`)** giving the **research team** direct access to the
  **KAP Veri Yayın Servisi** REST API (MKK / Borsa İstanbul) — every endpoint as a command, plus a layer
  of multi-call convenience "utilities".
- **Where:** `C:\dev\source\tuneup\kap-cli` — its **own git repo** (NOT part of `tuneup-api`).
- **Remote:** private GitHub `https://github.com/ufuk-kilinc/kap-cli` (`main` == origin).
- **Status:** **COMPLETE, live-verified against PROD, in active use.** 11 core commands + 8 utilities;
  **134 tests passing**; A+/A code-review verdicts across the build. Live numbers seen from an allowlisted
  IP: `last-index` → ~1.62M; members ~1124; funds ~4452; `fund-portfolio-report BON` → the latest PDR.
- **Tech:** `typer` (CLI) + `rich` (rendering) + `httpx` (HTTP) + `pydantic-settings` (config). Tests:
  `pytest` + `respx` (HTTP mocking) + Typer `CliRunner`. Pure Python; no JS/other stack; no DB.
- **How it was built:** brainstorm → spec → plan → subagent-driven TDD, every task spec+quality reviewed,
  every feature closed by an Opus whole-branch review. Five shipped increments: core CLI (+A+ hardening),
  ticker/fund utilities, fund-portfolio-report, fund-portfolio-pdf, `--out` directory auto-naming.

**The golden rule for extending this project:** *`KapClient` stays a thin 1:1 mirror of KAP endpoints;
all multi-call/business logic lives in `kap/utils.py`; the CLI (`kap/cli.py`) is a thin presentation layer
that wires arguments → client/util call → `render.output`.* See §7 for copy-pasteable recipes.

---

## 1. Purpose & audience

The research team needs to pull KAP data ad hoc — eyeball it, save JSON/CSV, grab attachment PDFs. The
authoritative auth + endpoint contract already lives in the C# `TuneUp.Integrations.Kap` client, but that's
locked inside the .NET app. **This CLI is a thin, faithful Python re-implementation of that same contract**,
packaged as a command anyone can run, and structured so an agent can keep growing it.

- **Core commands** = one-to-one with the 11 KAP service endpoints (no business logic).
- **Utilities** = a *separate, clearly-labeled* layer of multi-call conveniences (resolve a ticker/fund,
  recency-correct disclosures, portfolio report, PDF download). Shown in their own "Utilities" panel in `--help`.

**Out of scope** (lives in the C# Tuni layer, not here): financial-figures XBRL parsing, FR-cluster
discovery, PDF *text* extraction (we download the raw PDF; we don't OCR), DB/persistence/polling.

---

## 2. Install, PATH, configure

```bash
git clone https://github.com/ufuk-kilinc/kap-cli.git
cd kap-cli
pip install -e .                      # editable: edit code, changes apply with no reinstall
pip install -e ".[dev]"               # also installs pytest + respx (for running tests)
mkdir %USERPROFILE%\.kap & copy .env.example %USERPROFILE%\.kap\.env   # then put your key in it
# macOS/Linux:  mkdir -p ~/.kap && cp .env.example ~/.kap/.env
```
Requires **Python 3.11+** (uses `X | Y` unions, `list[...]` generics, `from __future__ import annotations`).

**Put `kap` on PATH** so it runs from any directory: add the user Scripts dir to your User PATH —
`%USERPROFILE%\AppData\Roaming\Python\Python3xx\Scripts` (Windows). Until then, `python -m kap ...` always
works (`kap/__main__.py` just calls `app()`).

**Configure `~/.kap/.env`** (Windows: `%USERPROFILE%\.kap\.env`) — read from ANY directory:
```bash
KAP_ACTIVE_ENV=production              # or: test
KAP_PROD_API_KEY=<prod-key>
KAP_TEST_API_KEY=<test-key>
```
- ⚠️ **A `.env` in the current directory is deliberately NOT read** (security; see §4). Config = `~/.kap/.env`
  + real env vars (which override). Override per-call with `--env test|production`.
- ⚠️ **You must be on an allowlisted egress IP** (see §4) or calls hang then fail with a connectivity hint.

**Common options** go AFTER the command (e.g. `kap members --format json`): `-f/--format table|json|csv`,
`-o/--out PATH` (format inferred from extension; may be a directory), `--env`, `-v/--verbose` (traceback on error).

---

## 3. Architecture / module map & data flow

Layered, small single-purpose files under `kap/`. **`KapClient` is the only thing that talks to the API;**
**utilities orchestrate it; the CLI is a thin presentation layer.** Data flows strictly one direction:

```
cli.py  ──load_config(env)──►  config.py  ──►  ResolvedConfig
   │                                              │
   │  _make_client(env)                           ▼
   ├────────────────────────────────────►  KapClient(config)  ──TokenProvider(auth.py)──► JWT (disk-cached)
   │                                              │  (one method per /api/vyk/* endpoint)
   │   core command: fn(client) = c.<endpoint>()  │
   │   utility:      utils.<composite>(client,…) ─┘  (utils.py calls KapClient repeatedly)
   │                                              │
   ▼                                              ▼
render.output(data, fmt, out, default_stem)  ◄── parsed JSON (dict / list[dict] / scalar / RawResponse)
   └─ table | json | csv ; stdout or file ; "Saved to <abs path>"
```

| File | Responsibility |
|---|---|
| `config.py` | `pydantic-settings` `Settings` (prefix `KAP_`, reads `~/.kap/.env` **only**) → frozen `ResolvedConfig`. `load_config(env)`. Raises `ValueError` on missing key / unknown env. |
| `errors.py` | `KapError` base; `KapApiError` (non-2xx envelope, `is_token_error`/`is_not_found`, `from_body`); `KapResponseError` (2xx-but-malformed); `KapConnectivityError` (network/allowlist). |
| `auth.py` | `TokenProvider` — mints JWT via `/auth/generateToken`, parses `exp` (no sig check), **disk-caches** atomically (0600), re-mints within skew. `parse_jwt_expiry`, `TokenCache`. |
| `client.py` | `KapClient` — one method per endpoint; `_send`/`_get`/`_get_list`/`_json` share raw-token auth + retry-once + connectivity + JSON-guard; `%PDF` unwrap; `RawResponse`/`JsonObj` types. **Thin 1:1 wrapper — keep it that way.** |
| `render.py` | `output(data, fmt, out, default_stem)` (table/json/csv, format inference + validation), `to_json`/`to_csv`, `decode_disclosure_bodies` (base64→ISO-8859-9, strip style/script), dir-detect + parent-mkdir + "Saved to" line. |
| `utils.py` | **Composite layer**: `resolve_company`/`resolve_fund`/`resolve_one`, `scan_disclosures` (backward window scan + `ScanResult`), `_enumerate_window` (forward pagination, beats the 50-cap), `find_fund_portfolio_reports` + `PortfolioReportResult` + `parse_report_period`, `attachment_id_from_url`. |
| `cli.py` | Typer app; 11 core commands + 8 utilities; shared `Annotated` option aliases; `_make_client(env)`; `_errors` context-manager (one error policy); `_run`/`_save_bytes`/`_render_scan` helpers; `_ENDPOINTS`+`_help` (yellow endpoints); forces UTF-8 stdout/stderr at import. |
| `__main__.py` | `python -m kap` entry → `from kap.cli import app; app()`. |

`pyproject.toml`: `[project.scripts] kap = "kap.cli:app"`; build backend `hatchling`; wheel packages `["kap"]`;
`requires-python = ">=3.11"`; `[tool.pytest.ini_options] testpaths = ["tests"]`.

---

## 4. Auth / token contract, error model, IP allowlist (the hard-won memory)

Reverse-engineered/verified live. **Trust these over the MKK docs** (which are incomplete/misleading).

### Auth (token exchange, not a static key)
- `GET {base}/auth/generateToken?apiKey=<key>` → `{"token":"<JWT>"}`.
- Send the token in the `Authorization` header **RAW — no `Bearer ` prefix** (Bearer → error `ER012`).
  See `KapClient._send`: `headers={"Authorization": token}`. Test asserts `req.headers["authorization"] == "tok1"`.
- Token TTL: **prod ≈24h / test ≈104 days**, read from the JWT `exp` claim via `parse_jwt_expiry` (base64-
  decodes the payload segment, no signature verification). If `exp` is unparseable, `TokenProvider._mint`
  **fails safe to now+3600s** so it re-mints soon.
- **Disk cache:** `~/.kap/token-<env>.json` = `{"token","expires_at"}`. Written atomically with
  `os.open(..., O_WRONLY|O_CREAT|O_TRUNC, 0o600)` (mode ignored on Windows); dir created `mode=0o700`. Cache
  is an optimization — all cache read/write failures are swallowed (`except OSError: pass`), never failing the call.
- **Skew:** `TokenProvider._is_expiring` treats a token as expired once `now >= expires_at - skew_seconds`
  (`token_refresh_skew_seconds`, default 60).
- **Hosts:** test `https://vykapipreprod.mkk.com.tr`, prod `https://kapdatafeed.kap.org.tr`; services under
  `/api/vyk/`, `generateToken` under `/auth/`.

### Error model
KAP errors are **non-2xx** carrying a JSON envelope `{"code":"ERxxx","message":"..."}`. The mapping
(`kap/errors.py`):

| Code | Meaning | Constant | Behavior |
|---|---|---|---|
| `ER005` | not found | `_NOT_FOUND_CODE` | `is_not_found` → list endpoints return `[]`, detail returns `None` |
| `ER004`, `ER006`, `ER012` | token issues | `_TOKEN_ERROR_CODES` | `is_token_error` → client invalidates token + retries **once** |
| anything else | real error | — | raised as `KapApiError` |

- `KapApiError(status_code, code, message)`; `.from_body(status_code, body)` parses the JSON envelope, falling
  back to the raw body as `message` and `code=None` when the body isn't JSON (HTML error page etc.). `str()`
  is `"KAP {code or '?'} (HTTP {status}): {message}"`.
- `KapResponseError(status_code, message)` — a **2xx** response whose body wasn't valid JSON / the expected
  shape (distinct from `KapApiError`). Raised by `KapClient._json`, `last_disclosure_index` (bad shape),
  `download_attachment` (no `%PDF`), and `TokenProvider._mint` (non-JSON / no token).
- `KapConnectivityError(message)` — network-level failure (raised by `_send` on `httpx.ConnectError` /
  `httpx.ConnectTimeout`), carrying the allowlist hint string.
- All inherit `KapError`. The CLI's `_errors` catches `(KapError, ValueError, OSError)`.

### IP allowlist ⚠️
MKK **IP-allowlists** the API. A non-allowlisted source IP isn't rejected with 401 — packets are **silently
dropped → TCP timeout**. `KapClient._send` converts that into a `KapConnectivityError` with this hint:
> "Could not connect to KAP. You may not be on an allowlisted IP — MKK silently drops non-allowlisted source
> IPs (TCP timeout, not 401). Check your VPN / egress IP, or ask MKK (kapdestek@mkk.com.tr) to allowlist it."

### Config security rationale (why `~/.kap/.env` only)
`Settings.model_config` sets `env_file=str(Path.home()/".kap"/".env")` — **never** a cwd `.env`. A globally-
installed `kap` runs from anywhere; loading a cwd `.env` would let any untrusted directory (a cloned repo, a
downloads folder) redirect `KAP_*_BASE_URL` and exfiltrate the API key. Dev overrides use real env vars
(e.g. `set KAP_ACTIVE_ENV=test`), which a cwd cannot control. `extra="ignore"` so unknown `KAP_*` vars don't crash.

---

## 5. Full public API surface (exact signatures, transcribed from the code)

### `kap/config.py`
```python
Environment = Literal["test", "production"]

@dataclass(frozen=True)
class ResolvedConfig:
    env: Environment
    base_url: str
    api_key: str
    token_refresh_skew_seconds: int

class Settings(BaseSettings):
    # model_config: env_prefix="KAP_", env_file=~/.kap/.env, env_file_encoding="utf-8", extra="ignore"
    active_env: str = "test"
    test_base_url: str = "https://vykapipreprod.mkk.com.tr"
    test_api_key: str = ""
    prod_base_url: str = "https://kapdatafeed.kap.org.tr"
    prod_api_key: str = ""
    token_refresh_skew_seconds: int = 60
    def resolve(self, env_override: str | None = None) -> ResolvedConfig: ...
        # env_override or active_env, lowercased/stripped; "prod" aliases "production";
        # base_url.rstrip("/"); skew clamped to >=0; raises ValueError on missing key / unknown env

def load_config(env_override: str | None = None) -> ResolvedConfig:  # = Settings().resolve(env_override)
```

### `kap/errors.py`
```python
class KapError(Exception): ...                       # base

class KapApiError(KapError):
    def __init__(self, status_code: int, code: str | None, message: str)
    status_code: int; code: str | None; message: str
    @property
    def is_token_error(self) -> bool                 # code in {"ER004","ER006","ER012"}
    @property
    def is_not_found(self) -> bool                    # code == "ER005"
    @classmethod
    def from_body(cls, status_code: int, body: str) -> KapApiError

class KapResponseError(KapError):
    def __init__(self, status_code: int, message: str)
    status_code: int; message: str

class KapConnectivityError(KapError): ...            # no extra fields; message carries the allowlist hint
```

### `kap/auth.py`
```python
class TokenCache(TypedDict): token: str; expires_at: int

def parse_jwt_expiry(jwt: str) -> int | None         # base64 payload → exp (unix s); None on garbage

class TokenProvider:
    def __init__(self, base_url: str, api_key: str, env: str, skew_seconds: int = 60,
                 cache_dir: Path | None = None, http: httpx.Client | None = None)
        # cache_dir defaults to ~/.kap ; cache_path = cache_dir / f"token-{env}.json"
    def get_token(self) -> str                        # cached-if-fresh else _mint()
    def invalidate(self) -> None                      # unlink cache file (errors swallowed)
    # internals: _is_expiring, _mint, _read_cache, _write_cache
```

### `kap/client.py`
```python
JsonObj = dict[str, Any]
_PDF_MARKER = b"%PDF"

class RawResponse(TypedDict):                         # authored here, NOT upstream
    service: str; status_code: int; is_success: bool; content_type: str | None; body: str

class KapClient:
    def __init__(self, config: ResolvedConfig,
                 token_provider: TokenProvider | None = None,
                 http: httpx.Client | None = None)    # http defaults to httpx.Client(base_url, timeout=60)

    # ── public endpoints (1:1 with KAP) ───────────────────────────────────────
    def last_disclosure_index(self) -> int            # reads the lastDisclosureIndex key (case-insensitive)
    def disclosures(self, index: int, *, disclosure_type: str | None = None,
                    disclosure_class: str | None = None,
                    company_id: str | int | None = None) -> list[JsonObj]
    def disclosure_detail(self, index: int, file_type: Literal["data","html"] = "data",
                          sub_report: str | None = None) -> JsonObj | None     # ER005 → None
    def download_attachment(self, attachment_id: str) -> bytes | None          # ER005 → None;
        # raises ValueError if id blank; strips Java envelope to the %PDF marker;
        # raises KapResponseError if no %PDF marker (never silently saves non-PDF)
    def members(self) -> list[JsonObj]
    def funds(self) -> list[JsonObj]
    def fund_detail(self, fund_id: int) -> list[JsonObj]
    def member_securities(self) -> list[JsonObj]
    def blocked_disclosures(self) -> list[JsonObj]
    def ca_event_status(self, ref_ids: list[int]) -> list[JsonObj]             # raises ValueError if empty;
        # joins ids comma-separated into processRefId
    def raw(self, path: str, query: dict[str, str] | None = None) -> RawResponse
        # DIAGNOSTIC: no retry, no error-mapping; returns status+body as-is for inspection

    def close(self) -> None
    def __enter__(self) -> "KapClient"; def __exit__(self, *exc) -> None        # context manager

    # ── internals (the shared request contract) ───────────────────────────────
    def _get(self, path, params=None) -> httpx.Response
        # GET with raw-token auth; on non-2xx builds KapApiError.from_body; if is_token_error AND first
        # attempt → self._auth.invalidate() + retry once; else raise. Returns the 2xx response.
    def _send(self, path, params) -> httpx.Response
        # get_token() → http.get(path, params, headers={"Authorization": token});
        # httpx.ConnectError/ConnectTimeout → KapConnectivityError(hint)
    def _get_list(self, path, params=None) -> list[JsonObj]
        # _json(_get(...)) or []; ER005 → []
    @staticmethod
    def _json(resp) -> Any                            # resp.json(); ValueError → KapResponseError
```

### `kap/render.py`
```python
Format = Literal["table", "json", "csv"]
_FORMATS: tuple[Format, ...] = ("table", "json", "csv")

def validate_format(fmt: str | None) -> None          # raises ValueError on an explicit unknown format
def resolve_format(fmt: str | None, out: Path | None, data: Any) -> Format
    # explicit fmt wins; else infer from out suffix (.csv/.json); else dict→"json", else "table"
def to_json(data: Any) -> str                          # ensure_ascii=False, indent=2, default=str
def to_csv(data: Any) -> str                           # union-of-keys header; lineterminator="\n" (Unix)
def decode_disclosure_bodies(detail: Any) -> Any       # MUTATES in place + returns; adds <lang>_text next
    # to each htmlMessages[].tr/.en (base64 → ISO-8859-9 → strip <style>/<script>/tags); failure → None
def output(data: Any, fmt: str | None = None, out: Path | None = None,
           default_stem: str = "output") -> None
    # chosen = resolve_format(...); if out.is_dir(): out = out/f"{default_stem}.{csv|json}";
    # json/csv → write/print; table: scalar→str, dict→json, list→rich Table (file→json);
    # parent dirs auto-created on write; if out: prints "Saved to {out.resolve()}"
# helpers: _is_scalar, _as_rows, _cell, _columns, _strip_html, _write_text, _print_table
```
Notes: a `--out` whose path is an **existing directory** auto-names `<default_stem>.<ext>`; a `--out` file
**creates missing parent dirs**; tables to a file fall back to JSON-on-disk (rich tables are terminal-only).

### `kap/utils.py` (the composite layer — where new business logic goes)
```python
def attachment_id_from_url(url: str) -> str            # last non-empty path segment of an attachmentUrls[].url
def resolve_company(client: KapClient, query: str) -> list[JsonObj]
    # exact stockCode token match (case-insensitive; field may be "AKM, AKMEN") wins, else title substring;
    # deduped by "id"
def resolve_fund(client: KapClient, query: str) -> list[JsonObj]
    # exact fundCode token match wins, else fundName substring; deduped by "fundId"
def resolve_one(matches: list[JsonObj], query: str, what: str,
                describe: Callable[[JsonObj], str]) -> JsonObj
    # the single match, or ValueError for 0 ("No {what} matching '{query}'") / >1 ("ambiguous … matches")

@dataclass
class ScanResult: items: list[JsonObj]; truncated: bool; windows: int

def scan_disclosures(client, company_id: str | int, limit: int, disclosure_class: str | None = None,
                     *, window: int = 36000, max_windows: int = 30) -> ScanResult
    # walks BACKWARD from last_disclosure_index in `window`-sized tiles, deduping by disclosureIndex,
    # until `limit` gathered or `max_windows` hit; returns NEWEST-first; truncated=True if any page hit 50

def parse_report_period(detail: JsonObj) -> str | None # "YYYY-MM" from summary.tr matching r"(\d{4})/(\d+).Ay"

@dataclass
class PortfolioReportResult: items: list[JsonObj]; truncated: bool; details_fetched: int

def find_fund_portfolio_reports(client, fund_code: str, company_id: str | int, *,
                                from_period: str | None = None, to_period: str | None = None,
                                window: int = 36000, max_windows: int = 60,
                                max_details: int = 400) -> PortfolioReportResult
    # scans the mgmt company's disclosures backward (newest window first), forward-paginating each window,
    # opening FON candidates newest-first; keeps subject.tr=="Portföy Dağılım Raporu" AND behalfFundCode==fund.
    # No range → latest (returns at first match). Range → all with period in [from,to].
    # Each item: {disclosureIndex, period, fundCode, fundTitle, attachmentUrls, presentation}

# internals: _dedupe(rows,key), _codes(value)->set[str] (comma-split, upper),
#            _row_idx(row)->int|None, _enumerate_window(client, company_id, win_start, win_end)->list[JsonObj]
#            (_enumerate_window forward-paginates cur→max_idx+1 to beat the 50-row page cap)
```

### `kap/cli.py` (helpers an extension touches)
```python
# Option aliases (Annotated) — reuse these on every new command, placed AFTER positional args:
EnvOpt    = Annotated[Optional[str],  typer.Option("--env",        help="test | production (overrides .env).")]
FormatOpt = Annotated[Optional[str],  typer.Option("--format","-f",help="table | json | csv.")]
OutOpt    = Annotated[Optional[Path], typer.Option("--out","-o",   help="Write output to this file.")]
VerboseOpt= Annotated[bool,           typer.Option("--verbose","-v",help="Show full error detail.")]
# Shared arg aliases for utilities:
_TICKER_ARG / _FUND_ARG / _LIMIT_OPT

_ENDPOINTS: dict[str, str]            # command-name → "GET /api/vyk/..." (single source of truth; yellow help)
_UTIL_PANEL = "Utilities (convenience — not raw API endpoints)"   # rich_help_panel for every utility
_PERIOD_RE_CLI = re.compile(r"^\d{4}-\d{2}$")

def _help(name: str, summary: str) -> str             # "[yellow]{endpoint}[/yellow]  {summary}" (columnar if wide)
def _make_client(env: Optional[str]) -> KapClient     # KapClient(load_config(env)); monkeypatched in CLI tests
def _describe_company(m) -> str / _describe_fund(f) -> str         # for resolve_one ambiguity messages

@contextmanager
def _errors(verbose: bool) -> Iterator[None]
    # catches (KapError, ValueError, OSError) → red "Error: …" on STDERR + typer.Exit(1);
    # full traceback only with --verbose

def _run(env, fmt, out, fn: Callable[[KapClient], Any], *, decode=False, verbose=False, out_name="output")
    # the CORE-command workhorse: _errors → validate_format(fmt) (fail fast) → with _make_client() as c: fn(c)
    # → optional decode_disclosure_bodies → output(data, fmt, out, default_stem=out_name)

def _save_bytes(env, out, fn: Callable[[KapClient], Optional[bytes]], default_name, *, verbose=False)
    # for binary downloads: None → "Not found." + exit 1; out dir → out/default_name; else out or Path(default_name);
    # parent mkdir; write_bytes; prints "Saved N bytes to <abs>"

def _render_scan(fmt, out, result: ScanResult, out_name="output")
    # prints the 50-cap truncation note to STDERR if result.truncated, then output(result.items, …)

def _validate_period_range(from_period, to_period) -> None        # YYYY-MM + ordering; typer.BadParameter
```

---

## 6. Live data-shape reference (per endpoint — learned live; the high-value memory)

The upstream payloads are **variable, polymorphic, and partly mislabeled** — that's why `KapClient` types
everything as `JsonObj`/`list[JsonObj]` and consumers parse defensively. Numeric ids appear both quoted and
unquoted across services; **treat ids as strings / parse defensively.**

- **`members`** rows: `id` (the **companyId**, a **string** like `"866"`), `title`, `stockCode`, type fields.
  `stockCode` is often **comma-joined** (`"AKM, AKMEN"`), and member rows can be **exact-duplicated**.
  → resolvers split tokens (`_codes`) and dedupe by `id` (`_dedupe`). `id` is what `disclosures --company-id` wants.
- **`funds`** rows: `fundId` (int), `fundCode`, `fundName`, `fundCompanyId` (the **management company's** id —
  used to scan a fund's disclosures). `fund-detail` takes `fundId`; disclosure scans take `fundCompanyId`.
- **`disclosures` LIST** rows expose only `disclosureIndex`, `disclosureType`, `disclosureClass`,
  `title` (= the **sender**, NOT the subject), `companyId`. **You cannot tell what a disclosure *is* or which
  fund it concerns from the list** — you must open its detail. `disclosureClass=FR` = financial reports;
  `disclosureType=FON` = fund disclosures.
- **Pagination contract (critical):** `disclosures(index, …)` returns **≤50 rows, OLDEST-first, within a
  ~36k forward index window** from `index`. For a heavy filer (a fund management company) a single call near
  `last-index` returns the *oldest* 50 of that window and **misses the newest**. To get genuinely recent items
  you must **forward-paginate** (step start → `max(returned index)+1`, see `_enumerate_window`) and/or step
  **back in windows** (see `scan_disclosures`). This is the whole reason the utilities exist.
- **`disclosure-detail`** default `--file-type data`: `subject`/`summary` as **`{tr, en}`** dicts, `flatData`,
  `link`, `attachmentUrls` (list of `{url, fileName}`), `presentation` (the structured data form),
  `behalfFundCode`/`behalfFundTitle` (on fund disclosures) — **no `htmlMessages`**. The readable base64 body
  appears **only** under `--file-type html` as `htmlMessages[].tr/.en` (base64 ISO-8859-9 XHTML);
  `decode_disclosure_bodies` adds `<lang>_text` plain text. FON html bodies can mojibake; the structured
  `presentation` is the clean source for fund reports. `disclosure-detail` is the only command routed with
  `_run(..., decode=True)`.
- **`downloadAttachment`** lies `Content-Type: application/pdf` but the body is a **Java-serialized `byte[]`
  envelope** (starts `0xAC 0xED…`, real `%PDF` at ~offset 27). `download_attachment` strips to the `%PDF`
  marker; a body with no `%PDF` is **rejected** (`KapResponseError`), never silently saved.
- **`caEventStatus`**: takes one or more `processRefId` (comma-joined); KP/SA/GAI/GK corporate-action status.
- **Fund / PDR specifics:** fund disclosures (incl. the **Portföy Dağılım Raporu** = portfolio allocation
  report) are filed under the fund's **management company** (`fundCompanyId`), not the fund itself — one per
  fund per period. A PDR is a `disclosureType=FON` disclosure whose **`subject.tr == "Portföy Dağılım Raporu"`**
  with a **`behalfFundCode`** naming the fund; its content is the detail's `presentation`; its report period
  (e.g. `"2026 / 3.Ay"`) is in **`summary.tr`** → `parse_report_period` → `"2026-03"`.

---

## 7. Conventions (match these exactly when extending)

- **Rich help, two panels.** Core commands appear in the default **Commands** panel via
  `short_help=_help(name, summary)`, which prints the **endpoint in yellow** (from `_ENDPOINTS`) + a summary,
  columnar only on wide terminals (`_WIDE`). Utilities appear in the **`_UTIL_PANEL`** ("Utilities (convenience —
  not raw API endpoints)") with a magenta **`[magenta]composite[/magenta]`** tag in their `short_help`.
- **Docstrings are the long `--help`.** Core: state the **endpoint**, the **inputs**, and an **example**.
  Utilities: open with **"Composite utility (not a single endpoint)."**, name the endpoints orchestrated, give
  an example; multi-step composites (`fund-portfolio-report`/`-pdf`) use a **numbered-step** docstring.
- **One error policy.** Every command body runs inside `with _errors(verbose):`. Expected failures
  (`KapError`/`ValueError`/`OSError`) → red `Error:` on **stderr** + exit 1; traceback only with `-v`. Never
  print errors to stdout (a CLI test asserts this separation). Use `typer.BadParameter` for bad arg values
  (also non-zero exit).
- **Config = `~/.kap/.env` + real env only** (security rationale in §4). Never read a cwd `.env`.
- **UTF-8 shim.** `cli.py` reconfigures `sys.stdout`/`stderr` to UTF-8 at import so Turkish text never crashes
  a cp1252 Windows terminal. Keep it.
- **`--out` semantics** (`render.output` + `_save_bytes`): a file path (format inferred from extension if
  `--format` omitted); an **existing directory** → `<out_name>.<ext>` (or the download's own filename); missing
  **parent dirs are auto-created**; every save prints the **absolute** "Saved …" path.
- **Pagination rule.** Remember the **≤50-rows-per-~36k-window, OLDEST-first** contract (§6). Core
  `disclosures` exposes it raw; **utilities forward-paginate** (`_enumerate_window`) and/or window backward
  (`scan_disclosures`) to return genuine "latest". If your new feature needs recent disclosures for an entity,
  reuse `scan_disclosures`/`_enumerate_window` — don't re-derive it.
- **Keep `KapClient` thin.** A `KapClient` method = exactly one endpoint, no orchestration, no business logic.
  Multi-call logic → `utils.py`.

---

## 8. Extension recipes (copy-pasteable, matching the existing patterns)

Always TDD (write the failing test first — see §9). Keep help honest about what the command actually does.

### (a) Add a CORE command (a new 1:1 endpoint)

**Step 1 — `kap/client.py`: add the typed method** (thin; mirror an existing one). For a hypothetical
`GET /api/vyk/indexList`:
```python
def index_list(self) -> list[JsonObj]:
    return self._get_list("api/vyk/indexList")
# (use _json(self._get(path, params)) for single-object/scalar endpoints; see last_disclosure_index)
```

**Step 2 — `kap/cli.py`: register the endpoint string** in `_ENDPOINTS` (single source of truth → yellow help):
```python
_ENDPOINTS = {
    ...,
    "index-list": "GET /api/vyk/indexList",
}
```

**Step 3 — `kap/cli.py`: add the command**, reusing the shared option aliases and `_run`:
```python
@app.command("index-list", short_help=_help("index-list", "all market indices"))
def index_list(env: EnvOpt = None, fmt: FormatOpt = None, out: OutOpt = None, verbose: VerboseOpt = False):
    """All market indices.

    Calls GET /api/vyk/indexList. No inputs.

    Example: kap index-list --format json
    """
    _run(env, fmt, out, lambda c: c.index_list(), verbose=verbose, out_name="index-list")
```
For binary downloads use `_save_bytes(...)` instead of `_run` (see `download-attachment`). For an endpoint
that returns nested-dict detail you want decoded, pass `decode=True` (see `disclosure-detail`).

**Step 4 — tests** (`tests/test_client.py` + `tests/test_cli.py`):
```python
# tests/test_client.py — respx at the HTTP boundary, _StubAuth for tokens
@respx.mock
def test_index_list():
    respx.get("https://h/api/vyk/indexList").mock(return_value=httpx.Response(200, json=[{"code": "XU100"}]))
    assert _client().index_list() == [{"code": "XU100"}]

# tests/test_cli.py — add index_list() to _FakeClient, then:
def test_index_list_command(fake_client):
    result = runner.invoke(cli.app, ["index-list"])
    assert result.exit_code == 0
```

### (b) Add a UTILITY (a composite — *this is the main thing researchers/agents will build*)

**Step 1 — `kap/utils.py`: put the orchestration here** (take a `KapClient`, return a small dataclass/dicts;
reuse `resolve_*`, `scan_disclosures`, `_enumerate_window`). Example — a fund's recent FON disclosures:
```python
def find_fund_fon_disclosures(client: KapClient, fund_company_id: str | int, limit: int) -> ScanResult:
    """A fund management company's recent FON-type disclosures, newest first."""
    return scan_disclosures(client, fund_company_id, limit, disclosure_class="FON")
```
If you need a new shape, add a small `@dataclass` next to `ScanResult`/`PortfolioReportResult`.
**Do NOT add this logic to `KapClient`.**

**Step 2 — `kap/cli.py`: add the command in the Utilities panel** with the magenta tag and a composite docstring:
```python
@app.command(
    "fund-fon-disclosures",
    rich_help_panel=_UTIL_PANEL,
    short_help="[magenta]composite[/magenta]  fund → recent FON disclosures",
)
def fund_fon_disclosures_cmd(
    query: _FUND_ARG, limit: _LIMIT_OPT = 20,
    env: EnvOpt = None, fmt: FormatOpt = None, out: OutOpt = None, verbose: VerboseOpt = False,
):
    """Composite utility (not a single endpoint). Recent FON disclosures for a fund, newest first.

    Resolves the fund via GET /api/vyk/funds, then pages GET /api/vyk/disclosures?disclosureType=FON
    backward by the fund's management-company id (fundCompanyId).

    Example: kap fund-fon-disclosures BON --limit 20
    """
    with _errors(verbose):
        validate_format(fmt)
        with _make_client(env) as client:
            fund = resolve_one(resolve_fund(client, query), query, "fund", _describe_fund)
            result = find_fund_fon_disclosures(client, fund["fundCompanyId"], limit)
        _render_scan(fmt, out, result, out_name="fund-fon-disclosures")
```
Notes matching the existing utilities: open the body with `with _errors(verbose):`, call `validate_format(fmt)`
**before** the network, resolve via `resolve_one(...)`, do the work **inside** the `with _make_client() as client:`
block, then render with `output(...)` (data) or `_render_scan(...)` (a `ScanResult`). For a numbered multi-step
docstring, follow `fund-portfolio-report`/`fund-portfolio-pdf`.

**Step 3 — tests** (`tests/test_utils.py` for the orchestration against the in-module `FakeClient`, plus
`tests/test_cli.py` for the wiring against the monkeypatched `_FakeClient` / `cli._make_client`).

---

## 9. Dev & test workflow

```bash
pip install -e ".[dev]"      # editable install + pytest + respx
python -m pytest             # 134 tests, ~13s, pristine output
```

**Process:** branch before code → **TDD** (failing test first) → per-task spec + quality reviews → close each
feature with a whole-branch review. Tests assert **real behavior at real boundaries** — not mock-theater.

**Test layout & fixtures** (mirror modules in `tests/`):

| File | What it exercises | Key fixtures / technique |
|---|---|---|
| `test_config.py` | `Settings.resolve` env/url/key, aliases, errors | `_settings(**kw)` passes `_env_file=None` so a real on-disk `.env` is ignored |
| `test_errors.py` | `from_body` parsing, `is_token_error`/`is_not_found`, `str()` | plain unit tests |
| `test_auth.py` | mint/exp/skew/disk-reuse/invalidate, mint failures | `respx` for `/auth/generateToken`; `tmp_path` as `cache_dir`; `_make_jwt(exp)` builds a fake JWT |
| `test_client.py` | every endpoint: raw-auth header, ER005→empty/None, token-retry-once, non-PDF reject, envelope strip, connectivity | `respx.mock`; `_StubAuth` (sequential tokens + invalidation count); `_client(auth)`; `httpx.MockTransport` for the connect-timeout case |
| `test_render.py` | format resolution/validation, csv union+Unix EOL, decode, dir-auto-name, parent-mkdir | `tmp_path`, `capsys` |
| `test_utils.py` | resolution (comma-codes/dedupe), backward scan, forward-pagination past the 50-cap, period parse, PDR latest/range/truncation | module-level `FakeClient(members,funds,pages,last,details)` — a hand-rolled stub with `.calls` |
| `test_cli.py` | command wiring, errors-on-stderr, fail-fast validation, exit codes, `--out` dir/parent | `CliRunner`; `_FakeClient` (context-manager stub with `.calls`); `fake_client` fixture monkeypatches `cli._make_client`; util commands monkeypatch `cli.find_fund_portfolio_reports` |

**Three different stand-ins, on purpose:** `_StubAuth` (token provider, in `test_client.py`),
`FakeClient` (full client stub for the orchestration tests, in `test_utils.py`), and `_FakeClient` (client stub
supporting the CLI's context-manager use, in `test_cli.py`). When you add a method to `KapClient`, add it to
both `FakeClient` and `_FakeClient` if a util/CLI test will call it. There are **no JS unit tests** (pure
Python). Live-verify network behavior manually from an allowlisted IP.

---

## 10. Core commands (11) — one KAP endpoint each

| Command | Endpoint | Notes |
|---|---|---|
| `last-index` | `GET /api/vyk/lastDisclosureIndex` | newest disclosure id market-wide; a polling cursor |
| `disclosures --index N` | `GET /api/vyk/disclosures` | ≤50 from N onward (oldest-first, ~36k window); `--type/--class/--company-id` |
| `disclosure-detail <index>` | `GET /api/vyk/disclosureDetail/{id}` | `--file-type data|html` (**html** = readable body, decoded), `--sub-report` |
| `download-attachment <id>` | `GET /api/vyk/downloadAttachment/{id}` | writes a PDF; Java-envelope auto-unwrapped; non-PDF rejected |
| `members` | `GET /api/vyk/members` | all companies (`id`=companyId string, `title`, `stockCode`, …) |
| `funds` | `GET /api/vyk/funds` | all funds (`fundId`, `fundCode`, `fundName`, `fundCompanyId`, …) |
| `fund-detail <id>` | `GET /api/vyk/fundDetail/{id}` | general-info sections (polymorphic); takes `fundId` |
| `member-securities` | `GET /api/vyk/memberSecurities` | ISIN-level securities |
| `blocked-disclosures` | `GET /api/vyk/blockedDisclosures` | disclosures blocked from access |
| `ca-event-status <ref-ids…>` | `GET /api/vyk/caEventStatus?processRefId=…` | corporate-action process status (variadic ids) |
| `raw <path>` | any relative path | diagnostic passthrough (no retry / no error-mapping); `--query k=v` (repeatable) |

---

## 11. Utilities (8) — composites, NOT raw endpoints

Shown in the **`_UTIL_PANEL`** with a magenta `composite` tag. Each resolves a ticker/fund and orchestrates
several calls. Resolution: exact code (case-insensitive; handles comma-joined codes like `"AKM, AKMEN"`) first,
else partial-name substring; deduped. Commands needing one entity exit 1 with a clear message on ambiguity/not-found.

| Utility | What it does | Orchestrates |
|---|---|---|
| `resolve-ticker <q>` | ticker or company-name → companyId + title | `members` |
| `resolve-fund <q>` | fund code or name → fundId + name | `funds` |
| `ticker-disclosures <q> [--limit N]` | a ticker's recent disclosures, newest-first | resolve + `scan_disclosures` |
| `ticker-financials <q> [--limit N]` | a ticker's recent FR (financial-report) filings | resolve + `scan_disclosures(class=FR)` |
| `fund-info <q>` | a fund's general-info sections | resolve + `fundDetail/{id}` |
| `fund-disclosures <q> [--limit N]` | a fund's **management-company** disclosures (covers all its funds) | resolve + `scan_disclosures` (by `fundCompanyId`) |
| `fund-portfolio-report <q> [--from YYYY-MM --to YYYY-MM]` | a fund's **Portföy Dağılım Raporu** (latest, or all in a period range) | resolve + `find_fund_portfolio_reports` (forward-paginated FON scan + `disclosureDetail`) |
| `fund-portfolio-pdf <q> [--from/--to] [--out/--out-dir]` | download a fund's **PDR PDF** (latest, or all in a range) | resolve + find report(s) + `downloadAttachment` |

**Worked recipes**
```bash
kap resolve-ticker ASELS
kap ticker-disclosures ASELS --limit 20
kap fund-portfolio-report BON                      # latest portfolio allocation report
kap fund-portfolio-report BON --from 2026-01 --to 2026-06   # all in range (slow — many detail calls)
kap fund-portfolio-pdf BON --out-dir reports       # download the PDF(s)
```
> `fund-disclosures` covers **all funds managed by the same company** (KAP files under the mgmt company, not
> per fund). `fund-portfolio-report` opens many disclosure details (the list doesn't expose subject/fund), so a
> wide range can be slow; latest-only is quick.

---

## 12. Progress log

- **2026-06-23 — Core CLI shipped.** 11 commands, token auth + disk cache, attachment unwrap, table/json/csv,
  README; subagent TDD + final review. Then an **A+ hardening pass** (`1ed289e`): `KapResponseError` + guarded
  JSON, non-PDF reject, single `_errors` policy, honest types/`Literal`s, Unix CSV, fail-fast `--format`/`--file-type`,
  strict `raw --query`. Pushed to a new private GitHub repo.
- **2026-06-24 — Live-verified against PROD** (allowlisted IP, real key). Config moved to `~/.kap/.env` (cwd
  `.env` dropped for security); `kap` put on User PATH; help redesigned (3-col Commands panel, width-aware, colored).
- **2026-06-24 — Utilities layer** (`8a75e8e`): resolve-ticker/fund, ticker-disclosures, ticker-financials,
  fund-info, fund-disclosures — separate "Utilities" panel; live-shape bugs (comma-codes, duplicate members) fixed.
- **2026-06-24 — `fund-portfolio-report`** (`b6aace8`): a fund's PDR via forward-paginated FON scan (so "latest"
  is the true latest, not a stale window) + subject/behalfFundCode match; default latest, `--from/--to` range.
- **2026-06-24 — `fund-portfolio-pdf`** (`ceb09cc`): downloads the report's attached PDF — reuses the finder
  (surfacing `attachmentUrls`) + `download-attachment`'s `%PDF` unwrap; `--out` / `--out-dir` (KAP's own filenames,
  path-safe). DRY'd the shared `--from/--to` validation into `_validate_period_range`. Live-verified.
- **2026-06-24 — `--out` directory auto-naming** (`35cb147` / `66b695e`): `--out <existing dir>` writes a
  sensibly-named file into it (`<command>.<ext>` for data; the attachment/PDF's own name for downloads) instead of
  `[Errno 13]`; missing parent dirs are auto-created; all "Saved" lines print the absolute resolved path.

Per-feature specs/plans + reviews under `docs/superpowers/specs|plans/`. SDD scratch (briefs/reports/diffs) is in
`.superpowers/` (gitignored).

---

## 13. Open items / future (only if asked)

- **`docs/getting-started.*`** — the planned non-developer human guide (printable how-to). Not yet written.
- **Distribute to the team:** share §2; confirm each researcher is on an allowlisted network.
- **Possible enhancements (YAGNI until requested):** make `disclosure-detail` default to `--file-type html`
  (or auto-fall-back when the body is absent); flatten the `presentation` allocation structure into tidy rows; a
  `--limit`/pagination helper on raw `disclosures`; fix the FON html-body mojibake (likely a UTF-8-vs-ISO-8859-9
  mismatch for fund bodies).

---

## 14. Contacts & references

- **MKK / KAP support** (IP allowlist, access, spec): `kapdestek@mkk.com.tr`.
- **Upstream contract** (authoritative source this mirrors): `../tuneup-api/docs/kap-integration.md`.
- **Repo:** `https://github.com/ufuk-kilinc/kap-cli` (private).
</content>
</invoke>
