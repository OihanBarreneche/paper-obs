"""Composite arenas: placing a primitive, and reading an arena as an editable list.

These two features exist for the interface: a sandbox where someone stacks
rectangles and cuts discs out of them needs to move a primitive without touching
the tree, and needs to read a tree back as the list of things it is made of.
"""

from __future__ import annotations

import math

import pytest

from paper_obs.domain import (
    ArbitraryPolygon,
    Arena,
    ArenaPart,
    Disk,
    Rect,
    RegularNGon,
    Translate,
    Union,
    arena_from_parts,
    arena_parts,
    part,
)


def test_a_translated_primitive_keeps_its_size() -> None:
    arena = Arena(shape=Translate(shape=Rect(width=4.0, height=2.0), dx=10.0, dy=-3.0))
    assert arena.area == pytest.approx(8.0)
    assert arena.bounds == pytest.approx((8.0, -4.0, 12.0, -2.0))
    assert arena.contains_point(10.0, -3.0)
    assert not arena.contains_point(0.0, 0.0)


def test_a_translated_primitive_survives_serialisation() -> None:
    arena = Arena(shape=Translate(shape=Disk(radius=2.0), dx=1.0, dy=2.0))
    restored = Arena.from_dict(arena.to_dict())
    assert restored.area == pytest.approx(arena.area)
    assert restored.contains_point(1.0, 2.0)


def test_parts_read_a_stacked_arena() -> None:
    arena = Arena.rectangle(10.0, 10.0).difference(Arena.disk(2.0)).union(Arena.rectangle(2.0, 14.0))
    parts = arena_parts(arena.shape)
    assert parts is not None
    assert [item.op for item in parts] == ["base", "difference", "union"]
    assert [type(item.primitive).__name__ for item in parts] == ["Rect", "Disk", "Rect"]


def test_parts_and_the_tree_are_inverses() -> None:
    arena = Arena.rectangle(10.0, 10.0).difference(Arena.disk(2.0))
    parts = arena_parts(arena.shape)
    assert parts is not None
    rebuilt = Arena(shape=arena_from_parts(parts))
    assert rebuilt.area == pytest.approx(arena.area)
    assert rebuilt.bounds == pytest.approx(arena.bounds)


def test_a_part_carries_its_placement() -> None:
    parts = (
        part("base", Rect(width=10.0, height=10.0)),
        part("difference", Disk(radius=2.0), x=3.0, y=-1.0),
    )
    arena = Arena(shape=arena_from_parts(parts))
    assert arena.area == pytest.approx(100.0 - 4.0 * 3.14159265, rel=1e-4)
    assert not arena.contains_point(3.0, -1.0)
    assert arena.contains_point(0.0, 0.0)
    assert parts[1].offset == (3.0, -1.0)
    assert isinstance(parts[1].primitive, Disk)


def test_an_arena_the_parts_cannot_describe_says_so() -> None:
    """A tree that is not left-nested is a valid arena, just not an editable stack."""
    right = Rect(width=2.0, height=2.0)
    shape = Union(left=Rect(width=1.0, height=1.0), right=Union(left=right, right=Rect(width=1.0, height=1.0)))
    assert arena_parts(shape) is None


def test_a_part_must_hold_a_primitive_and_a_known_operation() -> None:
    with pytest.raises(ValueError, match="unknown arena part operation"):
        ArenaPart(op="multiply", shape=Rect(width=1.0, height=1.0))
    with pytest.raises(ValueError, match="must hold a primitive"):
        ArenaPart(op="base", shape=Union(left=Rect(1.0, 1.0), right=Rect(1.0, 1.0)))


def test_rebuilding_needs_a_base_first() -> None:
    with pytest.raises(ValueError, match="must be the base"):
        arena_from_parts([part("union", Rect(1.0, 1.0))])
    with pytest.raises(ValueError, match="at least one part"):
        arena_from_parts([])


def test_a_drawn_polygon_can_be_a_part() -> None:
    hexagon = Arena(shape=RegularNGon(6, 5.0))
    triangle = ArbitraryPolygon(points=((0.0, 0.0), (4.0, 0.0), (0.0, 4.0)))
    arena = Arena(
        shape=arena_from_parts(
            [part("base", RegularNGon(6, 5.0)), part("intersection", triangle, x=0.0, y=1.0)]
        )
    )
    assert arena.area == pytest.approx(triangle.build().area)
    assert arena.area < hexagon.area


