"""The closed-form disc path: the values it pins, and where it beats the polygon.

A verdict that only involves discs has an arithmetic answer. The engine used to
read every curved wall through a circumscribed chord polygon
(`paper_obs.domain.tessellation`), which is a hair larger than the ideal curve,
so a disc could be accepted while sitting up to ~7.5e-5 of the radius outside it.
`geometry/exact_discs` answers those cases in closed form; these tests pin the
values and, head-on, the difference.
"""

from __future__ import annotations

import math

import pytest
import shapely
from shapely.geometry import Point

from paper_obs.domain import (
    Arena,
    Candidate,
    Circle,
    CoverRegion,
    MaximizeCount,
    Placement,
    Problem,
    RegularPolygon,
    RotationMode,
    RotationPolicy,
)
from paper_obs.domain.tessellation import (
    chord_area_relative_error,
    chord_radius_relative_error,
)
from paper_obs.geometry import exact_discs, facts_for, validate


def lens_area(distance: float, first: float = 1.0, second: float = 1.0) -> float:
    """Area shared by two discs, the textbook closed form."""
    if distance >= first + second:
        return 0.0
    if distance <= abs(first - second):
        return math.pi * min(first, second) ** 2
    first_angle = math.acos(
        (distance * distance + first * first - second * second) / (2.0 * distance * first)
    )
    second_angle = math.acos(
        (distance * distance + second * second - first * first) / (2.0 * distance * second)
    )
    triangle = 0.5 * math.sqrt(
        (-distance + first + second)
        * (distance + first - second)
        * (distance - first + second)
        * (distance + first + second)
    )
    return first * first * first_angle + second * second * second_angle - triangle


def test_the_area_of_a_unit_disc_is_pi() -> None:
    assert exact_discs.union_area([(0.0, 0.0, 1.0)]) == pytest.approx(math.pi, rel=1e-15)


@pytest.mark.parametrize("distance", [0.25, 0.5, 1.0, 1.5, 1.9])
def test_the_union_of_two_unit_discs_is_the_lens_closed_form(distance: float) -> None:
    union = exact_discs.union_area([(0.0, 0.0, 1.0), (distance, 0.0, 1.0)])
    assert union == pytest.approx(2.0 * math.pi - lens_area(distance), rel=1e-12)
    # The lens itself, read back from the union: the number the document pins.
    assert 2.0 * math.pi - union == pytest.approx(lens_area(distance), abs=1e-12)


def test_the_unit_lens_is_the_textbook_number() -> None:
    """Two unit discs a unit apart share 2 pi / 3 - sqrt(3) / 2."""
    expected = 2.0 * math.pi / 3.0 - math.sqrt(3.0) / 2.0
    assert lens_area(1.0) == pytest.approx(expected, abs=1e-15)
    union = exact_discs.union_area([(0.0, 0.0, 1.0), (1.0, 0.0, 1.0)])
    assert 2.0 * math.pi - union == pytest.approx(expected, abs=1e-12)


def test_a_disc_outside_a_disc_complements_the_lens() -> None:
    """The exact magnitude of a disc that leaves a disc-shaped arena."""
    assert exact_discs.disc_difference_area((0.0, 0.0, 1.0), (1.0, 0.0, 1.0)) == pytest.approx(
        math.pi - lens_area(1.0), abs=1e-12
    )
    assert exact_discs.disc_difference_area((0.0, 0.0, 0.5), (0.0, 0.0, 1.0)) == 0.0
    assert exact_discs.disc_difference_area((0.0, 0.0, 1.0), (5.0, 0.0, 1.0)) == pytest.approx(
        math.pi
    )


def test_tangent_concentric_and_coincident_discs_do_not_double_count() -> None:
    assert exact_discs.union_area([(0.0, 0.0, 1.0), (2.0, 0.0, 1.0)]) == pytest.approx(
        2.0 * math.pi
    )
    assert exact_discs.union_area([(0.0, 0.0, 1.0), (0.0, 0.0, 1.0)]) == pytest.approx(math.pi)
    assert exact_discs.union_area([(0.0, 0.0, 2.0), (0.1, 0.0, 0.5)]) == pytest.approx(
        4.0 * math.pi
    )


