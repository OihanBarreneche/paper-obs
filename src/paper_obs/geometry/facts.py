"""Everything the engine derives from one ``(problem, candidate)`` pair.

Building a :class:`Facts` runs the deterministic geometry exactly once: it
resolves every placement into concrete numbers, measures how far each shape
leaves the arena, and finds which pairs overlap or come close. Constraints,
metrics and analysis are then *readers* of that object, so a single validation
never computes the same distance twice, and a new constraint costs nothing when
it reuses an existing fact.

This module is also where the exact predicates of
:mod:`paper_obs.geometry.predicates` are dispatched per shape family. The
dispatch is deliberately explicit rather than polymorphic: the engine has to
know whether it is looking at a disc or at a convex polygon to stay exact, and
pretending otherwise would hide the one place where the MVP is approximate.

Two of those computations are batched instead of looped, because a per-shape
version was measured to dominate everything else: containment goes to shapely
once for the whole candidate, and a candidate made only of discs is resolved in
one numpy pass, since for a disc the bounding-circle test is the exact test.

A candidate of convex polygons keeps the exact separating-axis predicate. A
candidate that contains a concave polygon falls back to shapely for the pairs
involving it: the verdict stays exact, the reported magnitude becomes the square
root of the shared area, and the cost of those pairs is a polygon intersection
rather than a projection.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Iterator

import numpy as np
import shapely
from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points, polylabel

from paper_obs.domain.arena import (
    Arena,
    BooleanOp,
    Disk,
    Ellipse,
    Rect,
    RegularNGon,
    Rotate,
    Translate,
)
from paper_obs.domain.candidate import Candidate
from paper_obs.domain.placement import Placement
from paper_obs.domain.objectives import CONTAINERS
from paper_obs.domain.problem import Problem
from paper_obs.domain.shapes import CIRCLE_SEGMENTS
from paper_obs.domain.tessellation import chord_area_relative_error, chord_radius_relative_error

from . import exact_discs, predicates

#: Tolerance for a validity decision, in length units. Coordinates are assumed
#: to be of order 1 to 100, so an absolute epsilon is enough and a shape that
#: touches its neighbour to within a nanometre still counts as touching.
#: This is the tolerance of an **exact** reading: the disc predicates are closed
#: form and the polygon ones are exact on their vertices. Containment against a
#: curved wall that is not a plain disc is read on a chord polygon instead, and
#: there the tolerance is raised to the chord bound by :func:`_containment`;
#: see :mod:`paper_obs.domain.tessellation`.
LENGTH_TOLERANCE = 1e-9

#: Tolerance for a validity decision, in area units. Exact readings only, with
#: the same curved-wall exception as :data:`LENGTH_TOLERANCE`.
AREA_TOLERANCE = 1e-9

#: Tolerance used when a *descriptive* metric asks whether two outlines touch.
CONTACT_TOLERANCE = 1e-6

#: Absolute tolerance of the pole-of-inaccessibility search, in world length units.
#: A **descriptive** tolerance -- nothing is decided with it -- bounding how far the
#: reported centre may sit from the true centre of the largest contained disc.
POLYLABEL_TOLERANCE = 1e-6

#: Cells the axis-aligned square scan lays across the union's longer side. The scan
#: is deterministic and its absolute resolution is ``max(width, height) /
#: COVER_SCAN_CELLS``; that resolution is the one approximation the derived square
#: carries, and it is stated here rather than hidden in the search.
COVER_SCAN_CELLS = 192

#: Bisections that close on the largest square at one centre. Each one halves the
#: remaining interval, so the answer is exact for that centre at double precision.
COVER_FIT_ATTEMPTS = 48

#: Refinement rounds of the square centre's hill climb, each halving the step.
COVER_REFINEMENT_ROUNDS = 8

#: Below this, one square is not better than another: it stops the hill climb from
#: walking on numerical dust. A descriptive length tolerance.
COVER_SIDE_TOLERANCE = 1e-9


@dataclass(frozen=True, eq=False)
class ShapeInstance:
    """One placed shape resolved into numbers the predicates can use.

    ``vertices`` and ``geometry`` are exact for a convex polygon and ``None`` for
    a circle, whose exact predicates use the centre and the radius instead.
    Instances compare by identity: they hold numpy arrays.
    """

    shape_id: str
    index: int
    center: tuple[float, float]
    rotation: float
    scale: float
    is_circle: bool
    is_convex: bool
    inradius: float
    circumradius: float
    area: float
    vertices: np.ndarray | None
    geometry: Polygon | None

    def center_point(self) -> Point:
        """Return the centre as a shapely point."""
        return Point(self.center)


@dataclass(frozen=True)
class Containment:
    """How well one shape sits inside the arena."""

    shape_id: str
    index: int
    inside: bool
    overflow_area: float
    margin: float | None
    message: str
    #: For a shape that leaves the arena, the translation that brings its outline back to the
    #: wall it crosses: exact when one straight wall or a disc wall is crossed, a first step
    #: otherwise. ``None`` for a shape that is inside.
    inward: tuple[float, float] | None = None


@dataclass(frozen=True)
class Overlap:
    """Two shapes sharing area, with the depth of the penetration and its axis.

    ``direction`` is the unit vector along which the *second* shape has to move
    to leave the first: ``depth * direction`` is the shortest displacement that
    separates the pair. It is exact for two discs and for two convex polygons.
    When one outline is concave there is no single separating axis, and the
    direction is then only the line between the two centres — see
    :func:`_penetration` for what ``depth`` itself means in that case.
    """

    first: str
    second: str
    index_first: int
    index_second: int
    depth: float
    direction: tuple[float, float]


@dataclass(frozen=True)
class Clearance:
    """The distance between two shapes, 0.0 when they touch or overlap."""

    first: str
    second: str
    index_first: int
    index_second: int
    distance: float


@dataclass
class Facts:
    """The geometric truth about one candidate, computed once."""

    problem: Problem
    candidate: Candidate
    instances: tuple[ShapeInstance, ...]
    overlaps: tuple[Overlap, ...]
    containment: tuple[Containment, ...]
    region: Arena
    """The region the shapes are judged against.

    It is the problem's arena for every objective that packs into a declared
    region, and the container the engine measured around the arrangement for the
    objective that minimises one — so a constraint, a metric or a drawing asks
    "where" and gets the only region that means anything for this family.
    """
    container: Mapping[str, float] = field(default_factory=dict)
    """What the engine measured about the container, empty when nothing derives one."""
    by_id: dict[str, ShapeInstance] = field(init=False, repr=False)
    _clearances: dict[float, tuple[Clearance, ...]] = field(init=False, repr=False, default_factory=dict)
    _footprints: dict[str, BaseGeometry] = field(init=False, repr=False, default_factory=dict)
    _union: BaseGeometry | None = field(init=False, repr=False, default=None)
    _uncovered: float | None = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        self.by_id = {instance.shape_id: instance for instance in self.instances}

    @property
    def arena(self) -> Arena:
        """The region the candidate is packed into; see :attr:`region`."""
        return self.region

    def instance(self, shape_id: str) -> ShapeInstance:
        """Return the instance of one placed shape."""
        return self.by_id[shape_id]

    def clearances(self, slack: float = 0.0) -> tuple[Clearance, ...]:
        """Return the pairwise gaps not exceeding ``slack``, computed once per slack.

        ``slack`` is required rather than guessed: asking for "close pairs"
        always means a threshold, and hiding it in a constant would silently
        change what a constraint reports.
        """
        key = float(slack)
        cached = self._clearances.get(key)
        if cached is None:
            cached = _clearances(self.instances, key)
            self._clearances[key] = cached
        return cached

    def footprint(self, instance: ShapeInstance) -> BaseGeometry:
        """Return the outline as a shapely polygon, tessellating a circle on demand.

        Used by the diagnostics and by the empty-region analysis, never by a
        validity decision: a circle is approximated here, and the approximation
        is circumscribed so that a computed overflow area is never an
        underestimate. A circle *inside* the arena subtracts nothing, which is
        why the callers can afford to skip the tessellation for valid shapes.
        """
        cached = self._footprints.get(instance.shape_id)
        if cached is None:
            cached = instance.geometry or _tessellated_circle(instance)
            self._footprints[instance.shape_id] = cached
        return cached

    def iter_footprints(self) -> Iterator[BaseGeometry]:
        """Yield the outline of every shape, tessellating circles on demand."""
        for instance in self.instances:
            yield self.footprint(instance)

    def shape_union(self) -> BaseGeometry:
        """Return the union of every shape's outline, computed once and cached.

        This is the geometry a covering constraint reads: the footprints are
        unioned a single time for the whole candidate, never recomputed per pair
        and never per shape. A candidate with no shape unions to the empty
        polygon, so the uncovered area below is then the whole arena.
        """
        if self._union is None:
            footprints = list(self.iter_footprints())
            self._union = shapely.union_all(footprints) if footprints else Polygon()
        return self._union

    def uncovered_area(self) -> float:
        """Return the area of the arena no shape covers, computed once and cached.

        Covering is decided on this number, not on a boolean: it is the arena
        minus the union of the footprints, in the arena's square units, and it is
        what :class:`paper_obs.domain.constraints.ArenaCovered` reports as the
        magnitude of its violation. Both the union and the difference are
        computed here once, so several readers of the same fact pay for it once.

        Two readings, one per regime. When the arena and every footprint are
        discs, the covered area is closed form
        (:func:`paper_obs.geometry.exact_discs.clipped_union_area`) and the result
        carries no chord error at all. Otherwise the difference is read on the
        *compiled* arena -- the polygon the predicates and booleans use -- and then
        capped at :attr:`Arena.area`, the exact area of the declared shape: a
        curved wall is compiled as a circumscribed polygon, a hair larger than the
        ideal it stands for, and without the cap an empty candidate on a disc
        would report more uncovered area than the arena has. The cap changes
        nothing on a straight wall, where the two areas are the same number.
        """
        if self._uncovered is None:
            disc = self._exact_disc_region()
            if disc is not None:
                # Every outline is a disc and the region is one too: the covered
                # area is closed form, so the uncovered area is exact and no
                # chord enters the covering verdict.
                covered = exact_discs.clipped_union_area(
                    disc,
                    (
                        (instance.center[0], instance.center[1], instance.inradius)
                        for instance in self.instances
                    ),
                )
                self._uncovered = max(0.0, min(self.arena.area - covered, self.arena.area))
            else:
                difference = float(self.arena.geometry.difference(self.shape_union()).area)
                self._uncovered = min(difference, self.arena.area)
        return self._uncovered

    def _exact_disc_region(self) -> tuple[float, float, float] | None:
        """The declared disc this covering is answered in closed form for, or None.

        Two conditions: every footprint is a disc, and there are few enough of
        them that the arc sweep stays cheap (see
        :data:`paper_obs.geometry.exact_discs.ARC_SWEEP_DISC_LIMIT`). Above that
        count the polygon reading is kept and :meth:`coverage_resolution` says so.
        """
        if len(self.instances) > exact_discs.ARC_SWEEP_DISC_LIMIT:
            return None
        disc = _declared_disc(self.arena.shape)
        if disc is None or not all(instance.is_circle for instance in self.instances):
            return None
        return disc

    def coverage_resolution(self) -> float:
        """Relative area uncertainty of :meth:`uncovered_area`: the reading's fidelity class.

        A covering is judged on an area, so the verdict is no more precise than
        the representation the area is read from. When the region and every
        footprint are discs the area is closed form and this is zero. Otherwise a
        curved boundary is compiled to a circumscribed polygon, and the uncovered
        area carries the polygon's own area error -- see
        :func:`paper_obs.domain.tessellation.chord_area_relative_error`. A
        covering of straight walls alone is exact and reports zero here.
        """
        if self._exact_disc_region() is not None:
            return 0.0
        curved = any(instance.is_circle for instance in self.instances) or _has_curved_boundary(
            self.arena.shape
        )
        return chord_area_relative_error() if curved else 0.0


def build_facts(problem: Problem, candidate: Candidate) -> Facts:
    """Compute the geometric facts of a candidate: the engine's single entry point.

    A candidate that does not belong to the problem is refused here rather than
    silently scored: a search keeps candidates from several problems alive at
    once, and a mismatched pair is the kind of mistake that produces a plausible
    number and no warning at all.
    """
    if candidate.problem_id != problem.problem_id:
        raise ValueError(
            f"candidate {candidate.candidate_id} belongs to problem {candidate.problem_id!r}, "
            f"not to {problem.problem_id!r}"
        )
    instances = tuple(
        _instance(problem, placement, index, candidate.scale)
        for index, placement in enumerate(candidate.placements)
    )
    region = problem.arena
    measurements: dict[str, float] = {}
    kind = problem.objective.enclosing_container
    target = problem.objective.covered_target
    if kind is not None:
        if not instances:
            raise ValueError(
                f"{problem.objective.kind} has nothing to enclose in candidate "
                f"{candidate.candidate_id!r}: declare at least one shape"
            )
        region, measurements = enclosing_container(instances, kind)
    elif target is not None:
        # The twin reading: the target is not declared but measured *inside* the
        # union of the copies, and the same measured region is what the canvas
        # draws and every metric reads.
        region, measurements = covered_region(problem, instances, target)
    if region is None:
        raise ValueError(
            f"{problem.objective.kind} packs into an arena, which this problem does not declare"
        )
    return Facts(
        problem=problem,
        candidate=candidate,
        instances=instances,
        overlaps=_overlaps(instances),
        containment=_containment(instances, region),
        region=region,
        container=measurements,
    )


def enclosing_container(
    instances: tuple[ShapeInstance, ...], container: str
) -> tuple[Arena, dict[str, float]]:
    """Return the smallest container of that kind holding every shape, and its size.

    The square is the axis-aligned one: the box of the arrangement, made square on
    its longest side and centred on that box. That is the smallest square a reader
    of the arrangement can point at, and for the classic instances it *is* the
    published one — the solution for 17 unit squares occupies exactly a 4.6755
    square this way. A minimal square is not provably axis-aligned for every
    arrangement, so a tilted one could in principle be smaller; this is the
    definition the lab commits to, and the difference is the free-orientation
    problem, which is a search of its own.

    The bounds are read from each outline's own extent — a disc from its centre
    and radius, a polygon from its exact corners — so the measurement is exact and
    costs one pass over the shapes.
    """
    if container == "circle":
        # A disc is held from its centre and its own radius, a polygon from its exact
        # corners: the smallest circle through every corner and every centre, grown by
        # the largest radius, holds the arrangement. Exact while the shapes share a
        # size, which is what a problem of one family places; a candidate that mixes
        # local scales is the weighted problem, which this is not.
        points: list[tuple[float, float]] = []
        radius = 0.0
        for instance in instances:
            if instance.is_circle:
                points.append((float(instance.center[0]), float(instance.center[1])))
                radius = max(radius, float(instance.inradius))
            else:
                points.extend(
                    (float(x), float(y)) for x, y in instance.geometry.exterior.coords[:-1]
                )
        centre, reach = minimal_enclosing_circle(tuple(points))
        total = reach + radius
        disk = Arena(shape=Translate(shape=Disk(radius=total), dx=centre[0], dy=centre[1]))
        return disk, {"container_radius": float(total)}
    left, bottom, right, top = _arrangement_bounds(instances)
    width, height = right - left, top - bottom
    if container == "square":
        side = max(width, height)
        square = Arena(
            shape=Translate(
                shape=Rect(width=side, height=side),
                dx=(left + right) / 2.0,
                dy=(bottom + top) / 2.0,
            )
        )
        return square, {"container_side": float(side)}
    raise ValueError(
        f"unknown container {container!r}; known containers: {', '.join(CONTAINERS)}"
    )


def polygonal(geometry) -> Polygon | MultiPolygon | None:
    """Reduce a geometry to its polygonal parts, or return None when it has none."""
    if geometry.is_empty:
        return None
    if isinstance(geometry, (Polygon, MultiPolygon)):
        return geometry
    parts = [part for part in shapely.get_parts(geometry) if part.geom_type == "Polygon"]
    return shapely.union_all(parts) if parts else None


def covered_region(
    problem: Problem, instances: tuple[ShapeInstance, ...], target: str
) -> tuple[Arena, dict[str, float]]:
    """Return the largest target of ``target``'s family inside the copies' union.

    This is the twin of :func:`enclosing_container`: instead of the smallest
    container *around* the arrangement, it measures the largest target *inside* the
    union of the footprints, with the target's orientation fixed. The returned
    arena is that measured target -- centred where it was found -- so the canvas
    draws it and every metric reads it, and the second value carries its size under
    ``covered_size``: the radius of a disc, the side of a square.

    ``circle`` is the largest disc the union contains, read from the pole of
    inaccessibility to :data:`POLYLABEL_TOLERANCE` (a descriptive tolerance).
    ``square`` is the largest axis-aligned square, found by the bounded scan of
    :func:`largest_axis_aligned_square`; its absolute resolution is one cell of
    ``max(width, height) / COVER_SCAN_CELLS``. ``triangle`` is the largest
    equilateral triangle of fixed orientation -- one edge horizontal, apex up --
    found by the bounded scan of :func:`largest_equilateral_triangle`, on the same
    resolution. An empty or zero-area union measures zero and falls back to the
    problem's own draft frame, so an empty canvas still draws.
    """
    if target not in ("circle", "square", "triangle"):
        raise ValueError(
            f"unknown cover target {target!r}; known targets: circle, square, triangle"
        )
    union = polygonal(_shape_union(instances))
    if union is None or union.area <= 0.0:
        # Nothing to measure: a zero score and the problem's own draft frame keep
        # an empty canvas drawable and the ranking defined.
        return problem.draft_region, {"covered_size": 0.0}
    if target == "circle":
        pole = polylabel(union, tolerance=POLYLABEL_TOLERANCE)
        radius = float(union.boundary.distance(pole))
        if radius <= 0.0:
            return problem.draft_region, {"covered_size": 0.0}
        disk = Arena(
            shape=Translate(shape=Disk(radius=radius), dx=float(pole.x), dy=float(pole.y))
        )
        return disk, {"covered_size": radius}
    if target == "triangle":
        side, (centre_x, centre_y) = largest_equilateral_triangle(union)
        if side <= 0.0:
            return problem.draft_region, {"covered_size": 0.0}
        # The orientation the scan measured: one edge horizontal, apex up. A regular
        # 3-gon puts its vertices at 90, 210 and 330 degrees, which is that triangle,
        # so the region the canvas draws is the one the score was read from.
        triangle = Arena(
            shape=Translate(
                shape=RegularNGon(sides=3, circumradius=side / math.sqrt(3.0)),
                dx=centre_x,
                dy=centre_y,
            )
        )
        return triangle, {"covered_size": side}
    side, (centre_x, centre_y) = largest_axis_aligned_square(union)
    if side <= 0.0:
        return problem.draft_region, {"covered_size": 0.0}
    square = Arena(
        shape=Translate(shape=Rect(width=side, height=side), dx=centre_x, dy=centre_y)
    )
    return square, {"covered_size": side}


def _shape_union(instances: tuple[ShapeInstance, ...]) -> BaseGeometry:
    """Return the union of the footprints, tessellating a circle on demand."""
    footprints = [
        instance.geometry if instance.geometry is not None else _tessellated_circle(instance)
        for instance in instances
    ]
    return shapely.union_all(footprints) if footprints else Polygon()


def largest_axis_aligned_square(
    region: Polygon | MultiPolygon,
) -> tuple[float, tuple[float, float]]:
    """Return the side and centre of the largest axis-aligned square in ``region``.

    A bounded, deterministic scan, because the largest square contained in a union
    of polygons has no closed form the lab can point at. A grid of samples marks the
    interior, the largest all-interior block of cells seeds a centre, and that
    centre is hill-climbed while the side is closed by bisection on the region's
    own ``covers`` predicate. Every number returned is a square the region really
    contains -- the block only chooses where to look -- and the answer is within one
    scan cell of the largest, the cell being ``max(width, height) /
    COVER_SCAN_CELLS``. Nothing here decides validity: it measures a target the
    derived covering objective then scores.
    """
    bounds = region.bounds
    width = float(bounds[2] - bounds[0])
    height = float(bounds[3] - bounds[1])
    span = max(width, height)
    if span <= 0.0:
        return 0.0, (float(bounds[0]), float(bounds[1]))
    step = span / COVER_SCAN_CELLS
    columns = max(1, int(width / step))
    rows = max(1, int(height / step))
    xs = bounds[0] + (np.arange(columns) + 0.5) * step
    ys = bounds[1] + (np.arange(rows) + 0.5) * step
    grid_x, grid_y = np.meshgrid(xs, ys)
    inside = shapely.contains_xy(region, grid_x.ravel(), grid_y.ravel()).reshape(rows, columns)
    block = _largest_square_block(inside)
    if block is None:
        return 0.0, (float(bounds[0]), float(bounds[1]))
    row, column, cells = block
    centre = (
        float(bounds[0] + (column + cells / 2.0) * step),
        float(bounds[1] + (row + cells / 2.0) * step),
    )
    side = _largest_square_at(region, centre, span)
    # The seed is exact to one cell, so a shrinking 3x3 walk closes the last
    # fraction of it; only a strict improvement is kept, and a round that finds
    # none ends the walk.
    walk = step
    for _ in range(COVER_REFINEMENT_ROUNDS):
        walk *= 0.5
        improved = False
        for dx in (-1.0, 0.0, 1.0):
            for dy in (-1.0, 0.0, 1.0):
                if dx == 0.0 and dy == 0.0:
                    continue
                trial = (centre[0] + dx * walk, centre[1] + dy * walk)
                trial_side = _largest_square_at(region, trial, span)
                if trial_side > side + COVER_SIDE_TOLERANCE:
                    side, centre, improved = trial_side, trial, True
        if not improved:
            break
    return side, centre


def _largest_square_block(inside: np.ndarray) -> tuple[int, int, int] | None:
    """Return (top row, left column, cells) of the biggest all-inside block.

    The classic dynamic programme for the largest square of a binary matrix. The
    cells are sample points inside the region, so the block is a seed and not the
    answer: the answer is measured exactly at the centre it points to.
    """
    rows, columns = inside.shape
    best = 0
    best_at: tuple[int, int, int] | None = None
    previous = np.zeros(columns, dtype=np.int64)
    for row in range(rows):
        current = np.zeros(columns, dtype=np.int64)
        line = inside[row]
        for column in range(columns):
            if not line[column]:
                continue
            left = current[column - 1] if column else 0
            above = previous[column]
            diagonal = previous[column - 1] if column else 0
            value = 1 + min(left, above, diagonal)
            current[column] = value
            if value > best:
                best = value
                best_at = (row - value + 1, column - value + 1, value)
        previous = current
    return best_at


def _largest_square_at(
    region: Polygon | MultiPolygon, centre: tuple[float, float], upper: float
) -> float:
    """Return the largest axis-aligned square centred at ``centre`` inside ``region``.

    Zero when the centre is outside; otherwise one bisection on the side, each step
    asking the region's own ``covers`` predicate, so the returned side is a square
    the region contains and never an estimate of one.
    """
    if upper <= 0.0 or not region.covers(Point(centre)):
        return 0.0
    if region.covers(_square_box(centre, upper)):
        return upper
    low, high = 0.0, upper
    for _ in range(COVER_FIT_ATTEMPTS):
        middle = (low + high) / 2.0
        if region.covers(_square_box(centre, middle)):
            low = middle
        else:
            high = middle
    return low


def _square_box(centre: tuple[float, float], side: float) -> Polygon:
    """Return the axis-aligned square of ``side`` centred at ``centre``."""
    half = side / 2.0
    return shapely.box(
        centre[0] - half, centre[1] - half, centre[0] + half, centre[1] + half
    )


def largest_equilateral_triangle(
    region: Polygon | MultiPolygon,
) -> tuple[float, tuple[float, float]]:
    """Return the side and centroid of the largest equilateral triangle in ``region``.

    The orientation is fixed and stated: **one edge horizontal, apex up**. The side
    is the length of an edge and the centre is the centroid, which is the anchor a
    :class:`paper_obs.domain.arena.RegularNGon` of three sides is placed at; the
    drawn region and the score therefore agree by construction.

    A bounded, deterministic scan, because the largest fixed-orientation equilateral
    triangle inside a union of polygons has no closed form the lab can point at. The
    grid seed, the shrinking walk and the bisection are the square target's:
    ``COVER_SCAN_CELLS`` samples over the longer side mark the interior, the largest
    all-interior block of cells seeds a centroid, and that centroid is walked over a
    3x3 neighbourhood whose step is halved ``COVER_REFINEMENT_ROUNDS`` times. At
    every centre the side is closed by ``COVER_FIT_ATTEMPTS`` bisections on the
    region's own ``covers`` predicate, tested on the **whole triangle polygon** --
    never on its three vertices alone, because the union is generally non-convex and
    an edge can leave it. Every number returned is a triangle the region really
    contains, so the answer is a lower bound and never an over-estimate.

    Unlike the square, the seed block is not exact to one cell: a triangle's
    centroid is not the centre of the square that fits around it, so the walk runs
    all of its rounds -- the coarse ones that find nothing included -- instead of
    stopping at the first quiet neighbourhood. The absolute resolution of the grid
    is ``max(width, height) / COVER_SCAN_CELLS``; the answer is within that
    resolution of the best centre the walk visited.
    """
    bounds = region.bounds
    width = float(bounds[2] - bounds[0])
    height = float(bounds[3] - bounds[1])
    span = max(width, height)
    if span <= 0.0:
        return 0.0, (float(bounds[0]), float(bounds[1]))
    step = span / COVER_SCAN_CELLS
    columns = max(1, int(width / step))
    rows = max(1, int(height / step))
    xs = bounds[0] + (np.arange(columns) + 0.5) * step
    ys = bounds[1] + (np.arange(rows) + 0.5) * step
    grid_x, grid_y = np.meshgrid(xs, ys)
    inside = shapely.contains_xy(region, grid_x.ravel(), grid_y.ravel()).reshape(rows, columns)
    block = _largest_square_block(inside)
    if block is None:
        # No sample point is interior: the region is thinner than one scan cell, so
        # no triangle is reported rather than one the grid never tested.
        return 0.0, (float(bounds[0]), float(bounds[1]))
    row, column, cells = block
    centre = (
        float(bounds[0] + (column + cells / 2.0) * step),
        float(bounds[1] + (row + cells / 2.0) * step),
    )
    side = _largest_triangle_at(region, centre, span)
    walk = span
    for _ in range(COVER_REFINEMENT_ROUNDS):
        walk *= 0.5
        for dx in (-1.0, 0.0, 1.0):
            for dy in (-1.0, 0.0, 1.0):
                if dx == 0.0 and dy == 0.0:
                    continue
                trial = (centre[0] + dx * walk, centre[1] + dy * walk)
                trial_side = _largest_triangle_at(region, trial, span)
                if trial_side > side + COVER_SIDE_TOLERANCE:
                    side, centre = trial_side, trial
    return side, centre


def _largest_triangle_at(
    region: Polygon | MultiPolygon, centre: tuple[float, float], upper: float
) -> float:
    """Return the largest apex-up equilateral triangle centred at ``centre``.

    Zero when the centroid is outside; otherwise one bisection on the side, each
    step asking the region's own ``covers`` predicate for the whole triangle, so the
    returned side is a triangle the region contains and never an estimate of one.
    """
    if upper <= 0.0 or not region.covers(Point(centre)):
        return 0.0
    if region.covers(_triangle_polygon(centre, upper)):
        return upper
    low, high = 0.0, upper
    for _ in range(COVER_FIT_ATTEMPTS):
        middle = (low + high) / 2.0
        if region.covers(_triangle_polygon(centre, middle)):
            low = middle
        else:
            high = middle
    return low


def _triangle_polygon(centre: tuple[float, float], side: float) -> Polygon:
    """Return the apex-up equilateral triangle of ``side`` with that centroid.

    One edge is horizontal and the apex points to ``+y``. The centroid is the
    circumcentre, so the vertices sit at 90, 210 and 330 degrees around it, at the
    circumradius ``side / sqrt(3)`` -- the same three vertices a regular 3-gon of
    that circumradius draws.
    """
    reach = side / math.sqrt(3.0)
    return Polygon(
        (
            (centre[0], centre[1] + reach),
            (centre[0] - side / 2.0, centre[1] - reach / 2.0),
            (centre[0] + side / 2.0, centre[1] - reach / 2.0),
        )
    )


def instance_bounds(instance: ShapeInstance) -> tuple[float, float, float, float]:
    """Return the box of one shape's outline.

    Exact, and read from the outline itself: a disc is its centre and its radius,
    a polygon is the box of its corners, which already carries the rotation.
    """
    if instance.is_circle:
        x, y = instance.center
        radius = instance.inradius
        return (x - radius, y - radius, x + radius, y + radius)
    return (instance.geometry.bounds[0], instance.geometry.bounds[1],
            instance.geometry.bounds[2], instance.geometry.bounds[3])


def _arrangement_bounds(
    instances: tuple[ShapeInstance, ...]
) -> tuple[float, float, float, float]:
    """Return the box of the arrangement, each shape measured on its own outline."""
    left, bottom, right, top = math.inf, math.inf, -math.inf, -math.inf
    for instance in instances:
        bounds = instance_bounds(instance)
        left = min(left, bounds[0])
        bottom = min(bottom, bounds[1])
        right = max(right, bounds[2])
        top = max(top, bounds[3])
    return left, bottom, right, top


def minimal_enclosing_circle(
    points: tuple[tuple[float, float], ...],
) -> tuple[tuple[float, float], float]:
    """Return the centre and radius of the smallest circle holding every point.

    The incremental form of Welzl's algorithm: a point outside the circle built so
    far becomes a boundary point and the circle is rebuilt around it. The points are
    taken in the order the caller gives, which keeps the result deterministic — the
    shuffle a textbook version uses only shortens the walk — and the tolerance is the
    descriptive 1e-9 of the lab, this measures an arrangement rather than deciding
    whether it is legal.
    """
    circle: tuple[tuple[float, float], float] | None = None
    for index, point in enumerate(points):
        if circle is not None and _inside_circle(circle, point):
            continue
        circle = (point, 0.0)
        for nearer in range(index):
            first = points[nearer]
            if _inside_circle(circle, first):
                continue
            circle = _circle_from_pair(point, first)
            for innermost in range(nearer):
                second = points[innermost]
                if _inside_circle(circle, second):
                    continue
                circle = _circle_from_triple(point, first, second)
    return circle if circle is not None else ((0.0, 0.0), 0.0)


def _inside_circle(circle: tuple[tuple[float, float], float], point: tuple[float, float]) -> bool:
    """Whether a point is inside the circle, to the lab's descriptive tolerance."""
    (cx, cy), radius = circle
    return math.hypot(point[0] - cx, point[1] - cy) <= radius + 1e-9


