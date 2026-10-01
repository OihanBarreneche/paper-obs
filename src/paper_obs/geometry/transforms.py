"""Interactive transformations of a candidate, judged separately by the engine."""

from __future__ import annotations

from dataclasses import replace
from math import cos, radians, sin

from paper_obs.domain.candidate import Candidate
from paper_obs.domain.problem import Problem

from .view import build_view


def rotate_selection(
    problem: Problem, candidate: Candidate, shape_ids: tuple[str, ...], degrees: float
) -> Candidate:
    """Rotate selected placements around their visual bounding box centre.

    The engine supplies the drawn corners and radii; the browser only names the
    selection and the angle of the gesture. Invalid results remain candidates for
    the ordinary evaluator to judge.
    """
    selected = set(shape_ids)
    if not selected or not selected.issubset(candidate.shape_ids):
        raise ValueError("the selection must name at least one placed shape")
    primitives = [
        shape for shape in build_view(problem, candidate, with_violations=False).shapes
        if shape.shape_id in selected
    ]
    if len(primitives) == 1:
        pivot = primitives[0].center
    else:
        x_values: list[float] = []
        y_values: list[float] = []
        for shape in primitives:
            if shape.kind == "circle":
                radius = shape.radius or 0.0
                x_values.extend((shape.center[0] - radius, shape.center[0] + radius))
                y_values.extend((shape.center[1] - radius, shape.center[1] + radius))
            else:
                x_values.extend(point[0] for point in shape.points)
                y_values.extend(point[1] for point in shape.points)
        pivot = ((min(x_values) + max(x_values)) / 2, (min(y_values) + max(y_values)) / 2)
    angle = radians(degrees)
    dx_cos, dx_sin = cos(angle), sin(angle)
    placements = []
    for placement in candidate.placements:
        if placement.shape_id not in selected:
            placements.append(placement)
            continue
        dx, dy = placement.x - pivot[0], placement.y - pivot[1]
        placements.append(replace(
            placement,
            x=pivot[0] + dx * dx_cos - dy * dx_sin,
            y=pivot[1] + dx * dx_sin + dy * dx_cos,
            rotation=placement.rotation + degrees,
        ))
    return candidate.derive(placements=placements, origin="manual")
