"""Search intervals for the common scale.

A search needs to know where to look. This module derives an interval from the
problem alone, with one clearly stated piece of reasoning per bound and no
pretence of optimality: nothing here may ever be used to decide validity, only
to size a search or to lay out a slider in the UI.

A maximizing packing reads the interval one way round: the upper bound is the
perfect-packing bound — the scale at which the shapes would exactly fill the
arena if they could tile it — which no real packing ever reaches, and the lower
bound is a floor chosen by the caller, because "as small as you like" is not a
search interval. A *covering* reads it the other way round and derives both ends
from its own question: below the area bound no covering is possible at all, and
above the row-of-discs scale one is certain. A *total-perimeter* family fixes the
common scale at one and reads the interval as the range of a single copy's local
size, because that is the degree of freedom it searches. Every interval is finite,
cheap and honest, and none is ever a validity decision.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from paper_obs.domain.objectives import CoverRegion, MaximizeScale, MaximizeTotalPerimeter
from paper_obs.domain.problem import Problem


@dataclass(frozen=True)
class ScaleBounds:
    """An interval of common scales worth exploring."""

    low: float
    high: float
    rationale: str


def scale_bounds(problem: Problem, *, floor_ratio: float = 64.0) -> ScaleBounds:
    """Return the interval of common scales to explore for ``problem``.

    ``floor_ratio`` sets the low bound as a fraction of the high bound. It is a
    convention, not a result: a search that needs to go below it can, it just
    has to say so.
    """
    objective = problem.objective
    # The total-perimeter branch comes before the preset short-circuit on purpose.
    # That family fixes the *common* scale at 1 while each copy carries its own
    # local scale, so "the interval of the common scale" would be the degenerate
    # [1, 1]: it would describe the one number the objective already pins and hide
    # the size variation the family is about (and that its initialiser searches).
    # The interval returned here is therefore the one of a *local* size.
    if isinstance(objective, MaximizeTotalPerimeter):
        return _total_perimeter_bounds(problem, objective, floor_ratio)
    preset = objective.preset_scale()
    if preset is not None:
        return ScaleBounds(
            low=preset,
            high=preset,
            rationale="the objective fixes the common scale",
        )
    if isinstance(objective, MaximizeScale):
        area_bound = (problem.arena.area / (objective.count * problem.shape.area(1.0))) ** 0.5
        return ScaleBounds(
            low=max(area_bound / floor_ratio, 1e-9),
            high=area_bound,
            rationale=(
                f"{objective.count} shapes of area {problem.shape.area(1.0):.6g} at scale 1 cannot "
                f"exceed the arena area {problem.arena.area:.6g}"
            ),
        )
    if isinstance(objective, CoverRegion):
        return _covering_bounds(problem, objective)
    # A family whose scale varies must extend this function: there is no honest
    # interval to return without a reasoning about that family's own geometry.
    raise TypeError(f"no scale bounds known for objective {type(objective).__name__}")


def _total_perimeter_bounds(
    problem: Problem, objective: MaximizeTotalPerimeter, floor_ratio: float
) -> ScaleBounds:
    """Return the sizes one copy of a total-perimeter family may be given.

    The family's copies are of independent sizes, so the honest interval is over a
    single copy's local scale, not over the common scale the objective fixes at 1.
    Both ends are derived, and neither is ever a validity decision.

    *High*: the whole outline of a copy lies in the arena's bounding box, so its
    distance from its own anchor -- its circumradius -- cannot exceed half of the
    box's smaller side. Dividing that by the shape's circumradius at scale 1 turns
    the box into a bound on the local scale. It is tight on the disc and the square
    arenas and an over-estimate on a pointed one, which is what a search bound
    should be.

    *Low* is the same floor of convenience the maximizing packing uses, a
    ``floor_ratio``-th of the high end: a copy may be arbitrarily small, and an
    interval has to stop somewhere.

    ``objective`` is read only so the branch cannot be taken for another family; the
    arena is never ``None`` for an objective that packs into one, because the domain
    refuses that pair.
    """
    del objective  # the branch is the reason this function exists, not a parameter
    arena = problem.arena
    assert arena is not None  # a packing objective always declares its region
    shape = problem.shape
    width, height = arena.size
    circumradius = shape.circumradius(1.0)
    high = 0.5 * min(width, height) / circumradius if circumradius > 0.0 else 1.0
    low = max(high / floor_ratio, 1e-9)
    return ScaleBounds(
        low=low,
        high=high,
        rationale=(
            f"a copy whose circumradius {circumradius:.6g} at scale 1 exceeds half the "
            f"arena's smaller side ({0.5 * min(width, height):.6g}) cannot lie in the "
            f"arena's own bounding box, so a local scale above {high:.6g} cannot be "
            f"contained; the low end is the lab's floor of convenience, "
            f"{1.0 / floor_ratio:g} of the high end"
        ),
    )


def _covering_bounds(problem: Problem, objective: CoverRegion) -> ScaleBounds:
    """Return the scales a covering is worth searching, from two constructions.

    *Low* is the area bound: the union of the copies cannot be larger than the sum
    of their areas, so no arrangement covers the arena below the scale at which
    their total area equals the arena's. A covering therefore cannot be valid below
    this number, which makes it a genuine lower end and not a floor of convenience.

    *High* is a scale at which a covering is certain, built from the arena's own
    bounding box. Divide the box into ``count`` columns and put one copy in each:
    every shape contains its inscribed disc of radius ``inradius(scale)``, so the
    copies cover the box once that disc reaches half of a column's diagonal
    (``0.5 * hypot(width/count, height)``). Dividing by the shape's own inscribed
    radius at scale 1 gives the scale. The construction is crude — one row of
    tall columns — but it is a proof that a covering exists there, which is what
    an upper end has to be for a family that minimises its scale.

    The two bounds cannot cross: a shape contains its inscribed disc, so its area
    is at least ``pi * inradius(1)**2``, and the ratio ``high / low`` is therefore
    never below ``sqrt(pi / 2)``. The guard below is only for a degenerate shape
    whose inscribed radius is zero; it widens the interval instead of hiding a
    family the engine can still judge.
    """
    arena = problem.arena
    count = objective.count
    shape = problem.shape
    unit_area = shape.area(1.0)
    low = math.sqrt(arena.area / (count * unit_area))
    box_width, box_height = arena.size
    inscribed = 0.5 * math.hypot(box_width / count, box_height)
    inscribed_radius = shape.inradius(1.0)
    high = inscribed / inscribed_radius if inscribed_radius > 0.0 else low * 2.0
    if high <= low:
        high = low * 2.0
    return ScaleBounds(
        low=low,
        high=high,
        rationale=(
            f"{count} shapes of area {unit_area:.6g} at scale 1 cannot cover the arena area "
            f"{arena.area:.6g} below scale {low:.6g}, where their total area is smaller than "
            f"the region; a row of {count} inscribed discs of radius {inscribed:.6g} covers the "
            f"arena's bounding box, so scale {high:.6g} certainly covers"
        ),
    )


__all__ = ["ScaleBounds", "scale_bounds"]
