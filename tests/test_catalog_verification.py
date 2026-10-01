"""The catalogue verification must stay in step with the catalogue itself.

`apps/web/public/catalog/verification.json` is written by
`scripts/verify_catalog_records.py`, and the interface reads it to date a card's last
check and to offer the arrangement the engine confirmed. This module asserts the
observable contract of that file against the catalogue asset and the candidate files:
every card it names exists, every arrangement it offers exists and belongs to the
problem the interface files it under, a confirmed record carries a number printed to
at least five decimals, and a construction the lab holds is never promoted. Nothing
here recomputes geometry; the script is the judge.
"""

import json
from pathlib import Path

from paper_obs import catalog_verification

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "apps/web/public/catalog"
ASSET = CATALOG / "packing_equal_copies.json"
SUMMARY = CATALOG / "verification.json"
CANDIDATES = CATALOG / "candidates"

#: The identifiers two candidate files built by other tools already carry. They pin the
#: convention the interface files a card under, so a change to the mirror in the script
#: is caught here rather than by a candidate the app then refuses to load.
KNOWN_IDS = {
    ("squintri", 38, "ts38.gif"): "squares-38-in-smallest-triangle",
    ("taninL", 26, "26.gif"): "tans-26-in-smallest-l",
}


def verifier():
    """Return the module that owns the verification."""
    return catalog_verification


def asset() -> dict:
    return json.loads(ASSET.read_text(encoding="utf-8"))


def summary() -> dict:
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


def families() -> dict[str, dict]:
    return {family["slug"]: family for family in asset()["families"]}


def figure_of(family: dict, count: int) -> str:
    return next(
        instance["figure"] for instance in family["instances"] if count in instance["counts"]
    )


def test_the_summary_was_taken_against_the_asset_that_ships():
    assert summary()["catalog_generated"] == asset()["generated"]
    assert summary()["families"], "the catalogue verification is empty"


def test_every_verified_card_names_a_count_the_catalogue_lists():
    known = families()
    for slug, family in summary()["families"].items():
        assert slug in known, slug
        counts = {
            count for instance in known[slug]["instances"] for count in instance["counts"]
        }
        for count in family["entries"]:
            assert int(count) in counts, (slug, count)


def test_the_identifier_the_script_builds_is_the_one_the_interface_files():
    module = verifier()
    known = families()
    for (slug, count, figure), expected in KNOWN_IDS.items():
        assert module.copy_problem_id(known[slug], count, figure) == expected
    for path in sorted(CANDIDATES.glob("published-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        slug, _, count = path.stem.rpartition("-")
        slug = slug.removeprefix("published-")
        family = known[slug]
        identifier = module.copy_problem_id(family, int(count), figure_of(family, int(count)))
        assert data["problem_id"] == identifier, path.name


def test_a_confirmed_record_needs_a_number_printed_to_five_decimals():
    module = verifier()
    for family in summary()["families"].values():
        for entry in family["entries"].values():
            if not entry["promoted"]:
                continue
            assert entry["status"] == "reproduces"
            assert module.printed_decimals(entry["value"]) >= module.REQUIRED_DECIMALS


def test_every_offered_arrangement_exists_and_is_never_a_held_construction():
    for family in summary()["families"].values():
        for entry in family["entries"].values():
            url = entry["candidate"]
            if url is None:
                continue
            assert (ROOT / "apps/web/public" / url.lstrip("/")).exists(), url
            assert entry["source_kind"] in {"published", "seed", "approx"}


def test_a_construction_the_lab_holds_is_reported_but_never_promoted():
    """The owner's two record sessions stay visible as measurements only."""
    held = [
        entry
        for family in summary()["families"].values()
        for entry in family["entries"].values()
        if entry["source_kind"] == "record"
    ]
    assert held, "no held construction is reported at all"
    for entry in held:
        assert entry["promoted"] is False
        assert entry["candidate"] is None


def test_a_checked_date_is_never_older_than_the_catalogue_it_read():
    for family in summary()["families"].values():
        assert family["checked_on"] >= summary()["catalog_generated"]
        for entry in family["entries"].values():
            assert entry["checked_on"] >= summary()["catalog_generated"]