def _circle_from_pair(
    first: tuple[float, float], second: tuple[float, float]
) -> tuple[tuple[float, float], float]:
    """Return the circle whose diameter is the segment between two points."""
    centre = ((first[0] + second[0]) / 2.0, (first[1] + second[1]) / 2.0)
    return centre, math.hypot(first[0] - second[0], first[1] - second[1]) / 2.0


def _circle_from_triple(
    first: tuple[float, float], second: tuple[float, float], third: tuple[float, float]
) -> tuple[tuple[float, float], float]:
    """Return the circle through three points, or the widest pair when they are flat."""
    ax, ay = first
    bx, by = second
    cx, cy = third
    divisor = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(divisor) < 1e-12:
        pairs = (
            _circle_from_pair(first, second),
            _circle_from_pair(second, third),
            _circle_from_pair(first, third),
        )
        return max(pairs, key=lambda circle: circle[1])
    squared = (ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy)
    ux = (
        squared[0] * (by - cy) + squared[1] * (cy - ay) + squared[2] * (ay - by)
    ) / divisor
    uy = (
        squared[0] * (cx - bx) + squared[1] * (ax - cx) + squared[2] * (bx - ax)
    ) / divisor
    return (ux, uy), math.hypot(ax - ux, ay - uy)

def outline_to_arena_distance(instance: ShapeInstance, arena: Arena) -> float:
    """Return the distance from a shape outline to the arena boundary, 0.0 if it crosses.

    Used by the descriptive metrics: a lattice circle exactly on the wall is at
    distance zero, and so is a shape that overflows, which is what a contact
    count wants.
    """
    if instance.is_circle:
        signed = arena.signed_distance(*instance.center)
        return max(0.0, abs(signed) - instance.inradius)
    return float(shapely.distance(instance.geometry, arena.geometry.boundary))


