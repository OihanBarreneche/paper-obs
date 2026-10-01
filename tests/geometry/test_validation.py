"""What the engine accepts and what it rejects, at the exact boundary.

The interesting cases are all on a wall: a lattice whose shapes touch each other
and the arena boundary must be *valid*, because that is precisely the arrangement
a search converges to. An engine that rejects tangency is an engine that rejects
every good answer.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import ClassVar

import pytest

from paper_obs.domain import (
    Arena,
    Circle,
    CommonScale,
    MaximizeCoveredSize,
    MaximizeCount,
    MinimumClearance,
    Objective,
    ObjectiveScore,
    Placement,
    Problem,
    RegularPolygon,
    RequiredShapeCount,
    RotationMode,
    RotationPolicy,
)
from paper_obs.domain.shapes import CustomPolygon
from paper_obs.geometry import evaluate, facts_for, validate


def test_a_touching_lattice_is_valid(circle_problem, lattice, make_candidate) -> None:
    candidate = make_candidate(circle_problem, lattice(2, 2, 5.0), scale=5.0)
    validation = validate(circle_problem, candidate)
    assert validation.valid
    assert validation.severity == 0.0
    assert validation.violations == ()


def test_a_perfect_tiling_is_valid(square_problem, lattice, make_candidate) -> None:
    candidate = make_candidate(square_problem, lattice(4, 4, 2.5), scale=2.5)
    assert validate(square_problem, candidate).valid


def test_an_overlap_is_reported_with_the_depth_to_pull_apart(
    circle_problem, lattice, make_candidate
) -> None:
    placements = list(lattice(2, 2, 5.0))
    placements[1] = placements[1].moved(2.4, 2.5)
    validation = validate(circle_problem, make_candidate(circle_problem, placements, scale=5.0))
    assert not validation.valid
    collisions = validation.collisions
    assert len(collisions) == 1
    assert set(collisions[0].shape_ids) == {"s000", "s001"}
    assert collisions[0].magnitude == pytest.approx(0.1)


def test_leaving_the_arena_is_reported_with_an_exact_margin(
    circle_problem, lattice, make_candidate
) -> None:
    placements = list(lattice(2, 2, 5.0))
    placements[0] = placements[0].moved(-2.6, 2.5)
    candidate = make_candidate(circle_problem, placements, scale=5.0)
    validation = validate(circle_problem, candidate)
    assert not validation.valid
    assert len(validation.result("arena_containment").violations) == 1
    containment = facts_for(circle_problem, candidate).containment[0]
    assert containment.margin == pytest.approx(-0.1)
    assert containment.overflow_area > 0.0
    assert "leaves the arena by 0.1" in containment.message


def test_a_shape_inside_a_hole_is_outside_the_arena(circle_problem, make_candidate) -> None:
    holed = replace(
        circle_problem,
        arena=Arena.rectangle(10.0, 10.0).difference(Arena.disk(2.0)),
        objective=MaximizeCount(scale=1.0),
    )
    from paper_obs.domain import Placement

    candidate = make_candidate(holed, [Placement("s000", 0.0, 0.0)], scale=1.0)
    validation = validate(holed, candidate)
    assert not validation.valid
    assert validation.result("arena_containment") is not None


def test_a_disc_wall_is_exact_to_the_tessellation(
    lattice, make_candidate
) -> None:
    problem = Problem(
        problem_id="disk",
        arena=Arena.disk(5.0),
        shape=Circle(),
        objective=MaximizeCount(scale=2.0),
    )
    from paper_obs.domain import Placement

    on_the_wall = make_candidate(problem, [Placement("s000", 4.0, 0.0)], scale=2.0)
    assert validate(problem, on_the_wall).valid

    beyond = make_candidate(problem, [Placement("s000", 4.01, 0.0)], scale=2.0)
    validation = validate(problem, beyond)
    assert not validation.valid
    margin = facts_for(problem, beyond).containment[0].margin
    assert margin == pytest.approx(-0.01, abs=1e-3)


def test_an_ellipse_wall_is_exact_on_both_axes(make_candidate) -> None:
    problem = Problem(
        problem_id="ellipse",
        arena=Arena.ellipse(5.0, 3.0),
        shape=Circle(),
        objective=MaximizeCount(scale=2.0),
    )
    from paper_obs.domain import Placement

    # A natural-diameter circle at scale 2 has radius 1, so it is tangent to the
    # major axis at x = 4 and to the minor one at y = 2.
    on_the_major = make_candidate(problem, [Placement("s000", 4.0, 0.0)], scale=2.0)
    on_the_minor = make_candidate(problem, [Placement("s000", 0.0, 2.0)], scale=2.0)
    assert validate(problem, on_the_major).valid
    assert validate(problem, on_the_minor).valid

    beyond = make_candidate(problem, [Placement("s000", 4.01, 0.0)], scale=2.0)
    validation = validate(problem, beyond)
    assert not validation.valid
    margin = facts_for(problem, beyond).containment[0].margin
    assert margin == pytest.approx(-0.01, abs=1e-3)


def test_a_wrong_shape_count_is_a_violation(circle_problem, lattice, make_candidate) -> None:
    candidate = make_candidate(circle_problem, lattice(2, 2, 5.0)[:3], scale=5.0)
    result = validate(circle_problem, candidate).result("required_shape_count")
    assert result is not None and not result.valid
    assert result.violations[0].magnitude == pytest.approx(1.0)
    assert "expected 4 shapes, found 3" in result.message


def test_a_wrong_common_scale_is_a_violation(circle_problem, lattice, make_candidate) -> None:
    fixed = replace(circle_problem, objective=MaximizeCount(scale=2.0))
    candidate = make_candidate(fixed, lattice(2, 2, 5.0), scale=1.5)
    result = validate(fixed, candidate).result("common_scale")
    assert result is not None and not result.valid
    assert result.violations[0].magnitude == pytest.approx(0.5)
    assert isinstance(fixed.objective.constraints(fixed)[0], CommonScale)


def test_rotations_are_checked_against_the_policy(circle_problem, lattice, make_candidate) -> None:
    rotated = lattice(2, 2, 5.0, rotation=10.0)
    fixed = replace(circle_problem, rotation=RotationPolicy(mode=RotationMode.FIXED))
    assert not validate(fixed, make_candidate(fixed, rotated, scale=5.0)).valid

    free = replace(circle_problem, rotation=RotationPolicy(mode=RotationMode.FREE))
    assert validate(free, make_candidate(free, rotated, scale=5.0)).valid


def test_overlapping_squares_report_the_penetration(
    square_problem, lattice, make_candidate
) -> None:
    placements = list(lattice(4, 4, 2.5))
    placements[5] = placements[5].moved(placements[5].x - 0.5, placements[5].y)
    validation = validate(square_problem, make_candidate(square_problem, placements, scale=2.5))
    assert not validation.valid
    assert validation.collisions[0].magnitude == pytest.approx(0.5)


def test_a_square_straddling_a_hole_is_outside_the_arena(make_candidate) -> None:
    from paper_obs.domain import Placement, square

    problem = Problem(
        problem_id="straddle",
        arena=Arena.rectangle(10.0, 10.0).difference(Arena.disk(2.0)),
        shape=square(),
        objective=MaximizeCount(scale=2.0),
    )
    straddling = make_candidate(problem, [Placement("s000", 1.5, 0.0)], scale=2.0)
    validation = validate(problem, straddling)
    assert not validation.valid
    containment = facts_for(problem, straddling).containment[0]
    assert containment.overflow_area > 0.0
    assert containment.margin is None


def test_a_candidate_from_another_problem_is_refused(circle_problem, make_candidate) -> None:
    from dataclasses import replace

    other = replace(circle_problem, problem_id="another-problem")
    candidate = make_candidate(circle_problem, [], scale=1.0)
    with pytest.raises(ValueError, match="belongs to problem"):
        validate(other, candidate)


def test_a_minimum_clearance_constraint_reports_the_deficit(
    circle_problem, lattice, make_candidate
) -> None:
    spaced = replace(circle_problem, constraints=(MinimumClearance(distance=1.0),))
    placements = list(lattice(2, 2, 5.0))
    placements[1] = placements[1].moved(3.0, 2.5)
    validation = validate(spaced, make_candidate(spaced, placements, scale=5.0))
    result = validation.result("minimum_clearance")
    assert result is not None and not result.valid
    deficits = {violation.shape_ids: violation.magnitude for violation in result.violations}
    assert deficits[("s000", "s001")] == pytest.approx(0.5)
    assert validation.collisions == ()


def test_a_validation_survives_serialisation(circle_problem, lattice, make_candidate) -> None:
    from paper_obs.geometry.validation import Validation

    candidate = make_candidate(circle_problem, lattice(2, 2, 5.0), scale=5.0)
    validation = validate(circle_problem, candidate)
    assert Validation.from_dict(validation.to_dict()) == validation


def test_the_summary_names_what_is_wrong(circle_problem, lattice, make_candidate) -> None:
    places = list(lattice(2, 2, 5.0))
    places[1] = places[1].moved(2.4, 2.5)
    validation = validate(circle_problem, make_candidate(circle_problem, places, scale=5.0))
    assert "1 overlapping pair(s)" in validation.summary()


def test_a_count_above_the_required_one_is_a_violation_too(
    circle_problem, lattice, make_candidate
) -> None:
    """Five shapes where four are required is invalid, with the same clear message."""
    candidate = make_candidate(circle_problem, lattice(3, 2, 5.0)[:5], scale=5.0)
    validation = validate(circle_problem, candidate)
    result = validation.result("required_shape_count")

    assert not validation.valid
    assert result is not None and not result.valid
    assert result.severity == pytest.approx(1.0)
    assert result.violations[0].magnitude == pytest.approx(1.0)
    assert "expected 4 shapes, found 5" in result.message


def test_the_derived_covering_requires_its_count_below_and_above(make_candidate) -> None:
    """The count constraint holds on a derived covering, whose region is measured."""
    problem = Problem(
        problem_id="derived-count",
        arena=None,
        shape=RegularPolygon(sides=4, side=1.0),
        objective=MaximizeCoveredSize(count=4, target="square"),
        rotation=RotationPolicy(mode=RotationMode.FREE),
    )
    for count in (3, 5):
        candidate = make_candidate(
            problem,
            [Placement(f"s{index:03d}", float(index) * 3.0, 0.0) for index in range(count)],
        )
        verdict = evaluate(problem, candidate)
        result = verdict.validation.result("required_shape_count")

        assert not verdict.valid
        assert result is not None and not result.valid
        assert f"expected 4 shapes, found {count}" in result.message


def test_a_valid_candidate_outranks_an_invalid_one_with_a_bigger_score(
    circle_problem, lattice, make_candidate
) -> None:
    """The count violation is a verdict, not a footnote: the ranking reads it first."""
    valid = evaluate(circle_problem, make_candidate(circle_problem, lattice(2, 2, 5.0), scale=5.0))
    extra = make_candidate(
        circle_problem,
        lattice(2, 2, 5.0) + (Placement("s004", 0.0, -5.0),),
        scale=6.0,
    )
    invalid = evaluate(circle_problem, extra)

    assert valid.valid and not invalid.valid
    assert invalid.score.primary > valid.score.primary
    assert valid.is_better_than(invalid)
    assert not invalid.is_better_than(valid)


def test_a_problem_that_fixes_no_count_needs_none(make_candidate) -> None:
    """The composer's case: a free-count problem is valid however many shapes it holds."""
    composed = CustomPolygon(
        points=((0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (1.0, 1.0), (1.0, 2.0), (0.0, 2.0))
    )
    problem = Problem(
        problem_id="free-count",
        arena=Arena.rectangle(40.0, 40.0),
        shape=composed,
        objective=MaximizeCount(scale=1.0),
    )
    kinds = [constraint.kind for constraint in problem.effective_constraints]

    assert RequiredShapeCount.kind not in kinds
    for count in (1, 3, 5):
        candidate = make_candidate(
            problem,
            [Placement(f"s{index:03d}", float(index) * 4.0, 0.0) for index in range(count)],
        )
        assert validate(problem, candidate).valid


@dataclass(frozen=True)
class _ForgetfulCount(Objective):
    """An objective that fixes a count and forgets to declare the constraint."""

    count: int
    kind: ClassVar[str] = "forgetful_count"

    def evaluate(self, problem, candidate, measurements=None) -> ObjectiveScore:
        return ObjectiveScore(primary=float(candidate.n_shapes), label="forgetful")

    def constraints(self, problem):
        return ()

    def preset_count(self) -> int | None:
        return self.count

    def to_dict(self):
        return {"type": self.kind, "count": self.count}


def test_the_engine_enforces_a_count_the_objective_forgets(make_candidate) -> None:
    """The central guarantee: a fixed count is the problem's, whatever the objective says."""
    problem = Problem(
        problem_id="forgetful",
        arena=Arena.rectangle(10.0, 10.0),
        shape=Circle(),
        objective=_ForgetfulCount(count=4),
    )
    kinds = [constraint.kind for constraint in problem.effective_constraints]

    assert RequiredShapeCount.kind in kinds
    candidate = make_candidate(
        problem, [Placement(f"s{index:03d}", float(index), 0.0) for index in range(3)], scale=1.0
    )
    result = validate(problem, candidate).result("required_shape_count")

    assert result is not None and not result.valid
    assert "expected 4 shapes, found 3" in result.message
