"""The engine's covering verdict, and the exact published arrangements it admits.

Covering is decided by an area comparison, so it cannot be exact the way
containment and overlap are: the arena and every disc footprint are circumscribed
256-chords polygons. The tolerance is the lab's descriptive 1e-6, read relative to
the arena area, and these tests pin both ends of it -- the exact arrangements of
the collection are valid, and a real gap is reported with its area. They also pin
the family's structural silence: a covering applies neither containment nor
non-overlap, so a candidate whose copies overlap and stick out is judged on its
coverage alone.
"""

from __future__ import annotations

import math

import pytest

from paper_obs.domain import (
    Arena,
    Candidate,
    Circle,
    COVERAGE_TOLERANCE,
    CoverRegion,
    Placement,
    Problem,
    RegularPolygon,
    RotationMode,
    RotationPolicy,
)
from paper_obs.geometry import evaluate, facts_for, scale_bounds, validate

FREE = RotationPolicy(mode=RotationMode.FREE)


def _problem(problem_id: str, *, arena: Arena, shape, count: int) -> Problem:
    return Problem(
        problem_id=problem_id,
        arena=arena,
        shape=shape,
        objective=CoverRegion(count=count),
        rotation=FREE,
    )


def _candidate(problem: Problem, scale: float, placements: list[Placement]) -> Candidate:
    return Candidate(
        candidate_id="c",
        problem_id=problem.problem_id,
        scale=scale,
        placements=tuple(placements),
    )


def _unit_square_problem(problem_id: str, *, arena: Arena, count: int) -> Problem:
    return _problem(problem_id, arena=arena, shape=RegularPolygon(sides=4, side=1.0), count=count)


def test_one_unit_square_covers_a_unit_disc_at_scale_two() -> None:
    """Squares Covering Circles, n = 1: the published radius is 1/2, Trivial.

    One unit square covers a unit disc exactly when its side is 2, so the primary
    score is the reciprocal 1/2 -- the source's own number, read back.
    """
    problem = _unit_square_problem("sqcovcir-1", arena=Arena.disk(1.0), count=1)
    candidate = _candidate(problem, 2.0, [Placement("s000", 0.0, 0.0)])

    validation = validate(problem, candidate)

    assert validation.valid, validation.summary()
    assert evaluate(problem, candidate, with_metrics=False).primary == pytest.approx(0.5)


def test_the_published_two_square_optimum_is_valid() -> None:
    """Squares Covering Circles, n = 2: the published r = 2 - sqrt(2) is valid.

    The two squares are turned 45 degrees and meet on the disc's diagonals; the
    side that covers a unit disc is the reciprocal of the published radius. The
    number is the source's (proved by Trevor Green in August 1999), not one this
    test invents.
    """
    published_radius = 2.0 - math.sqrt(2.0)
    side = 1.0 / published_radius
    offset = (math.sqrt(2.0) - 1.0) / 2.0
    problem = _unit_square_problem("sqcovcir-2", arena=Arena.disk(1.0), count=2)
    candidate = _candidate(
        problem,
        side,
        [Placement("s000", -offset, 0.0, 45.0), Placement("s001", offset, 0.0, 45.0)],
    )

    validation = validate(problem, candidate)

    assert validation.valid, validation.summary()
    assert evaluate(problem, candidate, with_metrics=False).primary == pytest.approx(published_radius)


def test_a_candidate_that_leaves_a_gap_reports_the_uncovered_area() -> None:
    """On a unit square arena the missing area is exact: 1 - 0.5**2 = 0.75."""
    problem = _unit_square_problem("gap", arena=Arena.rectangle(1.0, 1.0), count=1)
    gapped = _candidate(problem, 0.5, [Placement("s000", 0.0, 0.0)])

    validation = validate(problem, gapped)

    assert not validation.valid
    result = validation.result("arena_covered")
    assert result is not None and not result.valid
    violation = result.violations[0]
    assert violation.kind == "uncovered_arena"
    assert violation.magnitude == pytest.approx(0.75, abs=1e-12)
    assert "uncovered" in violation.message
    # The same square at scale one covers the arena exactly, so the verdict is
    # about the arrangement and not about the arena's own numbers.
    assert validate(problem, _candidate(problem, 1.0, [Placement("s000", 0.0, 0.0)])).valid


def test_a_covering_ignores_containment_and_overlap() -> None:
    """Two overlapping squares sticking out of the disc are judged on coverage alone."""
    side = 1.0 + math.sqrt(2.0) / 2.0
    offset = (math.sqrt(2.0) - 1.0) / 2.0
    problem = _unit_square_problem("sqcovcir-2", arena=Arena.disk(1.0), count=2)
    candidate = _candidate(
        problem,
        side,
        [Placement("s000", -offset, 0.0, 45.0), Placement("s001", offset, 0.0, 45.0)],
    )

    facts = facts_for(problem, candidate)
    validation = validate(problem, candidate)

    assert facts.overlaps, "the two copies share area"
    assert any(not containment.inside for containment in facts.containment), "both stick out"
    assert validation.valid, validation.summary()
    assert validation.collisions == ()
    assert validation.result("arena_containment") is None
    assert validation.result("non_overlap") is None


