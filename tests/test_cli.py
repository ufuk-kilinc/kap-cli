import pytest
from typer.testing import CliRunner

import kap.cli as cli
from kap.errors import KapApiError
from kap.utils import PortfolioReportResult

runner = CliRunner()


class _FakeClient:
    """Stand-in for KapClient; supports the context-manager protocol the CLI uses."""

    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        pass

    def members(self):
        return [
            {"id": "1", "stockCode": "ACM", "title": "ACME"},
            {"id": "2", "stockCode": "ACB", "title": "ACME BETA"},
        ]

    def funds(self):
        return [{"fundId": 5900, "fundCode": "BON", "fundName": "TEST FON", "fundCompanyId": 700}]

    def last_disclosure_index(self):
        return 999

    def disclosures(self, index, *, disclosure_type=None, disclosure_class=None, company_id=None):
        self.calls.append(("disclosures", index, disclosure_class, company_id))
        return [{"disclosureIndex": str(index)}]

    def fund_detail(self, fund_id):
        self.calls.append(("fund_detail", fund_id))
        return [{"section": "general"}]

    def member_securities(self):
        return [{"isin": "TR0001"}]

    def blocked_disclosures(self):
        return []

    def disclosure_detail(self, index, file_type="data", sub_report=None):
        return {"htmlMessages": [], "disclosureIndex": index}

    def ca_event_status(self, ref_ids):
        self.calls.append(("ca", ref_ids))
        return []

    def download_attachment(self, attachment_id):
        return b"%PDF-1.7 bytes"

    def raw(self, path, query=None):
        self.calls.append(("raw", path, query))
        return {
            "service": path,
            "status_code": 200,
            "is_success": True,
            "content_type": "application/json",
            "body": "[]",
        }


@pytest.fixture
def fake_client(monkeypatch):
    fc = _FakeClient()
    monkeypatch.setattr(cli, "_make_client", lambda env: fc)
    return fc


def test_last_index(fake_client):
    result = runner.invoke(cli.app, ["last-index"])
    assert result.exit_code == 0
    assert "999" in result.stdout


def test_members_table(fake_client):
    result = runner.invoke(cli.app, ["members"])
    assert result.exit_code == 0
    assert "ACME" in result.stdout


def test_members_json(fake_client):
    result = runner.invoke(cli.app, ["members", "--format", "json"])
    assert result.exit_code == 0
    assert '"title": "ACME"' in result.stdout


def test_disclosures_passes_options(fake_client):
    result = runner.invoke(
        cli.app, ["disclosures", "--index", "500", "--class", "FR", "--company-id", "7"]
    )
    assert result.exit_code == 0
    assert ("disclosures", 500, "FR", 7) in fake_client.calls


def test_fund_detail_command(fake_client):
    result = runner.invoke(cli.app, ["fund-detail", "5900"])
    assert result.exit_code == 0
    assert ("fund_detail", 5900) in fake_client.calls


def test_member_securities_command(fake_client):
    result = runner.invoke(cli.app, ["member-securities"])
    assert result.exit_code == 0
    assert "TR0001" in result.stdout


def test_blocked_disclosures_command(fake_client):
    result = runner.invoke(cli.app, ["blocked-disclosures"])
    assert result.exit_code == 0


def test_ca_event_status_variadic(fake_client):
    result = runner.invoke(cli.app, ["ca-event-status", "11", "22"])
    assert result.exit_code == 0
    assert ("ca", [11, 22]) in fake_client.calls


def test_download_attachment_writes_pdf(fake_client, tmp_path):
    target = tmp_path / "doc.pdf"
    result = runner.invoke(cli.app, ["download-attachment", "abc", "--out", str(target)])
    assert result.exit_code == 0
    assert target.read_bytes() == b"%PDF-1.7 bytes"


def test_raw_passes_query_params(fake_client):
    result = runner.invoke(
        cli.app, ["raw", "api/vyk/members", "--query", "foo=bar", "--query", "baz=qux"]
    )
    assert result.exit_code == 0
    assert ("raw", "api/vyk/members", {"foo": "bar", "baz": "qux"}) in fake_client.calls


def test_raw_rejects_malformed_query(fake_client):
    result = runner.invoke(cli.app, ["raw", "api/vyk/members", "--query", "novalue"])
    assert result.exit_code != 0
    assert "key=value" in (result.stderr + result.stdout)


def test_api_error_goes_to_stderr_not_stdout(fake_client, monkeypatch):
    def boom():
        raise KapApiError(403, "ER001", "denied")

    monkeypatch.setattr(fake_client, "funds", boom, raising=False)
    result = runner.invoke(cli.app, ["funds"])
    assert result.exit_code == 1
    assert "ER001" in result.stderr or "denied" in result.stderr
    assert "ER001" not in result.stdout and "denied" not in result.stdout


