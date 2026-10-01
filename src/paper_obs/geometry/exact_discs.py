"""Closed-form geometry for discs: the exact path the chord polygon cannot give.

A disc has an exact area, an exact distance to another disc and an exact
containment test. The lab's general engine goes through shapely on polygons --
the right representation for the editor and for a boolean composition whose
closed form does not exist -- and a curved boundary is compiled to a
circumscribed chord polygon (see `paper_obs.domain.tessellation`). At the
default chord count that polygon carries a relative error of about 5.0e-5 of the
area and 7.5e-5 of the radius.

This module is the other half of that story: the verdicts and the measures that
only involve discs are answered here in closed form, so a disc packing is judged
exactly and the polygon path keeps only the cases that really need it. Every
function is pure arithmetic on `(cx, cy, r)` triples; nothing here reads or
writes a shapely geometry.

What is exact here:

* `disc_gap`, `discs_overlap`, `disc_clearance` -- two discs;
* `disc_inside_disc` -- a disc inside a disc, which is the disc-arena
  containment the polygon path used to decide against a chord;
* `disc_inside_polygon` -- a disc inside a polygon, on the polygon's exact
  vertices, the same closed form the engine already used through shapely;
* `point_in_disc`, `point_segment_distance`, `point_ring_distance`;
* `union_area` -- the area of the union of discs;
* `clipped_union_area` -- the area of a disc intersected with a union of
  discs, which is the covered area of a covering of discs on a disc arena.

The area is an **arc sweep**, not inclusion-exclusion. Inclusion-exclusion needs
`2**n - 1` terms -- 1.0e6 at n = 20, and the signs alternate -- while the sweep
visits every circle once and costs O(n**2 log n). It integrates the boundary arcs
of the region with Green's theorem, so a region that is a boolean combination of
discs is a sum of arc integrals and nothing more. The one restriction is stated
in :func:`region_area`: every boundary arc of the region must lie on one of the
given circles.

All of it is floating-point arithmetic, not symbolic: the answers are exact in
the sense that they carry the closed form, with a rounding error of a few units
in the last place, never the ~5e-5 of the chord polygon.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence

#: A disc as a centre and a radius.
Disc = tuple[float, float, float]

_TAU = 2.0 * math.pi

#: Relative angular width below which two crossing angles are the same event.
_ANGLE_EPSILON = 1e-12

#: Discs up to which the arc sweep is cheap enough for a search loop to call on
#: every candidate. The sweep visits O(n**2) arcs and probes O(n) circles at
#: each, so it is the one exact path with a real cost: measured at ~0.6 ms for
#: 10 discs, ~2 ms for 20, ~32 ms for 50 and ~262 ms for 100. The engine uses it
#: below this count and keeps the polygon reading -- declaring its chord
#: resolution -- above it; a caller that wants the exact area at any count calls
#: :func:`union_area` or :func:`clipped_union_area` directly.
ARC_SWEEP_DISC_LIMIT = 32

#: Directions probed on a circle that no other boundary crosses, to find a clear one.
_PROBE_DIRECTIONS = 16


def _distance(first: tuple[float, float], second: tuple[float, float]) -> float:
    return math.hypot(second[0] - first[0], second[1] - first[1])


def disc_gap(first: Disc, second: Disc) -> float:
    """Signed gap between two disc boundaries: positive apart, negative overlapping."""
    return _distance(first, second) - first[2] - second[2]


def discs_overlap(first: Disc, second: Disc, *, tolerance: float = 0.0) -> bool:
    """Whether two discs share area; a gap of exactly `tolerance` still counts as touching."""
    return disc_gap(first, second) < -tolerance


def point_in_disc(point: tuple[float, float], disc: Disc, *, tolerance: float = 0.0) -> bool:
    """Whether a point lies in a disc, its boundary included."""
    dx = point[0] - disc[0]
    dy = point[1] - disc[1]
    reach = disc[2] + tolerance
    return dx * dx + dy * dy <= reach * reach


def disc_inside_disc(inner: Disc, outer: Disc, *, tolerance: float = 0.0) -> bool:
    """Whether every point of `inner` lies in `outer`.

    The closed form is `distance(c1, c2) + r1 <= r2`: the farthest point of the
    inner disc from the outer centre is the one on the line through both centres.
    A disc touching its wall from the inside is inside, which is the tangency an
    exact lattice produces.
    """
    return _distance(inner, outer) + inner[2] <= outer[2] + tolerance


def disc_difference_area(inner: Disc, outer: Disc) -> float:
    """Area of @@inner@@ that lies outside @@outer@@, in closed form.

    Three cases: apart, the whole inner disc; contained, nothing; overlapping,
    the inner area minus the lens, which :func:`union_area` gives without a
    formula of its own. This is the exact magnitude of a disc that leaves a
    disc-shaped arena.
    """
    if disc_gap(inner, outer) >= 0.0:
        return math.pi * inner[2] * inner[2]
    if disc_inside_disc(inner, outer):
        return 0.0
    intersection = (
        math.pi * inner[2] * inner[2]
        + math.pi * outer[2] * outer[2]
        - union_area((inner, outer))
    )
    return max(0.0, math.pi * inner[2] * inner[2] - intersection)


def signed_distance_to_disc_boundary(point: tuple[float, float], disc: Disc) -> float:
    """Distance from a point to the disc boundary, positive inside and negative outside."""
    return disc[2] - _distance(point, disc)


def point_segment_distance(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> float:
    """Distance from a point to the closed segment between `start` and `end`."""
    vx = end[0] - start[0]
    vy = end[1] - start[1]
    length_squared = vx * vx + vy * vy
    wx = point[0] - start[0]
    wy = point[1] - start[1]
    if length_squared == 0.0:
        return math.hypot(wx, wy)
    parameter = max(0.0, min(1.0, (wx * vx + wy * vy) / length_squared))
    return math.hypot(wx - parameter * vx, wy - parameter * vy)


def _ring_vertices(ring: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    """Drop a repeated closing vertex, so every ring is a list of distinct corners."""
    vertices = [(float(x), float(y)) for x, y in ring]
    if len(vertices) > 1 and vertices[0] == vertices[-1]:
        vertices.pop()
    return vertices


def point_ring_distance(point: tuple[float, float], ring: Sequence[tuple[float, float]]) -> float:
    """Unsigned distance from a point to a closed polyline, every edge included."""
    vertices = _ring_vertices(ring)
    if len(vertices) < 2:
        return math.inf
    return min(
        point_segment_distance(point, vertices[index], vertices[(index + 1) % len(vertices)])
        for index in range(len(vertices))
    )


def point_in_ring(point: tuple[float, float], ring: Sequence[tuple[float, float]]) -> bool:
    """Even-odd ray cast: whether a point is inside a closed polyline.

    A point exactly on the boundary may read either way, which is why the caller
    that needs a boundary-aware answer uses :func:`point_ring_distance` as well.
    """
    vertices = _ring_vertices(ring)
    if len(vertices) < 3:
        return False
    x, y = point
    inside = False
    previous = len(vertices) - 1
    for index in range(len(vertices)):
        xi, yi = vertices[index]
        xj, yj = vertices[previous]
        if (yi > y) != (yj > y):
            crossing = xi + (y - yi) * (xj - xi) / (yj - yi)
            if x < crossing:
                inside = not inside
        previous = index
    return inside


def disc_inside_polygon(
    centre: tuple[float, float],
    radius: float,
    exterior: Sequence[tuple[float, float]],
    interiors: Iterable[Sequence[tuple[float, float]]] = (),
    *,
    tolerance: float = 0.0,
) -> bool:
    """Whether a disc lies in a polygon, on the polygon's exact vertices.

    A disc is inside when its centre is inside the outer ring, outside every
    hole, and at least `radius` away from every ring boundary. The distance is
    to the exact segments, so a disc touching an edge from the inside is inside.
    """
    if not point_in_ring(centre, exterior):
        return False
    if point_ring_distance(centre, exterior) + tolerance < radius:
        return False
    for hole in interiors:
        if point_in_ring(centre, hole):
            return False
        if point_ring_distance(centre, hole) + tolerance < radius:
            return False
    return True


def _directional_hits(
    circles: Sequence[Disc], index: int, ux: float, uy: float
) -> tuple[float, float]:
    """Nearest circle boundary inward of `r` and outward of `r` along a ray.

    Returns `(inside_hit, outside_hit)` for the ray leaving
    `circles[index]`'s centre in direction `(ux, uy)`. `inside_hit` is the
    largest crossing strictly below the circle's own radius (0 when there is
    none) and `outside_hit` the smallest strictly above it (infinity when
    there is none). Sampling at the midpoint of each gap keeps a test point in
    the same open cell as the arc it stands for, so a membership test there means
    what the caller thinks it means.
    """
    cx, cy, radius = circles[index]
    inside_hit = 0.0
    outside_hit = math.inf
    for other, (ox, oy, other_radius) in enumerate(circles):
        if other == index:
            continue
        if (
            abs(other_radius - radius) <= 1e-12 * radius
            and math.hypot(ox - cx, oy - cy) <= 1e-12 * radius
        ):
            # A coincident circle is the same boundary; it cannot cut itself.
            continue
        vx = ox - cx
        vy = oy - cy
        projection = ux * vx + uy * vy
        constant = vx * vx + vy * vy - other_radius * other_radius
        discriminant = projection * projection - constant
        if discriminant <= 0.0:
            continue
        root = math.sqrt(discriminant)
        for hit in (projection - root, projection + root):
            if hit <= 1e-12:
                continue
            if hit < radius:
                inside_hit = max(inside_hit, hit)
            elif hit > radius:
                outside_hit = min(outside_hit, hit)
    return inside_hit, outside_hit


def _arc_integral(cx: float, cy: float, radius: float, start: float, end: float) -> float:
    """Green's theorem contribution of a counter-clockwise arc of one circle.

    `1/2 * integral(x dy - y dx)` over the arc: the area the arc encloses with
    the two radii to its ends. A full circle of radius `r` gives `pi r**2`,
    which is the sanity check the tests pin.
    """
    return 0.5 * (
        radius * radius * (end - start)
        + radius
        * (cx * (math.sin(end) - math.sin(start)) - cy * (math.cos(end) - math.cos(start)))
    )


def _crossing_angles(circles: Sequence[Disc], index: int) -> list[float]:
    """Angles on one circle where any other circle boundary crosses it, sorted."""
    cx, cy, radius = circles[index]
    angles: list[float] = []
    for other, (ox, oy, other_radius) in enumerate(circles):
        if other == index:
            continue
        distance = math.hypot(ox - cx, oy - cy)
        if distance <= _ANGLE_EPSILON or distance >= radius + other_radius:
            continue
        if distance + radius <= other_radius or distance + other_radius <= radius:
            # One circle contains the other: no crossing, and no chord to cut.
            continue
        direction = math.atan2(oy - cy, ox - cx)
        cosine = (distance * distance + radius * radius - other_radius * other_radius) / (
            2.0 * distance * radius
        )
        offset = math.acos(max(-1.0, min(1.0, cosine)))
        if offset <= _ANGLE_EPSILON:
            continue
        angles.extend((direction - offset, direction + offset))
    angles = sorted(angle % _TAU for angle in angles)
    unique: list[float] = []
    for angle in angles:
        if not unique or angle - unique[-1] > _ANGLE_EPSILON:
            unique.append(angle)
    return unique


def _arc_sign(
    circles: Sequence[Disc],
    index: int,
    ux: float,
    uy: float,
    inside: Callable[[float, float], bool],
) -> int:
    """+1 when the arc is a boundary with the region inward, -1 outward, 0 neither.

    The two probes sit at the midpoints of the radial gaps on either side of the
    arc, so neither crosses another circle boundary: the membership they report
    is the membership of the cell the arc separates.
    """
    cx, cy, radius = circles[index]
    inside_hit, outside_hit = _directional_hits(circles, index, ux, uy)
    inner = 0.5 * (inside_hit + radius) if inside_hit > 0.0 else 0.5 * radius
    outer_bound = outside_hit if math.isfinite(outside_hit) else 2.0 * radius
    outer = 0.5 * (radius + outer_bound)
    if outer <= radius:
        outer = 1.5 * radius
    inward = inside(cx + inner * ux, cy + inner * uy)
    outward = inside(cx + outer * ux, cy + outer * uy)
    if inward and not outward:
        return 1
    if outward and not inward:
        return -1
    return 0


def _same_circle(first: Disc, second: Disc) -> bool:
    """Whether two discs are the same boundary, up to a rounding of centre and radius."""
    scale = max(1.0, abs(first[2]), abs(second[2]))
    return (
        abs(first[2] - second[2]) <= 1e-12 * scale
        and math.hypot(first[0] - second[0], first[1] - second[1]) <= 1e-12 * scale
    )


def _dedupe(circles: Iterable[Disc]) -> list[Disc]:
    """Drop repeated boundaries: a union counts a disc once however often it is listed."""
    unique: list[Disc] = []
    for circle in circles:
        if not any(_same_circle(circle, kept) for kept in unique):
            unique.append(circle)
    return unique


def region_area(
    circles: Sequence[Disc],
    inside: Callable[[float, float], bool],
) -> float:
    """Area of the region whose exact point membership is `inside`.

    The region must be a boolean combination of the given circles, in the sense
    that **every boundary arc of the region lies on one of the given circles**:
    that is exactly what makes the sweep below a complete account of the
    boundary. Union, intersection and difference of discs all satisfy it; a
    region with a straight side would not, and belongs to the polygon path.

    `inside` is the exact membership predicate of the region and must be
    constant on the open cells the circle crossings divide the plane into, which
    is what a boolean combination of discs gives. The sweep finds, on each
    circle, the arcs between consecutive crossings, decides from one point on
    each side whether the arc is a boundary of the region, and integrates it.
    """
    total = 0.0
    circles = _dedupe(circles)
    for index, (cx, cy, radius) in enumerate(circles):
        if radius <= 0.0:
            continue
        angles = _crossing_angles(circles, index)
        if not angles:
            # With no crossing, the whole circle contributes the same sign.
            # Tangencies can make one probe direction ambiguous even when its
            # outward ray has ample clearance; use the majority of probes.
            signs = {-1: 0, 0: 0, 1: 0}
            for step in range(_PROBE_DIRECTIONS):
                angle = _TAU * step / _PROBE_DIRECTIONS
                ux = math.cos(angle)
                uy = math.sin(angle)
                signs[_arc_sign(circles, index, ux, uy, inside)] += 1
            sign = max(signs, key=lambda value: signs[value])
            if signs[sign] <= _PROBE_DIRECTIONS / 2:
                sign = 0
            if sign:
                total += sign * _arc_integral(cx, cy, radius, 0.0, _TAU)
            continue
        arcs = []
        for position, start in enumerate(angles):
            end = angles[position + 1] if position + 1 < len(angles) else angles[0] + _TAU
            if end - start > _ANGLE_EPSILON:
                arcs.append((start, end))
        for start, end in arcs:
            middle = 0.5 * (start + end)
            sign = _arc_sign(circles, index, math.cos(middle), math.sin(middle), inside)
            if sign:
                total += sign * _arc_integral(cx, cy, radius, start, end)
    return total


def _membership(circles: Sequence[Disc]) -> Callable[[float, float], bool]:
    """Membership in the union of discs, written once for the sweep."""

    def inside(x: float, y: float) -> bool:
        for cx, cy, radius in circles:
            dx = x - cx
            dy = y - cy
            if dx * dx + dy * dy <= radius * radius:
                return True
        return False

    return inside


def union_area(discs: Iterable[Disc]) -> float:
    """Area of the union of a collection of discs, in closed form."""
    circles = _dedupe((float(cx), float(cy), float(radius)) for cx, cy, radius in discs)
    if not circles:
        return 0.0
    area = region_area(circles, _membership(circles))
    return max(0.0, area)


def clipped_union_area(arena: Disc, discs: Iterable[Disc]) -> float:
    """Area of a disc intersected with the union of a collection of discs.

    This is the covered area of a covering of discs on a disc arena: the copies
    stick out of the target by design, and the arena is what clips them back. The
    copies disjoint from the arena are dropped first, so the sweep does not walk
    circles that cannot contribute.
    """
    ax, ay, a_radius = (float(value) for value in arena)
    pieces = [
        piece
        for piece in _dedupe((float(cx), float(cy), float(radius)) for cx, cy, radius in discs)
        if disc_gap((ax, ay, a_radius), piece) <= 0.0
    ]
    if not pieces:
        return 0.0

    def inside(x: float, y: float) -> bool:
        dx = x - ax
        dy = y - ay
        if dx * dx + dy * dy > a_radius * a_radius:
            return False
        return _membership(pieces)(x, y)

    area = region_area([(ax, ay, a_radius), *pieces], inside)
    return max(0.0, min(area, math.pi * a_radius * a_radius))
