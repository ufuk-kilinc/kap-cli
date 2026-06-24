from __future__ import annotations

import re
import shutil
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any, Literal, Optional

import typer
from rich.console import Console

from kap.client import KapClient
from kap.config import load_config
from kap.errors import KapError
from kap.render import decode_disclosure_bodies, output, validate_format
from kap.utils import (
    PortfolioReportResult,
    ScanResult,
    attachment_id_from_url,
    find_fund_portfolio_reports,
    resolve_company,
    resolve_fund,
    resolve_one,
    scan_disclosures,
)

# Force UTF-8 so Turkish help text and disclosure data never crash on a
# cp1252 (default Windows) terminal.
for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure is not None:
        try:
            _reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass

# Command → KAP endpoint (single source of truth; shown in yellow in the Commands panel).
_ENDPOINTS: dict[str, str] = {
    "last-index": "GET /api/vyk/lastDisclosureIndex",
    "disclosures": "GET /api/vyk/disclosures",
    "disclosure-detail": "GET /api/vyk/disclosureDetail/{index}",
    "download-attachment": "GET /api/vyk/downloadAttachment/{id}",
    "members": "GET /api/vyk/members",
    "funds": "GET /api/vyk/funds",
    "fund-detail": "GET /api/vyk/fundDetail/{id}",
    "member-securities": "GET /api/vyk/memberSecurities",
    "blocked-disclosures": "GET /api/vyk/blockedDisclosures",
    "ca-event-status": "GET /api/vyk/caEventStatus",
    "raw": "GET /<path>",
}


_URL_W = max(len(url) for url in _ENDPOINTS.values())
# Align endpoint + summary into columns only when the window is wide enough; on a
# narrow terminal render compact so rows wrap cleanly instead of forcing the panel
# wider than the window (read once at startup).
_WIDE = shutil.get_terminal_size((80, 24)).columns >= 100


def _help(name: str, summary: str) -> str:
    """Commands-panel short help: endpoint (yellow) + summary; columnar only when wide."""
    url = _ENDPOINTS[name].ljust(_URL_W) if _WIDE else _ENDPOINTS[name]
    return f"[yellow]{url}[/yellow]  {summary}"


_EPILOG = (
    "Set your API key in [cyan]~/.kap/.env[/cyan] (KAP_PROD_API_KEY / KAP_TEST_API_KEY). "
    "Run [cyan]kap COMMAND --help[/cyan] for a command's own arguments.\n\n"
    "[bold]Common options[/bold] (on every command, placed AFTER it — e.g. "
    "[cyan]kap members --format json[/cyan]):  [cyan]-f/--format[/cyan] \\[table|json|csv], "
    "[cyan]-o/--out[/cyan] PATH, [cyan]--env[/cyan] \\[test|production], [cyan]-v/--verbose[/cyan].\n\n"
    "Core [bold]Commands[/bold] call one KAP endpoint each; [magenta]Utilities[/magenta] are "
    "multi-call convenience built on them."
)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="CLI for the KAP (Borsa Istanbul) disclosure data API.",
    epilog=_EPILOG,
)
_err_console = Console(stderr=True)

_UTIL_PANEL = "Utilities (convenience — not raw API endpoints)"


def _describe_company(m: dict) -> str:
    return f"{m.get('stockCode')} — {m.get('title')}"


def _describe_fund(f: dict) -> str:
    return f"{f.get('fundCode')} — {f.get('fundName')}"


def _render_scan(fmt: Optional[str], out: Optional[Path], result: ScanResult) -> None:
    if result.truncated:
        _err_console.print(
            "[yellow]Note:[/yellow] some windows hit the 50-result cap; very active filers may be "
            "incomplete — raise --limit."
        )
    output(result.items, fmt=fmt, out=out)


# Shared output options — available AFTER each command, e.g. kap members --format json.
EnvOpt = Annotated[Optional[str], typer.Option("--env", help="test | production (overrides .env).")]
FormatOpt = Annotated[Optional[str], typer.Option("--format", "-f", help="table | json | csv.")]
OutOpt = Annotated[Optional[Path], typer.Option("--out", "-o", help="Write output to this file.")]
VerboseOpt = Annotated[bool, typer.Option("--verbose", "-v", help="Show full error detail.")]


def _make_client(env: Optional[str]) -> KapClient:
    return KapClient(load_config(env))


