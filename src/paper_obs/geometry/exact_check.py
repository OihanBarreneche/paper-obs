"""An exact check of an arrangement of convex polygons, on a code path of its own.

Before a record is claimed, research mode asks for a second check that does not share the
engine's predicates (docs/research-mode.md). This one takes every corner as the domain places
it, converts each float to an exact fraction, and decides in rational arithmetic with the
separating-axis theorem: two convex polygons have disjoint interiors iff an edge normal of one
of them separates them, touching allowed. No tolerance is involved: the verdict is the one for
the corners as written, and the reported margins say how far from a contact each one is.

A copy lies in the arena when it lies in the arena's convex hull (one half-plane per hull
edge) and is separated from each convex obstacle the hull minus the arena splits into: the
notch of an L, a hole. A disc arena is the exact disc ``x² + y² <= r²``. Round copies are
outside its scope: `paper_obs.geometry.exact_discs` answers for discs.
"""

from __future__ import annotations

import math
from fractions import Fraction
from typing import Any

import numpy as np
import shapely
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

from paper_obs.domain.arena import Arena, Disk
from paper_obs.domain.candidate import Candidate
from paper_obs.domain.problem import Problem

Corners = list[tuple[Fraction, Fraction]]


def convex_parts(arena: Arena) -> tuple[np.ndarray | None, list[np.ndarray], float | None]:
    """Return an arena as its convex hull, the convex obstacles hull minus arena splits into,
    and a disc radius, each polygon counter-clockwise; a disc arena is only its radius."""
    if isinstance(arena.shape, Disk):
        return None, [], arena.shape.radius
    region = arena.geometry
    hull = orient(region.convex_hull, 1)
    obstacles = []
    rest = hull.difference(region)
    for piece in getattr(rest, "geoms", [rest]):
        if piece.area < 1e-12:
            continue
        convex = piece.convex_hull.area - piece.area < 1e-12
        for part in [piece] if convex else shapely.constrained_delaunay_triangles(piece).geoms:
            obstacles.append(np.asarray(orient(Polygon(part.exterior), 1).exterior.coords)[:-1])
    return np.asarray(hull.exterior.coords)[:-1], obstacles, None


def exact_check(problem: Problem, candidate: Candidate) -> dict[str, Any]:
    """Judge an arrangement of equal convex polygonal copies in exact arithmetic.

    Returns ``valid``, the overlapping pairs and the copies outside the arena (by index), and
    the smallest separation between two copies and between a copy and the arena's boundary, in
    world units (negative for an overlap or a copy out). Raises ValueError for round or
    non-convex copies, or a problem without an arena.
    """
    if problem.arena is None:
        raise ValueError("the exact check needs a fixed arena")
    if problem.shape.vertices(1.0) is None or not problem.shape.is_convex:
        raise ValueError("the exact check covers convex polygonal copies")
    copies = [_exact([(item.x + a, item.y + b) for a, b in
                      problem.shape.vertices(item.resolved_scale(candidate.scale), item.rotation)])
              for item in candidate.placements]
    hull, obstacles, radius = convex_parts(problem.arena)
    reach = 2 * problem.shape.circumradius(max(item.resolved_scale(candidate.scale) for item in candidate.placements))
    overlapping, separation = [], math.inf
    for i in range(len(copies)):
        for j in range(i + 1, len(copies)):
            p, q = candidate.placements[i], candidate.placements[j]
            if math.hypot(p.x - q.x, p.y - q.y) > reach * 1.01:  # far apart: a float margin decides
                continue
            apart, gap = _gap(copies[i], copies[j])
            separation = min(separation, gap)
            if not apart:
                overlapping.append([i, j])
    outside, clearance = [], math.inf
    walls = [] if hull is None else _exact(hull)
    holes = [_exact(item) for item in obstacles]
    for index, corners in enumerate(copies):
        if radius is not None:
            inside = min(radius - math.sqrt(float(x * x + y * y)) for x, y in corners)
            out = any(x * x + y * y > Fraction(radius) ** 2 for x, y in corners)
        else:
            sides = [_side(a, b, corner) for a, b in _edges(walls) for corner in corners]
            inside = min(size for _, size in sides)
            out = any(cross < 0 for cross, _ in sides)
            for hole in holes:
                apart, gap = _gap(corners, hole)
                inside, out = min(inside, gap), out or not apart
        clearance = min(clearance, inside)
        if out:
            outside.append(index)
    return {"valid": not overlapping and not outside, "copies": len(copies),
            "overlapping_pairs": overlapping, "outside": outside,
            "min_separation": separation, "min_clearance": clearance}


def _exact(points) -> Corners:
    return [(Fraction(float(x)), Fraction(float(y))) for x, y in points]


def _edges(corners: Corners):
    return [(corners[k], corners[(k + 1) % len(corners)]) for k in range(len(corners))]


def _side(a, b, point) -> tuple[Fraction, float]:
    """How far a point lies left of the edge a→b: the exact cross product, and the distance."""
    cross = (b[0] - a[0]) * (point[1] - a[1]) - (b[1] - a[1]) * (point[0] - a[0])
    return cross, float(cross) / math.dist(a, b)


def _gap(first: Corners, second: Corners) -> tuple[bool, float]:
    """Whether an edge normal of either polygon separates them, decided exactly, and the largest
    separation along one, in world units (negative when they overlap)."""
    apart, best = False, -math.inf
    for a, b in _edges(first) + _edges(second):
        nx, ny = b[1] - a[1], a[0] - b[0]
        p = [nx * x + ny * y for x, y in first]
        q = [nx * x + ny * y for x, y in second]
        gap = max(min(q) - max(p), min(p) - max(q))
        apart = apart or gap >= 0
        best = max(best, float(gap) / math.hypot(float(nx), float(ny)))
    return apart, best


__all__ = ["convex_parts", "exact_check"]
