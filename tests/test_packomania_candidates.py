"""Packomania's published packings must survive the trip to the engine.

The candidates under `apps/web/public/catalog/candidates/` are produced by
the maintainers' importer from the coordinates Packomania
publishes. This module reads them back with the lab's storage helpers, with no
network access, and asks the engine whether a handful of them -- at least one per
imported family, including an instance with N >= 20 -- still measures the record
the report recorded. The engine is the judge here as everywhere: the test never
recomputes a size, it only reads `1 / verdict.primary`.
"""

import json
from pathlib import Path

from paper_obs.domain import Problem
from paper_obs.geometry.engine import evaluate
from paper_obs.storage.files import load_candidate

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "apps/web/public/catalog/candidates"
REPORT = ROOT / "apps/web/public/catalog/packomania_candidates.json"

#: Absolute tolerance on the published size, the one the importer commits to.
TOLERANCE = 1e-9


def report() -> dict:
    """Return the importer's report of what it imported."""
    return json.loads(REPORT.read_text(encoding="utf-8"))


def picked_counts(family: dict) -> list[int]:
    """Return the instances checked for one family: first, middle and largest."""
    counts = sorted(item["n"] for item in family["imported"])
    return sorted({counts[0], counts[len(counts) // 2], counts[-1]})


def evaluate_instance(family: dict, count: int):
    """Load one candidate and the problem it belongs to, and score it."""
    entry = next(item for item in family["imported"] if item["n"] == count)
    candidate = load_candidate(CANDIDATES / entry["file"])
    template = json.loads(json.dumps(family["problem_template"]))
    template["problem_id"] = candidate.problem_id
    template["objective"]["count"] = count
    return evaluate(Problem.from_dict(template), candidate, with_metrics=False), entry


def test_every_imported_family_is_reported():
    document = report()
    families = document["families"]
    assert families, "the Packomania report names no family"
    for family in families:
        assert family["imported"], family["code"]
        assert family["problem_template"]["problem_id"], family["code"]
    assert document["totals"]["imported"] == sum(len(family["imported"]) for family in families)


def test_candidates_reproduce_the_published_records():
    for family in report()["families"]:
        for count in picked_counts(family):
            verdict, entry = evaluate_instance(family, count)
            measured = 1.0 / verdict.primary
            assert verdict.valid, f"{family['code']} n={count}: {verdict.validation.summary()}"
            assert abs(measured - entry["published"]) <= TOLERANCE, (
                f"{family['code']} n={count}: engine measured {measured!r}, "
                f"the report records {entry['published']!r}"
            )


def test_at_least_one_checked_instance_is_large():
    largest = max(
        item["n"] for family in report()["families"] for item in family["imported"]
    )
    assert largest >= 20, f"the catalogue's largest instance is only n={largest}"
