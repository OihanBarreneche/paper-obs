"""Hand-drawn shapes: centring, and what a concave outline changes in the engine.

A concave shape is the reason the engine has two collision paths at all. The
separating-axis theorem is exact and fast but assumes convexity: told to compare
two crosses sitting side by side, it would compare the convex hulls and report a
huge overlap that does not exist. These tests pin down the case that a plain SAT
implementation gets wrong.
"""

from __future__ import annotations

import math

import pytest
from shapely.geometry import Point, Polygon

from paper_obs.domain import (
    Arena,
    Candidate,
    CustomPolygon,
    MaximizeCount,
    PackableShape,
    Placement,
    Problem,
    RotationMode,
    RotationPolicy,
)
from paper_obs.geometry import evaluate, facts_for
from paper_obs.geometry.predicates import convex_penetration_depth

#: A plus sign, five unit cells around a centre cell: concave, and the convex
#: hull of two of them overlaps long before the outlines do.
PLUS = (
    (1.0, 0.0),
    (2.0, 0.0),
    (2.0, 1.0),
    (3.0, 1.0),
    (3.0, 2.0),
    (2.0, 2.0),
    (2.0, 3.0),
    (1.0, 3.0),
    (1.0, 2.0),
    (0.0, 2.0),
    (0.0, 1.0),
    (1.0, 1.0),
)

SQUARE = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))


def _cross() -> CustomPolygon:
    return CustomPolygon(points=PLUS)


def _problem(shape: PackableShape, arena: Arena | None = None) -> Problem:
    return Problem(
        problem_id="custom",
        arena=arena or Arena.rectangle(20.0, 20.0),
        shape=shape,
        objective=MaximizeCount(scale=1.0),
    )


def _candidate(problem: Problem, *positions: tuple[float, float]) -> Candidate:
    return Candidate(
        candidate_id="c",
        problem_id=problem.problem_id,
        scale=1.0,
        placements=tuple(
            Placement(shape_id=f"s{index:03d}", x=x, y=y)
            for index, (x, y) in enumerate(positions)
        ),
    )


def test_the_outline_is_centred_on_a_point_inside_it() -> None:
    cross = _cross()
    assert cross.area(1.0) == pytest.approx(5.0)
    assert cross.footprint(1.0).covers(Point(0.0, 0.0))
    # A cross is not convex, and its representative point is not its centroid.
    assert cross.is_convex is False
    assert CustomPolygon(points=SQUARE).is_convex is True


def test_measures_follow_the_scale() -> None:
    cross = _cross()
    assert cross.area(2.0) == pytest.approx(4.0 * cross.area(1.0))
    # The arms of a cross end halfway along its sides: the farthest vertex is
    # 1.5 out on one axis and 0.5 on the other, not the corner of the box.
    assert cross.circumradius(1.0) == pytest.approx(math.hypot(1.5, 0.5))
    # All four walls around the centre of a cross are open: the nearest outline
    # point from the origin is a corner, not the side of the middle cell.
    assert cross.inradius(1.0) == pytest.approx(math.hypot(0.5, 0.5))
    assert cross.natural_size == pytest.approx(3.0)


def test_rotation_turns_the_outline_about_its_own_point() -> None:
    cross = _cross()
    turned = cross.footprint(1.0, 90.0)
    assert turned.area == pytest.approx(cross.area(1.0))
    assert turned.covers(Point(0.0, 0.0))
    assert cross.footprint(1.0).symmetric_difference(turned).area > 0.0


def test_a_custom_shape_survives_serialisation() -> None:
    cross = _cross()
    assert PackableShape.from_dict(cross.to_dict()) == cross


def test_a_degenerate_outline_is_refused() -> None:
    with pytest.raises(ValueError, match="at least 3 vertices"):
        CustomPolygon(points=((0.0, 0.0), (1.0, 1.0)))
    with pytest.raises(ValueError, match="invalid polygon"):
        CustomPolygon(points=((0.0, 0.0), (2.0, 2.0), (2.0, 0.0), (0.0, 2.0)))


#: An L-tromino: three unit cells in an L. Two of them, one turned upside down,
#: tile a 3 x 2 rectangle exactly — so their convex hulls overlap while their
#: outlines only touch. A separating-axis predicate would report a deep overlap.
TROMINO = ((0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (1.0, 1.0), (1.0, 2.0), (0.0, 2.0))

#: Centre of the 3 x 2 rectangle the two pieces tile, and the anchor the shape
#: is stored around. A half-turn about the centre maps one piece onto the other,
#: so placing the second at ``2 * centre - anchor`` is exactly that half-turn.
TILING_CENTRE = (1.5, 1.0)
ANCHOR = Polygon(TROMINO).centroid


def _tromino_pair(*, offset: tuple[float, float] = (0.0, 0.0)) -> tuple[Problem, Candidate]:
    """Return two L-trominoes and their problem, the second one turned upside down.

    At ``offset=(0, 0)`` the two tile the 3 x 2 rectangle exactly; shifted a
    little, they overlap and the engine has to say by how much.
    """
    problem = Problem(
        problem_id="tiling",
        arena=Arena.rectangle(10.0, 10.0),
        shape=CustomPolygon(points=TROMINO),
        objective=MaximizeCount(scale=1.0),
        rotation=RotationPolicy(mode=RotationMode.FREE),
    )
    second = (
        2.0 * TILING_CENTRE[0] - ANCHOR.x + offset[0],
        2.0 * TILING_CENTRE[1] - ANCHOR.y + offset[1],
    )
    candidate = Candidate(
        candidate_id="c",
        problem_id=problem.problem_id,
        scale=1.0,
        placements=(
            Placement(shape_id="s000", x=0.0, y=0.0),
            Placement(shape_id="s001", x=second[0], y=second[1], rotation=180.0),
        ),
    )
    return problem, candidate


def test_two_concave_shapes_can_tile_a_rectangle() -> None:
    """The two pieces touch everywhere and overlap nowhere: a perfect tiling."""
    problem, candidate = _tromino_pair()
    facts = facts_for(problem, candidate)
    assert facts.overlaps == ()

    first, second = (instance.geometry for instance in facts.instances)
    assert first.union(second).area == pytest.approx(6.0)
    assert first.intersection(second).area == pytest.approx(0.0)

    # The convex-only predicate is exactly what would get this wrong: told to
    # compare the two pieces as if they were convex, it reports a deep overlap.
    assert convex_penetration_depth(facts.instances[0].vertices, facts.instances[1].vertices) > 0.0


def test_an_overlap_between_concave_shapes_is_reported_as_a_square_root_of_area() -> None:
    # The two pieces touch along a line when they tile, and a half-unit slide
    # along that line keeps them touching: it takes a full unit for the corner of
    # one to bite into the other.
    problem, slid = _tromino_pair(offset=(-1.0, 0.0))
    facts = facts_for(problem, slid)
    assert len(facts.overlaps) == 1
    shared = facts.instances[0].geometry.intersection(facts.instances[1].geometry).area
    assert shared > 0.0
    assert facts.overlaps[0].depth == pytest.approx(math.sqrt(shared))


def test_a_concave_shape_still_has_to_fit_in_the_arena() -> None:
    cross = _cross()
    small = Arena.rectangle(3.0, 3.0)
    inside = facts_for(_problem(cross, small), _candidate(_problem(cross, small), (0.0, 0.0)))
    assert all(containment.inside for containment in inside.containment)

    shifted = _candidate(_problem(cross, small), (8.0, 0.0))
    assert not evaluate(_problem(cross, small), shifted).valid
