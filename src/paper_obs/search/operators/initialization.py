"""Initialization operators: cheap, deterministic ways to fill an arena.

An operator *proposes*, the engine *judges*. None of these functions decides
whether a candidate is valid: they build placements, hand them to the engine,
and keep what fits.

They all share the same construction: lay shapes out inside the arena, where the
arithmetic is trivial, then let the engine say which of them are actually inside
the region and free of each other. That single rule is what makes one operator
work on a rectangle, a disc and a composite arena with holes without a special
case per arena — and it is why an operator can never disagree with the validator
about what "fitting" means.

A fixed-scale objective — a counting family — is filled in the bounding box,
where the last rows may be partial. A free-scale family on a fixed arena needs
two more decisions, and both are taken from the arena itself rather than from its
bounding box: *where* to anchor the lattice (a small deterministic set of the
region's interior points — its deepest one, and the quarter points that catch the
corner of an L or the right angle of a tan) and *how large* to make it (a descent
from the tight lattice, not a bracket of a few widths). The bounding box is only
ever the outer frame of that search; the engine still says which copies fit.

Randomness always goes through an explicit numpy generator, seeded from the
problem by default, so a run can be replayed exactly from its JSON file. The
anchor search is deterministic on its own, so it needs no draw and adds none.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator

import numpy as np

from paper_obs.domain.arena import Arena
from paper_obs.domain.candidate import Candidate, new_candidate_id
from paper_obs.domain.constraints import ArenaCovered
from paper_obs.domain.objectives import CoverRegion
from paper_obs.domain.placement import Placement
from paper_obs.domain.problem import Problem

from paper_obs.geometry.bounds import ScaleBounds, scale_bounds
from paper_obs.geometry.facts import build_facts

#: How far below the naive scale the shrink search is allowed to look.
SHRINK_FACTOR = 4.0

#: Halvings of the shrink bracket. Twelve puts the retained scale within a
#: thousandth of the largest that fits, for a dozen engine calls.
SHRINK_ATTEMPTS = 12

#: Relative gap left between the cells of a *concave* outline's lattice. A lattice
#: puts equal cells side by side, so the copies of a concave outline share a
#: boundary; the engine resolves that exact contact through its polygon-path
#: fallback, where a shared edge can be read as a hair of overlap and a copy is
#: dropped for a reason no arrangement caused. Separating the cells by a
#: millionth of a cell makes every copy strictly disjoint, so the verdict the
#: search reads back is the one the arrangement earned. A convex or circular
#: outline is left at exact contact: its predicates are exact, and a tileable
#: instance must still reach density one.
CONCAVE_SEPARATION = 1e-6

#: Local scale of the one large copy of a varied start, relative to the others.
#: That family's degree of freedom is each copy's own size, so its start uses it
#: rather than a lattice of equals.
VARIED_LARGE_RATIO = 2.0

#: Relative gap left between the cells of a varied start. The cells are disjoint by
#: construction, and this keeps two cell walls a hair apart on the polygon path,
#: exactly as CONCAVE_SEPARATION does for a lattice of equal cells.
VARIED_SEPARATION = 1e-6

#: Doublings that search for the largest factor the engine still contains, and
#: bisections that close on it. The construction cannot overlap at any factor, so
#: containment is the only question the engine is asked -- about two dozen
#: judgements per start, which is the price of a start that uses the whole arena
#: instead of only its inscribed disc.
VARIED_FIT_DOUBLINGS = 12
VARIED_FIT_ATTEMPTS = 20

#: Halvings allowed while descending from the tight lattice to the first scale
#: that holds the requested count. Each one halves the remaining interval, so the
#: descent covers any factor between the two down to the last bit of a double.
DESCENT_HALVINGS = 60

#: Bisections between the largest scale that fits and the one just above it.
BISECTION_ATTEMPTS = 40

#: Samples per side of the coarse sweep that seeds the deepest-point search.
COARSE_SAMPLES = 8

#: Refinement rounds of the deepest-point hill climb, each halving the step.
REFINEMENT_ROUNDS = 6

#: How far above the covering bound's own scale its construction may be grown, and
#: by what factor, before the operator gives up. The bound is proved on the *ideal*
#: inscribed disc, while the engine compiles the arena and every disc footprint
#: from chords: the construction can land a hair short, and these steps carry it
#: over that hair without ever asserting the result valid.
COVER_GROW_FACTOR = 1.5
COVER_GROW_STEPS = 12

#: Bisections that close on the smallest scale at which one covering arrangement is
#: still judged to cover. Coverage grows with the scale, so the frontier is a
#: single number and the bracket is the interval `scale_bounds` already derived.
COVER_SHRINK_ATTEMPTS = 30

#: A covering pair has one degree of freedom -- how far its two copies slide
#: towards each other -- and the golden section searches it on the engine's own
#: verdict. The pair is only a candidate: the row, the grid and the stack are
#: judged beside it, and the smallest scale the engine accepts wins.
COVER_PAIR_ATTEMPTS = 16
COVER_PAIR_GOLDEN = (math.sqrt(5.0) - 1.0) / 2.0
COVER_PAIR_ANGLES = (0.0, 45.0)

Layout = Callable[[float], list[Placement]]

#: A covering arrangement: the placements for one scale, which the fit search then
#: reads at another. Only the candidate's common scale changes between probes.
CoverLayout = Callable[[], list[Placement]]


def grid_initialize(
    problem: Problem,
    *,
    scale: float | None = None,
    count: int | None = None,
    origin: str = "grid",
) -> Candidate:
    """Place the shapes on an axis-aligned grid.

    With an explicit scale, the grid tiles the bounding box at that scale and the
    last rows can be partial: this is the fill mode used by a fixed-scale
    objective, where the question is how many shapes fit rather than how big they
    can be. A fixed-count objective whose own scale is fixed takes the same road:
    its scale is not a free variable to search, so the lattice is laid at that
    scale and the engine keeps what fits.

    With no explicit scale — a fixed-count, free-scale family on a declared arena
    — the grid is made as large as the arena allows for the count: the rows and
    columns are balanced to waste the least room, the lattice is anchored on the
    arena's deepest interior point rather than on its bounding-box centre, and the
    scale is searched downward from the tight lattice until the engine keeps the
    requested count. The anchor and the scale are the two decisions a pointed or
    non-convex arena makes for the initialiser, and both are read from the arena's
    own geometry.
    """
    target = count if count is not None else problem.objective.preset_count()
    box = _bounding_box(problem)
    cell_width, cell_height = _unit_cell(problem)

    if target is None or scale is not None:
        start = scale if scale is not None else _preset_or_bound(problem)

        def layout(value: float) -> list[Placement]:
            columns, rows = _fill_counts(box, cell_width * value, cell_height * value)
            return _grid_placements(
                problem.draft_region, columns, rows, cell_width * value, cell_height * value
            )

        return _place(problem, layout, start, target=target, origin=origin)

    preset = problem.objective.preset_scale()
    if preset is not None:
        columns, rows = _balanced_shape(target, box, cell_width, cell_height)

        def layout(value: float) -> list[Placement]:
            return _balanced_placements(
                problem.draft_region, columns, rows, target, cell_width * value, cell_height * value
            )

        return _place(problem, layout, preset, target=target, origin=origin)

    return _anchored_lattice(problem, target, cell_width, cell_height, origin=origin)


def staggered_initialize(
    problem: Problem,
    *,
    scale: float | None = None,
    count: int | None = None,
    origin: str = "staggered",
) -> Candidate:
    """Place discs on a staggered (hexagonal) lattice.

    Rows are offset by half a spacing and separated by a spacing times
    sqrt(3) / 2, which is exactly the distance at which a disc touches its two
    neighbours of the row above: the densest local arrangement of equal discs.

    Only defined for discs. A staggered lattice of convex polygons needs the
    offset geometry of the specific family, which the MVP does not implement —
    use grid_initialize instead, where staggering buys nothing anyway.
    """
    if not problem.shape.is_circle:
        raise ValueError(
            f"a staggered lattice is only defined for discs, {problem.shape.name} was given; "
            "use grid_initialize instead"
        )
    target = count if count is not None else problem.objective.preset_count()
    box = _bounding_box(problem)
    diameter = problem.shape.natural_size
    row_step = math.sqrt(3.0) / 2.0 * diameter

    if target is not None and scale is None:
        start, rows, columns = _balanced_staggered_shape(box, diameter, row_step, target)
        preset = problem.objective.preset_scale()
        start = preset if preset is not None else start

        def layout(value: float) -> list[Placement]:
            return _staggered_placements(
                problem.draft_region,
                rows=rows,
                columns=columns,
                spacing=diameter * value,
                row_step=row_step * value,
                limit=target,
            )

    else:
        start = scale if scale is not None else _preset_or_bound(problem)

        def layout(value: float) -> list[Placement]:
            rows, columns = _staggered_fill_counts(box, diameter * value, row_step * value)
            return _staggered_placements(
                problem.draft_region,
                rows=rows,
                columns=columns,
                spacing=diameter * value,
                row_step=row_step * value,
                limit=target,
            )

    return _place(problem, layout, start, target=target, origin=origin)


def varied_initialize(
    problem: Problem,
    *,
    scale: float | None = None,
    count: int | None = None,
    origin: str = "varied",
) -> Candidate:
    """Place one large copy and the rest smaller, each at its own local scale.

    This is the start a total-perimeter family needs. Its copies are of
    independent sizes -- that is what makes the sum of the perimeters interesting
    -- and every other initialiser builds one common size, which for that family
    can only be the wrong answer. Here each placement carries a local scale
    (``Placement.scale``), so the common scale the objective fixes at 1 is left
    alone and the size variation lives on the copies.

    The construction is read from the arena, never asserted. The copies are laid at
    the centres of disjoint cells, each cell twice the copy's own circumradius, so
    they cannot overlap; the block is centred on the arena's deepest interior
    point, where a first factor keeps every circumcircle inside the largest disc
    the arena holds and so proves containment. The engine then grows that factor
    until it reports a copy outside, and bisects it back to the largest one it
    accepts, so the start uses as much of the arena as the engine allows. Nothing
    here calls the result valid: the engine still judges it. ``count`` defaults
    to the objective's own count and ``scale``, when given, is the candidate's
    common scale, which the objective may itself fix.

    The sizes are one large copy and ``count - 1`` equal smaller ones. The rows
    and the absolute size are chosen to maximise the total perimeter this
    construction can hold, so the start is the best this family of layouts can do
    rather than an arbitrary one.
    """
    target = count if count is not None else (problem.objective.preset_count() or 1)
    if target < 1:
        raise ValueError(f"a varied start needs at least one shape, got {target!r}")
    arena = problem.draft_region
    anchor = _deepest_point(arena)
    depth = arena.signed_distance(*anchor)
    if depth <= 0.0:
        # A region with no interior at its deepest point: there is no size to
        # derive, and the copies are returned piled on the anchor for the engine
        # to refuse rather than the operator inventing a containment.
        depth = 1e-9
    common = _preset_or_bound(problem) if scale is None else float(scale)
    profile = _varied_profile(target)
    rows, factor = _varied_layout(problem, profile, depth)
    factor = _varied_fit(problem, profile, anchor, rows, factor, common)
    placements = _varied_placements(problem, profile, anchor, rows, factor)
    return Candidate(
        candidate_id=new_candidate_id(),
        problem_id=problem.problem_id,
        scale=common,
        placements=tuple(placements),
        origin=origin,
    )


def _varied_profile(count: int) -> list[float]:
    """Return the relative sizes of a varied start: one large, the rest equal."""
    if count < 1:
        raise ValueError(f"a varied profile needs at least one shape, got {count!r}")
    return [1.0] if count == 1 else [VARIED_LARGE_RATIO] + [1.0] * (count - 1)


def _varied_cells(
    problem: Problem, profile: list[float], rows: int
) -> tuple[list[float], list[float]]:
    """Return the column widths and row heights of the varied grid, in profile units.

    A cell is twice the copy's circumradius at its relative size, a hair wider:
    the copy's whole outline lies in that circle, the circle is inscribed in its
    cell, and two disjoint cells therefore hold two disjoint copies -- whatever
    the outline, which is what lets one construction serve a disc, a square and a
    concave drawing without a case per family.
    """
    radius = problem.shape.circumradius(1.0) * (1.0 + VARIED_SEPARATION)
    columns = math.ceil(len(profile) / rows)
    widths = [0.0] * columns
    heights = [0.0] * rows
    for index, value in enumerate(profile):
        row, column = divmod(index, columns)
        widths[column] = max(widths[column], 2.0 * radius * value)
        heights[row] = max(heights[row], 2.0 * radius * value)
    return widths, heights


def _varied_centres(
    widths: list[float], heights: list[float], count: int
) -> list[tuple[float, float]]:
    """Return each copy's cell centre, relative to the centre of the block."""
    columns = len(widths)
    left = -sum(widths) / 2.0
    top = sum(heights) / 2.0
    x_prefix = [0.0]
    for width in widths:
        x_prefix.append(x_prefix[-1] + width)
    y_prefix = [0.0]
    for height in heights:
        y_prefix.append(y_prefix[-1] + height)
    centres: list[tuple[float, float]] = []
    for index in range(count):
        row, column = divmod(index, columns)
        centres.append(
            (
                left + x_prefix[column] + widths[column] / 2.0,
                top - y_prefix[row] - heights[row] / 2.0,
            )
        )
    return centres


