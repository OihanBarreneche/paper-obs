"""Submission SVGs in world coordinates, converted to the source image frame."""
from __future__ import annotations

import colorsys

from shapely import affinity
from shapely.geometry import Polygon

from paper_obs.domain.candidate import Candidate
from paper_obs.domain.problem import Problem
from paper_obs.geometry.facts import build_facts


def submission_svg(problem: Problem, candidate: Candidate, style: dict, rotate: float = 0.0) -> str:
    """Draw in the source's pixel frame; ``rotate`` is counter-clockwise degrees.

    Resolve measured arenas through the engine's facts. Coverings frame protruding
    copies too; packing outlines fill the frame with one-pixel boundary strokes.
    """
    width, height = style["size"]
    resolved_arena = problem.arena if problem.arena is not None else build_facts(problem, candidate).arena
    region = resolved_arena.geometry
    arena = [affinity.rotate(part, rotate, origin=(0, 0))
             for part in getattr(region, "geoms", [region])]
    copies = [affinity.rotate(affinity.translate(problem.shape.footprint(item.resolved_scale(candidate.scale),
                                                                          item.rotation), item.x, item.y),
                              rotate, origin=(0, 0)) for item in candidate.placements]
    framed = arena + copies if problem.objective.kind in {"cover_region", "maximize_covered_size"} else arena
    boxes = [shape.bounds for shape in framed]
    left, bottom = min(box[0] for box in boxes), min(box[1] for box in boxes)
    right, top = max(box[2] for box in boxes), max(box[3] for box in boxes)
    # A one-pixel line centred half a pixel in from the border fills the picture's outer pixels.
    zoom = min((width - 1) / (right - left), (height - 1) / (top - bottom))
    dx = (width - zoom * (right - left)) / 2 - zoom * left
    dy = (height + zoom * (top - bottom)) / 2 + zoom * bottom

    def outline(shape: Polygon) -> str:
        return " ".join("M" + " L".join(f"{dx + zoom * x:.3f},{dy - zoom * y:.3f}" for x, y in ring.coords[:-1]) + " Z"
                        for ring in (shape.exterior, *shape.interiors))

    def colour(rgb) -> str:
        return "none" if rgb is None else "#%02x%02x%02x" % tuple(rgb)

    stroke = f'stroke="{colour(style["outline"])}" stroke-width="1"'
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
             f'shape-rendering="{"crispEdges" if style["crisp"] else "geometricPrecision"}">',
             f'<rect width="{width}" height="{height}" fill="{colour(style["outside"])}"/>']
    lines += [f'<path d="{outline(part)}" fill="{colour(style["inside"])}" fill-rule="evenodd" {stroke}/>' for part in arena]
    sizes = [item.resolved_scale(candidate.scale) for item in candidate.placements]
    high = max(sizes)
    for shape, size in zip(copies, sizes):
        fill = style["fill"]
        if style.get("rainbow"):
            # Use a zero-based size range: two almost equal sizes must stay
            # almost the same colour even if they are this figure's extremes.
            fraction = size / high
            fill = tuple(round(channel * 255) for channel in colorsys.hsv_to_rgb(0.75 * (1 - fraction), 1, 1))
        lines.append(f'<path d="{outline(shape)}" fill="{colour(fill)}" {stroke}/>')
    return "\n".join(lines + ["</svg>", ""])
