"""The exact check: rational arithmetic, its own predicates, and the same verdicts as the engine."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from paper_obs import research
from paper_obs.domain.candidate import Candidate
from paper_obs.geometry.engine import evaluate
from paper_obs.geometry.exact_check import exact_check

RECORDS = Path(__file__).resolve().parents[2] / "apps/web/public/catalog/candidates"


def _record(slug: str, count: int):
    problem = research.catalog_problem(slug, count)
    data = json.loads((RECORDS / f"record-{slug}-{count}.json").read_text(encoding="utf-8"))
    return problem, replace(Candidate.from_dict(data), problem_id=problem.problem_id)


@pytest.mark.parametrize(("slug", "count"), [("squintri", 38), ("taninL", 26)])
def test_the_shipped_records_are_valid_in_exact_arithmetic(slug: str, count: int) -> None:
    problem, candidate = _record(slug, count)
    verdict = exact_check(problem, candidate)
    assert verdict["valid"] and verdict["copies"] == count
    assert verdict["min_separation"] > 0 and verdict["min_clearance"] > 0


def test_a_copy_moved_onto_another_overlaps() -> None:
    problem, candidate = _record("squintri", 38)
    first, second = candidate.placements[:2]
    moved = replace(candidate, placements=(first, second.moved(first.x + 1e-3, first.y), *candidate.placements[2:]))
    verdict = exact_check(problem, moved)
    assert not verdict["valid"] and [0, 1] in verdict["overlapping_pairs"]
    assert not evaluate(problem, moved).valid


def test_a_tan_in_the_notch_of_the_l_is_outside() -> None:
    problem, candidate = _record("taninL", 26)
    left, bottom, right, top = problem.arena.geometry.bounds
    tans = list(candidate.placements)
    tans[5] = tans[5].moved(right - 0.25, top - 0.25)  # the notch is the top right quarter
    verdict = exact_check(problem, replace(candidate, placements=tuple(tans)))
    assert 5 in verdict["outside"] and verdict["min_clearance"] < 0
