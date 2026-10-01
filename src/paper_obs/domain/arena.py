"""The arena: the region shapes must be packed into.

An arena is a small tree of primitives and boolean operations rather than a flat
coordinate list. The tree is what gets serialised, edited in the problem editor
and rebuilt by the procedural generator; the shapely geometry is compiled from
it once per :class:`Arena` instance and then treated as read-only.

Conventions: every primitive is centred on the origin, ``+x`` points right and
``+y`` points up (mathematical orientation). The renderer flips ``y`` for SVG,
nothing else in the project does.

Arcs (``Disk``, ``Ellipse``) are tessellated into a *circumscribed* polygon: every
edge is tangent to the true curve, so the arena is at worst
``tessellation.chord_radius_relative_error()`` -- 7.53e-5 of the radius at the
default chord count -- larger than the ideal disc or ellipse. The direction of
that error is deliberate. An inscribed
tessellation would be marginally smaller, and would therefore reject the exact
tangent arrangements a lattice produces — an engine that refuses the wall is
worse for a lab that compares search strategies than an engine that grants a
hair of extra room on a curve. Straight walls, which is every other arena, are
exact.

The area a reader is shown is not that polygon's: a parametric primitive reports
the exact area of the *declared* shape -- ``pi * r**2`` for a disc of radius ``r``,
``pi * a * b`` for an ellipse, the closed form for a regular polygon -- and only a
boolean composition of arcs falls back on the compiled outline. The predicates and
booleans still read the compiled polygon, which is what :attr:`Arena.compiled_area`
exposes; see :attr:`Arena.area` for the two readings and why they differ.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import ClassVar

import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import MultiPolygon, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.validation import explain_validity

from .serde import JSON, as_float, as_int, discriminated, jsonable, require
from .tessellation import CHORD_COUNT

#: Number of chords used for a full circle when tessellating an arena arc. The
#: number lives in :mod:`paper_obs.domain.tessellation` with the error it
#: implies; a disc arena is decided in closed form by
#: :mod:`paper_obs.geometry.exact_discs`, not on this polygon.
ARC_SEGMENTS = CHORD_COUNT


def polygonal(geometry: BaseGeometry, *, context: str) -> BaseGeometry:
    """Reduce ``geometry`` to its polygonal parts, rejecting an empty result.

    Boolean operations can return a ``GeometryCollection`` (a polygon touching
    another one by a single point, for instance) or nothing at all. Both cases
    are turned into explicit errors here rather than silently propagating a
    degenerate arena into the engine.
    """
    if geometry.is_empty:
        raise ValueError(f"{context}: the operation produced an empty region")
    if isinstance(geometry, (Polygon, MultiPolygon)):
        return geometry
    parts = [part for part in shapely.get_parts(geometry) if part.geom_type in ("Polygon", "MultiPolygon")]
    if not parts:
        raise ValueError(f"{context}: the operation produced no 2D region")
    return shapely.union_all(parts)


class ArenaShape(ABC):
    """Abstract node of the arena tree."""

    #: Discriminator used in JSON documents.
    kind: ClassVar[str]

    @abstractmethod
    def build(self) -> BaseGeometry:
        """Compile the node into a shapely geometry."""

    @abstractmethod
    def to_dict(self) -> JSON:
        """Return the JSON representation, including the ``type`` discriminator."""

    @abstractmethod
    def describe(self) -> str:
        """One-line human-readable description of the node."""

    @property
    def area(self) -> float | None:
        """Exact area of the declared shape, or ``None`` when there is no closed form.

        A primitive with a parametric outline -- a rectangle, a disc, an ellipse, a
        regular polygon -- and any translation or rotation of one has an exact area,
        which is the number a reader means by "the area of the arena". An arbitrary
        polygon is exact too, but its own outline already carries it; a boolean
        composition of *arcs* has no closed form at all, and only the compiled
        polygon can answer. ``None`` is the honest answer in both cases: the caller
        then reads :attr:`Arena.compiled_area`.
        """
        return None

    @staticmethod
    def from_dict(data: JSON) -> ArenaShape:
        """Decode an arena node from its JSON representation."""
        return discriminated("arena", _ARENA_BUILDERS, data, "arena")


@dataclass(frozen=True)
class Rect(ArenaShape):
    """An axis-aligned rectangle centred on the origin."""

    width: float
    height: float
    kind: ClassVar[str] = "rect"

    def __post_init__(self) -> None:
        if not self.width > 0.0 or not self.height > 0.0:
            raise ValueError(f"rect dimensions must be positive, got {self.width!r} x {self.height!r}")

    def build(self) -> BaseGeometry:
        half_w, half_h = self.width / 2.0, self.height / 2.0
        return box(-half_w, -half_h, half_w, half_h)

    @property
    def area(self) -> float:
        return self.width * self.height

    def describe(self) -> str:
        return f"rectangle {self.width:g} x {self.height:g}"

    def to_dict(self) -> JSON:
        return {"type": self.kind, "width": self.width, "height": self.height}


@dataclass(frozen=True)
class Disk(ArenaShape):
    """A disc centred on the origin."""

    radius: float
    kind: ClassVar[str] = "disk"

    def __post_init__(self) -> None:
        if not self.radius > 0.0:
            raise ValueError(f"disk radius must be positive, got {self.radius!r}")

    def build(self) -> BaseGeometry:
        # Circumscribed: every edge is tangent to the true circle, so the arena
        # contains the ideal disc instead of cutting into it. A shape resting on
        # a curved wall is then accepted at the exact tangency a lattice
        # produces, rather than rejected by half a chord.
        radius = self.radius / math.cos(math.pi / ARC_SEGMENTS)
        return Point(0.0, 0.0).buffer(radius, quad_segs=ARC_SEGMENTS // 4)

    @property
    def area(self) -> float:
        # The declared disc, not the circumscribed 256-gon the boolean engine uses:
        # the area of the shape a problem asks about is the exact one, at any radius.
        return math.pi * self.radius * self.radius

    def describe(self) -> str:
        return f"disk of radius {self.radius:g}"

    def to_dict(self) -> JSON:
        return {"type": self.kind, "radius": self.radius}


@dataclass(frozen=True)
class Ellipse(ArenaShape):
    """An axis-aligned ellipse centred on the origin, given by its two semi-axes.

    ``a`` is the semi-axis along ``+x`` and ``b`` the one along ``+y``, so the ellipse
    spans ``2a`` by ``2b`` — the collection's own notation for the region it packs
    into ("with semi-axes a and b"). The two are independent: a tall ellipse is
    written with ``b > a``, and it is the region of the wide one turned a quarter
    turn.
    """

    a: float
    b: float
    kind: ClassVar[str] = "ellipse"

    def __post_init__(self) -> None:
        if not self.a > 0.0 or not self.b > 0.0:
            raise ValueError(f"ellipse semi-axes must be positive, got {self.a!r} x {self.b!r}")

    def build(self) -> BaseGeometry:
        # Circumscribed like a Disk, and for the same reason: the unit circle's
        # tangent polygon scaled by the two semi-axes. Scaling is affine, so it
        # carries tangent lines to tangent lines and every edge stays tangent to
        # the true ellipse; the arena grants the same hair of extra room on both
        # axes instead of cutting into the curve a lattice can rest on.
        unit = Point(0.0, 0.0).buffer(1.0 / math.cos(math.pi / ARC_SEGMENTS), quad_segs=ARC_SEGMENTS // 4)
        return affinity.scale(unit, xfact=self.a, yfact=self.b, origin=(0.0, 0.0))

    @property
    def area(self) -> float:
        return math.pi * self.a * self.b

    def describe(self) -> str:
        return f"ellipse of semi-axes {self.a:g} x {self.b:g}"

    def to_dict(self) -> JSON:
        return {"type": self.kind, "a": self.a, "b": self.b}


@dataclass(frozen=True)
class RegularNGon(ArenaShape):
    """A regular polygon centred on the origin, given by circumradius."""

    sides: int
    circumradius: float
    kind: ClassVar[str] = "regular_ngon"

    def __post_init__(self) -> None:
        if self.sides < 3:
            raise ValueError(f"a regular polygon needs at least 3 sides, got {self.sides!r}")
        if not self.circumradius > 0.0:
            raise ValueError(f"circumradius must be positive, got {self.circumradius!r}")

    def build(self) -> BaseGeometry:
        angles = 2.0 * math.pi * np.arange(self.sides) / self.sides + math.pi / 2.0
        return Polygon(np.column_stack((np.cos(angles), np.sin(angles))) * self.circumradius)

    @property
    def area(self) -> float:
        return 0.5 * self.sides * self.circumradius**2 * math.sin(2.0 * math.pi / self.sides)

    def describe(self) -> str:
        return f"regular {self.sides}-gon of circumradius {self.circumradius:g}"

    def to_dict(self) -> JSON:
        return {"type": self.kind, "sides": self.sides, "circumradius": self.circumradius}


@dataclass(frozen=True)
class ArbitraryPolygon(ArenaShape):
    """A polygon given by its vertices, for imported or hand-drawn arenas."""

    points: tuple[tuple[float, float], ...]
    kind: ClassVar[str] = "polygon"

    def __post_init__(self) -> None:
        if len(self.points) < 3:
            raise ValueError(f"a polygon needs at least 3 vertices, got {len(self.points)}")

    def build(self) -> BaseGeometry:
        return polygonal(Polygon(self.points), context="polygon")

    def describe(self) -> str:
        return f"polygon with {len(self.points)} vertices"

    def to_dict(self) -> JSON:
        return {"type": self.kind, "points": [list(point) for point in self.points]}


@dataclass(frozen=True)
class Translate(ArenaShape):
    """A node moved by a fixed offset: this is how a primitive is positioned.

    Primitives are defined at the origin, so placing one is a translation rather
    than an extra pair of coordinates on every node. That keeps the tree
    composable — moving a hole, moving a union and moving a polygon all read the
    same — and it means an editor can offer one drag handle per part.
    """

    shape: ArenaShape
    dx: float
    dy: float
    kind: ClassVar[str] = "translate"

    def build(self) -> BaseGeometry:
        return affinity.translate(self.shape.build(), xoff=self.dx, yoff=self.dy)

    @property
    def area(self) -> float | None:
        # A translation moves the region without changing its area.
        return self.shape.area

    def describe(self) -> str:
        return f"{self.shape.describe()} at ({self.dx:g}, {self.dy:g})"

    def to_dict(self) -> JSON:
        return {"type": self.kind, "shape": jsonable(self.shape), "dx": self.dx, "dy": self.dy}


@dataclass(frozen=True)
class Rotate(ArenaShape):
    """A node turned about its own origin by a fixed angle, in degrees.

    The pivot is the origin of the node's own frame — the point a
    :class:`Translate` displaces — never the centre of the compiled geometry, so
    an angle means the same thing wherever the primitive happens to be drawn. A
    part is written ``Translate(Rotate(primitive))``: the primitive is turned
    where it stands and the offset then places the turned thing, so a part's
    angle reads as a turn of that part in place rather than a turn of the whole
    arena. Like every angle in this project it is measured in degrees,
    counter-clockwise.
    """

    shape: ArenaShape
    angle: float
    kind: ClassVar[str] = "rotate"

    def build(self) -> BaseGeometry:
        return affinity.rotate(self.shape.build(), self.angle, origin=(0.0, 0.0), use_radians=False)

    @property
    def area(self) -> float | None:
        # A rotation about the node origin moves the region without changing its area.
        return self.shape.area

    def describe(self) -> str:
        return f"{self.shape.describe()} turned by {self.angle:g} degrees"

    def to_dict(self) -> JSON:
        return {"type": self.kind, "shape": jsonable(self.shape), "angle": self.angle}


@dataclass(frozen=True)
class BooleanOp(ArenaShape):
    """Base class of the two-operand nodes of the arena tree."""

    left: ArenaShape
    right: ArenaShape

    def _combine(self, left: BaseGeometry, right: BaseGeometry) -> BaseGeometry:
        raise NotImplementedError

    def build(self) -> BaseGeometry:
        return polygonal(
            self._combine(self.left.build(), self.right.build()),
            context=f"{self.kind} of {self.left.describe()} and {self.right.describe()}",
        )

    def to_dict(self) -> JSON:
        return {"type": self.kind, "left": jsonable(self.left), "right": jsonable(self.right)}


@dataclass(frozen=True)
class Union(BooleanOp):
    """Everything covered by either operand."""

    kind: ClassVar[str] = "union"

    def _combine(self, left: BaseGeometry, right: BaseGeometry) -> BaseGeometry:
        return left.union(right)

    def describe(self) -> str:
        return f"({self.left.describe()} union {self.right.describe()})"


@dataclass(frozen=True)
class Difference(BooleanOp):
    """The first operand minus the second one, which is how holes are made."""

    kind: ClassVar[str] = "difference"

    def _combine(self, left: BaseGeometry, right: BaseGeometry) -> BaseGeometry:
        return left.difference(right)

    def describe(self) -> str:
        return f"({self.left.describe()} minus {self.right.describe()})"


@dataclass(frozen=True)
class Intersection(BooleanOp):
    """What both operands share."""

    kind: ClassVar[str] = "intersection"

    def _combine(self, left: BaseGeometry, right: BaseGeometry) -> BaseGeometry:
        return left.intersection(right)

    def describe(self) -> str:
        return f"({self.left.describe()} intersected with {self.right.describe()})"


@dataclass
class Arena:
    """A compiled 2D region to pack into.

    The shapely geometry is built once, when the arena is created, and reused by
    every validation, metric and render call. Treat instances as immutable: the
    boolean helpers return new arenas instead of mutating this one.
    """

    shape: ArenaShape
    name: str = ""
    #: The length a published size of this container measures, in arena units: the leg
    #: of a tan, the short side of a domino or an L. A copy scale ``k`` then stands for
    #: the container ``reference_length / k`` around unit copies. ``None`` when the
    #: arena is not one size of a family of similar containers; a regular polygon needs
    #: none, its side is read from its own geometry.
    reference_length: float | None = None
    geometry: BaseGeometry = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.reference_length is not None and not self.reference_length > 0.0:
            raise ValueError(f"reference_length must be positive, got {self.reference_length!r}")
        geometry = polygonal(self.shape.build(), context=f"arena ({self.shape.describe()})")
        if not geometry.is_valid:
            raise ValueError(f"invalid arena geometry: {explain_validity(geometry)}")
        self.geometry = geometry

    # -- construction ---------------------------------------------------------

    @staticmethod
    def rectangle(width: float, height: float, name: str = "") -> Arena:
        """Build a rectangular arena centred on the origin."""
        return Arena(shape=Rect(width=width, height=height), name=name)

    @staticmethod
    def disk(radius: float, name: str = "") -> Arena:
        """Build a disc-shaped arena centred on the origin."""
        return Arena(shape=Disk(radius=radius), name=name)

    @staticmethod
    def ellipse(a: float, b: float, name: str = "") -> Arena:
        """Build an ellipse-shaped arena centred on the origin, with semi-axes ``a`` and ``b``."""
        return Arena(shape=Ellipse(a=a, b=b), name=name)

    @staticmethod
    def regular_polygon(sides: int, circumradius: float, name: str = "") -> Arena:
        """Build a regular polygon arena centred on the origin."""
        return Arena(shape=RegularNGon(sides=sides, circumradius=circumradius), name=name)

    @staticmethod
    def polygon(points: list[tuple[float, float]] | tuple[tuple[float, float], ...], name: str = "") -> Arena:
        """Build an arena from an explicit list of vertices."""
        return Arena(shape=ArbitraryPolygon(points=tuple(tuple(point) for point in points)), name=name)

    def _combine(self, other: Arena, node: type[BooleanOp]) -> Arena:
        return Arena(shape=node(left=self.shape, right=other.shape), name=self.name)

    def union(self, other: Arena) -> Arena:
        """Return a new arena covering this arena and ``other``."""
        return self._combine(other, Union)

    def difference(self, other: Arena) -> Arena:
        """Return a new arena made of this arena minus ``other`` (this is how holes are cut)."""
        return self._combine(other, Difference)

    def intersection(self, other: Arena) -> Arena:
        """Return a new arena made of the region shared with ``other``."""
        return self._combine(other, Intersection)

    # -- queries --------------------------------------------------------------

    @property
    def area(self) -> float:
        """Area of the arena, holes excluded.

        Exact for a parametric primitive -- a rectangle, a disc, an ellipse or a
        regular polygon -- and for any translation or rotation of one, because the
        declared shape has a closed form while the compiled outline is only a chord
        approximation: a disc of radius ``r`` really is ``pi * r**2``, not the area
        of its circumscribed 256-gon. A boolean composition of arcs has no closed
        form, and its area is then the compiled outline's. Use
        :attr:`compiled_area` when the polygon itself is what a caller means: the
        judge reads that polygon, and the two differ by about ``5e-5`` of the area
        on a curved wall.
        """
        declared = self.shape.area
        return float(self.geometry.area) if declared is None else float(declared)

    @property
    def compiled_area(self) -> float:
        """Area of the compiled outline: the polygon every predicate and boolean reads."""
        return float(self.geometry.area)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """Bounding box as ``(min_x, min_y, max_x, max_y)``."""
        min_x, min_y, max_x, max_y = self.geometry.bounds
        return (float(min_x), float(min_y), float(max_x), float(max_y))

    @property
    def size(self) -> tuple[float, float]:
        """Bounding box size as ``(width, height)``."""
        min_x, min_y, max_x, max_y = self.bounds
        return (max_x - min_x, max_y - min_y)

    @property
    def center(self) -> tuple[float, float]:
        """Centre of the bounding box."""
        min_x, min_y, max_x, max_y = self.bounds
        return ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)

    def contains_point(self, x: float, y: float) -> bool:
        """Whether the point lies inside the arena (boundary included)."""
        return bool(self.geometry.covers(Point(x, y)))

    def signed_distance(self, x: float, y: float) -> float:
        """Signed distance from a point to the arena boundary, positive inside.

        Exact for every arena: it is the distance to the polygon boundary,
        which includes hole rings.
        """
        point = Point(x, y)
        distance = float(shapely.distance(point, self.geometry.boundary))
        return distance if self.geometry.covers(point) else -distance

    # -- serialisation --------------------------------------------------------

    def to_dict(self) -> JSON:
        """Return the JSON representation: the arena tree, not the compiled geometry.

        ``reference_length`` is written only when set, so an arena without one keeps
        the representation it always had.
        """
        data: JSON = {"name": self.name, "shape": jsonable(self.shape)}
        if self.reference_length is not None:
            data["reference_length"] = self.reference_length
        return data

    @staticmethod
    def from_dict(data: JSON) -> Arena:
        """Rebuild an arena from its JSON representation."""
        length = data.get("reference_length")
        return Arena(
            shape=ArenaShape.from_dict(require(data, "shape", "arena")),
            name=str(data.get("name", "")),
            reference_length=None if length is None else as_float(length, "arena.reference_length"),
        )

    def describe(self) -> str:
        """One-line description used by logs, prompts and the CLI."""
        return f"{self.shape.describe()} (area {self.area:.4g})"


#: Operations a left-nested arena can apply to a primitive, after the base.
PART_OPERATIONS: tuple[str, ...] = (Union.kind, Difference.kind, Intersection.kind)

_OPERATION_NODES: dict[str, type[BooleanOp]] = {
    Union.kind: Union,
    Difference.kind: Difference,
    Intersection.kind: Intersection,
}

#: The primitives an editable part may hold.
_PRIMITIVES = (Rect, Disk, Ellipse, RegularNGon, ArbitraryPolygon)


def _placement(node: ArenaShape) -> tuple[ArenaShape, tuple[float, float], float]:
    """Split a part's node into its primitive, its offset and its angle, in that order.

    A part is written ``Translate(Rotate(primitive))`` — the turn comes first, the
    offset places what was turned — so peeling the two nodes in that order is what
    tells an editor what a part holds. A node nested the other way round leaves a
    non-primitive in the first slot, which :class:`ArenaPart` refuses, rather than
    reading a placement no gesture could produce.
    """
    offset = (node.dx, node.dy) if isinstance(node, Translate) else (0.0, 0.0)
    if isinstance(node, Translate):
        node = node.shape
    angle = node.angle if isinstance(node, Rotate) else 0.0
    if isinstance(node, Rotate):
        node = node.shape
    return node, offset, angle


@dataclass(frozen=True)
class ArenaPart:
    """One primitive of an arena, with the operation that combines it.

    The first part is the base (``op == "base"``); every later part is applied to
    the accumulator so far. That is exactly how a level editor thinks — lay a
    rectangle, cut a disc out of it, add another rectangle beside it — and it is
    what an editor can send back and forth without ever exposing the tree.

    A part may also carry an angle, in degrees, which the part-building functions
    lift into a :class:`Rotate` node exactly as they lift a position into a
    :class:`Translate`: the primitive is turned about its own origin first, and
    then placed at its offset. The offset is therefore always read in the arena's
    coordinates, whatever the angle, and turning one part never turns the others.
    """

    op: str
    shape: ArenaShape

    def __post_init__(self) -> None:
        if self.op != "base" and self.op not in PART_OPERATIONS:
            raise ValueError(f"unknown arena part operation {self.op!r}")
        if not isinstance(self.primitive, _PRIMITIVES):
            raise ValueError(f"an arena part must hold a primitive, found {self.shape.kind!r}")

    @property
    def primitive(self) -> ArenaShape:
        """The primitive itself, without its placement."""
        return _placement(self.shape)[0]

    @property
    def offset(self) -> tuple[float, float]:
        """Where the primitive sits, in the arena's coordinates."""
        return _placement(self.shape)[1]

    @property
    def angle(self) -> float:
        """How far the primitive is turned about its own origin, in degrees."""
        return _placement(self.shape)[2]

    def to_dict(self) -> JSON:
        """Return the JSON representation."""
        return {"op": self.op, "shape": jsonable(self.shape)}

    @staticmethod
    def from_dict(data: JSON) -> ArenaPart:
        """Decode a part from its JSON representation."""
        return ArenaPart(
            op=str(require(data, "op", "arena_part")),
            shape=ArenaShape.from_dict(require(data, "shape", "arena_part")),
        )


