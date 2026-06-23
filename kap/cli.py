from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from kap.client import KapClient
from kap.config import load_config
from kap.errors import KapError
from kap.render import decode_disclosure_bodies, output

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="CLI for the KAP Veri Yayın Servisi REST API (MKK / Borsa İstanbul).",
)
_err_console = Console(stderr=True)


@dataclass
class State:
    env: Optional[str] = None
    fmt: Optional[str] = None
    out: Optional[Path] = None
    verbose: bool = False


@app.callback()
def main(
    ctx: typer.Context,
    env: Optional[str] = typer.Option(None, "--env", help="test | production (overrides .env)."),
    fmt: Optional[str] = typer.Option(None, "--format", "-f", help="table | json | csv."),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Write output to this file."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show full error detail."),
):
    ctx.obj = State(env=env, fmt=fmt, out=out, verbose=verbose)


def _make_client(ctx: typer.Context) -> KapClient:
    return KapClient(load_config(ctx.obj.env))


def _run(ctx: typer.Context, fn, *, decode: bool = False, raw_bytes: bool = False, default_name: str | None = None):
    """Execute a client call, render output, and translate errors to clean exits."""
    state: State = ctx.obj
    try:
        client = _make_client(ctx)
        try:
            data = fn(client)
        finally:
            client.close()
    except KapError as exc:
        typer.echo(str(exc), err=False)
        raise typer.Exit(code=1)

    if raw_bytes:
        if data is None:
            _err_console.print("[yellow]Not found.[/yellow]")
            raise typer.Exit(code=1)
        target = state.out or Path(default_name or "attachment.pdf")
        target.write_bytes(data)
        print(f"Saved {len(data)} bytes to {target}")
        return

    if decode and isinstance(data, dict):
        data = decode_disclosure_bodies(data)
    output(data, fmt=state.fmt, out=state.out)


@app.command("last-index")
def last_index(ctx: typer.Context):
    """Latest published disclosure id (use as a polling cursor)."""
    _run(ctx, lambda c: c.last_disclosure_index())


@app.command()
def disclosures(
    ctx: typer.Context,
    index: int = typer.Option(..., "--index", help="Start disclosure index (required)."),
    type_: Optional[str] = typer.Option(None, "--type", help="disclosureType filter."),
    class_: Optional[str] = typer.Option(None, "--class", help="disclosureClass filter (e.g. FR)."),
    company_id: Optional[int] = typer.Option(None, "--company-id", help="companyId filter."),
):
    """First 50 disclosures from --index onward (optionally filtered)."""
    _run(ctx, lambda c: c.disclosures(index, type_, class_, company_id))


@app.command("disclosure-detail")
def disclosure_detail(
    ctx: typer.Context,
    index: int = typer.Argument(..., help="Disclosure index."),
    file_type: str = typer.Option("data", "--file-type", help="data | html."),
    sub_report: Optional[str] = typer.Option(None, "--sub-report", help="subReportList id."),
):
    """Full detail for one disclosure (base64 bodies decoded to readable text)."""
    _run(ctx, lambda c: c.disclosure_detail(index, file_type, sub_report), decode=True)


@app.command("download-attachment")
def download_attachment(
    ctx: typer.Context,
    attachment_id: str = typer.Argument(..., help="Attachment id (last path segment of an attachment url)."),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Write PDF to this file path."),
):
    """Download a disclosure attachment PDF (Java envelope auto-unwrapped)."""
    # local --out overrides the global one for raw-bytes commands
    if out is not None:
        ctx.obj.out = out
    _run(ctx, lambda c: c.download_attachment(attachment_id),
         raw_bytes=True, default_name=f"{attachment_id}.pdf")


@app.command()
def members(ctx: typer.Context):
    """All KAP-member companies."""
    _run(ctx, lambda c: c.members())


@app.command()
def funds(ctx: typer.Context):
    """All funds."""
    _run(ctx, lambda c: c.funds())


@app.command("fund-detail")
def fund_detail(ctx: typer.Context, fund_id: int = typer.Argument(..., help="Fund id.")):
    """General-info sections for one fund."""
    _run(ctx, lambda c: c.fund_detail(fund_id))


@app.command("member-securities")
def member_securities(ctx: typer.Context):
    """Listed (IGS) companies with their securities (ISIN-level)."""
    _run(ctx, lambda c: c.member_securities())


@app.command("blocked-disclosures")
def blocked_disclosures(ctx: typer.Context):
    """Disclosures blocked from access in KAP."""
    _run(ctx, lambda c: c.blocked_disclosures())


@app.command("ca-event-status")
def ca_event_status(
    ctx: typer.Context,
    ref_ids: list[int] = typer.Argument(..., help="One or more processRefId values."),
):
    """Corporate-action (rights-usage) process status for the given ref ids."""
    _run(ctx, lambda c: c.ca_event_status(ref_ids))


@app.command()
def raw(
    ctx: typer.Context,
    path: str = typer.Argument(..., help="Relative path, e.g. api/vyk/members."),
    query: list[str] = typer.Option([], "--query", help="Query as key=value (repeatable)."),
):
    """Raw exploration probe: call any relative path and dump the response."""
    params = {}
    for item in query:
        if "=" in item:
            k, v = item.split("=", 1)
            params[k] = v
    _run(ctx, lambda c: c.raw(path, params or None))