@contextmanager
def _errors(verbose: bool) -> Iterator[None]:
    """Turn any expected failure into a clean stderr message + exit 1.

    Covers config (ValueError), API/connectivity (KapError), and output/file
    writes (OSError). The full traceback is shown only with --verbose.
    """
    try:
        yield
    except (KapError, ValueError, OSError) as exc:
        _err_console.print(f"[red]Error:[/red] {exc}")
        if verbose:
            _err_console.print_exception()
        raise typer.Exit(code=1)


def _run(
    env: Optional[str],
    fmt: Optional[str],
    out: Optional[Path],
    fn: Callable[[KapClient], Any],
    *,
    decode: bool = False,
    verbose: bool = False,
) -> None:
    with _errors(verbose):
        validate_format(fmt)  # fail fast before any network call
        with _make_client(env) as client:
            data = fn(client)
        if decode and isinstance(data, dict):
            data = decode_disclosure_bodies(data)
        output(data, fmt=fmt, out=out)


def _save_bytes(
    env: Optional[str],
    out: Optional[Path],
    fn: Callable[[KapClient], Optional[bytes]],
    default_name: str,
    *,
    verbose: bool = False,
) -> None:
    with _errors(verbose):
        with _make_client(env) as client:
            data = fn(client)
        if data is None:
            _err_console.print("[yellow]Not found.[/yellow]")
            raise typer.Exit(code=1)
        target = out or Path(default_name)
        target.write_bytes(data)
        print(f"Saved {len(data)} bytes to {target}")


@app.command("last-index", short_help=_help("last-index", "latest disclosure id (cursor)"))
def last_index(env: EnvOpt = None, fmt: FormatOpt = None, out: OutOpt = None, verbose: VerboseOpt = False):
    """Latest published disclosure id (a market-wide cursor).

    Calls GET /api/vyk/lastDisclosureIndex. No inputs. Returns a single number —
    the id of the newest disclosure across all of KAP. Feed it to disclosures as
    --index, or poll it to detect new filings.

    Example: kap last-index
    """
    _run(env, fmt, out, lambda c: c.last_disclosure_index(), verbose=verbose)


@app.command(short_help=_help("disclosures", "first 50 from --index (filterable)"))
def disclosures(
    index: Annotated[int, typer.Option("--index", help="Start disclosure index (required).")],
    type_: Annotated[Optional[str], typer.Option("--type", help="disclosureType filter.")] = None,
    class_: Annotated[Optional[str], typer.Option("--class", help="disclosureClass filter (e.g. FR).")] = None,
    company_id: Annotated[Optional[int], typer.Option("--company-id", help="companyId filter.")] = None,
    env: EnvOpt = None,
    fmt: FormatOpt = None,
    out: OutOpt = None,
    verbose: VerboseOpt = False,
):
    """First 50 disclosures from --index onward (optionally filtered).

    Calls GET /api/vyk/disclosures. Required: --index (a disclosureIndex, e.g.
    from last-index); returns 50 disclosures from there. Optional filters:
    --type, --class (e.g. FR for financial reports), --company-id.

    Example: kap disclosures --index 1619914 --class FR
    """
    _run(
        env,
        fmt,
        out,
        lambda c: c.disclosures(
            index, disclosure_type=type_, disclosure_class=class_, company_id=company_id
        ),
        verbose=verbose,
    )


@app.command("disclosure-detail", short_help=_help("disclosure-detail", "one disclosure's full detail"))
def disclosure_detail(
    index: Annotated[int, typer.Argument(help="Disclosure index.")],
    file_type: Annotated[Literal["data", "html"], typer.Option("--file-type", help="data | html.")] = "data",
    sub_report: Annotated[Optional[str], typer.Option("--sub-report", help="subReportList id.")] = None,
    env: EnvOpt = None,
    fmt: FormatOpt = None,
    out: OutOpt = None,
    verbose: VerboseOpt = False,
):
    """Full detail for one disclosure.

    Calls GET /api/vyk/disclosureDetail/{index}. Required argument: the disclosure
    index (from disclosures). Use --file-type html to get the readable
    announcement body (decoded to text); the default --file-type data returns
    structured fields only (subject/summary/links/attachments). --sub-report
    picks one sub-report.

    Example: kap disclosure-detail 1619914 --file-type html
    """
    _run(env, fmt, out, lambda c: c.disclosure_detail(index, file_type, sub_report), decode=True, verbose=verbose)


