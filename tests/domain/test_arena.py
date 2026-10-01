"""The arena: composition, holes, containment, and what a bad arena does."""

from __future__ import annotations

import math

import pytest

from paper_obs.domain import Arena, ArenaShape, Disk, Ellipse, Translate, arena_parts


def test_rectangle_measures() -> None:
    arena = Arena.rectangle(10.0, 4.0)
    assert arena.area == pytest.approx(40.0)
    assert arena.bounds == pytest.approx((-5.0, -2.0, 5.0, 2.0))
    assert arena.size == pytest.approx((10.0, 4.0))
    assert arena.center == pytest.approx((0.0, 0.0))


def test_disk_area_is_close_to_the_analytic_value() -> None:
    arena = Arena.disk(5.0)
    assert arena.area == pytest.approx(math.pi * 25.0, rel=1e-3)


def test_a_parametric_arena_reports_its_exact_area() -> None:
    """The area shown is the declared shape's, not the circumscribed polygon's.

    The owner read 3.1418 on a disc of radius 1 and knew pi is 3.1415: the arena is
    compiled to a circumscribed 256-gon for the boolean engine, and its area is the
    polygon's. The area a problem asks about is the declared one, exactly, and the
    convention holds at any radius.
    """
    disc = Arena.disk(1.0)
    assert disc.area == pytest.approx(math.pi)
    assert Arena.disk(2.5).area == pytest.approx(math.pi * 2.5**2)
    # The compiled 256-gon is circumscribed, so it is a hair larger, never smaller.
    assert disc.compiled_area > disc.area
    assert disc.compiled_area == pytest.approx(disc.area, rel=1e-4)
    assert Arena.ellipse(3.0, 2.0).area == pytest.approx(6.0 * math.pi)
    assert Arena.regular_polygon(3, 2.0).area == pytest.approx(
        0.5 * 3 * 4.0 * math.sin(2.0 * math.pi / 3.0)
    )
    # A translation carries the exact area with it.
    moved = Arena(shape=Translate(shape=Disk(radius=2.0), dx=5.0, dy=-1.0))
    assert moved.area == pytest.approx(4.0 * math.pi)


def test_difference_cuts_a_real_hole() -> None:
    arena = Arena.rectangle(10.0, 10.0).difference(Arena.disk(2.0))
    assert arena.area == pytest.approx(100.0 - math.pi * 4.0, rel=1e-3)
    assert not arena.contains_point(0.0, 0.0)
    assert arena.contains_point(4.0, 4.0)
    assert arena.signed_distance(0.0, 0.0) == pytest.approx(-2.0, rel=1e-3)
    assert arena.signed_distance(3.0, 0.0) == pytest.approx(1.0, rel=1e-3)


def test_union_merges_two_overlapping_primitives() -> None:
    plus = Arena.rectangle(10.0, 2.0).union(Arena.rectangle(2.0, 10.0))
    assert plus.area == pytest.approx(36.0)


def test_signed_distance_is_zero_on_the_wall_and_positive_inside() -> None:
    arena = Arena.rectangle(10.0, 10.0)
    assert arena.signed_distance(5.0, 0.0) == pytest.approx(0.0)
    assert arena.signed_distance(4.0, 0.0) == pytest.approx(1.0)
    assert arena.signed_distance(6.0, 0.0) == pytest.approx(-1.0)


def test_holes_survive_serialisation() -> None:
    arena = Arena.rectangle(10.0, 10.0).difference(Arena.disk(2.0))
    restored = Arena.from_dict(arena.to_dict())
    assert restored.area == pytest.approx(arena.area)
    assert restored.contains_point(0.0, 0.0) is False
    assert restored.contains_point(4.0, 4.0) is True


def test_a_self_intersecting_polygon_is_rejected() -> None:
    bowtie = [(0.0, 0.0), (2.0, 2.0), (2.0, 0.0), (0.0, 2.0)]
    with pytest.raises(ValueError, match="invalid arena geometry"):
        Arena.polygon(bowtie)


def test_an_empty_composition_is_rejected() -> None:
    with pytest.raises(ValueError, match="empty region"):
        Arena.rectangle(2.0, 2.0).difference(Arena.rectangle(4.0, 4.0))


