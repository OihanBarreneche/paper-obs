"""Compiling a stack of primitives into a packable shape.

The arena editor and the shape composer send the same thing — a list of parts,
each a primitive with the operation that combines it with everything before it —
and this module folds that stack into the region a *shape* is made of.

A composed shape is stored as a polygon outline, not as the tree that produced
it. The engine's shape layer judges outlines: CustomPolygon (see
paper_obs.domain.shapes) is a coordinate list, and its area, its vertices and
every predicate read that one outline. A shape that also carried its tree would
be the same shape written twice, and the two writings could disagree — the tree
recompiled later by another shapely version, say. The tree the composer edits
therefore stays in the browser; what the engine files is the outline it measured.

The polygon is built from the domain's own helpers (arena_from_parts, polygonal,
CustomPolygon) and shapely, never from hand-written geometry.
"""

from __future__ import annotations

from collections.abc import Sequence

import shapely
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from paper_obs.domain.arena import ArenaPart, arena_from_parts, polygonal
from paper_obs.domain.serde import JSON
from paper_obs.domain.shapes import CustomPolygon
from paper_obs.geometry.view import path_data


def compose_shape(parts: Sequence[ArenaPart]) -> JSON:
    """Compile a stack of parts into a packable shape and its picture.

    The stack is read exactly like an arena's — the first part is the base, every
    later one applies its operation to what came before — so the composer and the
    arena editor speak the same language. The answer carries the shape document,
    the outline as SVG path data, the bounds, the area, and the shape's own
    one-line description.

    The path and the bounds are read from the *shape*, not from the composed
    frame: CustomPolygon recentres its outline on the anchor a placement uses,
    and a preview built from the composed frame would sit where a placement never
    draws it.

    Raises ValueError in the domain's words for a stack that describes nothing
    usable as a shape: empty, not a single connected outline, holed, or of zero
    area.
    """
    if not parts:
        raise ValueError("a composed shape needs at least one part")
    if parts[0].op != "base":
        raise ValueError(f"the first shape part must be the base, got {parts[0].op!r}")
    if any(item.op == "base" for item in parts[1:]):
        raise ValueError("only the first shape part may be the base")
    node = arena_from_parts(parts)
    context = f"shape ({node.describe()})"
    geometry = polygonal(node.build(), context=context)
    region = _single_outline(geometry, context=context)
    if region.area <= 0.0:
        raise ValueError(f"{context}: the operation produced a region of zero area")
    shape = CustomPolygon(
        points=tuple((float(x), float(y)) for x, y in region.exterior.coords[:-1])
    )
    return {
        "shape": shape.to_dict(),
        "path": path_data(shape.footprint(1.0)),
        "bounds": list(shape.bounding_box(1.0)),
        "area": shape.area(1.0),
        "summary": shape.describe(),
    }


def _single_outline(geometry: BaseGeometry, *, context: str) -> Polygon:
    """Return the one simple polygon the geometry is, or refuse in the domain's words.

    A packable shape is a single outline: CustomPolygon stores one ring of
    vertices, so a result made of several islands could not be written down and an
    interior hole would be silently filled. Both are refused here, by name, rather
    than flattened into a shape nobody drew.
    """
    pieces = shapely.get_parts(geometry)
    if len(pieces) != 1 or pieces[0].geom_type != "Polygon":
        raise ValueError(
            f"{context}: the parts are disjoint; a packable shape is a single connected outline"
        )
    polygon = pieces[0]
    if polygon.interiors:
        raise ValueError(
            f"{context}: the result has a hole; a packable shape is a single outline without holes"
        )
    return polygon


__all__ = ["compose_shape"]