@app.command("download-attachment", short_help=_help("download-attachment", "download an attachment PDF"))
def download_attachment(
    attachment_id: Annotated[str, typer.Argument(help="Attachment id (last path segment of an attachment url).")],
    out: OutOpt = None,
    env: EnvOpt = None,
    verbose: VerboseOpt = False,
):
    """Download a disclosure attachment PDF (Java envelope auto-unwrapped).

    Calls GET /api/vyk/downloadAttachment/{id}. Required argument: the attachment
    id — the last path segment of an attachment URL shown by
    disclosure-detail. Saves to --out (default <id>.pdf).

    Example: kap download-attachment 1234567 --out report.pdf
    """
    _save_bytes(env, out, lambda c: c.download_attachment(attachment_id), f"{attachment_id}.pdf", verbose=verbose)


@app.command(short_help=_help("members", "all KAP-member companies"))
def members(env: EnvOpt = None, fmt: FormatOpt = None, out: OutOpt = None, verbose: VerboseOpt = False):
    """All KAP-member companies (id, title, stock code, type).

    Calls GET /api/vyk/members. No inputs. The id here is the companyId used by
    disclosures --company-id.

    Example: kap members --out members.csv
    """
    _run(env, fmt, out, lambda c: c.members(), verbose=verbose)


@app.command(short_help=_help("funds", "all funds"))
def funds(env: EnvOpt = None, fmt: FormatOpt = None, out: OutOpt = None, verbose: VerboseOpt = False):
    """All funds.

    Calls GET /api/vyk/funds. No inputs. A fund's id feeds fund-detail.

    Example: kap funds --format json
    """
    _run(env, fmt, out, lambda c: c.funds(), verbose=verbose)


@app.command("fund-detail", short_help=_help("fund-detail", "one fund's info sections"))
def fund_detail(
    fund_id: Annotated[int, typer.Argument(help="Fund id.")],
    env: EnvOpt = None,
    fmt: FormatOpt = None,
    out: OutOpt = None,
    verbose: VerboseOpt = False,
):
    """General-info sections for one fund.

    Calls GET /api/vyk/fundDetail/{id}. Required argument: the fund id (from funds).

    Example: kap fund-detail 5900
    """
    _run(env, fmt, out, lambda c: c.fund_detail(fund_id), verbose=verbose)


@app.command("member-securities", short_help=_help("member-securities", "listed companies' securities (ISIN)"))
def member_securities(env: EnvOpt = None, fmt: FormatOpt = None, out: OutOpt = None, verbose: VerboseOpt = False):
    """Listed (IGS) companies with their securities (ISIN-level).

    Calls GET /api/vyk/memberSecurities. No inputs.

    Example: kap member-securities --out securities.csv
    """
    _run(env, fmt, out, lambda c: c.member_securities(), verbose=verbose)


@app.command("blocked-disclosures", short_help=_help("blocked-disclosures", "blocked disclosures"))
def blocked_disclosures(env: EnvOpt = None, fmt: FormatOpt = None, out: OutOpt = None, verbose: VerboseOpt = False):
    """Disclosures blocked from access in KAP.

    Calls GET /api/vyk/blockedDisclosures. No inputs.

    Example: kap blocked-disclosures
    """
    _run(env, fmt, out, lambda c: c.blocked_disclosures(), verbose=verbose)


@app.command("ca-event-status", short_help=_help("ca-event-status", "corporate-action status"))
def ca_event_status(
    ref_ids: Annotated[list[int], typer.Argument(help="One or more processRefId values.")],
    env: EnvOpt = None,
    fmt: FormatOpt = None,
    out: OutOpt = None,
    verbose: VerboseOpt = False,
):
    """Corporate-action (rights-usage) process status for the given ref ids.

    Calls GET /api/vyk/caEventStatus?processRefId=.... Required: one or more
    process ref ids, space-separated.

    Example: kap ca-event-status 111 222
    """
    _run(env, fmt, out, lambda c: c.ca_event_status(ref_ids), verbose=verbose)


@app.command(short_help=_help("raw", "probe any relative path"))
def raw(
    path: Annotated[str, typer.Argument(help="Relative path, e.g. api/vyk/members.")],
    query: Annotated[Optional[list[str]], typer.Option("--query", help="Query as key=value (repeatable).")] = None,
    env: EnvOpt = None,
    fmt: FormatOpt = None,
    out: OutOpt = None,
    verbose: VerboseOpt = False,
):
    """Raw exploration probe: call any relative path and dump the response.

    Calls GET /<path> on the active host (no retry, no parsing — returns status +
    body for inspection). Required argument: the relative path. Repeat --query
    key=value for query params.

    Example: kap raw api/vyk/members --query mkkMemberOid=4028
    """
    params: dict[str, str] = {}
    for item in query or []:
        if "=" not in item:
            raise typer.BadParameter(f"--query expects key=value, got '{item}'")
        key, value = item.split("=", 1)
        params[key] = value
    _run(env, fmt, out, lambda c: c.raw(path, params or None), verbose=verbose)


