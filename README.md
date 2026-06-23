# KAP CLI

Command-line access to every endpoint of the **KAP Veri Yayın Servisi** REST API
(MKK / Borsa İstanbul), for the research team.

## Install

```bash
git clone <repo-url> kap-cli
cd kap-cli
pip install -e .          # editable: edit the code, changes apply immediately
cp .env.example .env      # then fill in your API key(s)
```

> Requires Python 3.11+. (`pip install -e ".[dev]"` also installs the test deps.)

## Configure

Edit `.env`:

```bash
KAP_ACTIVE_ENV=test                 # or: production
KAP_TEST_API_KEY=your-test-key
KAP_PROD_API_KEY=your-prod-key
```

`.env` is gitignored — never commit your keys.

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

### Global options (before the command)

| Option | Meaning |
|---|---|
| `--env test\|production` | Override the active environment for this call. |
| `-f, --format table\|json\|csv` | Output format (default: table; nested responses default to json). |
| `-o, --out PATH` | Write output to a file (format inferred from extension if `--format` omitted). |
| `-v, --verbose` | Fuller error detail. |

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