def test_three_tangent_discs_inside_a_tangent_container_cover_three_discs() -> None:
    radius = 1.0 + 2.0 / math.sqrt(3.0)
    pieces = [(0.0, 2.0 / math.sqrt(3.0), 1.0),
              (-1.0, -1.0 / math.sqrt(3.0), 1.0),
              (1.0, -1.0 / math.sqrt(3.0), 1.0)]
    assert exact_discs.clipped_union_area((0.0, 0.0, radius), pieces) == pytest.approx(
        3.0 * math.pi, abs=1e-12
    )
    unequal = [(0.0, -1.0 / 3.0, 2.0 / 3.0),
               (0.0, 2.0 / 3.0, 1.0 / 3.0)]
    assert exact_discs.clipped_union_area((0.0, 0.0, 1.0), unequal) == pytest.approx(
        5.0 * math.pi / 9.0, abs=1e-12
    )


def test_containment_of_a_disc_in_a_disc_is_closed_form() -> None:
    assert exact_discs.disc_inside_disc((0.9, 0.0, 0.1), (0.0, 0.0, 1.0))
    assert exact_discs.disc_inside_disc((0.8, 0.0, 0.2), (0.0, 0.0, 1.0))  # tangent, inside
    assert not exact_discs.disc_inside_disc((0.9001, 0.0, 0.1), (0.0, 0.0, 1.0))


def test_the_polygon_path_grants_room_the_exact_engine_refuses() -> None:
    """The head-on case: a disc 3e-5 of the radius outside the ideal wall.

    The compiled 256-gon is circumscribed, so near a vertex its boundary sits
    7.53e-5 of the radius outside the ideal circle. A disc that leaves the ideal
    arena by 3e-5 and points at that vertex is accepted by the polygon -- the
    over-grant the document measures -- and refused by the exact containment.
    """
    arena = Arena.disk(1.0)
    radius = 0.1
    over = 3e-5
    distance = 1.0 - radius + over
    polygon_margin = (
        float(shapely.distance(Point(distance, 0.0), arena.geometry.boundary)) - radius
    )

    assert polygon_margin > 0.0, "the compiled polygon grants the room this test is about"
    assert polygon_margin <= chord_radius_relative_error()

    problem = Problem(
        problem_id="chord-grant",
        arena=arena,
        shape=Circle(radius=radius),
        objective=MaximizeCount(scale=1.0),
    )
    candidate = Candidate(
        candidate_id="chord-grant",
        problem_id="chord-grant",
        scale=1.0,
        placements=(Placement("s000", distance, 0.0),),
    )
    facts = facts_for(problem, candidate)

    assert facts.containment[0].margin == pytest.approx(-over, abs=1e-12)
    assert not validate(problem, candidate).valid


def test_the_exact_engine_accepts_the_exact_tangency() -> None:
    problem = Problem(
        problem_id="tangent",
        arena=Arena.disk(1.0),
        shape=Circle(radius=0.1),
        objective=MaximizeCount(scale=1.0),
    )
    candidate = Candidate(
        candidate_id="tangent",
        problem_id="tangent",
        scale=1.0,
        placements=(Placement("s000", 0.9, 0.0),),
    )
    facts = facts_for(problem, candidate)

    assert facts.containment[0].margin == pytest.approx(0.0, abs=1e-12)
    assert validate(problem, candidate).valid


def test_exact_and_polygon_never_disagree_beyond_the_documented_bound() -> None:
    """The two representations, side by side, over a fan of placements."""
    arena = Arena.disk(1.0)
    radius = 0.1
    for over in (-5e-5, -1e-5, 0.0, 1e-5, 5e-5):
        distance = 1.0 - radius + over
        exact_margin = 1.0 - distance - radius
        for step in range(64):
            angle = 2.0 * math.pi * step / 64.0
            point = Point(distance * math.cos(angle), distance * math.sin(angle))
            polygon_margin = float(shapely.distance(point, arena.geometry.boundary)) - radius
            # The polygon can only grant room, never take it away, and never by
            # more than the chord's radius error.
            assert polygon_margin >= exact_margin - 1e-9
            assert polygon_margin - exact_margin <= chord_radius_relative_error() + 1e-9


