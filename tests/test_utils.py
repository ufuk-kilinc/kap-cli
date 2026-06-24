import pytest

from kap.utils import ScanResult, parse_report_period, _enumerate_window, resolve_company, resolve_fund, resolve_one, scan_disclosures
from kap.utils import PortfolioReportResult, find_fund_portfolio_reports


class FakeClient:
    def __init__(self, members=None, funds=None, pages=None, last=0, details=None):
        self._members = members or []
        self._funds = funds or []
        self._pages = pages or {}
        self._last = last
        self._details = details or {}
        self.calls = []

    def members(self):
        return self._members

    def funds(self):
        return self._funds

    def last_disclosure_index(self):
        return self._last

    def disclosures(self, index, *, disclosure_type=None, disclosure_class=None, company_id=None):
        self.calls.append((index, disclosure_class, company_id))
        return self._pages.get(index, [])

    def disclosure_detail(self, index, file_type="data", sub_report=None):
        return self._details.get(int(index))


_MEMBERS = [
    {"id": "866", "stockCode": "ASELS", "title": "ASELSAN ELEKTRONIK SANAYI VE TICARET A.S."},
    {"id": "1107", "stockCode": "THYAO", "title": "TURK HAVA YOLLARI A.O."},
    {"id": "200", "stockCode": "AKBNK", "title": "AKBANK T.A.S."},
]
_FUNDS = [
    {"fundId": 5758, "fundCode": "BON", "fundName": "A1 CAPITAL PORTFOY BORCLANMA ARACLARI FONU", "fundCompanyId": 700},
    {"fundId": 5815, "fundCode": "DGF", "fundName": "A1 CAPITAL PORTFOY DEGISKEN FON", "fundCompanyId": 700},
]


def test_resolve_company_exact_ticker_case_insensitive():
    out = resolve_company(FakeClient(members=_MEMBERS), "asels")
    assert len(out) == 1 and out[0]["id"] == "866"


def test_resolve_company_partial_name():
    out = resolve_company(FakeClient(members=_MEMBERS), "turk hava")
    assert [m["stockCode"] for m in out] == ["THYAO"]


def test_resolve_company_not_found_returns_empty():
    assert resolve_company(FakeClient(members=_MEMBERS), "ZZZZ") == []


def test_resolve_company_exact_beats_partial():
    # query equals a stockCode → only the exact row, even if it also appears in a title
    out = resolve_company(FakeClient(members=_MEMBERS), "AKBNK")
    assert len(out) == 1 and out[0]["stockCode"] == "AKBNK"


def test_resolve_fund_exact_code():
    out = resolve_fund(FakeClient(funds=_FUNDS), "bon")
    assert len(out) == 1 and out[0]["fundId"] == 5758


def test_resolve_fund_partial_name_multiple():
    out = resolve_fund(FakeClient(funds=_FUNDS), "A1 CAPITAL")
    assert {f["fundCode"] for f in out} == {"BON", "DGF"}


def test_resolve_one_single_returns_it():
    assert resolve_one([{"x": 1}], "q", "ticker", lambda m: "x")["x"] == 1


def test_resolve_one_zero_raises():
    with pytest.raises(ValueError, match="No ticker matching"):
        resolve_one([], "ZZZ", "ticker", lambda m: "x")


def test_resolve_one_multiple_raises_with_list():
    matches = [{"fundCode": "BON"}, {"fundCode": "DGF"}]
    with pytest.raises(ValueError, match="ambiguous"):
        resolve_one(matches, "A1", "fund", lambda f: f["fundCode"])


def _d(idx):
    return {"disclosureIndex": str(idx), "title": f"d{idx}"}


def test_scan_collects_newest_first_to_limit():
    # window=50, last=200 → starts 150, 100, 50, 0
    pages = {150: [_d(180), _d(160)], 100: [_d(120)], 50: [_d(70)], 0: [_d(10)]}
    client = FakeClient(pages=pages, last=200)
    result = scan_disclosures(client, "C", limit=3, window=50, max_windows=10)
    assert isinstance(result, ScanResult)
    assert [d["disclosureIndex"] for d in result.items] == ["180", "160", "120"]
    assert result.truncated is False


def test_scan_dedupes_overlapping_windows():
    pages = {150: [_d(180)], 100: [_d(180), _d(120)]}
    client = FakeClient(pages=pages, last=200)
    result = scan_disclosures(client, "C", limit=10, window=50, max_windows=2)
    idxs = [d["disclosureIndex"] for d in result.items]
    assert idxs == ["180", "120"]  # 180 not duplicated


def test_scan_passes_disclosure_class_and_company_id():
    client = FakeClient(pages={0: [_d(1)]}, last=10)
    scan_disclosures(client, "866", limit=5, disclosure_class="FR", window=50)
    assert client.calls[0] == (0, "FR", "866")


def test_scan_respects_max_windows():
    client = FakeClient(pages={}, last=10_000)
    scan_disclosures(client, "C", limit=99, window=100, max_windows=3)
    assert len(client.calls) == 3


def test_scan_sets_truncated_when_window_returns_50():
    client = FakeClient(pages={0: [_d(i) for i in range(50)]}, last=10)
    result = scan_disclosures(client, "C", limit=5, window=50)
    assert result.truncated is True


