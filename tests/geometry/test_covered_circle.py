"""The largest circle a covering actually contains, and the optional union path.

The source pages ask for the largest circle n unit copies can cover. The
objective's score is that number *if* the copies covered the target; the metric
added here reads back what they contain from their own union, so a partial
covering still shows how far it has come. The union path is the same geometry,
serialised only when a caller asks for it. Both are engine computations: the
browser draws them and merges nothing.
"""

from __future__ import annotations

import math

import pytest

from paper_obs.domain import (
    Arena,
    Candidate,
    Circle,
    CoverRegion,
    CustomPolygon,
    MaximizeScale,
    MaximizeTotalPerimeter,
    MinimizeContainer,
    Placement,
    Problem,
    RegularPolygon,
    RotationMode,
    RotationPolicy,
)
from paper_obs.geometry import evaluate
from paper_obs.geometry.facts import build_facts
from paper_obs.geometry.metrics import COVERED_CIRCLE
from paper_obs.geometry.view import build_view, path_data

FREE = RotationPolicy(mode=RotationMode.FREE)


def _problem(problem_id: str, *, arena: Arena, shape, count: int = 1) -> Problem:
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


def _square_problem(problem_id: str, *, arena: Arena, count: int = 1) -> Problem:
    return _problem(problem_id, arena=arena, shape=RegularPolygon(sides=4, side=1.0), count=count)


def test_the_metric_recovers_the_published_radius_of_one_square_on_a_circle() -> None:
    """Squares covering a circle, n = 1: the published 1/2 is read back from geometry.

    The objective scores the reciprocal of the scale, which is the published
    radius only when the covering is valid. The metric is the largest circle the
    copies' union actually contains, in the units of the source's unit copies, so
    the two agree here and can be compared while a covering is incomplete.
    """
    problem = _square_problem("sqcovcir-1", arena=Arena.disk(1.0))
    candidate = _candidate(problem, 2.0, [Placement("s000", 0.0, 0.0)])

    verdict = evaluate(problem, candidate)

    assert verdict.valid
    assert verdict.metrics[COVERED_CIRCLE] == pytest.approx(0.5, abs=1e-6)


def test_the_metric_of_a_pinched_union_is_the_band_half_width() -> None:
    """A thin band across a unit disc: the largest circle inside is its half-height.

    The copies' union intersected with the disc is a band of half-width 0.1, so
    no circle inside it has a radius above 0.1, and the circle of radius 0.1
    centred on the origin fits. The disc is ten times that answer, which is
    exactly why the metric reads the union and not the target. The candidate is
    invalid on purpose: a progress reading is defined while the covering is not.
    """
    thin = CustomPolygon(points=((-1.5, -0.1), (1.5, -0.1), (1.5, 0.1), (-1.5, 0.1)))
    problem = _problem("band", arena=Arena.disk(1.0), shape=thin)
    candidate = _candidate(problem, 1.0, [Placement("s000", 0.0, 0.0)])

    verdict = evaluate(problem, candidate)

    assert not verdict.valid
    assert verdict.metrics[COVERED_CIRCLE] == pytest.approx(0.1, abs=1e-6)


def test_the_metric_is_read_in_unit_copy_units() -> None:
    """A unit copy contains the published half: the scale cancels out."""
    problem = _square_problem("sqcovcir-1", arena=Arena.disk(1.0))
    candidate = _candidate(problem, 1.0, [Placement("s000", 0.0, 0.0)])

    assert evaluate(problem, candidate).metrics[COVERED_CIRCLE] == pytest.approx(0.5, abs=1e-6)


def test_a_square_or_triangle_target_gets_no_circle_metric() -> None:
    """The published copy is a square or a triangle there, and a circle is not faked for it."""
    triangle = RegularPolygon(sides=3, side=1.0)
    arena = Arena.regular_polygon(3, 1.0 / (2.0 * math.sin(math.pi / 3.0)))
    problem = _problem("tricovtri-1", arena=arena, shape=triangle)
    candidate = _candidate(problem, 1.0, [Placement("s000", 0.0, 0.0)])

    verdict = evaluate(problem, candidate)

    assert verdict.valid
    assert COVERED_CIRCLE not in verdict.metrics


