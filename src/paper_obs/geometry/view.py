"""The drawable form of a candidate: what a picture of it is made of.

Rendering and the user interface need the same thing, and neither of them may
recompute it: a list of primitives in *world* coordinates (a disc centre and
radius, a polygon's corners), the arena as an SVG path, the bounds to frame the
picture, and which shapes a violation names. :func:`build_view` produces exactly
that, once, from the engine's own facts, and both consumers read it:

* :func:`paper_obs.geometry.rendering.render_svg` serialises it to an SVG
  document;
* the HTTP API serialises :meth:`View.to_dict` to JSON, so a browser can draw and
  drag shapes without ever knowing that a disc has a radius of ``0.5 * scale``.

Keeping one producer for both is what prevents the UI from slowly growing a
second geometry engine of its own — the failure mode this project is built to
avoid.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import hypot

import shapely

from paper_obs.domain.arena import (
    Arena,
    ArenaPart,
    arena_parts,
)
from paper_obs.domain.candidate import Candidate
from paper_obs.domain.problem import Problem
from paper_obs.domain.shapes import RegularPolygon
from paper_obs.domain.serde import JSON

from .analysis import CandidateAnalysis
from .facts import Facts, build_facts
from .validation import Validation, evaluate_constraints


@dataclass(frozen=True)
class ShapePrimitive:
    """One placed shape, in the only form a drawing needs.

    ``kind`` is ``"circle"`` with a centre and a radius, or ``"polygon"`` with
    its corners. ``invalid`` says whether a violation names it, which is the only
    styling decision the view carries; ``color`` is the placement's own colour, or
    ``None`` for a shape the theme paints.
    """

    shape_id: str
    kind: str
    center: tuple[float, float]
    bounds: tuple[float, float, float, float]
    radius: float | None = None
    points: tuple[tuple[float, float], ...] = ()
    invalid: bool = False
    color: str | None = None
    turn_anchor: tuple[float, float] | None = None
    turn_direction: tuple[float, float] | None = None
    orientation_group: int = 0
    orientation_deg: float = 0.0

    def to_dict(self) -> JSON:
        """Return the JSON representation, with the fields of its own kind only."""
        data: JSON = {
            "shape_id": self.shape_id,
            "kind": self.kind,
            "center": list(self.center),
            "bounds": list(self.bounds),
            "invalid": self.invalid,
            # Always written: the view is not a stored document, and a canvas
            # reads the colour of every shape from this one place.
            "color": self.color,
            "orientation_group": self.orientation_group,
            "orientation_deg": self.orientation_deg,
        }
        if self.radius is not None:
            data["radius"] = self.radius
        if self.points:
            data["points"] = [list(point) for point in self.points]
        if self.turn_anchor is not None and self.turn_direction is not None:
            data["turn_anchor"] = list(self.turn_anchor)
            data["turn_direction"] = list(self.turn_direction)
        return data


@dataclass(frozen=True)
class VoidBox:
    """One empty region, reduced to the bounding box a picture can outline."""

    area: float
    bounds: tuple[float, float, float, float]

    def to_dict(self) -> JSON:
        """Return the JSON representation."""
        return {"area": self.area, "bounds": list(self.bounds)}


@dataclass(frozen=True)
class ArenaPartView:
    """One primitive of a composite arena, in the form an editor can manipulate.

    ``params`` carries the primitive's own numbers and its ``kind``, so a form
    can render the right fields without knowing anything about arenas, and
    ``bounds`` is the primitive's own box, so a canvas can draw a drag handle
    without recomputing where the primitive ended up.

    ``path`` is the primitive's **own outline**, compiled by the engine, and it is
    what a canvas must draw, select and drag: ``bounds`` is a box around a disc,
    so grabbing it would move a square the user cannot see.

    ``angle`` is the turn the part carries, in degrees, about the origin of its own
    frame — so a client that gives the part back gives the engine the same shape it
    was handed, and a control that draws a turned part knows what it is turning.
    """

    index: int
    op: str
    label: str
    offset: tuple[float, float]
    bounds: tuple[float, float, float, float]
    path: str
    params: dict[str, object]
    angle: float = 0.0

    def to_dict(self) -> JSON:
        """Return the JSON representation."""
        return {
            "index": self.index,
            "op": self.op,
            "label": self.label,
            "offset": list(self.offset),
            "bounds": list(self.bounds),
            "path": self.path,
            "params": self.params,
            "angle": self.angle,
        }


@dataclass(frozen=True)
class View:
    """Everything needed to draw a candidate, and nothing else."""

    problem_id: str
    candidate_id: str
    bounds: tuple[float, float, float, float]
    arena_path: str
    arena_bounds: tuple[float, float, float, float]
    shapes: tuple[ShapePrimitive, ...] = ()
    voids: tuple[VoidBox, ...] = ()
    arena_parts: tuple[ArenaPartView, ...] = ()
    editable_arena: bool = False
    arena_fixed_by_objective: bool = False
    """True when the objective owns its arena, so editing it would change the question.

    It is reported beside :attr:`editable_arena` so the interface can say *why*
    an arena is read-only: an arena that is not a stack of primitives and one the
    objective has fixed are both uneditable, for two different reasons.
    """
    union_path: str | None = None
    """The union of the shape footprints as SVG path data, present only on request.

    It is the engine's own union (:meth:`paper_obs.geometry.facts.Facts.shape_union`),
    never a browser-side merge, and it is omitted unless the caller asked for it,
    so a problem that never displays a covering pays nothing for it.
    """
    validation: Validation | None = None
    analysis: CandidateAnalysis | None = None
    frame_overflowing_shapes: bool = False

    @property
    def frame(self) -> tuple[float, float, float, float]:
        """Frame the arena and, for covering, every copy that may extend beyond it."""
        if not self.frame_overflowing_shapes or not self.shapes:
            return self.arena_bounds
        return (
            min(self.arena_bounds[0], *(shape.bounds[0] for shape in self.shapes)),
            min(self.arena_bounds[1], *(shape.bounds[1] for shape in self.shapes)),
            max(self.arena_bounds[2], *(shape.bounds[2] for shape in self.shapes)),
            max(self.arena_bounds[3], *(shape.bounds[3] for shape in self.shapes)),
        )

    def to_dict(self) -> JSON:
        """Return the JSON representation handed to the user interface."""
        data: JSON = {
            "problem_id": self.problem_id,
            "candidate_id": self.candidate_id,
            "arena": {
                "path": self.arena_path,
                "bounds": list(self.arena_bounds),
                "editable": self.editable_arena,
                "objective_fixed": self.arena_fixed_by_objective,
                "parts": [item.to_dict() for item in self.arena_parts],
            },
            "frame": list(self.frame),
            "shapes": [shape.to_dict() for shape in self.shapes],
        }
        if self.union_path is not None:
            data["union"] = {"path": self.union_path}
        if self.voids:
            data["voids"] = [void.to_dict() for void in self.voids]
        return data


def build_view(
    problem: Problem,
    candidate: Candidate,
    *,
    facts: Facts | None = None,
    with_violations: bool = True,
    with_voids: bool = False,
    with_union: bool = False,
    void_limit: int = 5,
) -> View:
    """Build the drawable form of a candidate, at most one geometry pass.

    The caller may hand over facts it already computed — the HTTP API evaluates
    and draws the same candidate in one request — and otherwise only what the
    requested overlays need is computed.

    with_union adds the outline of the union of the shape footprints. A
    covering's constraint has already built that union by the time a view is
    drawn, so the request costs the path serialisation and nothing else; a
    problem that does not ask for it carries no union at all.
    """
    needs_facts = with_violations or with_voids or with_union or facts is not None
    # A problem whose region is measured rather than declared always needs the
    # measurement: it is what the caller draws.
    if facts is None and (needs_facts or problem.arena is None):
        facts = build_facts(problem, candidate)
    validation = evaluate_constraints(facts) if facts is not None and with_violations else None
    analysis = None
    if facts is not None and with_voids:
        from .analysis import analyze_facts

        analysis = analyze_facts(facts, void_limit=void_limit)

    region = facts.arena if facts is not None else problem.arena
    if region is None:  # pragma: no cover - build_facts resolves it above
        raise ValueError(f"{problem.objective.kind} needs a region to draw")
    # A region the problem declares can be edited by the client; one the objective
    # measured from the arrangement cannot — the domain refuses the pair outright,
    # so advertising it would invite a gesture the engine then answers with a 400.
    parts = arena_part_views(region) if problem.arena is not None else ()
    violating = _violating_shape_ids(validation)
    return View(
        problem_id=problem.problem_id,
        candidate_id=candidate.candidate_id,
        bounds=region.bounds,
        arena_path=arena_path(region),
        arena_bounds=region.bounds,
        shapes=_shapes(problem, candidate, violating),
        voids=tuple(
            VoidBox(area=void.area, bounds=void.bounds) for void in (analysis.voids if analysis else ())
        ),
        arena_parts=parts,
        editable_arena=bool(parts) and not problem.objective.arena_is_fixed,
        arena_fixed_by_objective=problem.objective.arena_is_fixed,
        union_path=path_data(facts.shape_union()) if with_union and facts is not None else None,
        validation=validation,
        analysis=analysis,
        frame_overflowing_shapes=problem.objective.kind in {"cover_region", "maximize_covered_size"},
    )


def arena_path(arena: Arena) -> str:
    """Return the arena outline as SVG path data, holes included."""
    return path_data(arena.geometry)


def arena_part_views(arena: Arena) -> tuple[ArenaPartView, ...]:
    """Return the editable parts of an arena, or nothing when it has none.

    An arena an editor cannot describe — a tree that is not a stack of
    primitives — simply yields no parts, and the interface shows the compiled
    outline without pretending it can be edited.
    """
    parts = arena_parts(arena.shape)
    if parts is None:
        return ()
    views = []
    for index, item in enumerate(parts):
        # Built once: the box and the outline come from the same geometry, and a
        # composite arena is recompiled at every edit of its stack.
        geometry = item.shape.build()
        views.append(
            ArenaPartView(
                index=index,
                op=item.op,
                label=item.primitive.describe(),
                offset=item.offset,
                bounds=tuple(float(value) for value in geometry.bounds),
                path=path_data(geometry),
                params=_part_params(item.primitive),
                angle=item.angle,
            )
        )
    return tuple(views)


def _part_params(primitive) -> dict[str, object]:
    """Return the numbers of one primitive, tagged with its kind.

    The domain serialises a type as ``type``; the interface reads ``kind``, the
    word it uses everywhere else for a discriminated union.
    """
    data = dict(primitive.to_dict())
    data["kind"] = data.pop("type")
    return data





def path_data(geometry) -> str:
    """Return the SVG path data of a polygonal geometry.

    Interior rings are emitted as ordinary sub-paths, to be filled with the
    even-odd rule: a hole is then a hole whatever winding order shapely
    produced.
    """
    commands = []
    for polygon in shapely.get_parts(geometry):
        if polygon.geom_type != "Polygon":
            continue
        commands.append(_ring_path(polygon.exterior.coords))
        commands.extend(_ring_path(ring.coords) for ring in polygon.interiors)
    return " ".join(commands)


def _ring_path(coordinates) -> str:
    """Return the SVG path commands of one closed ring."""
    points = list(coordinates)
    commands = [f"M {_number(points[0][0])} {_number(points[0][1])}"]
    commands.extend(f"L {_number(x)} {_number(y)}" for x, y in points[1:-1])
    commands.append("Z")
    return " ".join(commands)


def _shapes(
    problem: Problem, candidate: Candidate, violating: frozenset[str]
) -> tuple[ShapePrimitive, ...]:
    """Return the primitive of every placed shape, in placement order."""
    shape = problem.shape
    period = 360.0 / shape.sides if isinstance(shape, RegularPolygon) else 360.0
    # A regular polygon looks identical after one symmetry period; a circle has no angle.
    orientations = [0.0 if shape.is_circle else round(placement.rotation % period, 1)
                    for placement in candidate.placements]
    orientations = [0.0 if angle >= period - 0.05 else angle for angle in orientations]
    groups = {angle: index for index, angle in enumerate(sorted(set(orientations)))}
    representatives: dict[float, float] = {}
    for placement, angle in zip(candidate.placements, orientations):
        raw_angle = placement.rotation % period
        representatives.setdefault(
            angle, 0.0 if angle == 0 else (raw_angle if raw_angle <= period / 2 else raw_angle - period)
        )
    primitives = []
    for placement, angle in zip(candidate.placements, orientations):
        scale = placement.resolved_scale(candidate.scale)
        invalid = placement.shape_id in violating
        if shape.is_circle:
            radius = shape.inradius(scale)
            primitives.append(
                ShapePrimitive(
                    shape_id=placement.shape_id,
                    kind="circle",
                    center=(placement.x, placement.y),
                    bounds=(placement.x - radius, placement.y - radius,
                            placement.x + radius, placement.y + radius),
                    radius=radius,
                    turn_anchor=(placement.x + radius, placement.y),
                    turn_direction=(1.0, 0.0),
                    invalid=invalid,
                    color=placement.color,
                    orientation_group=groups[angle],
                    orientation_deg=representatives[angle],
                )
            )
            continue
        corners = shape.vertices(scale, placement.rotation) + (placement.x, placement.y)
        points = tuple((float(x), float(y)) for x, y in corners)
        bounds = (min(x for x, _ in points), min(y for _, y in points),
                  max(x for x, _ in points), max(y for _, y in points))
        # The handle belongs to a face, even when the polygon is rotated.
        midpoints = [
            ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            for a, b in zip(points, points[1:] + points[:1])
        ]
        anchor = max(midpoints, key=lambda point: point[0])
        direction = (anchor[0] - placement.x, anchor[1] - placement.y)
        length = hypot(*direction)
        direction = (direction[0] / length, direction[1] / length) if length else (1.0, 0.0)
        primitives.append(
            ShapePrimitive(
                shape_id=placement.shape_id,
                kind="polygon",
                center=(placement.x, placement.y),
                bounds=bounds,
                points=points,
                turn_anchor=anchor,
                turn_direction=direction,
                invalid=invalid,
                color=placement.color,
                orientation_group=groups[angle],
                orientation_deg=representatives[angle],
            )
        )
    return tuple(primitives)


def _violating_shape_ids(validation: Validation | None) -> frozenset[str]:
    """Return the shapes named by any violation, so they can be highlighted."""
    if validation is None:
        return frozenset()
    return frozenset(
        shape_id for violation in validation.violations for shape_id in violation.shape_ids
    )


def _number(value: float) -> str:
    """Format a coordinate compactly, with four significant digits."""
    return f"{float(value):.4g}"


__all__ = [
    "ArenaPartView",
    "ShapePrimitive",
    "View",
    "VoidBox",
    "arena_part_views",
    "arena_path",
    "build_view",
    "path_data",
]