def test_a_turned_part_measures_differently_from_its_unturned_twin() -> None:
    """A quarter turn of a 4 x 2 rectangle swaps the sides of its box; its area does not move."""
    arena = Arena(shape=arena_from_parts((part("base", Rect(width=4.0, height=2.0), angle=90.0),)))
    assert arena.area == pytest.approx(8.0)
    assert arena.bounds == pytest.approx((-1.0, -2.0, 1.0, 2.0))
    assert arena.contains_point(0.0, 1.9)
    assert not arena.contains_point(1.9, 0.0)


def test_a_part_is_turned_about_its_own_origin_before_it_is_placed() -> None:
    """The angle is a turn of the part in its own frame, never a turn of the arena.

    Turned first and placed after, this part stands on end around its offset
    ``(10, 0)``. The other order — placing it first, then turning it about the
    arena's origin — would leave it standing at ``(0, 10)`` instead.
    """
    parts = (part("base", Rect(width=4.0, height=2.0), x=10.0, y=0.0, angle=90.0),)
    arena = Arena(shape=arena_from_parts(parts))
    assert arena.bounds == pytest.approx((9.0, -2.0, 11.0, 2.0))
    assert arena.contains_point(10.0, 1.9)
    assert parts[0].offset == (10.0, 0.0)
    assert parts[0].angle == 90.0


def test_a_turned_part_survives_serialisation() -> None:
    original = part("base", Rect(width=6.0, height=6.0), x=1.0, y=2.0, angle=45.0)
    restored = ArenaPart.from_dict(original.to_dict())
    assert restored.angle == pytest.approx(45.0)
    assert restored.offset == (1.0, 2.0)
    # A square turned by 45 degrees reaches its corners: half a diagonal each way.
    reach = 3.0 * math.sqrt(2.0)
    assert Arena(shape=arena_from_parts((restored,))).bounds == pytest.approx(
        (1.0 - reach, 2.0 - reach, 1.0 + reach, 2.0 + reach)
    )


def test_a_part_writes_its_angle_only_when_it_has_one() -> None:
    """The document of an unturned part is the one it always was, byte for byte."""
    legacy = {
        "op": "difference",
        "shape": {"type": "translate", "shape": {"type": "disk", "radius": 2.0}, "dx": 3.0, "dy": -1.0},
    }
    assert ArenaPart.from_dict(legacy).to_dict() == legacy
    assert part("difference", Disk(radius=2.0), x=3.0, y=-1.0).to_dict() == legacy
    assert part("difference", Disk(radius=2.0), x=3.0, y=-1.0, angle=0.0).to_dict() == legacy
    assert part("base", Rect(width=2.0, height=2.0)).to_dict() == {
        "op": "base",
        "shape": {"type": "rect", "width": 2.0, "height": 2.0},
    }
    assert part("difference", Disk(radius=2.0), x=3.0, y=-1.0, angle=30.0).to_dict() == {
        "op": "difference",
        "shape": {
            "type": "translate",
            "shape": {"type": "rotate", "shape": {"type": "disk", "radius": 2.0}, "angle": 30.0},
            "dx": 3.0,
            "dy": -1.0,
        },
    }


def test_a_turned_part_reads_back_as_the_part_it_was_built_from() -> None:
    """The path an editor uses — read the stack, edit a part, rebuild it — keeps the angle."""
    parts = (
        part("base", Rect(width=6.0, height=6.0)),
        part("difference", Disk(radius=2.0), x=3.0, y=1.0, angle=30.0),
    )
    arena = Arena(shape=arena_from_parts(parts))
    read = arena_parts(arena.shape)
    assert read is not None
    assert read[1].angle == pytest.approx(30.0)
    assert read[1].offset == (3.0, 1.0)
    assert isinstance(read[1].primitive, Disk)
    assert Arena(shape=arena_from_parts(read)).area == pytest.approx(arena.area)


def test_a_turned_part_combines_with_the_others_through_a_boolean_operation() -> None:
    """A 4 x 2 bar turned on end crosses the 6 x 2 base and leaves only the 2 x 2 they share.

    The same bar left flat is swallowed by the base whole, so the two stacks differ
    by the four units the turned bar alone reaches.
    """
    base = part("base", Rect(width=6.0, height=2.0))
    turned = Arena(shape=arena_from_parts((base, part("difference", Rect(width=4.0, height=2.0), angle=90.0))))
    assert turned.area == pytest.approx(8.0)
    assert turned.bounds == pytest.approx((-3.0, -1.0, 3.0, 1.0))
    assert turned.contains_point(2.0, 0.0)
    assert not turned.contains_point(0.0, 0.0)
    flat = Arena(shape=arena_from_parts((base, part("difference", Rect(width=4.0, height=2.0)))))
    assert flat.area == pytest.approx(4.0)