def part(op: str, shape: ArenaShape, x: float = 0.0, y: float = 0.0, angle: float = 0.0) -> ArenaPart:
    """Return a part holding a primitive, turned and placed when it has to be.

    ``angle`` is in degrees, and a part with neither a turn nor a position holds
    its primitive bare, so a document written without either is unchanged.
    """
    turned = shape if angle == 0.0 else Rotate(shape=shape, angle=angle)
    placed = turned if x == 0.0 and y == 0.0 else Translate(shape=turned, dx=x, dy=y)
    return ArenaPart(op=op, shape=placed)


def arena_parts(shape: ArenaShape) -> tuple[ArenaPart, ...] | None:
    """Read an arena as an editable list of parts, or return ``None``.

    Only a left-nested tree can be read that way: a base primitive, then one
    operation per part. An arena built any other way is still a perfectly valid
    arena, it simply cannot be edited by a stack of primitives, and an editor
    must say so rather than guess.
    """
    parts: list[ArenaPart] = []
    node: ArenaShape = shape
    while isinstance(node, BooleanOp):
        try:
            parts.append(ArenaPart(node.kind, node.right))
        except ValueError:
            return None
        node = node.left
    try:
        parts.append(ArenaPart("base", node))
    except ValueError:
        return None
    parts.reverse()
    return tuple(parts)


