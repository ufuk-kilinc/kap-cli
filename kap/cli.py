from __future__ import annotations

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

# Force UTF-8 so Turkish help text and disclosure data never crash on a
# cp1252 (default Windows) terminal.
for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure is not None:
        try:
            _reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass

# Command → KAP endpoint, rendered as an aligned yellow column in kap --help.
_ENDPOINTS: list[tuple[str, str]] = [
    ("last-index", "GET /api/vyk/lastDisclosureIndex"),
    ("disclosures", "GET /api/vyk/disclosures"),
    ("disclosure-detail", "GET /api/vyk/disclosureDetail/{index}"),
    ("download-attachment", "GET /api/vyk/downloadAttachment/{id}"),
    ("members", "GET /api/vyk/members"),
    ("funds", "GET /api/vyk/funds"),
    ("fund-detail", "GET /api/vyk/fundDetail/{id}"),
    ("member-securities", "GET /api/vyk/memberSecurities"),
    ("blocked-disclosures", "GET /api/vyk/blockedDisclosures"),
    ("ca-event-status", "GET /api/vyk/caEventStatus"),
    ("raw", "GET /<path>"),
]
_cmd_w = max(len(name) for name, _ in _ENDPOINTS)
_endpoint_block = "\n\n".join(
    f"[cyan]{name.ljust(_cmd_w)}[/cyan]   [yellow]{endpoint}[/yellow]"
    for name, endpoint in _ENDPOINTS
)

_EPILOG = (
    "Set your API key in [cyan]~/.kap/.env[/cyan] (KAP_PROD_API_KEY / KAP_TEST_API_KEY). "
    "Run [cyan]kap COMMAND --help[/cyan] for a command's own arguments.\n\n"
    "[bold]Common options[/bold] (on every command, placed AFTER it — e.g. "
    "[cyan]kap members --format json[/cyan]):  [cyan]-f/--format[/cyan] \\[table|json|csv], "
    "[cyan]-o/--out[/cyan] PATH, [cyan]--env[/cyan] \\[test|production], [cyan]-v/--verbose[/cyan].\n\n"
    "[bold]Endpoint called by each command:[/bold]\n\n" + _endpoint_block
)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="CLI for the KAP (Borsa Istanbul) disclosure data API.",
    epilog=_EPILOG,
)
_err_console = Console(stderr=True)

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


@app.command("last-index")
def last_index(env: EnvOpt = None, fmt: FormatOpt = None, out: OutOpt = None, verbose: VerboseOpt = False):
    """Latest published disclosure id (a market-wide cursor).

    Calls GET /api/vyk/lastDisclosureIndex. No inputs. Returns a single number —
    the id of the newest disclosure across all of KAP. Feed it to disclosures as
    --index, or poll it to detect new filings.

    Example: kap last-index
    """
    _run(env, fmt, out, lambda c: c.last_disclosure_index(), verbose=verbose)


@app.command()
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


@app.command("disclosure-detail")
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


@app.command("download-attachment")
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


@app.command()
def members(env: EnvOpt = None, fmt: FormatOpt = None, out: OutOpt = None, verbose: VerboseOpt = False):
    """All KAP-member companies (id, title, stock code, type).

    Calls GET /api/vyk/members. No inputs. The id here is the companyId used by
    disclosures --company-id.

    Example: kap members --out members.csv
    """
    _run(env, fmt, out, lambda c: c.members(), verbose=verbose)


@app.command()
def funds(env: EnvOpt = None, fmt: FormatOpt = None, out: OutOpt = None, verbose: VerboseOpt = False):
    """All funds.

    Calls GET /api/vyk/funds. No inputs. A fund's id feeds fund-detail.

    Example: kap funds --format json
    """
    _run(env, fmt, out, lambda c: c.funds(), verbose=verbose)


@app.command("fund-detail")
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


@app.command("member-securities")
def member_securities(env: EnvOpt = None, fmt: FormatOpt = None, out: OutOpt = None, verbose: VerboseOpt = False):
    """Listed (IGS) companies with their securities (ISIN-level).

    Calls GET /api/vyk/memberSecurities. No inputs.

    Example: kap member-securities --out securities.csv
    """
    _run(env, fmt, out, lambda c: c.member_securities(), verbose=verbose)


@app.command("blocked-disclosures")
def blocked_disclosures(env: EnvOpt = None, fmt: FormatOpt = None, out: OutOpt = None, verbose: VerboseOpt = False):
    """Disclosures blocked from access in KAP.

    Calls GET /api/vyk/blockedDisclosures. No inputs.

    Example: kap blocked-disclosures
    """
    _run(env, fmt, out, lambda c: c.blocked_disclosures(), verbose=verbose)


@app.command("ca-event-status")
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


@app.command()
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
