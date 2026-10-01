"""The total-perimeter objective: what it scores, what it requires, how it round-trips.

The family packs copies of *independent* sizes and asks for the sum of their
perimeters. Its degree of freedom is each placement's own scale, so the common
scale is fixed at 1 and the constraints stay the packing pair; the promoted metric
is the sum of the local scales, which for the source's unit copies is the sum the
pages print. These tests pin the contract the engine, the interface and a stored
problem file all read.
"""

from __future__ import annotations

import math

import pytest

from paper_obs.domain import (
    Arena,
    Candidate,
    Circle,
    CommonScale,
    MaximizeTotalPerimeter,
    Objective,
    Placement,
    Problem,
    RequiredShapeCount,
    RotationMode,
    RotationPolicy,
)


def _problem(objective: MaximizeTotalPerimeter) -> Problem:
    return Problem(
        problem_id="p",
        arena=Arena.rectangle(1.0, 1.0),
        shape=Circle(radius=1.0),
        objective=objective,
        rotation=RotationPolicy(mode=RotationMode.FREE),
    )


def _candidate(*scales: float) -> Candidate:
    return Candidate(
        candidate_id="c",
        problem_id="p",
        scale=1.0,
        placements=tuple(
            Placement(shape_id=f"s{index:03d}", x=0.0, y=0.0, scale=scale)
            for index, scale in enumerate(scales)
        ),
    )


def test_the_primary_is_the_sum_the_engine_builds() -> None:
    problem = _problem(MaximizeTotalPerimeter(count=2))
    score = problem.objective.evaluate(problem, _candidate(0.5, 0.25))

    assert score.label == "total_perimeter"
    assert score.primary == pytest.approx(2.0 * math.pi * (0.5 + 0.25))
    assert score.secondary["total_scale"] == pytest.approx(0.75)
    assert score.secondary["unit_perimeter"] == pytest.approx(2.0 * math.pi)
    assert score.secondary["n_shapes"] == 2.0


def test_a_bigger_copy_scores_strictly_more_at_the_same_count() -> None:
    problem = _problem(MaximizeTotalPerimeter(count=1))
    bigger = problem.objective.evaluate(problem, _candidate(0.5))
    smaller = problem.objective.evaluate(problem, _candidate(0.4))

    assert bigger.primary > smaller.primary
    assert bigger.is_better_than(smaller)


def test_the_sum_of_the_local_scales_is_the_promoted_metric() -> None:
    objective = MaximizeTotalPerimeter(count=3)

    assert objective.promoted_metric == "total_scale"
    assert objective.preset_count() == 3
    assert objective.preset_scale() == 1.0
    assert "total perimeter" in objective.describe()
    assert "common scale fixed at 1" in objective.describe()


def test_the_structural_pair_still_applies_so_the_copies_stay_a_packing() -> None:
    """Unlike a covering, a total-perimeter packing keeps containment and non-overlap."""
    objective = MaximizeTotalPerimeter(count=4)
    problem = _problem(objective)

    structural = objective.structural_constraints(problem)
    assert [type(constraint).__name__ for constraint in structural] == [
        "ArenaContainment",
        "NonOverlap",
    ]

    implied = objective.constraints(problem)
    assert isinstance(implied[0], RequiredShapeCount) and implied[0].count == 4
    assert isinstance(implied[1], CommonScale) and implied[1].scale == 1.0

    kinds = [constraint.kind for constraint in problem.effective_constraints]
    assert kinds == [
        "arena_containment",
        "non_overlap",
        "rotation_policy",
        "required_shape_count",
        "common_scale",
    ]
    assert "arena_covered" not in kinds


def test_the_objective_survives_serialisation() -> None:
    objective = MaximizeTotalPerimeter(count=7)

    assert objective.to_dict() == {"type": "maximize_total_perimeter", "count": 7}
    decoded = Objective.from_dict(objective.to_dict())
    assert decoded == objective
    assert isinstance(decoded, MaximizeTotalPerimeter)


def test_degenerate_total_perimeter_objects_are_rejected() -> None:
    with pytest.raises(ValueError, match="at least one shape"):
        MaximizeTotalPerimeter(count=0)