def _instance(
    problem: Problem, placement: Placement, index: int, common_scale: float
) -> ShapeInstance:
    """Resolve one placement into the numbers the predicates need.

    A circle keeps ``vertices``/``geometry`` empty on purpose: its exact
    predicates are analytic, and building a 256-gon for every circle of every
    evaluated candidate would dominate the cost of a search loop.
    """
    shape = problem.shape
    scale = placement.resolved_scale(common_scale)
    is_circle = shape.is_circle
    vertices = None if is_circle else shape.vertices(scale, placement.rotation) + np.array(
        [placement.x, placement.y]
    )
    return ShapeInstance(
        shape_id=placement.shape_id,
        index=index,
        center=(placement.x, placement.y),
        rotation=placement.rotation,
        scale=scale,
        is_circle=is_circle,
        is_convex=shape.is_convex,
        inradius=shape.inradius(scale),
        circumradius=shape.circumradius(scale),
        area=shape.area(scale),
        vertices=vertices,
        geometry=None if is_circle else Polygon(vertices),
    )


def _declared_disc(shape) -> tuple[float, float, float] | None:
    """Return ``(cx, cy, r)`` when the arena tree is a placed disc, else ``None``.

    A disc is invariant under a rotation about its own centre, so peeling
    ``Rotate`` -- turning the resolved centre about the node origin -- and
    accumulating ``Translate`` recovers the declared disc exactly. Anything else
    (an ellipse, a polygon, a boolean composition) returns ``None`` and keeps the
    polygon path.
    """
    if isinstance(shape, Disk):
        return (0.0, 0.0, float(shape.radius))
    if isinstance(shape, Translate):
        inner = _declared_disc(shape.shape)
        if inner is None:
            return None
        return (inner[0] + float(shape.dx), inner[1] + float(shape.dy), inner[2])
    if isinstance(shape, Rotate):
        inner = _declared_disc(shape.shape)
        if inner is None:
            return None
        angle = math.radians(float(shape.angle))
        cosine, sine = math.cos(angle), math.sin(angle)
        return (
            inner[0] * cosine - inner[1] * sine,
            inner[0] * sine + inner[1] * cosine,
            inner[2],
        )
    return None