def test_resolve_company_handles_comma_joined_stockcode():
    members = [{"id": "9", "stockCode": "AKM, AKMEN", "title": "AKMERKEZ GMYO"}]
    out = resolve_company(FakeClient(members=members), "AKMEN")
    assert len(out) == 1 and out[0]["id"] == "9"


def test_resolve_company_dedupes_duplicate_id():
    row = {"id": "2413", "stockCode": "AKBNK", "title": "AKBANK T.A.S."}
    out = resolve_company(FakeClient(members=[dict(row), dict(row)]), "AKBNK")
    assert len(out) == 1 and out[0]["id"] == "2413"


def test_resolve_fund_dedupes_duplicate_fundid():
    row = {"fundId": 5758, "fundCode": "BON", "fundName": "TEST FON", "fundCompanyId": 700}
    out = resolve_fund(FakeClient(funds=[dict(row), dict(row)]), "BON")
    assert len(out) == 1


def test_scan_last_less_than_window():
    client = FakeClient(pages={0: [_d(5)]}, last=10)
    result = scan_disclosures(client, "C", limit=5, window=50)
    assert [d["disclosureIndex"] for d in result.items] == ["5"]


def test_scan_all_empty_pages_returns_empty():
    client = FakeClient(pages={}, last=200)
    result = scan_disclosures(client, "C", limit=5, window=50, max_windows=3)
    assert result.items == [] and result.windows == 3


def _fon(idx):
    return {"disclosureIndex": str(idx), "disclosureType": "FON"}


def test_parse_report_period_from_summary():
    detail = {"summary": {"tr": "2026 / 3.Ay Portföy Dağılım Raporu\n", "en": None}}
    assert parse_report_period(detail) == "2026-03"


def test_parse_report_period_none_on_garbage():
    assert parse_report_period({"summary": {"tr": "nope"}}) is None
    assert parse_report_period({}) is None


def test_enumerate_window_paginates_past_50_cap():
    # company has 60 rows (1..60); a single call caps at 50, so we must page to get all
    pages = {1: [_fon(i) for i in range(1, 51)], 51: [_fon(i) for i in range(51, 61)]}
    client = FakeClient(pages=pages)
    rows = _enumerate_window(client, "C", 1, 100)
    got = sorted(int(r["disclosureIndex"]) for r in rows)
    assert got == list(range(1, 61))  # nothing lost; 60 collected via 2 pages


def test_enumerate_window_excludes_beyond_win_end():
    pages = {1: [_fon(1), _fon(2), _fon(250)]}
    client = FakeClient(pages=pages)
    rows = _enumerate_window(client, "C", 1, 100)
    assert [int(r["disclosureIndex"]) for r in rows] == [1, 2]  # 250 > win_end dropped


def _pdr_detail(idx, fund_code, period_text, fund_title="FUND"):
    return {
        "disclosureIndex": str(idx),
        "subject": {"tr": "Portföy Dağılım Raporu", "en": "Portfolio Allocation Report"},
        "summary": {"tr": f"{period_text} Portföy Dağılım Raporu\n"},
        "behalfFundCode": fund_code,
        "behalfFundTitle": fund_title,
        "presentation": [{"alloc": idx}],
    }


def _make_finder_client():
    # one window [0,100]; FON rows 30,60,90 (BON PDRs), 95 (CBD PDR), 99 (FON non-PDR)
    pages = {0: [_fon(30), _fon(60), _fon(90), _fon(95), _fon(99)]}
    details = {
        30: _pdr_detail(30, "BON", "2025 / 12.Ay"),
        60: _pdr_detail(60, "BON", "2026 / 2.Ay"),
        90: _pdr_detail(90, "BON", "2026 / 3.Ay"),
        95: _pdr_detail(95, "CBD", "2026 / 3.Ay"),
        99: {"disclosureIndex": "99", "subject": {"tr": "Komisyon Bilgileri"}, "behalfFundCode": "BON"},
    }
    return FakeClient(pages=pages, details=details, last=100)


def test_finder_latest_returns_newest_match_and_stops():
    client = _make_finder_client()
    result = find_fund_portfolio_reports(client, "BON", "C", window=1000)
    assert isinstance(result, PortfolioReportResult)
    assert [i["disclosureIndex"] for i in result.items] == [90]
    assert result.items[0]["period"] == "2026-03"
    assert result.truncated is False
    # newest-first probe: fetched 99, 95, 90 (stops at 90) — not the older 60/30
    assert result.details_fetched == 3


def test_finder_range_collects_in_period_window():
    client = _make_finder_client()
    result = find_fund_portfolio_reports(client, "BON", "C", from_period="2026-01", to_period="2026-12", window=1000)
    assert [i["disclosureIndex"] for i in result.items] == [90, 60]  # 30 is 2025-12, below from


def test_finder_excludes_other_fund_and_non_pdr():
    client = _make_finder_client()
    result = find_fund_portfolio_reports(client, "CBD", "C", window=1000)
    assert [i["disclosureIndex"] for i in result.items] == [95]


def test_finder_truncates_on_max_details():
    client = _make_finder_client()
    result = find_fund_portfolio_reports(client, "BON", "C", from_period="2000-01", to_period="2999-12", window=1000, max_details=1)
    assert result.truncated is True