def test_the_uncovered_area_of_a_covering_of_discs_is_closed_form() -> None:
    problem = Problem(
        problem_id="cover",
        arena=Arena.disk(1.0),
        shape=Circle(radius=1.0),
        objective=CoverRegion(count=1),
        rotation=RotationPolicy(mode=RotationMode.FREE),
    )
    exact_cover = Candidate(
        candidate_id="exact",
        problem_id="cover",
        scale=1.0,
        placements=(Placement("s000", 0.0, 0.0),),
    )
    assert facts_for(problem, exact_cover).uncovered_area() == pytest.approx(0.0, abs=1e-12)

    shifted = Candidate(
        candidate_id="shifted",
        problem_id="cover",
        scale=1.0,
        placements=(Placement("s000", 0.5, 0.0),),
    )
    facts = facts_for(problem, shifted)
    expected = math.pi - lens_area(0.5)
    assert facts.uncovered_area() == pytest.approx(expected, rel=1e-12)

    # The polygon path reads a different number for the same arrangement; the two
    # agree within the chord bound, and the exact one is the closed form.
    polygon = shapely.affinity.translate(Circle(radius=1.0).footprint(1.0), xoff=0.5)
    polygon_uncovered = float(arena_geometry_difference(problem, polygon))
    assert abs(polygon_uncovered - expected) <= chord_area_relative_error() * problem.arena.area + 1e-9


def arena_geometry_difference(problem: Problem, polygon) -> float:
    """The uncovered area the polygon path would report for one footprint."""
    return problem.arena.geometry.difference(polygon).area


def test_the_coverage_reading_declares_its_resolution() -> None:
    disc_problem = Problem(
        problem_id="res-disc",
        arena=Arena.disk(1.0),
        shape=Circle(radius=1.0),
        objective=MaximizeCount(scale=1.0),
    )
    square_problem = Problem(
        problem_id="res-square",
        arena=Arena.disk(1.0),
        shape=RegularPolygon(sides=4, side=1.0),
        objective=MaximizeCount(scale=1.0),
    )
    placement = (Placement("s000", 0.0, 0.0),)
    exact = facts_for(
        disc_problem,
        Candidate(candidate_id="a", problem_id="res-disc", scale=1.0, placements=placement),
    )
    tessellated = facts_for(
        square_problem,
        Candidate(candidate_id="b", problem_id="res-square", scale=1.0, placements=placement),
    )

    assert exact.coverage_resolution() == 0.0
    assert tessellated.coverage_resolution() == pytest.approx(chord_area_relative_error())


def test_point_segment_and_ring_primitives_are_closed_form() -> None:
    square = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    assert exact_discs.point_segment_distance((0.5, 2.0), (0.0, 0.0), (1.0, 0.0)) == pytest.approx(
        2.0
    )
    assert exact_discs.point_segment_distance((-1.0, 0.0), (0.0, 0.0), (1.0, 0.0)) == pytest.approx(
        1.0
    )
    assert exact_discs.point_ring_distance((0.5, 0.5), square) == pytest.approx(0.5)
    assert exact_discs.point_in_ring((0.5, 0.5), square)
    assert not exact_discs.point_in_ring((1.5, 0.5), square)
    assert exact_discs.disc_inside_polygon((0.5, 0.5), 0.5, square)
    assert not exact_discs.disc_inside_polygon((0.5, 0.5), 0.5001, square)
    # A hole makes a swallowed disc leave the region.
    hole = [(0.4, 0.4), (0.6, 0.4), (0.6, 0.6), (0.4, 0.6)]
    assert not exact_discs.disc_inside_polygon((0.5, 0.5), 0.01, square, [hole])


def test_the_polygon_union_agrees_with_the_exact_one_within_the_chord_bound() -> None:
    from paper_obs.domain.shapes import Circle as CircleShape

    discs = [
        (2.5 * math.cos(2.0 * math.pi * k / 20.0), 2.5 * math.sin(2.0 * math.pi * k / 20.0), 1.0)
        for k in range(20)
    ]
    exact = exact_discs.union_area(discs)
    polygons = [
        shapely.affinity.translate(CircleShape(radius=1.0).footprint(1.0), xoff=x, yoff=y)
        for x, y, _ in discs
    ]
    polygon = float(shapely.union_all(polygons).area)

    # Circumscribed footprints overestimate, so the polygon union is never smaller.
    assert polygon >= exact - 1e-9
    assert polygon / exact - 1.0 <= chord_area_relative_error() * 1.5