def _varied_layout(
    problem: Problem, profile: list[float], depth: float
) -> tuple[int, float]:
    """Return the row count and the global factor of the best varied layout.

    The condition the factor enforces is the one fact the construction needs: a
    copy is contained when the distance from the arena's deepest point to its own
    anchor, plus its circumradius, does not exceed that point's depth. Both scale
    by the same factor, so shrinking the whole block uniformly keeps every copy
    inside the largest disc the arena holds there -- and that disc is inside the
    arena by the definition of the signed distance. The best row count is the one
    whose layout reaches the largest total perimeter.
    """
    shape = problem.shape
    circumradius = shape.circumradius(1.0)
    unit_perimeter = shape.perimeter(1.0)
    total_profile = sum(profile)
    best: tuple[float, int, float] | None = None
    for rows in range(1, len(profile) + 1):
        widths, heights = _varied_cells(problem, profile, rows)
        centres = _varied_centres(widths, heights, len(profile))
        reach = max(
            math.hypot(x, y) + circumradius * value
            for (x, y), value in zip(centres, profile)
        )
        factor = depth / reach if reach > 0.0 else 0.0
        total = unit_perimeter * total_profile * factor
        # The tie is broken on the smaller row count, so the choice is a function
        # of the geometry and the profile alone.
        if best is None or (total, -rows) > (best[0], -best[1]):
            best = (total, rows, factor)
    assert best is not None  # the loop always runs: the profile is never empty
    return best[1], best[2]


