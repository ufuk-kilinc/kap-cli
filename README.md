# KAP CLI

Command-line access to every endpoint of the **KAP Veri Yayın Servisi** REST API
(MKK / Borsa İstanbul), for the research team.

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

## Develop

```bash
pip install -e ".[dev]"
python -m pytest
```
