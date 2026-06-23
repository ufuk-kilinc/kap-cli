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
