"""Exact numerical kernels used by the geometry engine.

Three families, each exact within floating point for the shapes of the MVP:

* **bounding circles** — the broad phase. Two shapes cannot interact when the
  distance between their centres exceeds the sum of their bounding radii, so the
  expensive predicates only run on the pairs that survive.
* **circle predicates** — a circle is never a polygon here. Two circles are
  compared by centre distance, a circle and a polygon by the distance from the
  centre to that polygon, which shapely computes on exact vertices.
* **convex polygons** — the separating-axis theorem returns both the boolean
  answer and the penetration depth, which becomes the magnitude of the
  ``NonOverlap`` violation.

Everything is numpy in, numpy out, so the same kernel serves a single
validation and a batch of a thousand relaxations.
"""

from __future__ import annotations

import math

import numpy as np
import shapely
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry


def bounding_circle_pairs(
    centers: np.ndarray, radii: np.ndarray, slack: float = 0.0
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return the index pairs of potentially interacting bounding circles.

    Returns ``(first_indices, second_indices, center_distances)`` restricted to
    pairs whose bounding circles are within ``slack`` of touching. No pair that
    could interact is ever dropped: the bounding circle contains its shape, so
    its distance to a neighbour is a lower bound of the shape's own distance.

    O(n^2) in time and memory, which is what an honest MVP looks like: a few
    hundred shapes cost a few milliseconds, and a spatial index is the upgrade
    path the day a problem is large enough to need one.
    """
    count = len(centers)
    if count < 2:
        empty = np.empty(0, dtype=np.int64)
        return empty, empty, np.empty(0, dtype=float)
    first, second = np.triu_indices(count, k=1)
    deltas = centers[first] - centers[second]
    distances = np.hypot(deltas[:, 0], deltas[:, 1])
    close = distances <= radii[first] + radii[second] + slack
    return first[close], second[close], distances[close]


def circle_gaps(distances: np.ndarray, radii_a: np.ndarray, radii_b: np.ndarray) -> np.ndarray:
    """Signed gaps between circle outlines, array-wise: negative when they overlap.

    Written once, on arrays, because the entire overlap test of a candidate made
    of discs is this single expression. It is the hot path of every circle
    packing, and the scalar case is a one-element array away.
    """
    return distances - radii_a - radii_b


def circle_pair_gap(distance: float, radius_a: float, radius_b: float) -> float:
    """Signed gap between two circle outlines, for a single pair."""
    return float(
        circle_gaps(
            np.asarray(distance, dtype=float),
            np.asarray(radius_a, dtype=float),
            np.asarray(radius_b, dtype=float),
        )
    )


def circle_polygon_gap(center: Point, polygon: BaseGeometry, radius: float) -> float:
    """Signed gap between a disc outline and a polygon outline.

    Two cases, both exact on the polygon's vertices. When the centre is outside
    the polygon, the gap is the distance from the centre to the polygon minus the
    radius. When the centre is inside — a disc swallowed by a bigger shape — the
    cheapest way out is through the nearest edge, so the gap is the negated
    distance to that edge, plus the radius.

    Mixed families cannot occur in a problem of the MVP, which packs one shape
    family at a time; this is the kernel the documented extension to
    heterogeneous shapes will need.
    """
    if polygon.covers(center):
        return -(float(shapely.distance(center, polygon.boundary)) + radius)
    return float(shapely.distance(center, polygon)) - radius


def edge_normals(*polygons: np.ndarray) -> np.ndarray:
    """Return the unit normals of every edge of the given convex polygons.

    These are exactly the candidate separating axes of the separating-axis
    theorem: two convex polygons are disjoint when and only when one of their
    edge normals separates them. Degenerate edges of zero length are skipped.
    """
    normals: list[np.ndarray] = []
    for vertices in polygons:
        edges = np.roll(vertices, -1, axis=0) - vertices
        lengths = np.hypot(edges[:, 0], edges[:, 1])
        edges = edges[lengths > 0.0]
        lengths = lengths[lengths > 0.0]
        normals.append(np.column_stack((-edges[:, 1], edges[:, 0])) / lengths[:, None])
    return np.vstack(normals)


def convex_penetration_depth(vertices_a: np.ndarray, vertices_b: np.ndarray) -> float:
    """Return the smallest translation separating two convex polygons, 0.0 if apart.

    The minimum overlap over the separating axes is the penetration depth: the
    distance along the shallowest direction, which is the cheapest way to pull
    the two shapes apart. Touching polygons return 0.0, so an exact packing is
    never reported as an overlap by floating-point noise.
    """
    return convex_separation_axis(vertices_a, vertices_b)[0]


def convex_separation_axis(
    vertices_a: np.ndarray, vertices_b: np.ndarray
) -> tuple[float, tuple[float, float]]:
    """Return the smallest translation separating two convex polygons, and its axis.

    Same depth as :func:`convex_penetration_depth`, with the direction that
    produces it. The axis is a unit vector pointing from the first polygon
    towards the second, so ``depth * axis`` is the shortest displacement of the
    *second* polygon that removes the overlap — which is what a relaxation needs
    to repair a packing in one move instead of guessing.

    Touching or separated polygons return a depth of 0.0 and still get an axis:
    the direction between their centroids, or (1, 0) when those coincide. A
    caller pushing shapes apart needs somewhere to push even when there is
    nothing left to separate.
    """
    axes = edge_normals(vertices_a, vertices_b)
    projected_a = vertices_a @ axes.T
    projected_b = vertices_b @ axes.T
    overlaps = np.minimum(projected_a.max(axis=0), projected_b.max(axis=0)) - np.maximum(
        projected_a.min(axis=0), projected_b.min(axis=0)
    )
    if np.any(overlaps <= 0.0):
        return 0.0, unit_direction(vertices_a.mean(axis=0), vertices_b.mean(axis=0))
    shallowest = int(np.argmin(overlaps))
    axis = axes[shallowest]
    # Orientation matters: the same normal read the other way round would push
    # the second polygon further in. The centroids decide the sign.
    if float((vertices_b.mean(axis=0) - vertices_a.mean(axis=0)) @ axis) < 0.0:
        axis = -axis
    return float(overlaps[shallowest]), (float(axis[0]), float(axis[1]))


def unit_direction(
    origin: np.ndarray | tuple[float, float], target: np.ndarray | tuple[float, float]
) -> tuple[float, float]:
    """Return the unit vector pointing from one point to another.

    Two points that coincide have no direction between them, and (1, 0) is
    returned instead: an arbitrary but *stated* tie-break, because a search that
    has to be reproducible cannot accept a direction that depends on rounding.
    """
    dx = float(target[0]) - float(origin[0])
    dy = float(target[1]) - float(origin[1])
    length = math.hypot(dx, dy)
    if length == 0.0:
        return (1.0, 0.0)
    return (dx / length, dy / length)