def _varied_placements(
    problem: Problem, profile: list[float], anchor: tuple[float, float], rows: int, factor: float
) -> list[Placement]:
    """Return the placements of the chosen varied layout, each with its local scale."""
    widths, heights = _varied_cells(problem, profile, rows)
    centres = _varied_centres(widths, heights, len(profile))
    placements: list[Placement] = []
    for index, ((x, y), value) in enumerate(zip(centres, profile)):
        placements.append(
            Placement(
                shape_id=_shape_id(index),
                x=anchor[0] + x * factor,
                y=anchor[1] + y * factor,
                scale=value * factor,
            )
        )
    return placements


def _varied_fit(
    problem: Problem,
    profile: list[float],
    anchor: tuple[float, float],
    rows: int,
    lower: float,
    common: float,
) -> float:
    """Return the largest factor at which the engine still contains every copy.

    ``lower`` is the factor the inscribed-disc condition already proves: it is
    contained, and for a polygon matching its own arena it is far smaller than the
    arena allows, because a copy's circumcircle is not the copy. The engine is the
    one that knows, so the factor is grown until the engine reports a copy outside
    and then bisected back: the arrangement never overlaps at any factor, so
    containment is the only question asked. A convex arena is star-shaped about the
    anchor, which is why growing towards a refusal and bisecting is sound.
    """
    if lower <= 0.0:
        return lower
    high = lower
    refused = None
    for _ in range(VARIED_FIT_DOUBLINGS):
        trial = high * 2.0
        if not _all_inside(problem, profile, anchor, rows, trial, common):
            refused = trial
            break
        high = trial
    if refused is None:
        return high
    low = high
    high = refused
    for _ in range(VARIED_FIT_ATTEMPTS):
        middle = (low + high) / 2.0
        if _all_inside(problem, profile, anchor, rows, middle, common):
            low = middle
        else:
            high = middle
    return low


def _all_inside(
    problem: Problem,
    profile: list[float],
    anchor: tuple[float, float],
    rows: int,
    factor: float,
    common: float,
) -> bool:
    """Ask the engine whether every copy of one varied layout is inside the arena."""
    draft = Candidate(
        candidate_id=new_candidate_id(),
        problem_id=problem.problem_id,
        scale=common,
        placements=tuple(_varied_placements(problem, profile, anchor, rows, factor)),
    )
    return all(item.inside for item in build_facts(problem, draft).containment)


