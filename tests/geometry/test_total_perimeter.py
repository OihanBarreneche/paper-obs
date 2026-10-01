"""The engine's total-perimeter verdict, and the source's own published numbers.

The source packs copies of independent sizes and prints the largest sum of their
radii (circles) or sides (regular polygons). With the collection's unit copies --
a circle of radius 1, a regular polygon of side 1 -- the promoted total_scale is
exactly that printed sum, and the trivial n = 1 cases pin it: one circle of radius
1/2 in a unit square is the page's own Sigma r = 1/2. Containment and non-overlap
still decide validity, so a copy too large for the arena, or two copies sharing
area, are refused like any other packing.
"""

from __future__ import annotations

import math

import pytest

from paper_obs.domain import (
    Arena,
    Candidate,
    Circle,
    MaximizeTotalPerimeter,
    Placement,
    Problem,
    RegularPolygon,
    RotationMode,
    RotationPolicy,
)
from paper_obs.geometry import evaluate, scale_bounds, validate
from paper_obs.search import varied_initialize

FREE = RotationPolicy(mode=RotationMode.FREE)


def _problem(problem_id: str, *, arena: Arena, shape, count: int) -> Problem:
    return Problem(
        problem_id=problem_id,
        arena=arena,
        shape=shape,
        objective=MaximizeTotalPerimeter(count=count),
        rotation=FREE,
    )


def _candidate(problem: Problem, placements: list[Placement]) -> Candidate:
    """A total-perimeter candidate: the common scale is the objective's own 1."""
    return Candidate(
        candidate_id="c", problem_id=problem.problem_id, scale=1.0, placements=tuple(placements)
    )


def test_one_disc_of_radius_half_fills_a_unit_square_as_the_source_prints() -> None:
    """Circles in Squares, n = 1: "Sigma r = 1/2 = .500, Trivial"."""
    problem = _problem(
        "cirRsqu-1", arena=Arena.rectangle(1.0, 1.0), shape=Circle(radius=1.0), count=1
    )
    candidate = _candidate(problem, [Placement("s000", 0.0, 0.0, scale=0.5)])

    validation = validate(problem, candidate)
    verdict = evaluate(problem, candidate)

    assert validation.valid, validation.summary()
    assert verdict.primary == pytest.approx(math.pi)
    assert verdict.metrics["total_scale"] == pytest.approx(0.5)
    assert verdict.metrics["total_perimeter"] == pytest.approx(math.pi)
    assert verdict.promoted_metric == "total_scale"


def test_the_arena_refuses_a_copy_it_cannot_hold_and_the_engine_still_scores_it() -> None:
    """A bigger copy is worth more and is refused; a fitting one is worth less."""
    problem = _problem(
        "cirRsqu-1", arena=Arena.rectangle(1.0, 1.0), shape=Circle(radius=1.0), count=1
    )
    outside = _candidate(problem, [Placement("s000", 0.0, 0.0, scale=0.6)])
    fitting = _candidate(problem, [Placement("s000", 0.0, 0.0, scale=0.5)])
    smaller = _candidate(problem, [Placement("s000", 0.0, 0.0, scale=0.4)])

    assert not validate(problem, outside).valid
    assert validate(problem, outside).result("arena_containment").valid is False
    assert validate(problem, fitting).valid
    assert evaluate(problem, outside).primary > evaluate(problem, smaller).primary
    assert evaluate(problem, fitting).primary > evaluate(problem, smaller).primary


def test_two_copies_that_share_area_are_refused_by_non_overlap() -> None:
    problem = _problem(
        "overlap", arena=Arena.rectangle(1.0, 1.0), shape=Circle(radius=1.0), count=2
    )
    overlapping = _candidate(
        problem,
        [Placement("s000", 0.0, 0.0, scale=0.4), Placement("s001", 0.5, 0.0, scale=0.4)],
    )

    validation = validate(problem, overlapping)
    overlap = validation.result("non_overlap")

    assert not validation.valid
    assert overlap is not None and not overlap.valid


def test_a_polygon_copy_reads_the_published_sum_of_sides() -> None:
    """Triangles in Circles, n = 1: "Sigma s = sqrt(3) = 1.73205+, Trivial".

    The unit equilateral triangle inscribed in the unit circle has circumradius 1,
    so its scale is sqrt(3) and the sum of the local scales is the page's sum.
    """
    problem = _problem(
        "triRcir-1", arena=Arena.disk(1.0), shape=RegularPolygon(sides=3, side=1.0), count=1
    )
    candidate = _candidate(problem, [Placement("s000", 0.0, 0.0, scale=math.sqrt(3.0))])

    verdict = evaluate(problem, candidate)

    assert verdict.valid, verdict.validation.summary()
    assert verdict.metrics["total_scale"] == pytest.approx(math.sqrt(3.0))
    assert verdict.primary == pytest.approx(3.0 * math.sqrt(3.0))


def test_a_regular_polygon_matching_its_arena_copies_it() -> None:
    """Pentagons in Pentagons, n = 1: "Sigma s = 1, Trivial"."""
    circumradius = 1.0 / (2.0 * math.sin(math.pi / 5.0))
    problem = _problem(
        "penRpen-1",
        arena=Arena.regular_polygon(5, circumradius),
        shape=RegularPolygon(sides=5, side=1.0),
        count=1,
    )
    candidate = _candidate(problem, [Placement("s000", 0.0, 0.0, scale=1.0)])

    verdict = evaluate(problem, candidate)

    assert verdict.valid, verdict.validation.summary()
    assert verdict.metrics["total_scale"] == pytest.approx(1.0)
    assert verdict.primary == pytest.approx(5.0)


def test_the_scale_bounds_are_a_real_interval_over_a_local_size() -> None:
    """The interval describes one copy's local size, not the fixed common scale."""
    problem = _problem(
        "cirRsqu-5", arena=Arena.rectangle(1.0, 1.0), shape=Circle(radius=1.0), count=5
    )

    bounds = scale_bounds(problem)

    assert 0.0 < bounds.low < bounds.high
    assert bounds.high == pytest.approx(0.5)
    assert problem.objective.preset_scale() == 1.0
    assert "bounding box" in bounds.rationale


def test_the_varied_initialiser_starts_somewhere_the_engine_accepts() -> None:
    problem = _problem(
        "cirRsqu-6", arena=Arena.rectangle(1.0, 1.0), shape=Circle(radius=1.0), count=6
    )
    candidate = varied_initialize(problem)
    verdict = evaluate(problem, candidate)
    scales = [placement.scale for placement in candidate.placements]

    assert candidate.n_shapes == 6
    assert candidate.scale == 1.0
    assert all(scale is not None and scale > 0.0 for scale in scales)
    assert len({round(scale, 9) for scale in scales if scale is not None}) == 2, (
        "one large copy, the rest equal"
    )
    assert verdict.valid, verdict.validation.summary()
    assert verdict.primary > 0.0
    assert verdict.metrics["total_scale"] == pytest.approx(
        sum(scale for scale in scales if scale is not None)
    )


def test_the_varied_initialiser_is_deterministic() -> None:
    problem = _problem(
        "cirRsqu-6", arena=Arena.rectangle(1.0, 1.0), shape=Circle(radius=1.0), count=6
    )
    first = varied_initialize(problem)
    second = varied_initialize(problem)

    # The candidate id is fresh every call; the geometry is what must replay.
    assert first.placements == second.placements
    assert first.scale == second.scale