def _has_curved_boundary(shape) -> bool:
    """Whether an arena tree contains a curved primitive (a disc or an ellipse)."""
    if isinstance(shape, (Disk, Ellipse)):
        return True
    if isinstance(shape, (Translate, Rotate)):
        return _has_curved_boundary(shape.shape)
    if isinstance(shape, BooleanOp):
        return _has_curved_boundary(shape.left) or _has_curved_boundary(shape.right)
    return False


def _disc_containment(
    instances: tuple[ShapeInstance, ...], disc: tuple[float, float, float]
) -> tuple[Containment, ...]:
    """Containment of discs in a declared disc, in closed form.

    The signed distance from a centre to the wall is ``R - distance(c, centre)``,
    so the margin is exact and the compiled chord polygon is not read at all.
    The overflow area is the area of the disc outside the arena disc, also closed
    form, so even an invalid disc reports an exact magnitude.
    """
    records = []
    for instance in instances:
        margin = exact_discs.signed_distance_to_disc_boundary(instance.center, disc) - instance.inradius
        inside = margin >= -LENGTH_TOLERANCE
        overflow = (
            0.0
            if inside
            else exact_discs.disc_difference_area(
                (instance.center[0], instance.center[1], instance.inradius), disc
            )
        )
        inward = None
        if not inside:
            # Straight towards the arena's centre, by exactly the overflow depth.
            dx, dy = disc[0] - instance.center[0], disc[1] - instance.center[1]
            length = math.hypot(dx, dy)
            inward = (0.0, 0.0) if length == 0.0 else (-margin * dx / length, -margin * dy / length)
        records.append(
            Containment(
                instance.shape_id,
                instance.index,
                inside,
                overflow,
                margin,
                "inside the arena" if inside else f"{instance.shape_id} leaves the arena by {abs(margin):.6g}",
                inward,
            )
        )
    return tuple(records)