def test_arena_tree_is_what_gets_serialised() -> None:
    arena = Arena.rectangle(10.0, 10.0).difference(Arena.disk(2.0))
    assert arena.to_dict()["shape"]["type"] == "difference"
    assert arena.shape.describe() == "(rectangle 10 x 10 minus disk of radius 2)"


def test_a_reference_length_round_trips_and_is_omitted_when_unset() -> None:
    """The declared published length travels in JSON; an arena without one keeps its old form."""
    measured = Arena(shape=Arena.rectangle(2.0, 1.0).shape, reference_length=1.0)
    assert Arena.from_dict(measured.to_dict()).reference_length == 1.0
    assert "reference_length" not in Arena.rectangle(2.0, 1.0).to_dict()
    assert Arena.from_dict(Arena.rectangle(2.0, 1.0).to_dict()).reference_length is None


def test_a_non_positive_reference_length_is_refused() -> None:
    with pytest.raises(ValueError, match="reference_length"):
        Arena(shape=Arena.rectangle(2.0, 1.0).shape, reference_length=0.0)


# -- the ellipse ------------------------------------------------------------


def test_ellipse_measures() -> None:
    arena = Arena.ellipse(3.0, 2.0)
    assert arena.area == pytest.approx(math.pi * 6.0, rel=1e-3)
    assert arena.bounds == pytest.approx((-3.0, -2.0, 3.0, 2.0), rel=1e-3)
    assert arena.size == pytest.approx((6.0, 4.0), rel=1e-3)
    assert arena.center == pytest.approx((0.0, 0.0))


def test_an_ellipse_grants_room_on_both_axes() -> None:
    """The same circumscribed tessellation as a disc, applied to each semi-axis."""
    arena = Arena.ellipse(5.0, 2.0)
    assert arena.contains_point(4.0, 0.0)
    assert arena.contains_point(0.0, 1.0)
    assert not arena.contains_point(5.1, 0.0)
    assert not arena.contains_point(0.0, 2.1)
    assert arena.shape.describe() == "ellipse of semi-axes 5 x 2"


def test_an_ellipse_is_a_primitive_an_editor_can_hold() -> None:
    arena = Arena.ellipse(3.0, 2.0)
    parts = arena_parts(arena.shape)
    assert parts is not None and len(parts) == 1
    assert parts[0].primitive == Ellipse(a=3.0, b=2.0)


def test_a_semi_axis_is_what_gets_serialised() -> None:
    arena = Arena.ellipse(3.0, 2.0)
    assert arena.to_dict()["shape"] == {"type": "ellipse", "a": 3.0, "b": 2.0}
    assert ArenaShape.from_dict(arena.to_dict()["shape"]) == Ellipse(a=3.0, b=2.0)
    restored = Arena.from_dict(arena.to_dict())
    assert restored.area == pytest.approx(arena.area)
    assert restored.bounds == pytest.approx(arena.bounds)


def test_an_ellipse_composes_with_the_boolean_operations() -> None:
    holed = Arena.ellipse(4.0, 2.0).difference(Arena.disk(1.0))
    assert holed.area == pytest.approx(math.pi * 8.0 - math.pi, rel=1e-3)
    assert not holed.contains_point(0.0, 0.0)
    assert holed.contains_point(3.0, 0.0)

    wide, tall = Arena.ellipse(4.0, 2.0), Arena.ellipse(2.0, 4.0)
    shared, together = wide.intersection(tall), wide.union(tall)
    assert 0.0 < shared.area < min(wide.area, tall.area)
    # An ellipse is a parametric primitive, so its area is the exact pi*a*b; a
    # boolean result has no closed form and reports its compiled outline's area.
    # The identity of areas therefore holds on the compiled readings, which is the
    # geometry the boolean algebra actually acted on.
    assert shared.compiled_area == pytest.approx(
        wide.compiled_area + tall.compiled_area - together.compiled_area
    )


@pytest.mark.parametrize("a, b", [(0.0, 1.0), (1.0, 0.0), (-1.0, 1.0), (1.0, -2.0)])
def test_degenerate_ellipse_semi_axes_are_refused(a: float, b: float) -> None:
    with pytest.raises(ValueError, match="semi-axes must be positive"):
        Arena.ellipse(a, b)
