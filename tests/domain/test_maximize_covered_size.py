"""The derived covering objective: the target measured inside the copies' union.

This is the twin of `cover_region`. Instead of fixing the arena as the target and
shrinking the copies until they cover it, the copies are unit-sized and the target
is derived from the union of their footprints. These tests pin the contract the
engine, the interface and a stored problem file all read.
"""

from __future__ import annotations

import pytest

from paper_obs.domain import (
    Arena,
    Candidate,
    CommonScale,
    MaximizeCoveredSize,
    Objective,
    Placement,
    Problem,
    RegularPolygon,
    RequiredShapeCount,
    RotationMode,
    RotationPolicy,
)


def _problem(objective: MaximizeCoveredSize) -> Problem:
    return Problem(
        problem_id="p",
        arena=None,
        shape=RegularPolygon(sides=4, side=1.0),
        objective=objective,
        rotation=RotationPolicy(mode=RotationMode.FREE),
    )


def test_the_derived_covering_scores_the_measured_size() -> None:
    """The primary is the derived length, and nothing else in the candidate decides it."""
    problem = _problem(MaximizeCoveredSize(count=2, target="circle"))
    candidate = Candidate(
        candidate_id="c",
        problem_id="p",
        scale=1.0,
        placements=(Placement("s000", 0.0, 0.0), Placement("s001", 0.0, 0.0)),
    )

    score = problem.objective.evaluate(problem, candidate, {"covered_size": 0.5})

    assert score.primary == 0.5
    assert score.label == "covered_size"
    assert score.secondary["common_scale"] == 1.0
    assert score.secondary["n_shapes"] == 2.0


def test_the_derived_covering_scores_only_through_the_engine() -> None:
    """A size invented by the domain would be worse than a refusal."""
    problem = _problem(MaximizeCoveredSize(count=2))
    candidate = Candidate(candidate_id="c", problem_id="p", scale=1.0, placements=())

    with pytest.raises(ValueError, match="covered_size"):
        problem.objective.evaluate(problem, candidate)


def test_the_derived_covering_promotes_the_size_and_fixes_count_and_scale() -> None:
    objective = MaximizeCoveredSize(count=3, target="square")

    assert objective.promoted_metric == "covered_size"
    assert objective.preset_count() == 3
    assert objective.preset_scale() == 1.0
    assert objective.arena_is_fixed is False
    assert objective.derives_region is True
    assert "union" in objective.describe()
    assert "square" in objective.describe()


def test_the_derived_covering_adds_no_packing_rules() -> None:
    """A union is not a packing: containment, overlap and a covering constraint are absent."""
    objective = MaximizeCoveredSize(count=4)
    problem = _problem(objective)

    assert objective.structural_constraints(problem) == ()
    implied = objective.constraints(problem)
    assert isinstance(implied[0], RequiredShapeCount) and implied[0].count == 4
    assert isinstance(implied[1], CommonScale) and implied[1].scale == 1.0

    kinds = [constraint.kind for constraint in problem.effective_constraints]
    assert kinds == ["rotation_policy", "required_shape_count", "common_scale"]
    assert "arena_containment" not in kinds
    assert "non_overlap" not in kinds
    assert "arena_covered" not in kinds


def test_a_declared_arena_is_refused() -> None:
    """The target is measured, so a declared arena would be a region nothing reads."""
    with pytest.raises(ValueError, match="measures its own region"):
        Problem(
            problem_id="p",
            arena=Arena.disk(1.0),
            shape=RegularPolygon(sides=4, side=1.0),
            objective=MaximizeCoveredSize(count=1),
        )


def test_the_derived_covering_survives_serialisation() -> None:
    objective = MaximizeCoveredSize(count=5, target="square")
    assert objective.to_dict() == {
        "type": "maximize_covered_size",
        "count": 5,
        "target": "square",
    }

    decoded = Objective.from_dict(objective.to_dict())

    assert decoded == objective
    assert isinstance(decoded, MaximizeCoveredSize)
    # A document written without the target defaults to the disc.
    defaulted = MaximizeCoveredSize.from_dict({"type": "maximize_covered_size", "count": 2})
    assert defaulted == MaximizeCoveredSize(count=2)


def test_degenerate_targets_are_rejected() -> None:
    with pytest.raises(ValueError, match="at least one shape"):
        MaximizeCoveredSize(count=0)
    with pytest.raises(ValueError, match="unknown cover target"):
        MaximizeCoveredSize(count=1, target="hexagon")