def _inward(instance: ShapeInstance, arena: Arena, margin: float | None) -> tuple[float, float]:
    """Return the translation that brings an overflowing outline back to the arena wall.

    A disc moves along the line from its centre to the nearest wall point, by its overflow
    depth. A polygon moves its deepest outside vertex onto the nearest wall point, which is
    exact when one straight wall is crossed; an edge that crosses a concave corner without a
    vertex outside is left to the next repair pass.
    """
    boundary = arena.geometry.boundary
    if instance.is_circle and margin is not None:
        centre = Point(instance.center)
        near = nearest_points(boundary, centre)[0]
        dx, dy = near.x - centre.x, near.y - centre.y
        length = math.hypot(dx, dy)
        if length == 0.0:
            return (0.0, 0.0)
        # A centre inside moves away from the wall, a centre outside moves towards it.
        sign = -1.0 if arena.geometry.covers(centre) else 1.0
        depth = -margin if sign < 0 else length + instance.inradius
        return (sign * depth * dx / length, sign * depth * dy / length)
    corners = [Point(x, y) for x, y in (instance.vertices if instance.vertices is not None else ())]
    outside = [(float(shapely.distance(point, boundary)), point)
               for point in corners if not arena.geometry.covers(point)]
    if not outside:
        return (0.0, 0.0)
    _, deepest = max(outside, key=lambda item: item[0])
    near = nearest_points(boundary, deepest)[0]
    return (near.x - deepest.x, near.y - deepest.y)


