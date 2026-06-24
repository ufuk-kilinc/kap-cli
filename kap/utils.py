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


def _row_idx(row: JsonObj) -> int | None:
    """Parse a row's disclosureIndex to int, or None if missing/non-numeric (skip such rows)."""
    try:
        return int(row["disclosureIndex"])
    except (KeyError, TypeError, ValueError):
        return None


def _enumerate_window(client: KapClient, company_id: str | int, win_start: int, win_end: int) -> list[JsonObj]:
    """All of a company's disclosure rows with win_start <= disclosureIndex <= win_end.

    Forward-paginates (cur -> max index + 1) so it isn't limited by the API's 50-row page cap.
    """
    cur = win_start
    rows: list[JsonObj] = []
    while cur <= win_end:
        raw_page = client.disclosures(cur, company_id=company_id)
        page = []
        for r in raw_page:
            idx = _row_idx(r)
            if idx is not None and idx <= win_end:
                page.append((idx, r))
        if not page:
            break
        rows.extend(r for _, r in page)
        hi = max(idx for idx, _ in page)
        if len(page) < 50 or hi <= cur:
            break
        cur = hi + 1
    return rows


@dataclass
class PortfolioReportResult:
    items: list[JsonObj]
    truncated: bool
    details_fetched: int


def find_fund_portfolio_reports(
    client: KapClient,
    fund_code: str,
    company_id: str | int,
    *,
    from_period: str | None = None,
    to_period: str | None = None,
    window: int = 36000,
    max_windows: int = 60,
    max_details: int = 400,
) -> PortfolioReportResult:
    """Find a fund's Portföy Dağılım Raporu disclosure(s).

    Scans the management company's disclosures backward (newest window first), forward-paginating
    each window, and opens FON candidates newest-first to match subject + behalfFundCode. No range →
    the latest report (stops at first match); a range → all matches with period in [from, to].
    """
    target = str(fund_code).strip().upper()
    last = client.last_disclosure_index()
    range_mode = from_period is not None or to_period is not None
    items: list[JsonObj] = []
    seen: set[int] = set()
    details = 0
    truncated = False
    done = False
    win_end = last
    windows = 0

    while win_end >= 0 and windows < max_windows and not done:
        win_start = max(0, win_end - window)
        rows = _enumerate_window(client, company_id, win_start, win_end)
        fon = [
            (idx, r)
            for r in rows
            if r.get("disclosureType") == "FON" and (idx := _row_idx(r)) is not None
        ]
        fon.sort(key=lambda pair: pair[0], reverse=True)
        for idx, row in fon:
            if idx in seen:
                continue
            if details >= max_details:
                truncated = done = True
                break
            detail = client.disclosure_detail(idx)
            details += 1
            if not detail:
                continue
            subject = detail.get("subject") if isinstance(detail, dict) else None
            subj_tr = subject.get("tr") if isinstance(subject, dict) else None
            if subj_tr != _PDR_SUBJECT:
                continue
            if str(detail.get("behalfFundCode") or "").strip().upper() != target:
                continue
            period = parse_report_period(detail)
            item: JsonObj = {
                "disclosureIndex": idx,
                "period": period,
                "fundCode": detail.get("behalfFundCode"),
                "fundTitle": detail.get("behalfFundTitle"),
                "presentation": detail.get("presentation"),
            }
            if not range_mode:
                return PortfolioReportResult(items=[item], truncated=False, details_fetched=details)
            if from_period is not None and period is not None and period < from_period:
                done = True
                break
            if to_period is not None and period is not None and period > to_period:
                continue  # newer than the range; keep scanning back
            if period is None:
                continue  # can't place an undated report in a range
            seen.add(idx)
            items.append(item)
        if win_start == 0:
            break
        win_end = win_start - 1
        windows += 1

    if windows >= max_windows and not done:
        truncated = True
    return PortfolioReportResult(items=items, truncated=truncated, details_fetched=details)
