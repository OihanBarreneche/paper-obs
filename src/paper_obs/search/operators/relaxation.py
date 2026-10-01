"""Relaxation operators: get more out of the placements that are already there.

Two levers, both judged by the engine. :func:`increase_scale` grows the shapes in
place and asks the validator how far that can go; :func:`local_relax` moves
anchors and keeps a move only when :meth:`Evaluation.is_better_than` agrees.

Neither computes a score, a distance or a verdict of its own. The ranking lives
in :meth:`Evaluation.rank_key`, and the day a constraint or an objective changes,
an operator that had reimplemented the comparison would silently drift from the
engine it claims to serve.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import numpy as np

from paper_obs.domain.candidate import Candidate
from paper_obs.domain.problem import Problem

from paper_obs.geometry.bounds import scale_bounds
from paper_obs.geometry.engine import Evaluation, evaluate, validate

from .mutation import jitter

#: Share of a candidate a single relaxation move jitters. One shape in four is a
#: convention: moving a single shape cannot untangle a lattice whose shapes all
#: touch their neighbours, and moving every shape at once is a restart, not a
#: relaxation. The caller still decides the amplitude and the iteration count.
RELAX_BATCH = 4

#: Share of the common scale a contraction keeps. Five percent is a compromise:
#: enough to open the room a wall-tight packing needs, small enough that the
#: score it costs stays a deliberate price rather than a silent giveaway.
DEFAULT_CONTRACTION = 0.95


def increase_scale(
    problem: Problem,
    candidate: Candidate,
    *,
    upper: float | None = None,
    iterations: int = 24,
    origin: str = "increase_scale",
) -> Candidate:
    """Return the same placements at the largest common scale the engine accepts.

    Growing the common scale enlarges every shape about its own anchor. The
    anchors do not move, so a packing that was tight becomes overlapping and a
    shape near a wall overflows it: the predicate "is this still valid" is
    monotone in the scale for every constraint of the MVP, and the largest
    accepted scale is found by bisection on ``[candidate.scale, upper]``.

    ``upper`` defaults to the perfect-packing bound of
    :func:`paper_obs.geometry.bounds.scale_bounds` — and that is a *bound*, not
    a target: it is the scale at which the shapes would tile the arena exactly,
    which nothing reaches, but it is finite, cheap and honest. An explicit
    ``upper`` never turns the operator loose: every probe is validated, and only
    an accepted scale is ever returned.

    Two cases return the candidate itself, without a new child: when the input is
    not valid — no scale is then known to be good, and the bisection would have no
    floor — and when no larger scale keeps the placements valid. ``iterations``
    halvings place the retained scale within ``(upper - scale) / 2 ** iterations``
    of the largest one, for one validator call each.
    """
    if not validate(problem, candidate).valid:
        return candidate
    low = candidate.scale
    high = upper if upper is not None else scale_bounds(problem).high
    if high <= low:
        return candidate

    def accepts(value: float) -> bool:
        return validate(problem, candidate.derive(scale=value, origin=origin)).valid

    if accepts(high):
        return candidate.derive(scale=high, origin=origin)
    retained = _largest_valid(low, high, accepts, iterations)
    if retained <= candidate.scale:
        return candidate
    return candidate.derive(scale=retained, origin=origin)


def _largest_valid(
    low: float, high: float, accepts: Callable[[float], bool], iterations: int
) -> float:
    """Return the largest value of the bracket a monotone predicate still accepts.

    Every constraint of the lab gets harder as a copy grows: one that overlaps or overflows
    at a size does the same at any larger one. That is what makes a bisection sound here
    rather than a search, and it is the only reason this helper may assume it.
    """
    for _ in range(iterations):
        middle = (low + high) / 2.0
        if not low < middle < high:
            # The bracket has closed on the float grid: probing again would return the
            # same two values for ever.
            break
        if accepts(middle):
            low = middle
        else:
            high = middle
    return low


def grow_sizes(
    problem: Problem,
    candidate: Candidate,
    *,
    shape_id: str | None = None,
    upper: float | None = None,
    iterations: int = 24,
    origin: str = "grow_sizes",
) -> Candidate:
    """Grow the sizes a candidate carries: one copy, or every copy together.

    A family that sizes its copies one by one has no common scale to raise, and
    :func:`increase_scale` is then the wrong lever: it moves the number the objective
    fixes, and the engine refuses the result. What grows here is the local size of a
    placement, which is what such an objective scores.

    Given a `shape_id`, that copy alone is enlarged about its own anchor until the engine
    refuses, and the largest size it accepts is kept: this is the move a sum of perimeters
    is made of, and it is how one copy's size trades against its neighbours'. Given none,
    every sized copy is multiplied by one common factor found by the same bisection, which
    keeps the proportions the arrangement already has.

    `upper` is the per-copy bound of :func:`paper_obs.geometry.bounds.scale_bounds` —
    the scale at which the copies would tile the arena exactly, which is finite, cheap and
    never reached. A candidate the engine rejects, or one whose copies carry no local size
    at all, is returned untouched: there is nothing to grow, and nothing known to be good.
    A `shape_id` that names no copy raises `KeyError`.
    """
    if not validate(problem, candidate).valid:
        return candidate
    sized = [item for item in candidate.placements if item.scale is not None]
    if not sized:
        return candidate
    try:
        bound = scale_bounds(problem).high if upper is None else upper
    except TypeError:
        # An objective that measures its own region has no bound to grow into.
        return candidate

    def resized(item: object, value: float) -> object:
        return replace(item, scale=value)  # type: ignore[type-var]

    def only(value: float) -> Candidate:
        return candidate.derive(
            placements=[
                resized(item, value) if item.shape_id == shape_id else item
                for item in candidate.placements
            ],
            origin=origin,
        )

    if shape_id is not None:
        target = next((item for item in sized if item.shape_id == shape_id), None)
        if target is None:
            raise KeyError(shape_id)
        if bound <= target.scale:
            return candidate
        if validate(problem, only(bound)).valid:
            return only(bound)
        retained = _largest_valid(
            target.scale, bound, lambda value: validate(problem, only(value)).valid, iterations
        )
        return candidate if retained <= target.scale else only(retained)

    def scaled(factor: float) -> Candidate:
        return candidate.derive(
            placements=[
                resized(item, item.scale * factor) if item.scale is not None else item
                for item in candidate.placements
            ],
            origin=origin,
        )

    ceiling = bound / max(item.scale for item in sized)
    if ceiling <= 1.0:
        return candidate
    if validate(problem, scaled(ceiling)).valid:
        return scaled(ceiling)
    factor = _largest_valid(
        1.0, ceiling, lambda value: validate(problem, scaled(value)).valid, iterations
    )
    return candidate if factor <= 1.0 else scaled(factor)


#: Growth of the common scale per step while placements do not cover yet, and how many
#: steps are tried before :func:`fit_cover_scale` gives up and hands them back unchanged.
COVER_GROWTH = 1.05
COVER_GROWTH_STEPS = 24


def fit_cover_scale(
    problem: Problem,
    candidate: Candidate,
    *,
    iterations: int = 30,
    origin: str = "fit_cover_scale",
) -> Candidate:
    """Return the same placements at the smallest common scale the engine calls a cover.

    The mirror of :func:`increase_scale` for a covering, whose score is the reciprocal of
    the scale. Every copy grows about its own anchor, so coverage only grows with the scale
    and the frontier is found by bisection, down to the problem's own lower bound. Copies
    that do not cover at their scale are first grown by :data:`COVER_GROWTH` until they do;
    placements that never cover within :data:`COVER_GROWTH_STEPS` come back untouched, for
    the engine to refuse. ``iterations`` halvings place the scale within
    ``(high - low) / 2 ** iterations`` of the frontier.
    """

    def covers(value: float) -> bool:
        return validate(problem, candidate.derive(scale=value, origin=origin)).valid

    high = candidate.scale
    for _ in range(COVER_GROWTH_STEPS):
        if covers(high):
            break
        high *= COVER_GROWTH
    else:
        return candidate
    low = min(scale_bounds(problem).low, high)
    for _ in range(iterations):
        middle = (low + high) / 2.0
        if not low < middle < high:
            break
        if covers(middle):
            high = middle
        else:
            low = middle
    return candidate if high == candidate.scale else candidate.derive(scale=high, origin=origin)


def contract_scale(
    problem: Problem,
    candidate: Candidate,
    *,
    factor: float = DEFAULT_CONTRACTION,
    floor: float | None = None,
    origin: str = "contract_scale",
) -> Candidate:
    """Return the same placements at a smaller common scale.

    A candidate packed to the walls cannot have an overlap removed by moving
    shapes: every direction that separates two of them pushes one into the arena
    boundary, the engine sees a containment violation appear where an overlap
    disappeared, and the ranking refuses the move. The only way out is to trade
    scale for room, which is what this does. The anchors do not move, so the
    packing keeps its arrangement and only gives up size — the scale is a property
    of the shapes, never of their positions.

    ``factor`` is the share of the scale the candidate keeps, and ``floor`` is
    where the descent stops: the problem's own lower bound by default, so a caller
    may put this in a loop without checking anything.
    """
    if not 0.0 < factor < 1.0:
        raise ValueError(f"factor must be in (0, 1), got {factor!r}")
    low = scale_bounds(problem).low if floor is None else floor
    scale = max(low, candidate.scale * factor)
    if scale >= candidate.scale:
        return candidate
    return candidate.derive(scale=scale, origin=origin)


def local_relax(
    problem: Problem,
    candidate: Candidate,
    *,
    iterations: int,
    amplitude: float,
    turn: float = 0.0,
    generator: np.random.Generator | None = None,
    origin: str = "local_relax",
) -> Candidate:
    """Stochastic hill climbing over the placements, ranked by the engine.

    One iteration jitters a ``1 / RELAX_BATCH`` share of the shapes — and turns them
    by up to ``turn`` degrees when it is positive — and keeps the
    result only when ``Evaluation.is_better_than`` prefers it, so the candidate
    never walks downhill and the returned candidate is never worse than the input
    under :meth:`Evaluation.rank_key` — it is the input itself when nothing was
    accepted. The engine is asked without metrics: a ranking needs the verdict,
    the score and the severity, never the descriptive numbers.

    With the two objectives of the MVP the primary score is a property of the
    candidate, not of its placements — a common scale, or a shape count — so a
    same-scale move can only improve an *invalid* candidate, through the severity
    tie-break of ``rank_key``. Relaxation is therefore used after
    :func:`increase_scale` or after a mutation, not instead of them.
    """
    if iterations < 1 or candidate.n_shapes == 0:
        return candidate
    rng = generator if generator is not None else np.random.default_rng(problem.seed)
    batch = max(1, candidate.n_shapes // RELAX_BATCH)
    best = candidate
    best_evaluation: Evaluation = evaluate(problem, candidate, with_metrics=False)
    for _ in range(iterations):
        trial = jitter(
            problem, best, amplitude=amplitude, generator=rng, count=batch, turn=turn,
            origin=origin,
        )
        trial_evaluation = evaluate(problem, trial, with_metrics=False)
        if trial_evaluation.is_better_than(best_evaluation):
            best, best_evaluation = trial, trial_evaluation
    return best


def compact(
    problem: Problem,
    candidate: Candidate,
    *,
    factor: float = 0.05,
    passes: int = 4,
) -> Candidate:
    """Pull each anchor toward their centroid when the engine keeps it valid.

    ``factor`` is the fraction of the remaining distance tried per shape and
    pass. This creates room near the boundary for later scale growth. It returns
    the input when no accepted move exists and does not alter the common scale.
    """
    if not 0 < factor < 1 or passes < 1:
        raise ValueError("factor must be in (0, 1) and passes must be positive")
    if candidate.n_shapes < 2 or not validate(problem, candidate).valid:
        return candidate
    current = candidate
    for _ in range(passes):
        cx = sum(item.x for item in current.placements) / current.n_shapes
        cy = sum(item.y for item in current.placements) / current.n_shapes
        changed = False
        for item in current.placements:
            moved = item.moved(item.x + factor * (cx - item.x), item.y + factor * (cy - item.y))
            trial = current.derive(
                placements=[moved if other.shape_id == item.shape_id else other for other in current.placements],
                origin="compact",
            )
            if validate(problem, trial).valid:
                current, changed = trial, True
        if not changed:
            break
    return current