def _containment(instances: tuple[ShapeInstance, ...], arena: Arena) -> tuple[Containment, ...]:
    """Measure, for every shape at once, how far it leaves the arena.

    Two exact rules, one per family. A disc is contained when its centre is at
    least its radius away from the arena boundary. A convex polygon is contained
    when the arena covers it, on its exact vertices. Both tests are asked to
    shapely for the whole candidate in one call rather than shape by shape: a
    packing of a few hundred discs spends all of its time here otherwise.

    A candidate made only of discs inside a disc-shaped arena never reaches that
    call: :func:`_disc_containment` answers it in closed form, which is both the
    exact verdict and the cheap one -- the compiled polygon is not built for the
    distance. Every other family keeps the exact-on-vertices shapely path; the
    one place a curved wall is still read through a chord is a shape against a
    **composite** arena that contains an arc -- a box with a disc cut out of it,
    for instance -- because a composition of arcs has no closed form here. In
    that case the tolerances are raised to the chord bound
    (:func:`paper_obs.domain.tessellation.chord_radius_relative_error`) rather
    than deciding at 1e-9 on a reading that is only good to ~7.5e-5.

    The overflow area, which is what a violation reports and what a reader
    understands, is only computed for the shapes that actually fail: it needs a
    difference against the arena, and computing it for a valid shape is work
    nobody reads.
    """
    if not instances:
        return ()
    disc = _declared_disc(arena.shape)
    if disc is not None and all(instance.is_circle for instance in instances):
        return _disc_containment(instances, disc)
    slack_length = LENGTH_TOLERANCE
    slack_area = AREA_TOLERANCE
    if _has_curved_boundary(arena.shape):
        # A curved wall reaches this path only as a compiled chord polygon. The
        # margin and the overflow are then read on chords, so the verdict cannot
        # be tighter than the chord's own error.
        scale = max((abs(value) for value in arena.bounds), default=1.0)
        slack_length = max(slack_length, chord_radius_relative_error() * scale)
        slack_area = max(slack_area, chord_area_relative_error() * arena.area)
    points = shapely.points(np.array([instance.center for instance in instances]))
    to_boundary = shapely.distance(points, arena.geometry.boundary)
    covered = shapely.covers(arena.geometry, points)
    polygons = [instance for instance in instances if not instance.is_circle]
    covered_polygons = dict(
        zip(
            (instance.shape_id for instance in polygons),
            shapely.covers(
                arena.geometry, np.array([instance.geometry for instance in polygons], dtype=object)
            )
            if polygons
            else (),
        )
    )

    records = []
    for index, instance in enumerate(instances):
        margin: float | None = None
        if instance.is_circle:
            if disc is not None:
                signed = exact_discs.signed_distance_to_disc_boundary(instance.center, disc)
            else:
                signed = float(to_boundary[index]) if covered[index] else -float(to_boundary[index])
            margin = signed - instance.inradius
            inside = margin >= -slack_length
            overflow = 0.0 if inside else _circle_overflow_area(instance, arena)
            message = (
                "inside the arena"
                if inside
                else f"{instance.shape_id} leaves the arena by {abs(margin):.6g}"
            )
        else:
            inside = bool(covered_polygons[instance.shape_id])
            # ``covers`` and the area of the difference can only disagree by
            # floating-point dust on an exact polygon, so the area decides.
            overflow = 0.0 if inside else float(instance.geometry.difference(arena.geometry).area)
            inside = overflow <= slack_area
            message = (
                "inside the arena"
                if inside
                else f"{instance.shape_id} overflows the arena by {overflow:.6g}"
            )
        records.append(
            Containment(
                instance.shape_id, instance.index, inside, overflow, margin, message,
                None if inside else _inward(instance, arena, margin),
            )
        )
    return tuple(records)


