"""Packable shape families and their size convention.

A :class:`PackableShape` describes a *family* of identical shapes, not a placed
object: it knows the outline at a given scale, its area, and the few numbers the
geometry layer needs to build exact predicates. Position and rotation belong to
:class:`paper_obs.domain.placement.Placement`.

Size convention — every shape is defined by its **natural size** at ``scale = 1``
(a circle of natural radius 0.5 has diameter 1, a square of natural side 1 has
side 1). ``scale`` is a dimensionless multiplier applied to every length of the
shape, and it is exactly the value maximised by the ``maximize_scale``
objective: the primary score of a candidate is therefore a single number, not a
geometry-dependent quantity.

Canonical orientation — a placement's rotation is measured in degrees,
counter-clockwise, about the shape's centre. At rotation 0 a regular polygon
with an even number of sides is axis-aligned (edge parallel to the x axis), and
one with an odd number of sides points up (a vertex on the +y axis). This keeps
the natural bounding boxes comparable between families: a unit square stays
``1 x 1``, a unit triangle is ``1 x sqrt(3)/2``.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

import numpy as np
from shapely import affinity
from shapely.geometry import Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.validation import explain_validity

from .serde import JSON, as_float, as_int, discriminated, require
from .tessellation import CHORD_COUNT

#: Chord count for the circumscribed approximation of a circle when shapely
#: needs an actual polygon (rendering, empty-region analysis, diagnostic areas).
#: The number itself lives in :mod:`paper_obs.domain.tessellation`, with the
#: error it implies; a disc-only verdict is answered in closed form by
#: :mod:`paper_obs.geometry.exact_discs` rather than on this approximation.
CIRCLE_SEGMENTS = CHORD_COUNT


def _circle_angles(segments: int = CHORD_COUNT) -> np.ndarray:
    return np.linspace(0.0, 2.0 * math.pi, segments, endpoint=False)


class PackableShape(ABC):
    """Abstract family of identical packable shapes.

    Subclasses are frozen dataclasses holding the natural size parameters, so
    two shapes of the same family and size compare equal and can be used as
    dictionary keys.
    """

    #: Discriminator used in JSON documents and by operator dispatch.
    kind: ClassVar[str]

    @abstractmethod
    def footprint(self, scale: float, rotation: float = 0.0) -> BaseGeometry:
        """Return the outline centred on the origin, rotated by ``rotation`` degrees."""

    @abstractmethod
    def area(self, scale: float) -> float:
        """Return the shape area at ``scale``."""

    @abstractmethod
    def perimeter(self, scale: float) -> float:
        """Return the outline length at ``scale``, in world length units.

        It is the exact length of the outline the engine builds -- ``2*pi*r`` for a
        disc, ``sides*side`` for a regular polygon, the sum of the segment lengths
        for a hand-drawn outline -- multiplied by ``scale``. The total-perimeter
        objective sums it over the copies, and the source collection's own quantity
        is that sum divided by the copy's unit perimeter: ``2*pi`` for a disc of
        natural radius 1, the side count for a regular polygon of natural side 1.
        """
    @abstractmethod
    def circumradius(self, scale: float) -> float:
        """Return the distance from the centre to the farthest outline point."""

    @abstractmethod
    def inradius(self, scale: float) -> float:
        """Return the distance from the centre to the nearest outline point."""

    @abstractmethod
    def to_dict(self) -> JSON:
        """Return the JSON representation, including the ``type`` discriminator."""

    @property
    def is_circle(self) -> bool:
        """Whether the outline is a disc, which unlocks exact analytic predicates."""
        return False

    @property
    def is_convex(self) -> bool:
        """Whether the outline is convex, which the separating-axis theorem requires."""
        return True

    @property
    def name(self) -> str:
        """Human-readable family name, used by the CLI, the UI and prompts."""
        return self.kind

    @property
    @abstractmethod
    def natural_size(self) -> float:
        """The length that ``scale`` multiplies (a diameter, or a side length)."""

    @property
    def symmetry_period(self) -> float:
        """The smallest rotation, in degrees, that maps the outline onto itself.

        Two rotations that differ by a multiple of it place the same outline. A disc has
        none worth turning for and reports 0; an outline with no symmetry reports 360.
        """
        return 360.0

    def vertices(self, scale: float, rotation: float = 0.0) -> np.ndarray | None:
        """Return the outline corners as a ``(n, 2)`` array, or ``None`` for a circle."""
        return None

    def bounding_box(self, scale: float, rotation: float = 0.0) -> tuple[float, float, float, float]:
        """Return ``(min_x, min_y, max_x, max_y)`` of the outline centred on the origin."""
        min_x, min_y, max_x, max_y = self.footprint(scale, rotation).bounds
        return (float(min_x), float(min_y), float(max_x), float(max_y))

    def describe(self) -> str:
        """One-line description for logs, prompts and the UI."""
        return f"{self.name}, natural size {self.natural_size:g} at scale 1"

    @staticmethod
    def from_dict(data: JSON) -> PackableShape:
        """Decode a shape from its JSON representation."""
        return discriminated("shape", _SHAPE_BUILDERS, data, "shape")


@dataclass(frozen=True)
class Circle(PackableShape):
    """A disc, described by its natural radius (diameter 1 by default)."""

    radius: float = 0.5
    kind: ClassVar[str] = "circle"

    def __post_init__(self) -> None:
        if not self.radius > 0.0:
            raise ValueError(f"circle radius must be positive, got {self.radius!r}")

    @property
    def is_circle(self) -> bool:
        return True

    @property
    def name(self) -> str:
        return "circle"

    @property
    def natural_size(self) -> float:
        return 2.0 * self.radius

    @property
    def symmetry_period(self) -> float:
        return 0.0

    def footprint(self, scale: float, rotation: float = 0.0) -> BaseGeometry:
        radius = self.radius * scale
        angles = _circle_angles()
        # Circumscribed n-gon: it contains the true disc, so any shapely test
        # built on it errs on the safe side (never hides an overflow).
        points = np.column_stack((np.cos(angles), np.sin(angles))) * (radius / math.cos(math.pi / CIRCLE_SEGMENTS))
        return Polygon(points)

    def area(self, scale: float) -> float:
        return math.pi * (self.radius * scale) ** 2

    def perimeter(self, scale: float) -> float:
        return 2.0 * math.pi * self.radius * scale

    def circumradius(self, scale: float) -> float:
        return self.radius * scale

    def inradius(self, scale: float) -> float:
        return self.radius * scale

    def bounding_box(self, scale: float, rotation: float = 0.0) -> tuple[float, float, float, float]:
        """Exact bounding box of the disc, rather than that of its polygon approximation."""
        radius = self.radius * scale
        return (-radius, -radius, radius, radius)

    def to_dict(self) -> JSON:
        return {"type": self.kind, "radius": self.radius}


@dataclass(frozen=True)
class RegularPolygon(PackableShape):
    """A regular convex polygon, described by its side count and natural side length."""

    sides: int
    side: float = 1.0
    kind: ClassVar[str] = "regular_polygon"

    def __post_init__(self) -> None:
        if self.sides < 3:
            raise ValueError(f"a regular polygon needs at least 3 sides, got {self.sides!r}")
        if not self.side > 0.0:
            raise ValueError(f"polygon side must be positive, got {self.side!r}")

    @property
    def name(self) -> str:
        return {3: "equilateral triangle", 4: "square", 6: "regular hexagon"}.get(
            self.sides, f"regular polygon ({self.sides} sides)"
        )

    @property
    def natural_size(self) -> float:
        return self.side

    @property
    def symmetry_period(self) -> float:
        return 360.0 / self.sides

    def _start_angle(self) -> float:
        return math.pi / self.sides if self.sides % 2 == 0 else math.pi / 2.0

    def vertices(self, scale: float, rotation: float = 0.0) -> np.ndarray:
        radius = self.circumradius(scale)
        steps = 2.0 * math.pi / self.sides
        angles = self._start_angle() + math.radians(rotation) + steps * np.arange(self.sides)
        return np.column_stack((np.cos(angles), np.sin(angles))) * radius

    def footprint(self, scale: float, rotation: float = 0.0) -> BaseGeometry:
        return Polygon(self.vertices(scale, rotation))

    def area(self, scale: float) -> float:
        side = self.side * scale
        return self.sides * side**2 / (4.0 * math.tan(math.pi / self.sides))

    def perimeter(self, scale: float) -> float:
        return self.sides * self.side * scale

    def circumradius(self, scale: float) -> float:
        return self.side * scale / (2.0 * math.sin(math.pi / self.sides))

    def inradius(self, scale: float) -> float:
        return self.side * scale / (2.0 * math.tan(math.pi / self.sides))

    def to_dict(self) -> JSON:
        return {"type": self.kind, "sides": self.sides, "side": self.side}


@dataclass(frozen=True)
class CustomPolygon(PackableShape):
    """A polygon drawn by hand: any simple outline, convex or not.

    The vertices are recentred on the shape's own centroid, so that a symmetric
    drawing stays symmetric — its inradius and circumradius read like those of a
    regular polygon. When the centroid falls outside the outline, which is what
    a crescent or a C does, the anchor becomes a point guaranteed to be inside
    instead: a placement's position must always be a point of the shape, since
    an editor drags a shape by its origin and expects the shape to follow.

    Rotation turns the outline about that same point, and ``scale`` multiplies
    every coordinate, so the natural size is the outline as it was drawn.
    """

    points: tuple[tuple[float, float], ...]
    kind: ClassVar[str] = "custom_polygon"

    def __post_init__(self) -> None:
        if len(self.points) < 3:
            raise ValueError(f"a polygon needs at least 3 vertices, got {len(self.points)}")
        outline = Polygon(self.points)
        if not outline.is_valid:
            raise ValueError(f"invalid polygon: {explain_validity(outline)}")
        if outline.area <= 0.0:
            raise ValueError("a polygon must enclose a non-zero area")
        centroid = outline.centroid
        anchor = centroid if outline.covers(centroid) else outline.representative_point()
        object.__setattr__(self, "_outline", affinity.translate(outline, xoff=-anchor.x, yoff=-anchor.y))
        object.__setattr__(self, "_convex", bool(self._outline.equals(self._outline.convex_hull)))
        # The outline length is a fixed property of the drawing, measured once here
        # because the total-perimeter objective reads it at every evaluation.
        object.__setattr__(self, "_perimeter", float(self._outline.exterior.length))

    @property
    def is_convex(self) -> bool:
        """Whether the outline is convex, which decides which predicate can be used."""
        return self._convex

    @property
    def name(self) -> str:
        return f"custom polygon ({len(self.points)} vertices)"

    @property
    def natural_size(self) -> float:
        return float(max(self._outline.bounds[2] - self._outline.bounds[0],
                         self._outline.bounds[3] - self._outline.bounds[1]))

    def vertices(self, scale: float, rotation: float = 0.0) -> np.ndarray:
        points = np.array(self._outline.exterior.coords[:-1], dtype=float) * scale
        angle = math.radians(rotation)
        rotation_matrix = np.array(
            [[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]]
        )
        return points @ rotation_matrix.T

    def footprint(self, scale: float, rotation: float = 0.0) -> BaseGeometry:
        return Polygon(self.vertices(scale, rotation))

    def area(self, scale: float) -> float:
        return float(self._outline.area) * scale**2

    def perimeter(self, scale: float) -> float:
        return float(self._perimeter) * scale

    def circumradius(self, scale: float) -> float:
        return float(np.hypot(*np.array(self._outline.exterior.coords[:-1]).T).max()) * scale

    def inradius(self, scale: float) -> float:
        return float(self._outline.boundary.distance(Point(0.0, 0.0))) * scale

    def to_dict(self) -> JSON:
        return {"type": self.kind, "points": [list(point) for point in self.points]}


def square(side: float = 1.0) -> RegularPolygon:
    """Return a square with the given natural side length."""
    return RegularPolygon(sides=4, side=side)


def equilateral_triangle(side: float = 1.0) -> RegularPolygon:
    """Return an upright equilateral triangle with the given natural side length."""
    return RegularPolygon(sides=3, side=side)


def right_isosceles_triangle(leg: float = 1.0) -> CustomPolygon:
    """Return the isosceles right triangle the collection calls a *tan*, leg 1.

    The tangram is cut from this triangle, and the reference collection packs it,
    so its natural size is the leg: one unit of the published side is one leg.
    """
    return CustomPolygon(points=((0.0, 0.0), (leg, 0.0), (0.0, leg)))


def domino(short_side: float = 1.0) -> CustomPolygon:
    """Return a 2 x 1 rectangle, the domino of the collection.

    Its natural size is the long side, like every family here measures its longest
    axis; the published side of a square holding dominoes is in short sides, which
    is why the short side is the unit.
    """
    long_side = 2.0 * short_side
    return CustomPolygon(
        points=((0.0, 0.0), (long_side, 0.0), (long_side, short_side), (0.0, short_side))
    )


def l_tromino(unit: float = 1.0) -> CustomPolygon:
    """Return the L of three unit squares, the collection's "L".

    Three squares of side one in an L: the outline is concave, which is why this
    family is the one that exercises the polygon path rather than the convex one.
    """
    return CustomPolygon(
        points=(
            (0.0, 0.0),
            (2.0 * unit, 0.0),
            (2.0 * unit, unit),
            (unit, unit),
            (unit, 2.0 * unit),
            (0.0, 2.0 * unit),
        )
    )

#: The families an interface offers as a palette, in the order it shows them. Each
#: entry is an identifier a caller stores, the label a menu shows, and the shape
#: that choice builds: the natural size of a family is the domain's decision, so
#: nobody else has to invent one — a disc of diameter 1, a polygon of side 1, a tan of
#: leg 1, a domino of short side 1, an L of unit squares. The last three come from the
#: reference collection's own matrix, which packs tans, dominoes and L's as well as the
#: regular shapes, and names them there.
PALETTE: tuple[tuple[str, str, PackableShape], ...] = (
    ("disc", "circle", Circle()),
    ("square", "square", square()),
    ("triangle", "equilateral triangle", equilateral_triangle()),
    ("right_triangle", "right triangle", right_isosceles_triangle()),
    ("polygon", "regular polygon", RegularPolygon(sides=5, side=1.0)),
    ("domino", "domino", domino()),
    ("l_tromino", "L-tromino", l_tromino()),
)

#: Palette entries whose side count a caller may change. The count such an entry
#: carries is only the one it starts from, which is why it is labelled without a
#: number: a menu offering to change it would otherwise show a count it is about
#: to be told to forget. There is no hexagon preset for the same reason — a
#: regular polygon of six sides is one field away, and a menu that offered both a
#: hexagon and a polygon would be offering the same shape twice. The default is
#: five rather than six because the domain *names* a six-sided polygon "regular
#: hexagon", which would contradict a menu showing the count in a field.
EDITABLE_SIDES: tuple[str, ...] = ("polygon",)


def catalogue() -> tuple[dict[str, JSON], ...]:
    """Return the shape families a problem can be built from.

    The interface shows this list when a click has to add a shape, and stores the
    ``shape`` it picked. Nothing in the browser needs to know which families exist,
    nor how big one is by default. An entry that carries ``sides`` is a regular
    polygon whose side count the caller chooses; ``shape.sides`` is then only the
    count it starts from.
    """
    entries: list[dict[str, JSON]] = []
    for name, label, shape in PALETTE:
        entry: dict[str, JSON] = {"id": name, "label": label, "shape": shape.to_dict()}
        if name in EDITABLE_SIDES:
            entry["sides"] = shape.sides
        entries.append(entry)
    return tuple(entries)


_SHAPE_BUILDERS = {
    Circle.kind: lambda payload: Circle(
        radius=as_float(require(payload, "radius", "shape"), "shape.radius")
    ),
    RegularPolygon.kind: lambda payload: RegularPolygon(
        sides=as_int(require(payload, "sides", "shape"), "shape.sides"),
        side=as_float(require(payload, "side", "shape"), "shape.side"),
    ),
    CustomPolygon.kind: lambda payload: CustomPolygon(
        points=tuple(
            (as_float(point[0], "shape.points"), as_float(point[1], "shape.points"))
            for point in require(payload, "points", "shape")
        )
    ),
}

__all__ = [
    "CIRCLE_SEGMENTS",
    "PALETTE",
    "Circle",
    "CustomPolygon",
    "PackableShape",
    "RegularPolygon",
    "catalogue",
    "domino",
    "equilateral_triangle",
    "l_tromino",
    "right_isosceles_triangle",
    "square",
]
