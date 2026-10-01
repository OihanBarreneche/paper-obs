"""The translation the engine reports for a shape that leaves the arena.

A repair reads it instead of guessing a direction, so the property that matters is
the observable one: moving the shape by it brings the shape back inside.
"""

from __future__ import annotations

import pytest

from paper_obs.domain import (
    Arena,
    Candidate,
    Circle,
    MaximizeScale,
    Placement,
    Problem,
    RegularPolygon,
    RotationMode,
    RotationPolicy,
    new_candidate_id,
)
from paper_obs.geometry.engine import facts_for


def _one(problem: Problem, x: float, y: float, rotation: float = 0.0) -> Candidate:
    return Candidate(
        candidate_id=new_candidate_id("test"), problem_id=problem.problem_id, scale=1.0,
        placements=(Placement("s000", x, y, rotation),),
    )


def _containment(problem: Problem, candidate: Candidate):
    [record] = facts_for(problem, candidate).containment
    return record


FREE = RotationPolicy(mode=RotationMode.FREE)
CASES = {
    "disc in a disc": (Problem("in-disc", Arena.disk(2.0), Circle(), MaximizeScale(count=1)), (1.8, 0.6, 0.0)),
    "disc centre outside a disc": (Problem("out-disc", Arena.disk(2.0), Circle(), MaximizeScale(count=1)), (2.3, 0.0, 0.0)),
    "disc in a square": (Problem("in-square", Arena.rectangle(4.0, 4.0), Circle(), MaximizeScale(count=1)), (1.8, -0.4, 0.0)),
    "pentagon in a square": (Problem("penta-square", Arena.rectangle(4.0, 4.0), RegularPolygon(sides=5),
                                     MaximizeScale(count=1), rotation=FREE), (1.6, 0.3, 17.0)),
}


@pytest.mark.parametrize("label", CASES)
def test_moving_an_overflowing_shape_by_its_inward_translation_brings_it_inside(label: str) -> None:
    problem, (x, y, rotation) = CASES[label]
    outside = _containment(problem, _one(problem, x, y, rotation))
    assert not outside.inside and outside.inward is not None
    dx, dy = outside.inward
    assert _containment(problem, _one(problem, x + dx, y + dy, rotation)).inside


def test_a_shape_past_a_corner_is_brought_back_by_successive_translations() -> None:
    """Two walls crossed at once: each translation fixes the nearest one, the next the other."""
    problem = Problem("corner", Arena.rectangle(4.0, 4.0), Circle(), MaximizeScale(count=1))
    x, y = 1.8, -1.9
    for _ in range(3):
        record = _containment(problem, _one(problem, x, y))
        if record.inside:
            break
        x, y = x + record.inward[0], y + record.inward[1]
    assert _containment(problem, _one(problem, x, y)).inside


def test_a_shape_inside_reports_no_translation() -> None:
    problem = Problem("inside", Arena.disk(2.0), Circle(), MaximizeScale(count=1))
    record = _containment(problem, _one(problem, 0.2, 0.1))
    assert record.inside and record.inward is None