def _overlaps(instances: tuple[ShapeInstance, ...]) -> tuple[Overlap, ...]:
    """Return every pair of shapes sharing area, broad phase first.

    A candidate made only of discs is resolved in one vectorized pass: for discs
    the bounding-circle test *is* the exact test, so the broad phase has already
    computed everything that matters.
    """
    if len(instances) < 2:
        return ()
    centers, radii = _centers_and_radii(instances)
    first, second, distances = predicates.bounding_circle_pairs(centers, radii)
    if _all_circles(instances):
        gaps = predicates.circle_gaps(distances, radii[first], radii[second])
        return tuple(
            _overlap(instances, first, second, -gaps, pair)
            for pair in np.flatnonzero(gaps < -LENGTH_TOLERANCE)
        )
    overlaps = []
    for pair in range(len(first)):
        left = instances[first[pair]]
        right = instances[second[pair]]
        depth, direction = _penetration(left, right, float(distances[pair]))
        if depth > LENGTH_TOLERANCE:
            overlaps.append(
                Overlap(left.shape_id, right.shape_id, left.index, right.index, depth, direction)
            )
    return tuple(overlaps)


def _overlap(
    instances: tuple[ShapeInstance, ...],
    first: np.ndarray,
    second: np.ndarray,
    depths: np.ndarray,
    pair: int,
) -> Overlap:
    """Build the overlap record of one index pair.

    The depth comes from the caller, which computed it on whole arrays; the
    direction of two discs is the line between their centres, and it is read here
    so that the vectorized path yields the same record as the general one.
    """
    left = instances[first[pair]]
    right = instances[second[pair]]
    return Overlap(
        left.shape_id,
        right.shape_id,
        left.index,
        right.index,
        float(depths[pair]),
        predicates.unit_direction(left.center, right.center),
    )


