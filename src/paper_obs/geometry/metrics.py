"""Descriptive numbers attached to a candidate.

Metrics never decide anything: they describe a packing for a human, a plot or a
prompt. They are kept in one place, and small, because the objective score alone
says nothing about *why* a candidate is good — an empty arena and a packed one
can share a score, a density cannot.
"""

from __future__ import annotations

import math

from shapely.ops import polylabel

from paper_obs.domain.arena import Arena, Disk, RegularNGon, Rotate, Translate
from paper_obs.domain.objectives import CoverRegion, MaximizeScale

from .facts import (
    CONTACT_TOLERANCE,
    POLYLABEL_TOLERANCE,
    Facts,
    outline_to_arena_distance,
    polygonal,
)

#: Relative size below which a filled arena is the same area as the arena. The
#: areas are sums of shapely results, so a perfect tiling lands a quadrillionth of
#: a square away from the arena's own area and reports a void of ``-1.4e-14`` and a
#: density of ``1.0000000000000002``. This is a **descriptive** tolerance: nothing
#: is decided with it. It is relative because an arena of side 1 and one of side
#: 100 have different absolute noise, and it is far below any gap a person could
#: mean — a thousandth of a square unit in a hundred-unit arena is a hundred
#: thousand times larger.
AREA_NOISE = 1e-9

#: Name of the metric that reports the largest circle the copies actually contain.
#: It is descriptive, like every metric here: it changes no verdict, and a reader
#: compares it with the covering objective's promoted covered_size.
COVERED_CIRCLE = "covered_circle_radius"


def compute_metrics(facts: Facts, *, contact_tolerance: float = CONTACT_TOLERANCE) -> dict[str, float]:
    """Return the descriptive metrics of a candidate.

    ``density`` is the fraction of the arena area covered by shapes, which is the
    honest reading of "how full is this packing" for any shape family.
    ``boundary_contacts`` counts the shapes resting on the arena wall within
    ``contact_tolerance``, the signature of a boundary-driven arrangement.

    ``packed_area`` is the **sum of the shapes' own areas**, which is what "total
    area of placed shapes" means, and it is never negative. ``covered_area`` is the
    area of the arena the *union* of the footprints actually covers, and
    ``void_area`` the rest of the arena. The two readings differ whenever copies
    overlap or stick out -- which a covering does by definition -- and the void and
    the density are read from the union, never from that sum: an area is not a
    signed quantity, and a sum used as a covered area would report a negative void
    and a density above one on an arrangement the engine calls valid.

    The sizes of the shapes are summed too: total_scale is the sum of every
    placement's resolved scale and total_perimeter the sum of the outlines the
    engine builds, with max_scale and min_scale bounding the spread. They describe
    any arrangement and are the numbers the total-perimeter objective reads -- its
    promoted metric is total_scale, which for the reference collection's unit
    copies is the sum the source pages print.

    The measurements the engine took about a *derived* region are merged in
    unchanged, so a family that minimises its container reports the size of that
    container as an ordinary metric and every reader of metrics sees it.

    ``arena_area`` is the exact area of the arena's *declared* shape whenever that
    has a closed form -- a rectangle, a disc, an ellipse, a regular polygon -- and
    the compiled outline's area only for a boolean composition of arcs, which has
    none. The void is the union-based reading of ``Facts.uncovered_area()``, capped
    at that area: the compiled arena is a hair larger than the ideal curve it
    approximates, and without the cap an empty candidate on a disc would report a
    negative covered area. ``covered_area`` and ``void_area`` therefore always sum
    to ``arena_area``, neither is negative, and ``density`` never exceeds one.
    """
    arena_area = facts.arena.area
    # The sum of the shapes' own areas: honest by itself, and never the covered
    # area, because overlapping copies share area and summing them counts the
    # shared part twice. Keeping it under its own name is what lets a covering
    # report both numbers without either of them lying.
    packed_area = float(sum(instance.area for instance in facts.instances))
    if abs(packed_area - arena_area) <= AREA_NOISE * arena_area:
        # A perfect tiling lands a quadrillionth of a square short of the arena;
        # the sum of its own areas *is* the arena, and the snapped number is what a
        # reader of "total area of placed shapes" should be shown.
        packed_area = arena_area
    # What the arena actually has left uncovered is the union-based reading, and it
    # is what makes the void and the density non-negative whatever the arrangement.
    uncovered = facts.uncovered_area()
    if uncovered <= AREA_NOISE * arena_area:
        # A packing that fills the arena exactly *is* the arena: the union of a
        # perfect tiling lands a quadrillionth of a square short, and reporting that
        # as a void, with a density just under one, is arithmetic talking rather
        # than a fact about the packing. The void and the density are derived from
        # the snapped number, so the three agree with each other.
        uncovered = 0.0
    # Circumscribed disc outlines slightly overstate their union. The covered
    # area cannot exceed the exact sum of the copies' own areas, even when the
    # arena and copies are judged through those outlines.
    covered_area = min(packed_area, max(0.0, arena_area - uncovered))
    uncovered = arena_area - covered_area
    boundary_contacts = sum(
        1
        for instance in facts.instances
        if outline_to_arena_distance(instance, facts.arena) <= contact_tolerance
    )
    scales = [instance.scale for instance in facts.instances]
    shape = facts.problem.shape
    metrics = {
        "n_shapes": float(facts.candidate.n_shapes),
        # The sum of the shapes' own areas, then the union-based readings: the
        # covered area, the void and the density all come from the union, so no
        # area metric can be negative and no density can exceed one.
        "packed_area": packed_area,
        "covered_area": covered_area,
        "arena_area": arena_area,
        "void_area": uncovered,
        "density": covered_area / arena_area,
        "boundary_contacts": float(boundary_contacts),
        # The sizes of the copies, which describe any arrangement and are the
        # quantity the total-perimeter family scores.
        "total_scale": math.fsum(scales),
        "total_perimeter": math.fsum(shape.perimeter(scale) for scale in scales),
        "max_scale": max(scales, default=0.0),
        "min_scale": min(scales, default=0.0),
        **facts.container,
    }
    # Catalog pages often state the size of the smallest container, while the
    # engine optimizes copy scale in a fixed arena. Report the equivalent unscaled
    # size so the UI can compare the same units directly: the length the arena
    # declares (a tan's leg, an L's short side), or a regular polygon's own side.
    arena = facts.problem.arena
    if (isinstance(facts.problem.objective, MaximizeScale)
            and arena is not None
            and facts.candidate.scale > 0.0):
        length = arena.reference_length
        if length is None and isinstance(arena.shape, RegularNGon):
            length = 2.0 * arena.shape.circumradius * math.sin(math.pi / arena.shape.sides)
        if length is not None:
            metrics["equivalent_container_side"] = length / facts.candidate.scale
    covered = covered_circle_radius(facts)
    if covered is not None:
        metrics[COVERED_CIRCLE] = covered
    return metrics