def cover_initialize(
    problem: Problem,
    *,
    scale: float | None = None,
    count: int | None = None,
    origin: str = "cover",
) -> Candidate:
    """Lay copies over the arena so the engine can judge them a covering.

    The mirror image of every other initialiser here: they *fill* an arena with
    disjoint shapes, while a covering wants the union of the copies to contain the
    region, overlaps and overhangs included. The construction is the one
    :func:`paper_obs.geometry.bounds.scale_bounds` already proves: split the
    arena's bounding box into *count* columns, put one copy in each, and take the
    scale at which a copy's inscribed disc reaches half of a column's diagonal. The
    bounding box is then covered, and the arena inside it with it.

    That proof is about the *ideal* inscribed disc, while the engine compiles the
    arena and every disc footprint from chords: the bound's own scale can land a
    hair short, so the construction is grown in small steps until the engine's own
    *ArenaCovered* verdict accepts it, then bisected back down to the smallest
    scale that still covers. Three arrangements are tried -- the bound's row of
    columns, a balanced grid, and every copy stacked on the arena's deepest point --
    and, for a pair, the two copies slid together along the arena's longer axis; the
    one the engine accepts at the smallest scale wins. Nothing here decides
    validity: the verdict read is the constraint's own, and the candidate returned
    is one that verdict accepted, or the honest column proposal when none covers.

    *scale* fixes the common scale and skips the search, as it does for the other
    initialisers. *count* defaults to the objective's own count.
    """
    objective = problem.objective
    if not isinstance(objective, CoverRegion):
        raise ValueError(
            f"a covering start is only defined for a cover_region objective, "
            f"{type(objective).__name__} was given"
        )
    target = count if count is not None else (objective.preset_count() or 1)
    if target < 1:
        raise ValueError(f"a covering start needs at least one shape, got {target!r}")

    layouts: tuple[CoverLayout, ...] = (
        lambda: _cover_columns(problem, target),
        lambda: _cover_balanced(problem, target),
        lambda: _cover_stacked(problem, target),
    )
    if scale is not None:
        return _cover_candidate(problem, layouts[0](), float(scale), origin)

    bounds = scale_bounds(problem)
    best: Candidate | None = None
    for layout in layouts:
        fitted = _cover_fit(problem, layout, bounds, origin)
        # The best covering is the one at the smallest scale, since the score is its
        # reciprocal: the engine accepted each of them, and the ranking is arithmetic.
        if fitted is not None and (best is None or fitted.scale < best.scale):
            best = fitted
    if target == 2:
        # Two is the first count where the row stops being the best construction
        # this operator can build: see _cover_pair.
        paired = _cover_pair(problem, bounds, origin)
        if paired is not None and (best is None or paired.scale < best.scale):
            best = paired
    if best is not None:
        return best
    # No arrangement covered even after growing: the bound's own construction is
    # returned for the engine to refuse, rather than this operator inventing a cover.
    return _cover_candidate(problem, layouts[0](), bounds.high, origin)


def _cover_fit(
    problem: Problem, layout: CoverLayout, bounds: ScaleBounds, origin: str
) -> Candidate | None:
    """Return the smallest scale at which one arrangement is judged to cover.

    Coverage grows with the scale, so the search is a bracket: it starts at the
    bound's certain-cover scale, is grown while the engine still refuses the
    construction, and is then halved down to the frontier the engine accepts. The
    result is a candidate the engine's own coverage constraint called valid, or
    None when even the grown construction never covers.
    """
    low = bounds.low
    high = bounds.high
    if not _covers(problem, layout(), high):
        for _ in range(COVER_GROW_STEPS):
            high *= COVER_GROW_FACTOR
            if _covers(problem, layout(), high):
                break
        else:
            return None
    for _ in range(COVER_SHRINK_ATTEMPTS):
        middle = (low + high) / 2.0
        if not low < middle < high:
            break
        if _covers(problem, layout(), middle):
            high = middle
        else:
            low = middle
    return _cover_candidate(problem, layout(), high, origin)


def _covers(problem: Problem, placements: list[Placement], scale: float) -> bool:
    """Ask the engine's own coverage constraint whether an arrangement covers."""
    draft = Candidate(
        candidate_id=new_candidate_id(),
        problem_id=problem.problem_id,
        scale=scale,
        placements=tuple(placements),
    )
    return ArenaCovered().evaluate(build_facts(problem, draft)).valid


def _cover_candidate(
    problem: Problem, placements: list[Placement], scale: float, origin: str
) -> Candidate:
    """Return one covering arrangement as a candidate at a common scale."""
    return Candidate(
        candidate_id=new_candidate_id(),
        problem_id=problem.problem_id,
        scale=scale,
        placements=tuple(placements),
        origin=origin,
    )


def _cover_columns(problem: Problem, count: int) -> list[Placement]:
    """Return one copy at the centre of each of the count columns of the box.

    The row the covering bound is proved on. Its columns tile the arena's bounding
    box, and a copy's inscribed disc covers its own column once the common scale
    reaches the bound: the disc is centred on the shape origin for every family of
    the palette, which is what makes the centre of the column the right anchor.
    """
    min_x, min_y, max_x, max_y = _bounding_box(problem)
    step = (max_x - min_x) / count
    centre_y = (min_y + max_y) / 2.0
    return [
        Placement(shape_id=_shape_id(index), x=min_x + (index + 0.5) * step, y=centre_y)
        for index in range(count)
    ]


def _cover_balanced(problem: Problem, count: int) -> list[Placement]:
    """Return a balanced grid of copies spanning the arena's whole bounding box.

    A pointed arena packs its box poorly in one row; the grid spreads the count
    over both directions and gives the fit search a second arrangement to rank.
    The cell layout is the same balanced pair the lattice initialisers use.
    """
    min_x, min_y, max_x, max_y = _bounding_box(problem)
    columns, rows = _balanced_shape(count, (min_x, min_y, max_x, max_y), *_unit_cell(problem))
    return _anchored_placements(
        columns,
        rows,
        count,
        (max_x - min_x) / columns,
        (max_y - min_y) / rows,
        (min_x + max_x) / 2.0,
        (min_y + max_y) / 2.0,
        0.0,
        0.0,
    )


def _cover_stacked(problem: Problem, count: int) -> list[Placement]:
    """Return every copy piled on the arena's deepest interior point.

    Their union is one copy, so this arrangement is the arena's own single-copy
    covering, measured by the engine. It is the honest fallback for a region whose
    bounding box is a poor frame, and for a count of one it is the natural start.
    """
    x, y = _deepest_point(problem.draft_region)
    return [Placement(shape_id=_shape_id(index), x=x, y=y) for index in range(count)]


