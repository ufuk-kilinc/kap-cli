import base64
import json

from kap.render import (
    decode_disclosure_bodies,
    output,
    resolve_format,
    to_csv,
    to_json,
)


def test_resolve_format_explicit_wins():
    assert resolve_format("csv", None, [{"a": 1}]) == "csv"


def test_resolve_format_infers_from_out_extension(tmp_path):
    assert resolve_format(None, tmp_path / "x.json", [{"a": 1}]) == "json"
    assert resolve_format(None, tmp_path / "x.csv", [{"a": 1}]) == "csv"


def test_resolve_format_defaults_table_for_list_and_scalar():
    assert resolve_format(None, None, [{"a": 1}]) == "table"
    assert resolve_format(None, None, 123) == "table"


def test_resolve_format_defaults_json_for_nested_dict():
    assert resolve_format(None, None, {"a": {"b": 1}}) == "json"


def test_to_csv_union_of_keys():
    rows = [{"a": 1, "b": 2}, {"a": 3, "c": 4}]
    text = to_csv(rows)
    header = text.splitlines()[0]
    assert set(header.split(",")) == {"a", "b", "c"}


def test_to_json_is_utf8_readable():
    text = to_json({"name": "Türkçe"})
    assert "Türkçe" in text


def test_decode_disclosure_bodies_decodes_iso8859_9():
    body = "<style>x{}</style><p>Şirket</p>"
    enc = base64.b64encode(body.encode("iso-8859-9")).decode()
    detail = {"htmlMessages": [{"id": 1, "tr": enc, "en": None}]}
    out = decode_disclosure_bodies(detail)
    text = out["htmlMessages"][0]["tr_text"]
    assert "Şirket" in text
    assert "x{}" not in text   # <style> contents stripped


def test_output_writes_json_file(tmp_path):
    target = tmp_path / "out.json"
    output([{"a": 1}], out=target)
    assert json.loads(target.read_text()) == [{"a": 1}]


def test_output_writes_csv_file(tmp_path):
    target = tmp_path / "out.csv"
    output([{"a": 1, "b": 2}], out=target)
    lines = target.read_text().splitlines()
    assert lines[0].replace("\r", "") in ("a,b", "b,a")


def test_output_scalar_to_stdout(capsys):
    output(42)
    assert capsys.readouterr().out.strip() == "42"
