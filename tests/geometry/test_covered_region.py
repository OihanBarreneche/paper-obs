"""The derived covering measurement: the largest target inside the copies' union.

The engine measures the target from the union of the footprints, hands it back as
the region the canvas draws, and the objective scores its size. These tests pin the
two targets the lab computes -- a disc and an axis-aligned square -- the refusal of
the one it does not, and the direction of the score: overlapping copies shrink the
target, spreading them grows it.
"""

from __future__ import annotations

import math

import pytest
import shapely

from paper_obs.domain import (
    Candidate,
    MaximizeCoveredSize,
    Placement,
    Problem,
    RegularPolygon,
    RotationMode,
    RotationPolicy,
)
from paper_obs.geometry import evaluate, facts_for
from paper_obs.geometry.facts import (
    largest_axis_aligned_square,
    largest_equilateral_triangle,
)

FREE = RotationPolicy(mode=RotationMode.FREE)


def _problem(target: str, count: int, shape) -> Problem:
    return Problem(
        problem_id=f"covered-{target}-{count}",
        arena=None,
        shape=shape,
        objective=MaximizeCoveredSize(count=count, target=target),
        rotation=FREE,
    )


def _candidate(problem: Problem, placements) -> Candidate:
    return Candidate(
        candidate_id="c",
        problem_id=problem.problem_id,
        scale=1.0,
        placements=tuple(placements),
    )


def _square() -> RegularPolygon:
    return RegularPolygon(sides=4, side=1.0)


def _block() -> list[Placement]:
    """Four unit squares meeting edge to edge in a 2 x 2 block."""
    return [
        Placement(f"s{index:03d}", x, y)
        for index, (x, y) in enumerate(
            ((-0.5, -0.5), (0.5, -0.5), (-0.5, 0.5), (0.5, 0.5))
        )
    ]


def _stack() -> list[Placement]:
    """Four unit squares on one another: the union is a single unit square."""
    return [Placement(f"s{index:03d}", 0.0, 0.0) for index in range(4)]


def test_a_unit_square_contains_a_circle_of_its_inradius() -> None:
    problem = _problem("circle", 1, _square())
    verdict = evaluate(problem, _candidate(problem, [Placement("s000", 0.0, 0.0)]))

    assert verdict.valid
    assert verdict.score.primary == pytest.approx(0.5, abs=1e-6)
    assert verdict.metrics["covered_size"] == pytest.approx(0.5, abs=1e-6)
    assert verdict.promoted_metric == "covered_size"


def test_a_block_of_squares_grows_the_contained_circle() -> None:
    problem = _problem("circle", 4, _square())
    verdict = evaluate(problem, _candidate(problem, _block()))

    assert verdict.valid
    assert verdict.score.primary == pytest.approx(1.0, abs=1e-4)


def test_overlapping_copies_score_lower_than_spread_copies() -> None:
    """The regression the owner asked for: stacking shrinks the target, a block grows it."""
    problem = _problem("circle", 4, _square())

    stacked = evaluate(problem, _candidate(problem, _stack()))
    spread = evaluate(problem, _candidate(problem, _block()))

    assert stacked.valid and spread.valid
    assert stacked.score.primary < spread.score.primary
    assert stacked.metrics["covered_size"] < spread.metrics["covered_size"]


def test_the_axis_aligned_square_target_of_a_block_is_two() -> None:
    problem = _problem("square", 4, _square())
    verdict = evaluate(problem, _candidate(problem, _block()))

    assert verdict.valid
    assert verdict.score.primary == pytest.approx(2.0, abs=1e-3)


def test_the_axis_aligned_square_target_of_a_stack_is_one() -> None:
    problem = _problem("square", 4, _square())
    verdict = evaluate(problem, _candidate(problem, _stack()))

    assert verdict.valid
    assert verdict.score.primary == pytest.approx(1.0, abs=1e-3)


def test_the_largest_axis_aligned_square_of_a_rectangle_is_its_short_side() -> None:
    """A direct check of the scan: a 2 x 1 box holds a unit square and nothing larger."""
    side, (centre_x, centre_y) = largest_axis_aligned_square(
        shapely.box(-1.0, -0.5, 1.0, 0.5)
    )

    assert side == pytest.approx(1.0, abs=1e-3)
    # The centre may sit anywhere the unit square fits; the scan picks a valid one.
    assert abs(centre_x) <= 0.5 + 1e-3
    assert abs(centre_y) < 0.1