def _cover_pair(problem: Problem, bounds: ScaleBounds, origin: str) -> Candidate | None:
    """Return the best symmetric pair the engine accepts, or None.

    Two is the first count where the bound's row stops being the best construction
    this operator can build: the row's copies sit half a box apart, while a covering
    pair is free to slide together until the arena's own extreme points lie on the
    copies' edges. That spacing is the pair's only degree of freedom, so it is
    searched with a golden section on the engine's own coverage verdict, each
    trial's scale itself bisected by _cover_fit. Two orientations are tried, straight
    and turned by 45 degrees. Nothing here decides validity either: every trial that
    reaches the return is one _cover_fit judged covering, and a pair that never
    covers is not reported.
    """
    min_x, min_y, max_x, max_y = _bounding_box(problem)
    width, height = max_x - min_x, max_y - min_y
    along_x = width >= height
    reach = 0.5 * max(width, height)
    centre_x, centre_y = (min_x + max_x) / 2.0, (min_y + max_y) / 2.0

    def fit(offset: float, angle: float) -> Candidate | None:
        delta_x = offset if along_x else 0.0
        delta_y = 0.0 if along_x else offset

        def layout() -> list[Placement]:
            return [
                Placement(
                    shape_id=_shape_id(index),
                    x=centre_x + sign * delta_x,
                    y=centre_y + sign * delta_y,
                    rotation=angle,
                )
                for index, sign in enumerate((-1.0, 1.0))
            ]

        return _cover_fit(problem, layout, bounds, origin)

    def key(candidate: Candidate | None) -> float:
        return math.inf if candidate is None else candidate.scale

    best: Candidate | None = None
    for angle in COVER_PAIR_ANGLES:
        low, high = 0.0, reach
        left = high - COVER_PAIR_GOLDEN * (high - low)
        right = low + COVER_PAIR_GOLDEN * (high - low)
        left_fit, right_fit = fit(left, angle), fit(right, angle)
        for _ in range(COVER_PAIR_ATTEMPTS):
            if key(left_fit) <= key(right_fit):
                high, right, right_fit = right, left, left_fit
                left = high - COVER_PAIR_GOLDEN * (high - low)
                left_fit = fit(left, angle)
            else:
                low, left, left_fit = left, right, right_fit
                right = low + COVER_PAIR_GOLDEN * (high - low)
                right_fit = fit(right, angle)
        for candidate in (left_fit, right_fit):
            if candidate is not None and (best is None or candidate.scale < best.scale):
                best = candidate
    return best


def random_initialize(
    problem: Problem,
    *,
    scale: float | None = None,
    count: int | None = None,
    attempts: int = 4,
    generator: np.random.Generator | None = None,
    origin: str = "random",
) -> Candidate:
    """Scatter shapes uniformly in the arena bounding box.

    Several times as many positions as needed are drawn, then kept in order when
    they are free: the surplus is what makes the result usable instead of a pile
    of overlaps. The scale defaults to the tight lattice scale, so the samples
    are dense enough to be interesting and loose enough to be feasible.
    """
    target = count if count is not None else problem.objective.preset_count()
    box = _bounding_box(problem)
    # A scale the objective fixes is not a free variable, and a scatter at another
    # one is a candidate that objective's own constraint refuses: the preset wins.
    if scale is None:
        scale = problem.objective.preset_scale()
    if scale is None:
        scale = (
            _preset_or_bound(problem)
            if target is None
            else tight_lattice_scale(box, *_unit_cell(problem), target)
        )
    rng = generator if generator is not None else np.random.default_rng(problem.seed)
    samples = max(1, (target or 1) * max(1, attempts))
    normalised = rng.random((samples, 2))
    min_x, min_y, max_x, max_y = box

    def layout(value: float) -> list[Placement]:
        points = np.column_stack(
            (min_x + normalised[:, 0] * (max_x - min_x), min_y + normalised[:, 1] * (max_y - min_y))
        )
        return [
            Placement(shape_id=_shape_id(index), x=float(x), y=float(y))
            for index, (x, y) in enumerate(points)
        ]

    return _place(problem, layout, scale, target=target, origin=origin)


def _anchored_lattice(
    problem: Problem,
    target: int,
    cell_width: float,
    cell_height: float,
    *,
    origin: str,
) -> Candidate:
    """Place the requested count on the largest lattice an arena's geometry allows.

    Three decisions are taken here, none of them from the bounding box alone.

    *Where.* The lattice is anchored on a short deterministic list of interior
    points — the bounding-box centre first, so a symmetric arena keeps its exact
    centre and a rectangle reproduces the old placements, then the arena's deepest
    point, then the four quarter points of its box, which is what catches the
    corner of an L. The engine ranks the anchors: the one that reaches the
    requested count at the larger scale wins.

    *Which shape.* The rows and columns are the balanced pair that wastes the
    least room for the count in the arena's box, as before.

    *How large.* The search starts at the tight lattice — the scale at which the
    cells exactly fill the box, an upper bound on any placement of that block —
    and descends by halving until the engine keeps the requested count, then
    bisects between the first scale that fits and the last that did not. A fixed
    bracket of a few widths, which is what the operator used to use, missed every
    pointed arena whose useful scale lay further below the box: a triangle, an
    octagon or an L asks for an order of magnitude, not a factor of four.
    """
    arena = problem.draft_region
    columns, rows = _balanced_shape(target, arena.bounds, cell_width, cell_height)
    offset_x, offset_y = _bbox_offset(problem)
    # A concave outline needs its cells a hair apart; a convex or circular one must
    # not be moved at all, or a tileable instance stops tiling. See CONCAVE_SEPARATION.
    separation = 0.0 if problem.shape.is_convex else CONCAVE_SEPARATION
    upper = tight_lattice_scale(arena.bounds, cell_width, cell_height, target)

    best: Candidate | None = None
    for anchor_x, anchor_y in _anchor_candidates(arena):
        # An anchor is only searched in full once it can hold the count at the scale
        # the incumbent already reached; one that cannot is below the incumbent and
        # is skipped for the price of a single judgement.
        probe = None if best is None else best.scale
        candidate = _fit_lattice_at(
            problem,
            target,
            columns,
            rows,
            cell_width,
            cell_height,
            offset_x,
            offset_y,
            separation,
            anchor_x,
            anchor_y,
            upper,
            origin=origin,
            probe=probe,
        )
        if candidate is None:
            continue
        # The tight lattice is an upper bound on any placement of this block, so the
        # first anchor that reaches the count there cannot be beaten by another.
        if candidate.n_shapes >= target and candidate.scale >= upper:
            return candidate
        if best is None or _better_lattice(candidate, best, target):
            best = candidate
    # _anchor_candidates always yields at least the deepest point, so this is only
    # a defensive branch for a degenerate arena.
    if best is None:
        raise ValueError("the arena has no interior point to anchor a lattice on")
    return best


