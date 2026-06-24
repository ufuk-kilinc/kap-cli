# KAP CLI

Command-line access to every endpoint of the **KAP Veri Yayın Servisi** REST API
(MKK / Borsa İstanbul), for the research team.

> 📖 **New here? Read [`docs/kap-cli-handoff.md`](docs/kap-cli-handoff.md)** — the project memory:
> full command/utility reference, the KAP domain gotchas (auth, IP allowlist, data shapes), architecture,
> and progress log.

## Install

```bash
git clone <repo-url> kap-cli
cd kap-cli
pip install -e .          # editable: edit the code, changes apply immediately
mkdir %USERPROFILE%\.kap  && copy .env.example %USERPROFILE%\.kap\.env   # Windows
# macOS/Linux:  mkdir -p ~/.kap && cp .env.example ~/.kap/.env
```

> Requires Python 3.11+. (`pip install -e ".[dev]"` also installs the test deps.)

## Configure

Put your keys in **`~/.kap/.env`** (Windows: `%USERPROFILE%\.kap\.env`). This one file is read
no matter which directory you run `kap` from.

```bash
KAP_ACTIVE_ENV=production            # or: test
KAP_PROD_API_KEY=your-prod-key
KAP_TEST_API_KEY=your-test-key
```

`~/.kap/.env` is outside the repo and never committed.

> **Security:** `kap` reads config only from `~/.kap/.env` and real environment variables — it does
> **not** read a `.env` from the current directory. That's deliberate: a globally-installed CLI run
> inside an untrusted folder must not pick up a stray `.env` that could redirect `KAP_*_BASE_URL` and
> leak your key. For a temporary override, set an environment variable (e.g. `set KAP_ACTIVE_ENV=test`),
> which always takes priority.

> **IP allowlist:** KAP only answers allowlisted source IPs. If a command hangs then
> fails with a connectivity error, you're probably on a non-allowlisted IP (VPN/egress) —
> contact `kapdestek@mkk.com.tr`.

## Usage

```bash
kap last-index
kap members
kap members --format json
kap members --out members.csv          # format inferred from extension
kap funds --out funds.csv
kap disclosures --index 1000000 --class FR --company-id 42
kap disclosure-detail 1234567          # bodies decoded to readable text
kap download-attachment <attachment-id> --out report.pdf
kap fund-detail 5900
kap ca-event-status 111 222
kap raw api/vyk/members --query foo=bar
```

### Common options (place after the command name)

| Option | Meaning |
|---|---|
| `--env test\|production` | Override the active environment for this call. |
| `-f, --format table\|json\|csv` | Output format (default: table; nested responses default to json). |
| `-o, --out PATH` | Write output to a file (format inferred from extension if `--format` omitted). |
| `-v, --verbose` | Fuller error detail (prints full traceback on error). |

## Commands ↔ endpoints

| Command | Endpoint |
|---|---|
| `last-index` | `GET /api/vyk/lastDisclosureIndex` |
| `disclosures` | `GET /api/vyk/disclosures` |
| `disclosure-detail` | `GET /api/vyk/disclosureDetail/{id}` |
| `download-attachment` | `GET /api/vyk/downloadAttachment/{id}` |
| `members` | `GET /api/vyk/members` |
| `funds` | `GET /api/vyk/funds` |
| `fund-detail` | `GET /api/vyk/fundDetail/{id}` |
| `member-securities` | `GET /api/vyk/memberSecurities` |
| `blocked-disclosures` | `GET /api/vyk/blockedDisclosures` |
| `ca-event-status` | `GET /api/vyk/caEventStatus` |
| `raw` | any relative path |

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
| `fund-disclosures <q> [--limit N]` | recent disclosures for a fund's management company (covers all its funds) | resolve + paged `GET /disclosures` (by fundCompanyId) |
| `fund-portfolio-report <q> [--from YYYY-MM --to YYYY-MM]` | a fund's Portföy Dağılım Raporu (latest, or all in a period range) | resolve + scan FON disclosures + `GET /disclosureDetail` |
| `fund-portfolio-pdf <q> [--from/--to] [--out/--out-dir]` | download a fund's Portföy Dağılım Raporu **PDF** (latest, or all in a range) | resolve + find report(s) + `GET /downloadAttachment` |

```bash
kap resolve-ticker ASELS
kap ticker-disclosures ASELS --limit 20
kap resolve-fund BON
kap fund-info BON
```

> Disclosure utilities page backward from the latest index to return genuinely recent filings
> (the raw `disclosures` command only scans a bounded window forward).

```bash
kap fund-portfolio-report BON                      # latest portfolio allocation report
kap fund-portfolio-report BON --from 2026-01 --to 2026-06
```
> `fund-portfolio-report` opens many disclosure details (the list doesn't expose subject/fund), so a
> wide period range can be slow; the latest-only call is quick.

```bash
kap fund-portfolio-pdf BON                              # latest report PDF → KAP's own filename
kap fund-portfolio-pdf BON --from 2026-01 --to 2026-06 --out-dir reports
```

## Develop

```bash
pip install -e ".[dev]"
python -m pytest
```