def test_a_family_that_is_not_a_covering_gets_no_metric() -> None:
    """The metric answers the covering question, so no other family is given it."""
    problem = Problem(
        problem_id="max",
        arena=Arena.disk(1.0),
        shape=Circle(radius=0.2),
        objective=MaximizeScale(count=1),
        rotation=FREE,
    )
    candidate = _candidate(problem, 1.0, [Placement("s000", 0.0, 0.0)])

    assert COVERED_CIRCLE not in evaluate(problem, candidate).metrics


def test_the_union_path_is_present_only_when_asked_for() -> None:
    """The optional overlay changes nothing for a caller that does not request it."""
    problem = _square_problem("sqcovcir-1", arena=Arena.disk(1.0))
    candidate = _candidate(problem, 2.0, [Placement("s000", 0.0, 0.0)])

    without = build_view(problem, candidate)
    asked = build_view(problem, candidate, with_union=True)

    assert without.union_path is None
    assert "union" not in without.to_dict()
    assert asked.union_path is not None
    assert asked.to_dict()["union"]["path"] == asked.union_path
    # It is the engine's own union of the footprints, not a second construction:
    # the same geometry the covering constraint reads, serialised once.
    facts = build_facts(problem, candidate)
    assert asked.union_path == path_data(facts.shape_union())
    assert asked.union_path.startswith("M ")
    # The union is not tentative: asking twice gives the same string.
    assert asked.union_path == build_view(problem, candidate, with_union=True).union_path


def test_the_objectives_that_own_their_arena_say_so() -> None:
    """The domain is the one that decides whether an arena may be edited."""
    assert CoverRegion(count=1).arena_is_fixed is True
    assert MaximizeTotalPerimeter(count=1).arena_is_fixed is True
    assert MaximizeScale(count=1).arena_is_fixed is False
    # A container family derives its region, so it has no declared arena to edit.
    assert MinimizeContainer(count=1).derives_region is True
    assert MinimizeContainer(count=1).arena_is_fixed is False


def test_a_covering_view_reports_its_arena_fixed_and_read_only() -> None:
    """The view is what tells the interface the arena workspace is read-only."""
    problem = _square_problem("sqcovcir-1", arena=Arena.disk(1.0))
    candidate = _candidate(problem, 2.0, [Placement("s000", 0.0, 0.0)])

    view = build_view(problem, candidate)
    arena = view.to_dict()["arena"]

    assert view.arena_fixed_by_objective is True
    assert view.editable_arena is False
    assert arena["objective_fixed"] is True
    assert arena["editable"] is False


def test_a_maximizing_view_keeps_its_arena_editable() -> None:
    """A family whose arena is only the sandbox it packs into leaves it editable."""
    problem = Problem(
        problem_id="max",
        arena=Arena.disk(1.0),
        shape=RegularPolygon(sides=4, side=1.0),
        objective=MaximizeScale(count=1),
        rotation=FREE,
    )
    candidate = _candidate(problem, 0.5, [Placement("s000", 0.0, 0.0)])

    view = build_view(problem, candidate)

    assert view.arena_fixed_by_objective is False
    assert view.editable_arena is True


def test_a_total_perimeter_view_reports_its_arena_fixed() -> None:
    """The copies move inside the source's container; the container is the question."""
    problem = Problem(
        problem_id="per",
        arena=Arena.rectangle(1.0, 1.0),
        shape=Circle(radius=1.0),
        objective=MaximizeTotalPerimeter(count=1),
        rotation=FREE,
    )
    candidate = _candidate(problem, 1.0, [Placement("s000", 0.0, 0.0, scale=0.4)])

    view = build_view(problem, candidate)

    assert view.arena_fixed_by_objective is True
    assert view.editable_arena is False
