from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from kap.client import JsonObj, KapClient


def resolve_company(client: KapClient, query: str) -> list[JsonObj]:
    """Resolve a stock ticker or company-name fragment to member rows.

    Exact stockCode match (case-insensitive) wins; otherwise a case-insensitive
    substring match on the company title. Returns all matches.
    """
    q = query.strip().upper()
    members = client.members()
    exact = [m for m in members if str(m.get("stockCode") or "").upper() == q]
    if exact:
        return exact
    return [m for m in members if q in str(m.get("title") or "").upper()]


def resolve_fund(client: KapClient, query: str) -> list[JsonObj]:
    """Resolve a fund code or fund-name fragment to fund rows.

    Exact fundCode match (case-insensitive) wins; otherwise a case-insensitive
    substring match on the fund name. Returns all matches.
    """
    q = query.strip().upper()
    funds = client.funds()
    exact = [f for f in funds if str(f.get("fundCode") or "").upper() == q]
    if exact:
        return exact
    return [f for f in funds if q in str(f.get("fundName") or "").upper()]


def resolve_one(matches: list[JsonObj], query: str, what: str, describe: Callable[[JsonObj], str]) -> JsonObj:
    """Return the single match, or raise ValueError for 0 (not found) / >1 (ambiguous)."""
    if not matches:
        raise ValueError(f"No {what} matching '{query}'.")
    if len(matches) > 1:
        shown = "; ".join(describe(m) for m in matches[:8])
        more = "" if len(matches) <= 8 else f" (+{len(matches) - 8} more)"
        raise ValueError(
            f"'{query}' is ambiguous — {len(matches)} {what} matches: {shown}{more}. "
            "Narrow it or use the exact code."
        )
    return matches[0]


@dataclass
class ScanResult:
    items: list[JsonObj]
    truncated: bool
    windows: int


def scan_disclosures(
    client: KapClient,
    company_id: str | int,
    limit: int,
    disclosure_class: str | None = None,
    *,
    window: int = 36000,
    max_windows: int = 30,
) -> ScanResult:
    """Collect an entity's most recent disclosures by walking BACKWARD from the latest index.

    The disclosures endpoint scans a bounded ~36k-index window forward from a start index and
    caps at 50; this tiles windows backward from last-index, deduping by disclosureIndex, until
    `limit` are gathered (or `max_windows` is reached). Returns newest-first.
    """
    last = client.last_disclosure_index()
    found: dict[int, JsonObj] = {}
    truncated = False
    start = max(0, last - window)
    windows = 0
    while len(found) < limit and windows < max_windows:
        page = client.disclosures(start, disclosure_class=disclosure_class, company_id=company_id)
        if len(page) >= 50:
            truncated = True
        for item in page:
            try:
                idx = int(item["disclosureIndex"])
            except (KeyError, TypeError, ValueError):
                continue
            found[idx] = item
        windows += 1
        if start == 0:
            break
        start = max(0, start - window)
    ordered = [item for _, item in sorted(found.items(), key=lambda kv: kv[0], reverse=True)]
    return ScanResult(items=ordered[:limit], truncated=truncated, windows=windows)