def _centers_and_radii(instances: tuple[ShapeInstance, ...]) -> tuple[np.ndarray, np.ndarray]:
    """Return the centres and bounding radii of every instance, as arrays."""
    return (
        np.array([instance.center for instance in instances]),
        np.array([instance.circumradius for instance in instances]),
    )


def _all_circles(instances: tuple[ShapeInstance, ...]) -> bool:
    """Whether every instance is a disc, which unlocks the vectorized predicates."""
    return all(instance.is_circle for instance in instances)


def _penetration(
    left: ShapeInstance, right: ShapeInstance, center_distance: float
) -> tuple[float, tuple[float, float]]:
    """Return how far two shapes overlap, and the axis that separates them.

    Three cases. Two discs are arithmetic, a disc against any polygon is a
    distance to that polygon, and two *convex* polygons go through the
    separating-axis theorem, which gives the exact shallowest way out together
    with its direction. Two polygons of which one is concave have no single
    separating axis: the overlap is measured by the area they share and reported
    as the square root of that area — a length-like, monotone proxy, because a
    search pulling two shapes apart needs a magnitude in the same unit as the
    others — and the direction is then only the line between the two centres, so
    a caller may have to iterate rather than solve in one go.

    Only the two convex-polygon case is exact in its direction as well as its
    depth; the disc cases point along the line between centres, which is exact
    for two discs and an approximation for a disc against a polygon.
    """
    if left.is_circle and right.is_circle:
        gap = predicates.circle_pair_gap(center_distance, left.inradius, right.inradius)
    elif left.is_circle or right.is_circle:
        circle, polygon = (left, right) if left.is_circle else (right, left)
        gap = _circle_polygon_gap(circle, polygon)
    elif left.is_convex and right.is_convex:
        return predicates.convex_separation_axis(left.vertices, right.vertices)
    else:
        depth = math.sqrt(max(0.0, float(left.geometry.intersection(right.geometry).area)))
        return depth, predicates.unit_direction(left.center, right.center)
    return max(0.0, -gap), predicates.unit_direction(left.center, right.center)


def _circle_polygon_gap(circle: ShapeInstance, polygon: ShapeInstance) -> float:
    """Signed gap between a disc outline and a polygon outline, on exact vertices."""
    return predicates.circle_polygon_gap(circle.center_point(), polygon.geometry, circle.inradius)


def _clearances(instances: tuple[ShapeInstance, ...], slack: float) -> tuple[Clearance, ...]:
    """Return the pairs closer than ``slack``, with their distance.

    The disc case is vectorized for the same reason as the overlap test: the
    whole computation is one subtraction on arrays.
    """
    if len(instances) < 2:
        return ()
    centers, radii = _centers_and_radii(instances)
    first, second, distances = predicates.bounding_circle_pairs(centers, radii, slack)
    if _all_circles(instances):
        gaps = np.maximum(0.0, predicates.circle_gaps(distances, radii[first], radii[second]))
        return tuple(
            _clearance_record(instances[first[pair]], instances[second[pair]], float(gaps[pair]))
            for pair in np.flatnonzero(gaps <= slack)
        )
    clearances = []
    for pair in range(len(first)):
        left = instances[first[pair]]
        right = instances[second[pair]]
        distance = _clearance(left, right, float(distances[pair]))
        if distance <= slack:
            clearances.append(_clearance_record(left, right, distance))
    return tuple(clearances)


def _clearance_record(left: ShapeInstance, right: ShapeInstance, distance: float) -> Clearance:
    """Build the clearance record of one pair."""
    return Clearance(left.shape_id, right.shape_id, left.index, right.index, distance)


def _clearance(left: ShapeInstance, right: ShapeInstance, center_distance: float) -> float:
    """Return the distance between two outlines, 0.0 when they touch or overlap."""
    if left.is_circle and right.is_circle:
        return max(0.0, predicates.circle_pair_gap(center_distance, left.inradius, right.inradius))
    if left.is_circle or right.is_circle:
        circle, polygon = (left, right) if left.is_circle else (right, left)
        return max(0.0, _circle_polygon_gap(circle, polygon))
    return float(shapely.distance(left.geometry, right.geometry))


def _tessellated_circle(instance: ShapeInstance) -> BaseGeometry:
    """Return a circumscribed polygon approximation of a circle instance."""
    angles = np.linspace(0.0, 2.0 * math.pi, CIRCLE_SEGMENTS, endpoint=False)
    radius = instance.inradius / math.cos(math.pi / CIRCLE_SEGMENTS)
    points = np.column_stack((np.cos(angles), np.sin(angles))) * radius
    return Polygon(points + np.array(instance.center))


def _circle_overflow_area(instance: ShapeInstance, arena: Arena) -> float:
    """Return the area of a circle lying outside the arena, on its approximation."""
    return float(_tessellated_circle(instance).difference(arena.geometry).area)