def test_the_same_shape_covers_its_unit_arena() -> None:
    """A family covers its own unit target exactly: the trivial n = 1 cases.

    Triangles Covering Triangles publishes s = 1 for one unit triangle, and
    Circles Covering Circles publishes r = 1 for one unit circle; both are the
    arena copied onto itself, so the uncovered area is zero, not merely small.
    """
    triangle = RegularPolygon(sides=3, side=1.0)
    triangle_arena = Arena.regular_polygon(3, 1.0 / (2.0 * math.sin(math.pi / 3.0)))
    tri_problem = _problem("tricovtri-1", arena=triangle_arena, shape=triangle, count=1)
    tri_candidate = _candidate(tri_problem, 1.0, [Placement("s000", 0.0, 0.0)])

    assert validate(tri_problem, tri_candidate).valid
    assert facts_for(tri_problem, tri_candidate).uncovered_area() == pytest.approx(0.0, abs=1e-12)

    circle_arena = Arena.disk(1.0)
    circ_problem = _problem("circovcir-1", arena=circle_arena, shape=Circle(radius=1.0), count=1)
    circ_candidate = _candidate(circ_problem, 1.0, [Placement("s000", 0.0, 0.0)])

    assert validate(circ_problem, circ_candidate).valid
    assert evaluate(circ_problem, circ_candidate, with_metrics=False).primary == pytest.approx(1.0)


def test_the_facts_cache_the_union_and_the_uncovered_area() -> None:
    """The union of the footprints is built once per candidate, never per reader."""
    problem = _unit_square_problem("cache", arena=Arena.disk(1.0), count=1)
    facts = facts_for(problem, _candidate(problem, 1.5, [Placement("s000", 0.0, 0.0)]))

    union = facts.shape_union()

    assert facts.shape_union() is union
    uncovered = facts.uncovered_area()
    assert facts.uncovered_area() == uncovered
    assert uncovered == pytest.approx(facts.arena.geometry.difference(union).area)
    assert uncovered > 0.0


def test_covering_bounds_are_a_real_interval_around_the_published_optimum() -> None:
    """The interval is derived, not chosen, and it contains the arrangement's scale."""
    published_radius = 2.0 - math.sqrt(2.0)
    side = 1.0 / published_radius
    problem = _unit_square_problem("sqcovcir-2", arena=Arena.disk(1.0), count=2)

    bounds = scale_bounds(problem)

    assert 0.0 < bounds.low < bounds.high
    assert bounds.low <= side <= bounds.high
    assert "cannot cover" in bounds.rationale
    assert COVERAGE_TOLERANCE == 1e-6


def test_a_covering_reports_no_negative_area() -> None:
    """The union, never the sum of the copies' areas, is what an area metric reads.

    The published two-square optimum overlaps its copies and sticks out of the
    disc: summing their own areas gives 5.83 for an arena of 3.14, so a void read
    from that sum would be -2.69 and a density 1.86. The void is the area the
    arena has left uncovered -- a number that cannot be negative -- and the
    density is the fraction of the arena the union covers. This is the regression
    for the metric the owner saw as a negative area on a valid covering.
    """
    published_radius = 2.0 - math.sqrt(2.0)
    side = 1.0 / published_radius
    offset = (math.sqrt(2.0) - 1.0) / 2.0
    problem = _unit_square_problem("sqcovcir-2", arena=Arena.disk(1.0), count=2)
    candidate = _candidate(
        problem,
        side,
        [Placement("s000", -offset, 0.0, 45.0), Placement("s001", offset, 0.0, 45.0)],
    )

    verdict = evaluate(problem, candidate)

    assert verdict.valid
    metrics = verdict.metrics
    assert metrics["void_area"] >= 0.0
    assert metrics["covered_area"] >= 0.0
    assert 0.0 <= metrics["density"] <= 1.0
    # The sum of the copies' own areas is larger than the arena they cover; kept
    # under its own name it is a legitimate number, and never a covered area.
    assert metrics["packed_area"] > metrics["arena_area"]
    # The void is exactly the union-based reading the constraint and the analysis
    # use, and the two areas partition the arena.
    assert metrics["void_area"] == pytest.approx(facts_for(problem, candidate).uncovered_area())
    assert metrics["covered_area"] + metrics["void_area"] == pytest.approx(metrics["arena_area"])