def covered_circle_radius(facts: Facts) -> float | None:
    """Return the largest circle the copies actually contain, or None.

    For a covering whose target is a disc this is the quantity the source pages
    publish — "the largest circle covered by n unit squares" — read back from the
    arrangement rather than from the scale the objective claims. The region
    measured is the copies' union intersected with the target, and the circle is
    the largest one inside that region: shapely's pole of inaccessibility
    (polylabel) gives its centre, and the distance from that pole to the region's
    boundary gives its radius. The radius is divided by the candidate's common
    scale, so the number is expressed in the units of the source's *unit* copies
    and is directly comparable to the promoted covered_size. When the copies
    cover the target the two agree; while they do not, this is the honest
    progress towards it, defined even for an invalid candidate.

    Only a disc target is measured, because only then is the largest copy of the
    target's own family a circle. For a square or triangular target the largest
    inscribed square or triangle is a different and much harder optimisation —
    an orientation and a position to search, not a single pole — so no number is
    reported rather than a circle's radius passed off as the target's size. A
    family that is not a covering, or a target that is not a disc, gets no metric
    at all.

    The value is approximate, to the lab's descriptive tolerances: a disc
    footprint on this path is a circumscribed chord polygon
    (:data:`paper_obs.domain.tessellation.CHORD_COUNT` chords, a radius excess of
    :func:`paper_obs.domain.tessellation.chord_radius_relative_error`, 7.53e-5 at
    the default), and the pole search stops at POLYLABEL_TOLERANCE. Nothing here
    is ever a validity decision; an empty intersection reports nothing rather
    than zero. The union-based metrics are a different story: when the arena and
    every footprint are discs, ``Facts.uncovered_area`` -- and therefore
    ``void_area``, ``covered_area`` and ``density`` -- is closed form and carries
    no chord error at all.
    """
    if not isinstance(facts.problem.objective, CoverRegion):
        return None
    if not _circular_target(facts.problem.arena):
        return None
    scale = facts.candidate.scale
    if not scale > 0.0:
        return None
    region = polygonal(facts.arena.geometry.intersection(facts.shape_union()))
    if region is None:
        return None
    pole = polylabel(region, tolerance=POLYLABEL_TOLERANCE)
    return float(region.boundary.distance(pole)) / scale


def _circular_target(arena: Arena | None) -> bool:
    """Whether the declared arena is a disc, with or without its placement.

    A part is written as a translated (and possibly turned) primitive, so the
    wrappers are peeled before the leaf is read.
    """
    if arena is None:
        return False
    node = arena.shape
    while isinstance(node, (Translate, Rotate)):
        node = node.shape
    return isinstance(node, Disk)
