"""Small, optional contact guides for a manual translation.

The caller supplies a distance in world units, normally converted from a few
screen pixels. Only a valid packing can be guided, and every proposed correction
is validated again by the same engine that judges ordinary placements. A guide
never repairs an invalid placement or drags a shape to an arbitrary coordinate.
"""

from __future__ import annotations

import math
from dataclasses import replace

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points

from paper_obs.domain.candidate import Candidate
from paper_obs.domain.problem import Problem

from .facts import ShapeInstance, build_facts
from .validation import evaluate_constraints


def snap_to_contact(
    problem: Problem, candidate: Candidate, shape_ids: tuple[str, ...],
    max_distance: float, motion: tuple[float, float],
) -> Candidate:
    """Move a selection at most ``max_distance`` world units onto a valid contact.

    Circles use their exact radius for the proposed gap. Curved arena walls and
    concave outlines use their compiled polygon for the nearest direction; the
    final validity decision still uses the engine's ordinary predicates. No
    correction is made for an invalid candidate, a missing contact constraint,
    or a correction that the judge would reject.
    """
    if not math.isfinite(max_distance) or max_distance < 0:
        raise ValueError("max_distance must be a finite nonnegative length")
    if len(motion) != 2 or not all(math.isfinite(value) for value in motion):
        raise ValueError("motion must be two finite world displacements")
    selected = set(shape_ids)
    if not selected or not selected.issubset(candidate.shape_ids):
        raise ValueError("the selection must name at least one placed shape")
    if max_distance == 0:
        return candidate
    facts = build_facts(problem, candidate)
    if not evaluate_constraints(facts).valid:
        return candidate

    constraints = {item.kind for item in problem.effective_constraints}
    moving = [item for item in facts.instances if item.shape_id in selected]
    suggestions: list[tuple[float, float, float]] = []
    for item in moving:
        if problem.arena is not None and "arena_containment" in constraints:
            correction = _toward_boundary(item, problem.arena.geometry.boundary)
            if correction is not None:
                suggestions.append(correction)
    if "non_overlap" in constraints:
        # Facts prunes distant pairs with bounding circles before any polygonal
        # nearest-point work. Only a selected/unselected pair can guide a group.
        for pair in facts.clearances(max_distance):
            if (pair.first in selected) == (pair.second in selected):
                continue
            source = pair.first if pair.first in selected else pair.second
            target = pair.second if pair.first in selected else pair.first
            correction = _toward_shape(facts.by_id[source], facts.by_id[target])
            if correction is not None:
                suggestions.append(correction)

    for distance, dx, dy in sorted(suggestions):
        # A subnanometre correction is numerical dust, not a visual guide.
        if not 1e-9 < distance <= max_distance:
            continue
        # A person pulling a touching shape away must never be dragged back to
        # the old contact. Only finish movement *toward* a nearby constraint.
        if dx * motion[0] + dy * motion[1] <= 0:
            continue
        translated = replace(candidate, placements=tuple(
            replace(item, x=item.x + dx, y=item.y + dy)
            if item.shape_id in selected else item
            for item in candidate.placements
        ))
        if evaluate_constraints(build_facts(problem, translated)).valid:
            return translated
    return candidate


def _toward_boundary(item: ShapeInstance, boundary: BaseGeometry) -> tuple[float, float, float] | None:
    if item.is_circle:
        nearest = nearest_points(Point(item.center), boundary)[1]
        return _gap_vector(item.center, (nearest.x, nearest.y), item.inradius)
    if item.geometry is None:
        return None
    source, target = nearest_points(item.geometry, boundary)
    return _gap_vector((source.x, source.y), (target.x, target.y), 0.0)


def _toward_shape(moving: ShapeInstance, fixed: ShapeInstance) -> tuple[float, float, float] | None:
    if moving.is_circle and fixed.is_circle:
        return _gap_vector(moving.center, fixed.center, moving.inradius + fixed.inradius)
    if moving.is_circle:
        if fixed.geometry is None:
            return None
        nearest = nearest_points(Point(moving.center), fixed.geometry)[1]
        return _gap_vector(moving.center, (nearest.x, nearest.y), moving.inradius)
    if moving.geometry is None:
        return None
    if fixed.is_circle:
        nearest = nearest_points(moving.geometry, Point(fixed.center))[0]
        return _gap_vector((nearest.x, nearest.y), fixed.center, fixed.inradius)
    if fixed.geometry is None:
        return None
    source, target = nearest_points(moving.geometry, fixed.geometry)
    return _gap_vector((source.x, source.y), (target.x, target.y), 0.0)


def _gap_vector(
    source: tuple[float, float], target: tuple[float, float], radius: float
) -> tuple[float, float, float] | None:
    vx, vy = target[0] - source[0], target[1] - source[1]
    centre_distance = math.hypot(vx, vy)
    gap = centre_distance - radius
    if centre_distance <= 0 or gap <= 0:
        return None
    return gap, vx * gap / centre_distance, vy * gap / centre_distance
