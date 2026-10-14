"""Observable contracts of the maintainer's source refresh, without network."""
import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import build_packing_catalog as packing
import update_catalog as update


def table(heads, values):
    return "<table><tr>" + "".join(f'<td>{label}.<br><img src="{figure}">' for label, figure in heads) + "</tr><tr>" + "".join(f"<td>{value}" for value in values) + "</tr></table>"


def family():
    return {"slug": "example", "page": "https://example.invalid/example/",
            "section": "Packing Equal Copies", "instances": [{"counts": [1],
            "value": 2, "formula": "", "symbol": "s", "status": "best_known",
            "attribution": "Found by A", "figure": "1.png", "candidate": "local.json"}],
            "problem_template": {"custom": True}, "source_checked_on": "2026-10-01",
            "intro": "", "warnings": []}


def test_missing_equals_and_exact_formulas_do_not_shift_later_records():
    html = table([("1.-2", "2.gif"), ("3", "3.gif"), ("4", "4.gif")],
                 ["s = √3/2 Trivial", "s 1.98857+ Found by A", "s = 1.99877+ Found by B"])
    warnings = []
    rows = packing.instances(html, "example", warnings)
    assert [r["counts"] for r in rows] == [[1, 2], [3], [4]]
    assert [r["value"] for r in rows] == pytest.approx([math.sqrt(3)/2, 1.98857, 1.99877])
    assert rows[0]["formula"] == "√3/2" and rows[0]["status"] == "proved"
    assert not warnings
    assert packing.reading("s = 1/2 Trivial") == (0.5, "1/2", "s", "Trivial")


def test_unequal_cells_keep_figures_without_assigning_the_wrong_values():
    html = table([("49", "49.png"), ("50", "50.png")],
                 ["Σ r = 4.66314+ Found by A", "Σ r = 4.81437+ Found by A", "Σ r = 4.86154+ Found by A"])
    warnings = []
    rows = packing.instances(html, "example", warnings)
    assert len(rows) == 2 and warnings
    for row in rows:
        assert row["value"] is None and row["source_ambiguous"] is True
        assert row["source_values"] == [4.66314, 4.81437, 4.86154]
        assert "value_upper_bound" not in row


def test_refresh_keeps_engine_data_but_removes_resolved_ambiguity():
    previous = family()
    previous["instances"][0].update(source_ambiguous=True, source_values=[1, 2])
    current = update.refresh_family(previous, table([("1", "1.png")], ["s = 1.23400+ Found by A"]), "2026-10-14")
    assert current["problem_template"] == previous["problem_template"]
    row = current["instances"][0]
    assert row["candidate"] == "local.json" and row["value"] == 1.234
    assert "source_ambiguous" not in row and "value_upper_bound" not in row
    previous["section"] = "Packing Copies to Maximize Total Perimeter"
    current = update.refresh_family(previous, table([("1", "1.png")], ["Σ r = 1.23400+ Found by A"]), "2026-10-14")
    assert current["instances"][0]["value_upper_bound"] == pytest.approx(1.23401)


def test_overlapping_ranges_keep_the_best_construction_per_count():
    previous = family()
    html = table([("29", "29.gif"), ("29.-33", "33.gif")], ["s = 9.93198+ Found by A", "s = 10 Trivial"])
    current = update.refresh_family(previous, html, "2026-10-14")
    assert [r["counts"] for r in current["instances"]] == [[29], [30, 31, 32, 33]]
    assert current["instances"][0]["value"] == 9.93198
    assert current["warnings"]


def test_compact_refresh_preserves_candidates_and_historical_reference():
    compact = {"families": [family()]}
    source = update.refresh_family(family(), table([("1", "1.png")], ["s = 1.9 Found by B"]), "2026-10-14")
    current = update.compact_copy(compact, {"example": source}, "2026-10-14")
    row = current["families"][0]["instances"][0]
    assert row["candidate"] == "local.json" and row["value"] == 1.9
    assert row["historical_reference"]["value"] == 2
    assert compact["families"][0]["instances"][0]["value"] == 2


def test_missing_source_aborts_before_publishing_any_asset(tmp_path, monkeypatch):
    asset = tmp_path / "packing_equal_copies.json"
    snapshot = {"generated": "2026-10-01", "source": "index", "families": [family()]}
    original = json.dumps(snapshot)
    asset.write_text(original)
    monkeypatch.setattr(update, "ASSET", asset)
    monkeypatch.setattr(update, "REPORT", tmp_path / "report.json")
    monkeypatch.setattr(update, "index_membership", lambda html: {"example"})

    def fetch(url, name, **kwargs):
        if name == "example":
            raise TimeoutError("unavailable")
        return ""

    monkeypatch.setattr(update, "fetch", fetch)
    monkeypatch.setattr(update.squares, "parse_page", lambda html: {})
    monkeypatch.setattr(update.squares, "catalog_rows", lambda: {})
    monkeypatch.setattr(update.squares, "check", lambda page, rows: [])
    assert update.main([]) == 1
    assert asset.read_text() == original
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["failures"][0]["family"] == "example"


def test_offline_cannot_change_source_dates_or_assets():
    with pytest.raises(SystemExit) as error:
        update.main(["--offline"])
    assert error.value.code == 2


def test_http_not_modified_reuses_html_but_checks_the_server(tmp_path, monkeypatch):
    import urllib.error

    monkeypatch.setattr(update, "CACHE", tmp_path)
    (tmp_path / "example.html").write_text("cached page")
    (tmp_path / "example.json").write_text(json.dumps({"url": "https://example.invalid/", "etag": '"v1"'}))
    requests = []

    def open_url(request, **kwargs):
        requests.append(request)
        raise urllib.error.HTTPError(request.full_url, 304, "Not Modified", {}, None)

    monkeypatch.setattr(update.urllib.request, "urlopen", open_url)
    assert update.fetch("https://example.invalid/", "example", offline=False) == "cached page"
    assert requests[0].get_header("If-none-match") == '"v1"'


def test_removed_compact_record_requires_review():
    source = family()
    source["instances"] = []
    with pytest.raises(ValueError, match="compact selection needs review"):
        update.compact_copy({"families": [family()]}, {"example": source}, "2026-10-14")


def test_new_audit_keeps_the_previous_source_comparison():
    before = {"checked_on": "2026-10-01", "changes": [{"count": 1, "before": {"value": 2}, "after": {"value": 1.9}}]}
    latest = {"checked_on": "2026-10-14", "offline": False, "changes": []}
    audit = update.audit_of(latest, before)
    assert audit["changes"] == [] and "offline" not in audit
    assert audit["history"][0] == before
    assert "history" not in before
