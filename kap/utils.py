from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from kap.client import JsonObj, KapClient


def _dedupe(rows: list[JsonObj], key: str) -> list[JsonObj]:
    """Drop rows with a duplicate value for `key` (KAP returns exact-duplicate rows), keeping order."""
    seen: set = set()
    out: list[JsonObj] = []
    for row in rows:
        k = row.get(key)
        if k in seen:
            continue
        seen.add(k)
        out.append(row)
    return out


def _codes(value) -> set[str]:
    """A code cell may be comma-joined (e.g. 'AKM, AKMEN'); return the uppercase token set."""
    return {c.strip().upper() for c in str(value or "").split(",") if c.strip()}


def resolve_company(client: KapClient, query: str) -> list[JsonObj]:
    """Resolve a stock ticker or company-name fragment to member rows.

    Exact stockCode token match (case-insensitive; the field may be comma-joined) wins; otherwise
    a case-insensitive substring match on the company title. Deduped by company id.
    """
    q = query.strip().upper()
    members = client.members()
    exact = [m for m in members if q in _codes(m.get("stockCode"))]
    matches = exact if exact else [m for m in members if q in str(m.get("title") or "").upper()]
    return _dedupe(matches, "id")


def resolve_fund(client: KapClient, query: str) -> list[JsonObj]:
    """Resolve a fund code or fund-name fragment to fund rows.

    Exact fundCode token match (case-insensitive; the field may be comma-joined) wins; otherwise a
    case-insensitive substring match on the fund name. Deduped by fundId.
    """
    q = query.strip().upper()
    funds = client.funds()
    exact = [f for f in funds if q in _codes(f.get("fundCode"))]
    matches = exact if exact else [f for f in funds if q in str(f.get("fundName") or "").upper()]
    return _dedupe(matches, "fundId")


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


_PERIOD_RE = re.compile(r"(\d{4})\s*/\s*(\d+)\s*\.?\s*Ay")
_PDR_SUBJECT = "Portföy Dağılım Raporu"


def parse_report_period(detail: JsonObj) -> str | None:
    """Extract the report period as 'YYYY-MM' from a disclosure detail's Turkish summary."""
    summary = detail.get("summary") if isinstance(detail, dict) else None
    text = summary.get("tr") if isinstance(summary, dict) else None
    if not isinstance(text, str):
        return None
    match = _PERIOD_RE.search(text)
    if not match:
        return None
    return f"{match.group(1)}-{int(match.group(2)):02d}"


def _enumerate_window(client: KapClient, company_id: str | int, win_start: int, win_end: int) -> list[JsonObj]:
    """All of a company's disclosure rows with win_start <= disclosureIndex <= win_end.

    Forward-paginates (cur -> max index + 1) so it isn't limited by the API's 50-row page cap.
    """
    cur = win_start
    rows: list[JsonObj] = []
    while cur <= win_end:
        page = client.disclosures(cur, company_id=company_id)
        page = [r for r in page if int(r["disclosureIndex"]) <= win_end]
        if not page:
            break
        rows.extend(page)
        hi = max(int(r["disclosureIndex"]) for r in page)
        if len(page) < 50 or hi <= cur:
            break
        cur = hi + 1
    return rows