def test_invalid_file_type_rejected(fake_client):
    result = runner.invoke(cli.app, ["disclosure-detail", "7", "--file-type", "pdf"])
    assert result.exit_code != 0
    assert "pdf" in (result.stderr + result.stdout)


def test_invalid_format_fails_fast(fake_client):
    # The fake client never errors, so a non-zero exit proves --format was
    # validated before the (mocked) call ran.
    result = runner.invoke(cli.app, ["members", "--format", "jsonn"])
    assert result.exit_code == 1
    assert "Unknown format" in result.stderr


def test_config_error_exits_cleanly(monkeypatch):
    def boom(env):
        raise ValueError("Missing API key for env 'test'.")

    monkeypatch.setattr(cli, "_make_client", boom)
    result = runner.invoke(cli.app, ["members"])
    assert result.exit_code == 1
    assert "Missing API key" in result.stderr


def test_output_write_error_exits_cleanly(fake_client, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(cli, "output", boom)
    result = runner.invoke(cli.app, ["members"])
    assert result.exit_code == 1
    assert "disk full" in result.stderr


def test_resolve_ticker_lists_matches(fake_client):
    result = runner.invoke(cli.app, ["resolve-ticker", "ACM", "--format", "json"])
    assert result.exit_code == 0
    assert '"stockCode": "ACM"' in result.stdout


def test_resolve_fund_lists_matches(fake_client):
    result = runner.invoke(cli.app, ["resolve-fund", "BON", "--format", "json"])
    assert result.exit_code == 0
    assert '"fundId": 5900' in result.stdout


def test_ticker_disclosures_scans_by_company_id(fake_client):
    result = runner.invoke(cli.app, ["ticker-disclosures", "ACM", "--limit", "5"])
    assert result.exit_code == 0
    # resolved ACM → id "1"; scan called disclosures with that company_id
    assert any(c[0] == "disclosures" and c[3] == "1" for c in fake_client.calls)


def test_ticker_financials_filters_fr(fake_client):
    result = runner.invoke(cli.app, ["ticker-financials", "ACM"])
    assert result.exit_code == 0
    assert any(c[0] == "disclosures" and c[2] == "FR" for c in fake_client.calls)


def test_fund_info_resolves_and_details(fake_client):
    result = runner.invoke(cli.app, ["fund-info", "BON"])
    assert result.exit_code == 0
    assert "general" in result.stdout


def test_fund_disclosures_scans_by_fund_company_id(fake_client):
    result = runner.invoke(cli.app, ["fund-disclosures", "BON"])
    assert result.exit_code == 0
    assert any(c[0] == "disclosures" and c[3] == 700 for c in fake_client.calls)


def test_ambiguous_ticker_exits_with_message(fake_client):
    # "ACME" is not an exact stockCode, matches both titles → ambiguous
    result = runner.invoke(cli.app, ["ticker-disclosures", "ACME"])
    assert result.exit_code == 1
    assert "ambiguous" in result.stderr


def test_unknown_ticker_exits_with_message(fake_client):
    result = runner.invoke(cli.app, ["ticker-disclosures", "ZZZZ"])
    assert result.exit_code == 1
    assert "No ticker matching" in result.stderr


def test_fund_portfolio_report_returns_latest(fake_client, monkeypatch):
    monkeypatch.setattr(
        cli, "find_fund_portfolio_reports",
        lambda *a, **k: PortfolioReportResult(
            items=[{"disclosureIndex": 90, "period": "2026-03", "fundCode": "BON",
                    "fundTitle": "T", "presentation": [{"alloc": 1}]}],
            truncated=False, details_fetched=3),
    )
    result = runner.invoke(cli.app, ["fund-portfolio-report", "BON", "--format", "json"])
    assert result.exit_code == 0
    assert '"disclosureIndex": 90' in result.stdout


def test_fund_portfolio_report_not_found_exits_1(fake_client, monkeypatch):
    monkeypatch.setattr(
        cli, "find_fund_portfolio_reports",
        lambda *a, **k: PortfolioReportResult(items=[], truncated=False, details_fetched=0),
    )
    result = runner.invoke(cli.app, ["fund-portfolio-report", "BON"])
    assert result.exit_code == 1
    assert "No Portföy Dağılım Raporu" in result.stderr


def test_fund_portfolio_report_bad_period_format(fake_client):
    result = runner.invoke(cli.app, ["fund-portfolio-report", "BON", "--from", "2026-1"])
    assert result.exit_code != 0
    assert "YYYY-MM" in (result.stderr + result.stdout)


def test_fund_portfolio_report_from_after_to(fake_client):
    result = runner.invoke(cli.app, ["fund-portfolio-report", "BON", "--from", "2026-06", "--to", "2026-01"])
    assert result.exit_code != 0
    assert "after" in (result.stderr + result.stdout)


def _pdf_result(items):
    return PortfolioReportResult(items=items, truncated=False, details_fetched=len(items))


def _report(idx, period, name="BON_%s.pdf", atts=True):
    fn = name % period if "%s" in name else name
    return {
        "disclosureIndex": idx, "period": period, "fundCode": "BON", "fundTitle": "T",
        "attachmentUrls": [{"url": f"https://h/api/vyk/downloadAttachment/AID{idx}", "fileName": fn}] if atts else [],
        "presentation": [],
    }


def test_fund_portfolio_pdf_single_to_out_dir(fake_client, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "find_fund_portfolio_reports", lambda *a, **k: _pdf_result([_report(90, "2026-04")]))
    result = runner.invoke(cli.app, ["fund-portfolio-pdf", "BON", "--out-dir", str(tmp_path)])
    assert result.exit_code == 0
    saved = tmp_path / "BON_2026-04.pdf"
    assert saved.read_bytes() == b"%PDF-1.7 bytes"


def test_fund_portfolio_pdf_single_to_out_file(fake_client, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "find_fund_portfolio_reports", lambda *a, **k: _pdf_result([_report(90, "2026-04")]))
    target = tmp_path / "latest.pdf"
    result = runner.invoke(cli.app, ["fund-portfolio-pdf", "BON", "--out", str(target)])
    assert result.exit_code == 0
    assert target.read_bytes() == b"%PDF-1.7 bytes"


def test_fund_portfolio_pdf_multiple_to_out_dir(fake_client, monkeypatch, tmp_path):
    monkeypatch.setattr(
        cli, "find_fund_portfolio_reports",
        lambda *a, **k: _pdf_result([_report(90, "2026-04"), _report(60, "2026-03")]),
    )
    result = runner.invoke(cli.app, ["fund-portfolio-pdf", "BON", "--out-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "BON_2026-04.pdf").exists() and (tmp_path / "BON_2026-03.pdf").exists()


def test_fund_portfolio_pdf_out_with_multiple_rejected(fake_client, monkeypatch, tmp_path):
    monkeypatch.setattr(
        cli, "find_fund_portfolio_reports",
        lambda *a, **k: _pdf_result([_report(90, "2026-04"), _report(60, "2026-03")]),
    )
    result = runner.invoke(cli.app, ["fund-portfolio-pdf", "BON", "--out", str(tmp_path / "x.pdf")])
    assert result.exit_code != 0
    assert "out-dir" in (result.stderr + result.stdout)


def test_fund_portfolio_pdf_no_attachment_exits_1(fake_client, monkeypatch):
    monkeypatch.setattr(cli, "find_fund_portfolio_reports", lambda *a, **k: _pdf_result([_report(90, "2026-04", atts=False)]))
    result = runner.invoke(cli.app, ["fund-portfolio-pdf", "BON"])
    assert result.exit_code == 1
    assert "No PDF attachments" in result.stderr


def test_fund_portfolio_pdf_not_found_exits_1(fake_client, monkeypatch):
    monkeypatch.setattr(cli, "find_fund_portfolio_reports", lambda *a, **k: _pdf_result([]))
    result = runner.invoke(cli.app, ["fund-portfolio-pdf", "BON"])
    assert result.exit_code == 1
    assert "No Portföy Dağılım Raporu" in result.stderr


def test_fund_portfolio_pdf_download_none_exits_1(fake_client, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "find_fund_portfolio_reports", lambda *a, **k: _pdf_result([_report(90, "2026-04")]))
    monkeypatch.setattr(fake_client, "download_attachment", lambda attachment_id: None, raising=False)
    result = runner.invoke(cli.app, ["fund-portfolio-pdf", "BON", "--out-dir", str(tmp_path)])
    assert result.exit_code == 1


def test_members_out_directory_auto_names(fake_client, tmp_path):
    result = runner.invoke(cli.app, ["members", "--out", str(tmp_path)])
    assert result.exit_code == 0
    saved = tmp_path / "members.json"
    assert saved.exists()
    import json as _json
    data = _json.loads(saved.read_text(encoding="utf-8"))
    assert data[0] == {"id": "1", "stockCode": "ACM", "title": "ACME"}
    assert "Saved to" in result.stdout


def test_download_attachment_out_directory(fake_client, tmp_path):
    result = runner.invoke(cli.app, ["download-attachment", "abc", "--out", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "abc.pdf").read_bytes() == b"%PDF-1.7 bytes"