def _fit_lattice_at(
    problem: Problem,
    target: int,
    columns: int,
    rows: int,
    cell_width: float,
    cell_height: float,
    offset_x: float,
    offset_y: float,
    separation: float,
    anchor_x: float,
    anchor_y: float,
    upper: float,
    *,
    origin: str,
    probe: float | None,
) -> Candidate | None:
    """Search the scale of one anchored lattice, largest first; None when it cannot win.

    The descent is incremental rather than bracketed: the tight lattice is tried
    first because it is exact on a rectangle, then each halving either fits — and
    becomes the low end of a bisection — or is itself the new high end. A scale
    that fits only in a narrow band below its neighbour is still found, which a
    fixed bracket cannot promise.

    The probe is the incumbent's scale. A lattice shrinks monotonically about an
    interior anchor, so an anchor that cannot hold the count there cannot hold it
    at a larger scale, and the descent is not spent on it. On a region that is not
    star-shaped the probe can pass over a better anchor; it never turns a fitting
    proposal into an invalid one. The first anchor gets None and sets the incumbent.
    """

    def layout(value: float) -> list[Placement]:
        step_x = cell_width * value * (1.0 + separation)
        step_y = cell_height * value * (1.0 + separation)
        return _anchored_placements(
            columns, rows, target, step_x, step_y, anchor_x, anchor_y,
            offset_x * value, offset_y * value,
        )

    def kept(value: float) -> Candidate:
        return _keep_compatible(problem, layout(value), value, origin=origin, limit=target)

    if probe is not None and kept(probe).n_shapes < target:
        return None
    candidate = kept(upper)
    if candidate.n_shapes >= target:
        return candidate

    closest = candidate
    failing = upper
    scale = upper
    fitting: Candidate | None = None
    for _ in range(DESCENT_HALVINGS):
        scale *= 0.5
        trial = kept(scale)
        if trial.n_shapes >= target:
            fitting = trial
            break
        if trial.n_shapes > closest.n_shapes:
            closest = trial
        failing = scale
    if fitting is None:
        # The arena cannot hold the count even at the smallest scale the descent
        # reached. The closest proposal is returned honestly short; the engine
        # reports the missing copies rather than this operator inventing validity.
        return closest

    low, high = scale, failing
    best = fitting
    for _ in range(BISECTION_ATTEMPTS):
        middle = (low + high) / 2.0
        trial = kept(middle)
        if trial.n_shapes >= target:
            if trial.scale > best.scale:
                best = trial
            low = middle
        else:
            high = middle
    return best


def _better_lattice(candidate: Candidate, incumbent: Candidate, target: int) -> bool:
    """Whether one anchor's proposal beats another's for the same request.

    Reaching the count comes first, then the larger scale; among incomplete
    proposals the one holding the most copies is the honest fallback.
    """
    reached = candidate.n_shapes >= target
    previous = incumbent.n_shapes >= target
    if reached != previous:
        return reached
    if reached:
        return candidate.scale > incumbent.scale
    if candidate.n_shapes != incumbent.n_shapes:
        return candidate.n_shapes > incumbent.n_shapes
    return candidate.scale > incumbent.scale


def _anchor_candidates(arena: Arena) -> Iterator[tuple[float, float]]:
    """Yield the deterministic anchors a free-scale lattice is tried on, best first.

    The bounding-box centre comes first: a symmetric arena keeps its exact centre,
    so a single square is still placed exactly at (0, 0), and a rectangle reaches
    the tight lattice there — which the caller takes as final without asking for
    the rest. Then the arena's deepest interior point, which is what a pointed
    region needs. Then the four quarter points of the box, because a polygon with
    a notch or a right angle fits best where its own inscribed circle does not
    reach: the corner of an L is the quarter point, not the deepest point.

    Every candidate is asked of the arena and a point outside it, or on its
    boundary, is dropped: nothing fits around a boundary point. The walk is
    deterministic and yields lazily, so a rectangle that is already optimal pays
    for the deepest-point search only.
    """
    tolerance = max(max(arena.size), 1.0) * 1e-9
    seen: list[tuple[float, float]] = []

    def fresh(point: tuple[float, float]) -> bool:
        return all(math.hypot(point[0] - x, point[1] - y) > tolerance for x, y in seen)

    centre = arena.center
    if arena.signed_distance(*centre) > 0.0:
        seen.append(centre)
        yield centre
    deepest = _deepest_point(arena)
    if fresh(deepest):
        seen.append(deepest)
        yield deepest
    min_x, min_y, max_x, max_y = arena.bounds
    width, height = max_x - min_x, max_y - min_y
    for fraction_x in (0.25, 0.75):
        for fraction_y in (0.25, 0.75):
            point = (min_x + fraction_x * width, min_y + fraction_y * height)
            if arena.signed_distance(*point) > 0.0 and fresh(point):
                seen.append(point)
                yield point


def _deepest_point(arena: Arena) -> tuple[float, float]:
    """Return an interior point of the arena, as deep as a small search finds.

    The arena's own signed_distance is hill-climbed: a coarse sweep of the
    bounding box seeds it — a single climb from the centre would stop in a saddle
    of an L — then a shrinking 3x3 neighbourhood refines the winner. Every
    measurement is the arena's, so nothing geometric is reimplemented here, and
    the walk is deterministic, so it needs no seed.
    """
    min_x, min_y, max_x, max_y = arena.bounds
    width, height = max_x - min_x, max_y - min_y
    best = arena.center
    best_depth = arena.signed_distance(*best)
    for column in range(COARSE_SAMPLES):
        for row in range(COARSE_SAMPLES):
            x = min_x + (column + 0.5) / COARSE_SAMPLES * width
            y = min_y + (row + 0.5) / COARSE_SAMPLES * height
            depth = arena.signed_distance(x, y)
            if depth > best_depth:
                best, best_depth = (x, y), depth
    step = max(width, height) / (2.0 * COARSE_SAMPLES)
    for _ in range(REFINEMENT_ROUNDS):
        for dx in (-1.0, 0.0, 1.0):
            for dy in (-1.0, 0.0, 1.0):
                x = best[0] + dx * step
                y = best[1] + dy * step
                depth = arena.signed_distance(x, y)
                if depth > best_depth:
                    best, best_depth = (x, y), depth
        step *= 0.5
    return best


