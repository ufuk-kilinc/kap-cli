from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from kap.client import KapClient
from kap.config import load_config
from kap.errors import KapError
from kap.render import decode_disclosure_bodies, output

# Force UTF-8 so Turkish help text and disclosure data never crash on a
# cp1252 (default Windows) terminal.
for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure is not None:
        try:
            _reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="CLI for the KAP (Borsa Istanbul) disclosure data API.",
)
_err_console = Console(stderr=True)

# Shared output options — available AFTER each command, e.g. `kap members --format json`.
EnvOpt = Annotated[Optional[str], typer.Option("--env", help="test | production (overrides .env).")]
FormatOpt = Annotated[Optional[str], typer.Option("--format", "-f", help="table | json | csv.")]
OutOpt = Annotated[Optional[Path], typer.Option("--out", "-o", help="Write output to this file.")]
VerboseOpt = Annotated[bool, typer.Option("--verbose", "-v", help="Show full error detail.")]


def _make_client(env: Optional[str]) -> KapClient:
    return KapClient(load_config(env))


def _run(env, fmt, out, fn, *, decode: bool = False) -> None:
    try:
        client = _make_client(env)
        try:
            data = fn(client)
        finally:
            client.close()
    except (KapError, ValueError) as exc:
        _err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)
    if decode and isinstance(data, dict):
        data = decode_disclosure_bodies(data)
    output(data, fmt=fmt, out=out)


def _save_bytes(env, out, fn, default_name: str) -> None:
    try:
        client = _make_client(env)
        try:
            data = fn(client)
        finally:
            client.close()
    except (KapError, ValueError) as exc:
        _err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)
    if data is None:
        _err_console.print("[yellow]Not found.[/yellow]")
        raise typer.Exit(code=1)
    target = out or Path(default_name)
    target.write_bytes(data)
    print(f"Saved {len(data)} bytes to {target}")


@app.command("last-index")
def last_index(env: EnvOpt = None, fmt: FormatOpt = None, out: OutOpt = None, verbose: VerboseOpt = False):
    """Latest published disclosure id (use as a polling cursor)."""
    _run(env, fmt, out, lambda c: c.last_disclosure_index())


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
    """First 50 disclosures from --index onward (optionally filtered)."""
    _run(env, fmt, out, lambda c: c.disclosures(index, type_, class_, company_id))


@app.command("disclosure-detail")
def disclosure_detail(
    index: Annotated[int, typer.Argument(help="Disclosure index.")],
    file_type: Annotated[str, typer.Option("--file-type", help="data | html.")] = "data",
    sub_report: Annotated[Optional[str], typer.Option("--sub-report", help="subReportList id.")] = None,
    env: EnvOpt = None,
    fmt: FormatOpt = None,
    out: OutOpt = None,
    verbose: VerboseOpt = False,
):
    """Full detail for one disclosure (base64 bodies decoded to readable text)."""
    _run(env, fmt, out, lambda c: c.disclosure_detail(index, file_type, sub_report), decode=True)


@app.command("download-attachment")
def download_attachment(
    attachment_id: Annotated[str, typer.Argument(help="Attachment id (last path segment of an attachment url).")],
    out: OutOpt = None,
    env: EnvOpt = None,
):
    """Download a disclosure attachment PDF (Java envelope auto-unwrapped)."""
    _save_bytes(env, out, lambda c: c.download_attachment(attachment_id), f"{attachment_id}.pdf")


@app.command()
def members(env: EnvOpt = None, fmt: FormatOpt = None, out: OutOpt = None, verbose: VerboseOpt = False):
    """All KAP-member companies."""
    _run(env, fmt, out, lambda c: c.members())


@app.command()
def funds(env: EnvOpt = None, fmt: FormatOpt = None, out: OutOpt = None, verbose: VerboseOpt = False):
    """All funds."""
    _run(env, fmt, out, lambda c: c.funds())


@app.command("fund-detail")
def fund_detail(
    fund_id: Annotated[int, typer.Argument(help="Fund id.")],
    env: EnvOpt = None,
    fmt: FormatOpt = None,
    out: OutOpt = None,
    verbose: VerboseOpt = False,
):
    """General-info sections for one fund."""
    _run(env, fmt, out, lambda c: c.fund_detail(fund_id))


@app.command("member-securities")
def member_securities(env: EnvOpt = None, fmt: FormatOpt = None, out: OutOpt = None, verbose: VerboseOpt = False):
    """Listed (IGS) companies with their securities (ISIN-level)."""
    _run(env, fmt, out, lambda c: c.member_securities())


@app.command("blocked-disclosures")
def blocked_disclosures(env: EnvOpt = None, fmt: FormatOpt = None, out: OutOpt = None, verbose: VerboseOpt = False):
    """Disclosures blocked from access in KAP."""
    _run(env, fmt, out, lambda c: c.blocked_disclosures())


@app.command("ca-event-status")
def ca_event_status(
    ref_ids: Annotated[list[int], typer.Argument(help="One or more processRefId values.")],
    env: EnvOpt = None,
    fmt: FormatOpt = None,
    out: OutOpt = None,
    verbose: VerboseOpt = False,
):
    """Corporate-action (rights-usage) process status for the given ref ids."""
    _run(env, fmt, out, lambda c: c.ca_event_status(ref_ids))


@app.command()
def raw(
    path: Annotated[str, typer.Argument(help="Relative path, e.g. api/vyk/members.")],
    query: Annotated[Optional[list[str]], typer.Option("--query", help="Query as key=value (repeatable).")] = None,
    env: EnvOpt = None,
    fmt: FormatOpt = None,
    out: OutOpt = None,
    verbose: VerboseOpt = False,
):
    """Raw exploration probe: call any relative path and dump the response."""
    params: dict[str, str] = {}
    for item in query or []:
        if "=" in item:
            key, value = item.split("=", 1)
            params[key] = value
    _run(env, fmt, out, lambda c: c.raw(path, params or None))
