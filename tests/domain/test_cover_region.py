"""The covering objective: what it scores, what it requires, how it round-trips.

Covering is the one family of the reference collection whose copies are meant to
lie over the region and usually overlap each other. Its objective therefore asks
for a fixed count and for the arena to be covered, and for nothing else: no
containment and no non-overlap. These tests pin the contract the engine, the
interface and a stored problem file all read.
"""

from __future__ import annotations

import pytest

from paper_obs.domain import (
    Arena,
    ArenaCovered,
    Candidate,
    COVERAGE_TOLERANCE,
    Constraint,
    CoverRegion,
    Objective,
    Placement,
    Problem,
    RegularPolygon,
    RequiredShapeCount,
    RotationMode,
    RotationPolicy,
)


def _problem(objective: CoverRegion) -> Problem:
    return Problem(
        problem_id="p",
        arena=Arena.disk(1.0),
        shape=RegularPolygon(sides=4, side=1.0),
        objective=objective,
        rotation=RotationPolicy(mode=RotationMode.FREE),
    )


def test_cover_region_scores_the_reciprocal_of_the_common_scale() -> None:
    """The primary is 1 / scale, the number the source publishes at unit size."""
    problem = _problem(CoverRegion(count=2))
    candidate = Candidate(
        candidate_id="c",
        problem_id="p",
        scale=2.0,
        placements=(Placement("s000", 0.0, 0.0), Placement("s001", 0.0, 0.0)),
    )

    score = problem.objective.evaluate(problem, candidate)

    assert score.primary == pytest.approx(0.5)
    assert score.label == "covered_size"
    assert score.secondary["common_scale"] == 2.0
    assert score.secondary["shape_area"] == pytest.approx(problem.shape.area(2.0))
    assert score.secondary["n_shapes"] == 2.0


def test_cover_region_promotes_the_covered_size_and_fixes_its_count() -> None:
    objective = CoverRegion(count=3)
    assert objective.promoted_metric == "covered_size"
    assert objective.preset_count() == 3
    assert objective.preset_scale() is None
    assert "smallest common scale" in objective.describe()


def test_cover_region_requires_its_count_and_coverage_and_no_packing_rules() -> None:
    """Structural constraints are empty: a covering is not a packing at all."""
    objective = CoverRegion(count=4)
    problem = _problem(objective)

    assert objective.structural_constraints(problem) == ()

    implied = objective.constraints(problem)
    assert isinstance(implied[0], RequiredShapeCount) and implied[0].count == 4
    assert isinstance(implied[1], ArenaCovered)

    kinds = [constraint.kind for constraint in problem.effective_constraints]
    assert kinds == ["rotation_policy", "required_shape_count", "arena_covered"]
    assert "arena_containment" not in kinds
    assert "non_overlap" not in kinds


def test_cover_region_survives_serialisation() -> None:
    objective = CoverRegion(count=7)
    assert objective.to_dict() == {"type": "cover_region", "count": 7}
    decoded = Objective.from_dict(objective.to_dict())
    assert decoded == objective
    assert isinstance(decoded, CoverRegion)


def test_the_cover_constraint_survives_serialisation() -> None:
    constraint = ArenaCovered()
    assert constraint.to_dict() == {"type": "arena_covered", "tolerance": COVERAGE_TOLERANCE}
    assert Constraint.from_dict(constraint.to_dict()) == constraint
    assert "cover the whole arena" in constraint.describe()


def test_degenerate_covering_objects_are_rejected() -> None:
    with pytest.raises(ValueError, match="at least one shape"):
        CoverRegion(count=0)
    with pytest.raises(ValueError, match="tolerance"):
        ArenaCovered(tolerance=-1.0)