def _bbox_offset(problem: Problem) -> tuple[float, float]:
    """Return the shape's bounding-box centre at scale 1, relative to its origin.

    A placement positions the shape's own origin, which for a right triangle or an
    L is not the centre of its box. Centering the *boxes* on the anchor is what
    lets a triangle in a domino rest on both edges instead of on one, and it is
    zero for the symmetric families, whose behaviour is untouched.
    """
    min_x, min_y, max_x, max_y = problem.shape.bounding_box(1.0)
    return ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)


def _anchored_placements(
    columns: int,
    rows: int,
    count: int,
    step_x: float,
    step_y: float,
    anchor_x: float,
    anchor_y: float,
    offset_x: float,
    offset_y: float,
) -> list[Placement]:
    """Return a balanced lattice centred on an anchor, boxes rather than origins.

    Rows differ by at most one copy and every row is centred, and the block is
    placed so that the *bounding boxes* of the copies are centred on the anchor:
    the shape origin is pulled back by its own box offset. When the offset is
    zero this is the same grid _balanced_placements builds.
    """
    block_width = columns * step_x
    block_height = rows * step_y
    left = anchor_x - block_width / 2.0
    bottom = anchor_y - block_height / 2.0
    base, extra = divmod(count, rows)
    placements: list[Placement] = []
    for row in range(rows):
        in_row = base + (1 if row < extra else 0)
        centring = (columns - in_row) * step_x / 2.0
        for column in range(in_row):
            placements.append(
                Placement(
                    shape_id=_shape_id(len(placements)),
                    x=left + centring + (column + 0.5) * step_x - offset_x,
                    y=bottom + (row + 0.5) * step_y - offset_y,
                )
            )
    return placements


def tight_lattice_scale(
    box: tuple[float, float, float, float],
    cell_width: float,
    cell_height: float,
    count: int,
) -> float:
    """Return the scale at which the count of balanced cells exactly fills the bounding box."""
    if count < 1:
        raise ValueError(f"a lattice needs at least one shape, got {count!r}")
    columns, rows = _balanced_shape(count, box, cell_width, cell_height)
    return min(
        (box[2] - box[0]) / (columns * cell_width), (box[3] - box[1]) / (rows * cell_height)
    )


def _bounding_box(problem: Problem) -> tuple[float, float, float, float]:
    """Return the arena bounding box, the frame every initializer lays out in."""
    return problem.draft_region.bounds


def _unit_cell(problem: Problem) -> tuple[float, float]:
    """Return the smallest axis-aligned cell holding the shape at scale 1."""
    min_x, min_y, max_x, max_y = problem.shape.bounding_box(1.0)
    return (max_x - min_x, max_y - min_y)


def _preset_or_bound(problem: Problem) -> float:
    """Return the scale fixed by the objective, or the perfect-packing bound."""
    preset = problem.objective.preset_scale()
    return preset if preset is not None else scale_bounds(problem).high


def _balanced_shape(
    count: int,
    box: tuple[float, float, float, float],
    cell_width: float,
    cell_height: float,
) -> tuple[int, int]:
    """Return the (columns, rows) grid that wastes the least room for the count.

    Measured rather than guessed: one column of the count and one row of the count
    are both lattice shapes, and so is everything between them.
    """
    box_width, box_height = box[2] - box[0], box[3] - box[1]
    best = (count, 1)
    best_scale = 0.0
    for columns in range(1, count + 1):
        rows = math.ceil(count / columns)
        filled = min(box_width / (columns * cell_width), box_height / (rows * cell_height))
        if filled > best_scale:
            best, best_scale = (columns, rows), filled
    return best


def _balanced_staggered_shape(
    box: tuple[float, float, float, float], diameter: float, row_step: float, count: int
) -> tuple[float, int, int]:
    """Return the (scale, rows, columns) of the largest staggered lattice that fits."""
    box_width, box_height = box[2] - box[0], box[3] - box[1]
    best = (0.0, 1, count)
    for rows in range(1, count + 1):
        columns = math.ceil(count / rows)
        filled = min(
            box_width / ((columns + 0.5) * diameter),
            box_height / (diameter + (rows - 1) * row_step),
        )
        if filled > best[0]:
            best = (filled, rows, columns)
    return best