_TICKER_ARG = Annotated[str, typer.Argument(help="Stock ticker (e.g. ASELS) or a company-name fragment.")]
_FUND_ARG = Annotated[str, typer.Argument(help="Fund code (e.g. BON) or a fund-name fragment.")]
_LIMIT_OPT = Annotated[int, typer.Option("--limit", min=1, help="Max disclosures, newest first.")]


@app.command(
    "resolve-ticker",
    rich_help_panel=_UTIL_PANEL,
    short_help="[magenta]composite[/magenta]  ticker/name → companyId",
)
def resolve_ticker_cmd(
    query: _TICKER_ARG, env: EnvOpt = None, fmt: FormatOpt = None, out: OutOpt = None, verbose: VerboseOpt = False
):
    """Composite utility (not a single endpoint). Resolve a stock ticker or company-name
    fragment to its companyId + title.

    Calls GET /api/vyk/members and matches stockCode (exact) or title (substring).

    Example: kap resolve-ticker ASELS
    """
    with _errors(verbose):
        validate_format(fmt)
        with _make_client(env) as client:
            matches = resolve_company(client, query)
        output(matches, fmt=fmt, out=out)


@app.command(
    "resolve-fund",
    rich_help_panel=_UTIL_PANEL,
    short_help="[magenta]composite[/magenta]  fund code/name → fundId",
)
def resolve_fund_cmd(
    query: _FUND_ARG, env: EnvOpt = None, fmt: FormatOpt = None, out: OutOpt = None, verbose: VerboseOpt = False
):
    """Composite utility (not a single endpoint). Resolve a fund code or fund-name fragment to
    its fundId + name.

    Calls GET /api/vyk/funds and matches fundCode (exact) or fundName (substring).

    Example: kap resolve-fund BON
    """
    with _errors(verbose):
        validate_format(fmt)
        with _make_client(env) as client:
            matches = resolve_fund(client, query)
        output(matches, fmt=fmt, out=out)


@app.command(
    "ticker-disclosures",
    rich_help_panel=_UTIL_PANEL,
    short_help="[magenta]composite[/magenta]  ticker → recent disclosures (newest first)",
)
def ticker_disclosures_cmd(
    query: _TICKER_ARG,
    limit: _LIMIT_OPT = 20,
    env: EnvOpt = None,
    fmt: FormatOpt = None,
    out: OutOpt = None,
    verbose: VerboseOpt = False,
):
    """Composite utility (not a single endpoint). Recent disclosures for a ticker, newest first.

    Resolves the ticker via GET /api/vyk/members, then pages GET /api/vyk/disclosures backward
    from the latest index until --limit are collected.

    Example: kap ticker-disclosures ASELS --limit 20
    """
    with _errors(verbose):
        validate_format(fmt)
        with _make_client(env) as client:
            company = resolve_one(resolve_company(client, query), query, "ticker", _describe_company)
            result = scan_disclosures(client, company["id"], limit)
        _render_scan(fmt, out, result)


@app.command(
    "ticker-financials",
    rich_help_panel=_UTIL_PANEL,
    short_help="[magenta]composite[/magenta]  ticker → recent FR filings (newest first)",
)
def ticker_financials_cmd(
    query: _TICKER_ARG,
    limit: _LIMIT_OPT = 20,
    env: EnvOpt = None,
    fmt: FormatOpt = None,
    out: OutOpt = None,
    verbose: VerboseOpt = False,
):
    """Composite utility (not a single endpoint). Recent financial-report (FR-class) filings for
    a ticker, newest first.

    Resolves the ticker via GET /api/vyk/members, then pages GET /api/vyk/disclosures?disclosureClass=FR
    backward from the latest index until --limit are collected.

    Example: kap ticker-financials ASELS
    """
    with _errors(verbose):
        validate_format(fmt)
        with _make_client(env) as client:
            company = resolve_one(resolve_company(client, query), query, "ticker", _describe_company)
            result = scan_disclosures(client, company["id"], limit, disclosure_class="FR")
        _render_scan(fmt, out, result)