def test_an_empty_union_scores_zero() -> None:
    """Nothing to measure: a zero score, an invalid count and the draft frame to draw."""
    problem = _problem("circle", 4, _square())
    verdict = evaluate(problem, _candidate(problem, []))

    assert not verdict.valid
    assert verdict.score.primary == 0.0
    assert verdict.metrics["covered_size"] == 0.0


def test_the_largest_triangle_side_of_a_square_is_its_side() -> None:
    """A 2 x 2 square holds an equilateral triangle of side 2 and no wider one.

    The orientation is fixed -- one edge horizontal, apex up -- so the triangle's
    width is its side and a square of side 2 cannot hold a wider one. The scan is
    exact here: the analytic value is 2.
    """
    side, _centre = largest_equilateral_triangle(shapely.box(-1.0, -1.0, 1.0, 1.0))

    assert side == pytest.approx(2.0, abs=1e-6)


def test_the_triangle_target_of_a_block_is_the_analytic_side() -> None:
    """Four unit squares in a 2 x 2 block measure an equilateral triangle of side 2.

    The same scan the square target uses, with the containment test asked of the
    whole triangle rather than its three vertices. The drawn region is the measured
    triangle, so its exact area is (sqrt(3) / 4) * 2**2.
    """
    problem = _problem("triangle", 4, _square())
    verdict = evaluate(problem, _candidate(problem, _block()))

    assert verdict.valid
    assert verdict.score.primary == pytest.approx(2.0, abs=1e-6)
    assert verdict.metrics["covered_size"] == pytest.approx(2.0, abs=1e-6)
    assert verdict.metrics["arena_area"] == pytest.approx(math.sqrt(3.0), abs=1e-6)


def test_the_triangle_target_of_a_stack_is_a_unit_square_side() -> None:
    """Four coincident unit squares are one unit square: the triangle side is 1."""
    problem = _problem("triangle", 4, _square())
    stacked = evaluate(problem, _candidate(problem, _stack()))

    assert stacked.valid
    assert stacked.score.primary == pytest.approx(1.0, abs=1e-6)


def test_overlapping_copies_shrink_the_triangle_and_spreading_grows_it() -> None:
    """The regression the owner asked for, on the triangle as on the disc."""
    problem = _problem("triangle", 4, _square())

    stacked = evaluate(problem, _candidate(problem, _stack()))
    spread = evaluate(problem, _candidate(problem, _block()))

    assert stacked.valid and spread.valid
    assert stacked.score.primary < spread.score.primary


def test_a_union_thinner_than_a_scan_cell_reports_no_triangle() -> None:
    """Too thin to sample: the answer is zero, not a triangle nothing tested."""
    side, _centre = largest_equilateral_triangle(shapely.box(-2.0, -0.001, 2.0, 0.001))

    assert side == 0.0


def test_the_reported_triangle_is_contained_as_a_whole_polygon() -> None:
    """The scan tests the triangle, not its three vertices: an edge cannot leave."""
    problem = _problem("triangle", 4, _square())
    facts = facts_for(problem, _candidate(problem, _block()))

    assert facts.shape_union().covers(facts.arena.geometry)


def test_the_empty_union_scores_zero_for_the_triangle_too() -> None:
    problem = _problem("triangle", 4, _square())
    verdict = evaluate(problem, _candidate(problem, []))

    assert not verdict.valid
    assert verdict.score.primary == 0.0
    assert verdict.metrics["covered_size"] == 0.0


def test_the_derived_region_is_a_disc_inside_the_union() -> None:
    """The region the canvas draws is the measured target, not the box the union occupies."""
    problem = _problem("circle", 4, _square())
    candidate = _candidate(problem, _block())

    facts = facts_for(problem, candidate)

    assert facts.arena.area == pytest.approx(math.pi, rel=2e-3)
    # The compiled disc is a circumscribed 256-gon, so it sits about 5e-5 of the
    # radius outside the ideal circle: the union contains it to that descriptive
    # tolerance, exactly as a covering's compiled target does.
    assert facts.shape_union().buffer(1e-3).covers(facts.arena.geometry)
