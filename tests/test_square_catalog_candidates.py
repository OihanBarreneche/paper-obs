"""Published catalog candidates must remain usable by the deterministic engine."""

import json
from pathlib import Path

from paper_obs.domain import Candidate, Problem
from paper_obs.geometry.engine import evaluate


ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "apps/web/public/catalog/candidates"


def test_square_catalog_candidates_are_valid():
    template = json.loads((ROOT / "examples/squares_5_in_smallest_square.json").read_text(encoding="utf-8"))
    for count in range(1, 30):
        document = json.loads((CANDIDATES / f"squares-{count}.json").read_text(encoding="utf-8"))
        template["problem_id"] = document["problem_id"]
        template["objective"]["count"] = count
        problem = Problem.from_dict(template)
        candidate = Candidate.from_dict(document)
        assert len(candidate.placements) == count
        verdict = evaluate(problem, candidate, with_metrics=False)
        assert verdict.valid, f"n={count}: {verdict.validation.summary()}"


def test_catalog_reproduces_published_record_sides():
    template = json.loads((ROOT / "examples/squares_5_in_smallest_square.json").read_text(encoding="utf-8"))
    for count, side in {5: 2.70710678118654, 17: 4.67553009360455,
                        28: 5.82444461667405, 29: 5.93383346267692}.items():
        document = json.loads((CANDIDATES / f"squares-{count}.json").read_text(encoding="utf-8"))
        template["problem_id"] = document["problem_id"]
        template["objective"]["count"] = count
        verdict = evaluate(Problem.from_dict(template), Candidate.from_dict(document), with_metrics=False)
        assert verdict.valid
        assert abs(1 / verdict.primary - side) < 1e-8
