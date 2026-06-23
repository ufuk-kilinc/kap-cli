import pytest

from kap.utils import resolve_company, resolve_fund, resolve_one


class FakeClient:
    def __init__(self, members=None, funds=None, pages=None, last=0):
        self._members = members or []
        self._funds = funds or []
        self._pages = pages or {}
        self._last = last
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
