"""The shape families: measures, canonical orientation, JSON round trip."""

from __future__ import annotations

import math

import numpy as np
import pytest

from paper_obs.domain import (
    EDITABLE_SIDES,
    Circle,
    PackableShape,
    RegularPolygon,
    catalogue,
    domino,
    equilateral_triangle,
    l_tromino,
    right_isosceles_triangle,
    square,
)


def test_circle_measures_follow_the_natural_size() -> None:
    circle = Circle(radius=0.5)
    assert circle.area(1.0) == pytest.approx(math.pi * 0.25)
    assert circle.area(2.0) == pytest.approx(math.pi)
    assert circle.circumradius(2.0) == pytest.approx(1.0)
    assert circle.inradius(2.0) == pytest.approx(1.0)
    assert circle.bounding_box(2.0) == pytest.approx((-1.0, -1.0, 1.0, 1.0))


def test_square_is_axis_aligned_at_rest() -> None:
    shape = square()
    corners = sorted(map(tuple, np.round(shape.vertices(1.0), 12).tolist()))
    assert corners == [(-0.5, -0.5), (-0.5, 0.5), (0.5, -0.5), (0.5, 0.5)]
    assert shape.area(1.0) == pytest.approx(1.0)
    assert shape.inradius(1.0) == pytest.approx(0.5)
    assert shape.circumradius(1.0) == pytest.approx(math.sqrt(0.5))


def test_triangle_points_up() -> None:
    shape = equilateral_triangle()
    vertices = shape.vertices(1.0)
    # Centred on its circumcentre, the upright triangle is taller above than below.
    assert vertices[:, 1].max() == pytest.approx(shape.circumradius(1.0))
    assert shape.area(1.0) == pytest.approx(math.sqrt(3.0) / 4.0)
    min_x, min_y, max_x, max_y = shape.bounding_box(1.0)
    assert max_x - min_x == pytest.approx(1.0)
    assert max_y - min_y == pytest.approx(math.sqrt(3.0) / 2.0)


def test_rotation_by_a_symmetry_maps_the_outline_onto_itself() -> None:
    shape = equilateral_triangle()
    rotated = shape.footprint(1.0, 120.0)
    assert shape.footprint(1.0).symmetric_difference(rotated).area == pytest.approx(0.0, abs=1e-12)


def test_scale_multiplies_every_length() -> None:
    shape = RegularPolygon(sides=6, side=1.0)
    assert shape.area(3.0) == pytest.approx(9.0 * shape.area(1.0))
    assert shape.circumradius(3.0) == pytest.approx(3.0 * shape.circumradius(1.0))
    assert shape.footprint(2.0).area == pytest.approx(shape.area(2.0))


@pytest.mark.parametrize(
    "shape",
    [Circle(radius=0.75), square(side=2.0), RegularPolygon(sides=7, side=1.5)],
)
def test_shapes_round_trip_through_json(shape: PackableShape) -> None:
    assert PackableShape.from_dict(shape.to_dict()) == shape


def test_degenerate_shapes_are_rejected() -> None:
    with pytest.raises(ValueError, match="at least 3 sides"):
        RegularPolygon(sides=2)
    with pytest.raises(ValueError, match="side must be positive"):
        RegularPolygon(sides=4, side=0.0)
    with pytest.raises(ValueError, match="radius must be positive"):
        Circle(radius=0.0)


def test_shapes_have_readable_names() -> None:
    assert square().name == "square"
    assert equilateral_triangle().name == "equilateral triangle"
    assert RegularPolygon(sides=7).name == "regular polygon (7 sides)"
    assert Circle().name == "circle"


def test_the_catalogue_offers_only_shapes_the_domain_can_rebuild() -> None:
    """A palette is a promise: what it offers, a problem can hold."""
    entries = catalogue()
    ids = [entry["id"] for entry in entries]
    assert len(set(ids)) == len(ids), "two entries would collide in a menu"
    rebuilt = [PackableShape.from_dict(entry["shape"]) for entry in entries]
    assert [shape.to_dict() for shape in rebuilt] == [entry["shape"] for entry in entries]
    # Four distinct families: a palette of four discs would be a menu nobody
    # could choose from. A regular polygon of six sides is a field away in the
    # menu, so no hexagon preset is needed beside it.
    assert {shape.name for shape in rebuilt} == {
        "circle",
        "square",
        "equilateral triangle",
        "regular polygon (5 sides)",
        "custom polygon (3 vertices)",
        "custom polygon (4 vertices)",
        "custom polygon (6 vertices)",
    }


def test_the_catalogue_says_which_family_a_caller_may_resize() -> None:
    """An entry that carries ``sides`` is a polygon the caller may resize."""
    entries = {entry["id"]: entry for entry in catalogue()}
    assert [entry["id"] for entry in catalogue() if "sides" in entry] == list(EDITABLE_SIDES)
    polygon = entries["polygon"]
    assert polygon["sides"] == polygon["shape"]["sides"]
    # The label names the family, not the count it starts from: the menu shows the
    # count in a field the caller is about to change.
    assert polygon["label"] == "regular polygon"
    assert not any(character.isdigit() for character in polygon["label"])


def test_the_three_collection_shapes_measure_what_they_are() -> None:
    """A tan of leg 1, a domino of short side 1, an L of unit squares: the collection's units."""
    tan = right_isosceles_triangle()
    assert tan.natural_size == pytest.approx(1.0)
    assert tan.area(1.0) == pytest.approx(0.5)
    assert tan.is_convex
    assert len(tan.vertices(1.0)) == 3

    piece = domino()
    # The natural size is the longest axis, as everywhere else in the domain, so a
    # scale of one is a 2 x 1 piece and the published side reads in short sides.
    assert piece.natural_size == pytest.approx(2.0)
    assert piece.area(1.0) == pytest.approx(2.0)
    assert piece.is_convex

    ell = l_tromino()
    assert ell.natural_size == pytest.approx(2.0)
    assert ell.area(1.0) == pytest.approx(3.0)
    # The L is the family that exercises the concave polygon path rather than the
    # convex one: three squares in an L cannot be separated by a single axis.
    assert not ell.is_convex


def test_perimeters_are_the_exact_outline_lengths() -> None:
    """The outline length at a scale, in world length units.

    A disc is 2*pi*r, a regular polygon is sides*side, and a hand-drawn outline is
    the sum of its segment lengths. The value is the natural length multiplied by
    the scale, which is what the total-perimeter objective sums over the copies.
    """
    disc = Circle(radius=0.5)
    assert disc.perimeter(1.0) == pytest.approx(math.pi)
    assert disc.perimeter(2.0) == pytest.approx(2.0 * math.pi)

    triangle = equilateral_triangle()
    assert triangle.perimeter(1.0) == pytest.approx(3.0)
    assert triangle.perimeter(2.5) == pytest.approx(7.5)

    # Legs 1 and 1, hypotenuse sqrt(2): the collection's tan.
    tan = right_isosceles_triangle()
    assert tan.perimeter(1.0) == pytest.approx(2.0 + math.sqrt(2.0))

    # Three unit squares in an L: twelve cell sides less the two shared pairs.
    assert l_tromino().perimeter(1.0) == pytest.approx(8.0)
    assert l_tromino().perimeter(0.5) == pytest.approx(4.0)