def arena_from_parts(parts: Sequence[ArenaPart]) -> ArenaShape:
    """Rebuild a left-nested arena from its parts, the exact inverse of :func:`arena_parts`."""
    if not parts:
        raise ValueError("an arena needs at least one part")
    if parts[0].op != "base":
        raise ValueError(f"the first arena part must be the base, got {parts[0].op!r}")
    node = parts[0].shape
    for item in parts[1:]:
        node = _OPERATION_NODES[item.op](left=node, right=item.shape)
    return node


_ARENA_BUILDERS = {
    Rect.kind: lambda payload: Rect(
        width=as_float(require(payload, "width", "arena.rect"), "arena.rect.width"),
        height=as_float(require(payload, "height", "arena.rect"), "arena.rect.height"),
    ),
    Disk.kind: lambda payload: Disk(radius=as_float(require(payload, "radius", "arena.disk"), "arena.disk.radius")),
    Ellipse.kind: lambda payload: Ellipse(
        a=as_float(require(payload, "a", "arena.ellipse"), "arena.ellipse.a"),
        b=as_float(require(payload, "b", "arena.ellipse"), "arena.ellipse.b"),
    ),
    RegularNGon.kind: lambda payload: RegularNGon(
        sides=as_int(require(payload, "sides", "arena.regular_ngon"), "arena.regular_ngon.sides"),
        circumradius=as_float(
            require(payload, "circumradius", "arena.regular_ngon"), "arena.regular_ngon.circumradius"
        ),
    ),
    ArbitraryPolygon.kind: lambda payload: ArbitraryPolygon(
        points=tuple(
            (as_float(point[0], "arena.polygon.point"), as_float(point[1], "arena.polygon.point"))
            for point in require(payload, "points", "arena.polygon")
        )
    ),
    Translate.kind: lambda payload: Translate(
        shape=ArenaShape.from_dict(require(payload, "shape", "arena.translate")),
        dx=as_float(require(payload, "dx", "arena.translate"), "arena.translate.dx"),
        dy=as_float(require(payload, "dy", "arena.translate"), "arena.translate.dy"),
    ),
    Rotate.kind: lambda payload: Rotate(
        shape=ArenaShape.from_dict(require(payload, "shape", "arena.rotate")),
        angle=as_float(require(payload, "angle", "arena.rotate"), "arena.rotate.angle"),
    ),
    Union.kind: lambda payload: Union(
        left=ArenaShape.from_dict(require(payload, "left", "arena.union")),
        right=ArenaShape.from_dict(require(payload, "right", "arena.union")),
    ),
    Difference.kind: lambda payload: Difference(
        left=ArenaShape.from_dict(require(payload, "left", "arena.difference")),
        right=ArenaShape.from_dict(require(payload, "right", "arena.difference")),
    ),
    Intersection.kind: lambda payload: Intersection(
        left=ArenaShape.from_dict(require(payload, "left", "arena.intersection")),
        right=ArenaShape.from_dict(require(payload, "right", "arena.intersection")),
    ),
}

__all__ = [
    "ARC_SEGMENTS",
    "ArbitraryPolygon",
    "Arena",
    "ArenaShape",
    "BooleanOp",
    "Difference",
    "Disk",
    "Ellipse",
    "Intersection",
    "Rect",
    "PART_OPERATIONS",
    "RegularNGon",
    "Rotate",
    "Translate",
    "Union",
    "arena_from_parts",
    "arena_parts",
    "part",
    "polygonal",
]