def _fill_counts(
    box: tuple[float, float, float, float], cell_width: float, cell_height: float
) -> tuple[int, int]:
    """Return how many whole cells of a given size fit in the bounding box, at least one."""
    if cell_width <= 0.0 or cell_height <= 0.0:
        raise ValueError("cell dimensions must be positive")
    return (
        max(1, int((box[2] - box[0]) // cell_width)),
        max(1, int((box[3] - box[1]) // cell_height)),
    )


def _staggered_fill_counts(
    box: tuple[float, float, float, float], spacing: float, row_step: float
) -> tuple[int, int]:
    """Return the (rows, columns) of a staggered lattice that fills the bounding box."""
    if spacing <= 0.0 or row_step <= 0.0:
        raise ValueError("a staggered lattice needs positive spacings")
    columns = max(1, int((box[2] - box[0]) // spacing))
    rows = max(1, int(((box[3] - box[1]) - spacing) // row_step) + 1)
    return (rows, columns)


def _grid_placements(
    arena: Arena, columns: int, rows: int, cell_width: float, cell_height: float
) -> list[Placement]:
    """Return one placement at the centre of every cell of a full grid."""
    origin_x, origin_y = _grid_origin(arena, columns, rows, cell_width, cell_height)
    return [
        Placement(
            shape_id=_shape_id(row * columns + column),
            x=origin_x + (column + 0.5) * cell_width,
            y=origin_y + (row + 0.5) * cell_height,
        )
        for row in range(rows)
        for column in range(columns)
    ]


def _balanced_placements(
    arena: Arena, columns: int, rows: int, count: int, cell_width: float, cell_height: float
) -> list[Placement]:
    """Return a centred grid distributing the count over the rows.

    Rows differ by at most one shape and every row is centred instead of
    left-aligned: on a disc or a composite arena, that is the difference between
    a lattice that fits and one that has to drop its last row.
    """
    origin_x, origin_y = _grid_origin(arena, columns, rows, cell_width, cell_height)
    base, extra = divmod(count, rows)
    placements: list[Placement] = []
    for row in range(rows):
        in_row = base + (1 if row < extra else 0)
        offset = (columns - in_row) * cell_width / 2.0
        for column in range(in_row):
            placements.append(
                Placement(
                    shape_id=_shape_id(len(placements)),
                    x=origin_x + offset + (column + 0.5) * cell_width,
                    y=origin_y + (row + 0.5) * cell_height,
                )
            )
    return placements


def _staggered_placements(
    arena: Arena,
    *,
    rows: int,
    columns: int,
    spacing: float,
    row_step: float,
    limit: int | None,
) -> list[Placement]:
    """Return the placements of a staggered lattice centred in the arena bounds."""
    min_x, min_y, max_x, max_y = arena.bounds
    block_width = columns * spacing + spacing / 2.0
    block_height = spacing + (rows - 1) * row_step
    origin_x = (min_x + max_x) / 2.0 - block_width / 2.0
    origin_y = (min_y + max_y) / 2.0 - block_height / 2.0
    placements: list[Placement] = []
    for row in range(rows):
        offset = (spacing / 2.0) if row % 2 else 0.0
        for column in range(columns):
            if limit is not None and len(placements) >= limit:
                return placements
            placements.append(
                Placement(
                    shape_id=_shape_id(len(placements)),
                    x=origin_x + offset + (column + 0.5) * spacing,
                    y=origin_y + spacing / 2.0 + row * row_step,
                )
            )
    return placements


def _grid_origin(
    arena: Arena, columns: int, rows: int, cell_width: float, cell_height: float
) -> tuple[float, float]:
    """Return the lower-left corner of a grid centred in the arena bounds."""
    min_x, min_y, max_x, max_y = arena.bounds
    return (
        (min_x + max_x) / 2.0 - columns * cell_width / 2.0,
        (min_y + max_y) / 2.0 - rows * cell_height / 2.0,
    )


def _shape_id(index: int) -> str:
    """Return the identifier of the index-th shape, zero-padded to stay sortable."""
    return f"s{index:03d}"


def _place(
    problem: Problem,
    layout: Layout,
    scale: float,
    *,
    target: int | None,
    origin: str,
) -> Candidate:
    """Build the candidate, shrinking the lattice until everything asked for fits.

    A lattice sized for the bounding box of a disc has corners outside it, and a
    candidate that leaves the arena is invalid for a fixed-count objective. The
    scale is therefore halved down while the count is not reached, keeping the
    largest scale that does reach it. Shrinking only ever helps the count, since
    every placement moves towards the centre of a fixed frame.

    A ladder rung is only worth trying at a scale the objective accepts. Where the
    objective *fixes* the common scale, every rung below it contradicts that
    objective: the ladder would trade a candidate the engine can use for one it
    refuses, and the reason would be the operator's own invention rather than the
    arrangement. The descent is therefore floored at the objective's own scale, and
    where that floor is the whole interval there is nothing to try.
    """
    candidate = _keep_compatible(problem, layout(scale), scale, origin=origin, limit=target)
    if target is None or candidate.n_shapes >= target:
        return candidate
    best: Candidate | None = None
    closest = candidate
    low, high = scale / SHRINK_FACTOR, scale
    preset = problem.objective.preset_scale()
    if preset is not None:
        low = max(low, preset)
    if low >= high:
        return candidate
    for _ in range(SHRINK_ATTEMPTS):
        middle = (low + high) / 2.0
        trial = _keep_compatible(problem, layout(middle), middle, origin=origin, limit=target)
        if trial.n_shapes > closest.n_shapes:
            closest = trial
        if trial.n_shapes >= target:
            if best is None or trial.scale > best.scale:
                best = trial
            low = middle
        else:
            high = middle
    return best if best is not None else closest


def _keep_compatible(
    problem: Problem,
    placements: list[Placement],
    scale: float,
    *,
    origin: str,
    limit: int | None,
) -> Candidate:
    """Keep the placements that fit inside the arena without overlapping.

    The draft candidate is handed to the engine, which reports which shapes leave
    the arena and which pairs overlap; the surviving placements are then accepted
    in order. Asking the engine rather than reimplementing the test is what keeps
    an operator from disagreeing with the validator about what "fitting" means.

    Only the rules the problem actually applies filter anything: a covering and the
    derived covering declare neither containment nor non-overlap, and a derived
    region is measured *from* the draft rather than imposed on it, so filtering on
    it would reject the very shapes it was measured around.
    """
    draft = Candidate(
        candidate_id=new_candidate_id(),
        problem_id=problem.problem_id,
        scale=scale,
        placements=tuple(placements),
        origin=origin,
    )
    if not placements:
        return draft
    effective = {constraint.kind for constraint in problem.effective_constraints}
    facts = build_facts(problem, draft)
    rejected = (
        {containment.shape_id for containment in facts.containment if not containment.inside}
        if "arena_containment" in effective
        else set()
    )
    conflicting: dict[str, set[str]] = {placement.shape_id: set() for placement in placements}
    if "non_overlap" in effective:
        for overlap in facts.overlaps:
            conflicting[overlap.first].add(overlap.second)
            conflicting[overlap.second].add(overlap.first)

    kept: list[Placement] = []
    accepted: set[str] = set()
    for placement in placements:
        if placement.shape_id in rejected or conflicting[placement.shape_id] & accepted:
            continue
        kept.append(placement)
        accepted.add(placement.shape_id)
        if limit is not None and len(kept) >= limit:
            break
    return Candidate(
        candidate_id=draft.candidate_id,
        problem_id=problem.problem_id,
        scale=scale,
        placements=tuple(kept),
        origin=origin,
    )
