from pathlib import Path

import pytest
from typer.testing import CliRunner

import kap.cli as cli
from kap.errors import KapApiError

runner = CliRunner()


class _FakeClient:
    def __init__(self):
        self.calls = []

    def last_disclosure_index(self):
        return 999

    def members(self):
        return [{"companyId": 1, "title": "ACME"}]

    def funds(self):
        return []

    def disclosures(self, index, disclosure_type=None, disclosure_class=None, company_id=None):
        self.calls.append(("disclosures", index, disclosure_class, company_id))
        return [{"disclosureIndex": index}]

    def disclosure_detail(self, index, file_type="data", sub_report=None):
        return {"htmlMessages": [], "disclosureIndex": index}

    def ca_event_status(self, ref_ids):
        self.calls.append(("ca", ref_ids))
        return []

    def download_attachment(self, attachment_id):
        return b"%PDF-1.7 bytes"

    def close(self):
        pass


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


def test_ca_event_status_variadic(fake_client):
    result = runner.invoke(cli.app, ["ca-event-status", "11", "22"])
    assert result.exit_code == 0
    assert ("ca", [11, 22]) in fake_client.calls


def test_download_attachment_writes_pdf(fake_client, tmp_path):
    target = tmp_path / "doc.pdf"
    result = runner.invoke(cli.app, ["download-attachment", "abc", "--out", str(target)])
    assert result.exit_code == 0
    assert target.read_bytes() == b"%PDF-1.7 bytes"


def test_api_error_exits_nonzero_with_message(fake_client, monkeypatch):
    def boom():
        raise KapApiError(403, "ER001", "denied")

    monkeypatch.setattr(fake_client, "funds", boom, raising=False)
    result = runner.invoke(cli.app, ["funds"])
    assert result.exit_code == 1
    combined = result.output + (getattr(result, "stderr", "") or "")
    assert "ER001" in combined or "denied" in combined