@app.command(
    "fund-info",
    rich_help_panel=_UTIL_PANEL,
    short_help="[magenta]composite[/magenta]  fund code/name → fund detail",
)
def fund_info_cmd(
    query: _FUND_ARG, env: EnvOpt = None, fmt: FormatOpt = None, out: OutOpt = None, verbose: VerboseOpt = False
):
    """Composite utility (not a single endpoint). General-info sections for a fund, by code or name.

    Resolves the fund via GET /api/vyk/funds, then calls GET /api/vyk/fundDetail/{id}.

    Example: kap fund-info BON
    """
    with _errors(verbose):
        validate_format(fmt)
        with _make_client(env) as client:
            fund = resolve_one(resolve_fund(client, query), query, "fund", _describe_fund)
            data = client.fund_detail(fund["fundId"])
        output(data, fmt=fmt, out=out)


@app.command(
    "fund-disclosures",
    rich_help_panel=_UTIL_PANEL,
    short_help="[magenta]composite[/magenta]  fund's mgmt company → recent disclosures",
)
def fund_disclosures_cmd(
    query: _FUND_ARG,
    limit: _LIMIT_OPT = 20,
    env: EnvOpt = None,
    fmt: FormatOpt = None,
    out: OutOpt = None,
    verbose: VerboseOpt = False,
):
    """Composite utility (not a single endpoint). Recent disclosures for a fund, newest first.

    Resolves the fund via GET /api/vyk/funds, then pages GET /api/vyk/disclosures backward by the
    fund's company id (fundCompanyId).

    Note: KAP files disclosures under the management company, not per fund — results cover ALL
    funds managed by the same company as the queried fund, not just that one fund.

    Example: kap fund-disclosures BON --limit 20
    """
    with _errors(verbose):
        validate_format(fmt)
        with _make_client(env) as client:
            fund = resolve_one(resolve_fund(client, query), query, "fund", _describe_fund)
            result = scan_disclosures(client, fund["fundCompanyId"], limit)
        _render_scan(fmt, out, result)


_PERIOD_RE_CLI = re.compile(r"^\d{4}-\d{2}$")


def _validate_period_range(from_period: Optional[str], to_period: Optional[str]) -> None:
    """Validate --from/--to are YYYY-MM and correctly ordered (raises typer.BadParameter)."""
    for label, value in (("--from", from_period), ("--to", to_period)):
        if value is not None and not _PERIOD_RE_CLI.match(value):
            raise typer.BadParameter(f"{label} must be YYYY-MM, got '{value}'")
    if from_period is not None and to_period is not None and from_period > to_period:
        raise typer.BadParameter(f"--from ({from_period}) is after --to ({to_period})")


@app.command(
    "fund-portfolio-report",
    rich_help_panel=_UTIL_PANEL,
    short_help="[magenta]composite[/magenta]  fund → Portföy Dağılım Raporu",
)
def fund_portfolio_report_cmd(
    query: _FUND_ARG,
    from_period: Annotated[Optional[str], typer.Option("--from", help="Start report period, YYYY-MM.")] = None,
    to_period: Annotated[Optional[str], typer.Option("--to", help="End report period, YYYY-MM.")] = None,
    env: EnvOpt = None,
    fmt: FormatOpt = None,
    out: OutOpt = None,
    verbose: VerboseOpt = False,
):
    """Composite utility (not a single endpoint). A fund's Portföy Dağılım Raporu (portfolio allocation report).

    What it does:

    1. Resolve the fund to its management-company id — GET /api/vyk/funds

    2. Read the latest disclosure index — GET /api/vyk/lastDisclosureIndex

    3. Scan that company's disclosures backward (forward-paginated per window so recent filings aren't missed), keeping disclosureType=FON — GET /api/vyk/disclosures

    4. Open each candidate and keep those whose subject is "Portföy Dağılım Raporu" for THIS fund — GET /api/vyk/disclosureDetail

    No range returns the latest report; --from/--to (YYYY-MM, by report period) return all in that range. Note: this fans out into many detail calls, so a wide range can be slow.

    Examples:

    kap fund-portfolio-report BON

    kap fund-portfolio-report BON --from 2026-01 --to 2026-06
    """
    _validate_period_range(from_period, to_period)
    with _errors(verbose):
        validate_format(fmt)
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
        if result.truncated:
            _err_console.print(
                "[yellow]Note:[/yellow] scan bound hit (max windows/details); results may be "
                "incomplete — narrow the --from/--to range."
            )
        output(result.items, fmt=fmt, out=out)


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
    _validate_period_range(from_period, to_period)
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
                    tag = item.get("period") or item["disclosureIndex"]
                    _err_console.print(f"[yellow]Note:[/yellow] {tag} has no PDF attachment — skipped.")
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
