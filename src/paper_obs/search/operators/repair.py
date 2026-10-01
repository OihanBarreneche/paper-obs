"""Repair operators: bring a broken candidate back towards validity.

Repair is a local search with a direction, in the literal sense: the geometry
façade reports, for every overlapping pair, how deep the overlap is *and* the unit
axis along which the second shape leaves the first, and for every shape that
leaves the arena the translation that brings it back to the wall. An operator
that only knew the depth had to guess where to push — a uniform jitter, kept when
the engine preferred the result — and guessing is what keeps a strongly shaken
lattice broken. Knowing the axis makes the move a function of the state instead
of a draw.

Nothing here judges the result. :func:`repair_overlaps` returns the least broken
candidate it reached, valid or not, because "is it valid" is a question for
:func:`paper_obs.geometry.engine.validate` and the caller that asked.
"""

from __future__ import annotations

from paper_obs.domain.candidate import Candidate
from paper_obs.domain.problem import Problem

from paper_obs.geometry.engine import Evaluation, evaluate, facts_for

from .mutation import displace

#: Share of an overlap depth a single shape absorbs in one repair pass. Half is
#: the exact separation for a lone pair — each shape travels half the depth, and
#: the two together travel all of it — and a dense cluster may want less, so the
#: pushes a shape receives from several neighbours do not overshoot.
DEFAULT_SHARE = 0.5


def repair_overlaps(
    problem: Problem,
    candidate: Candidate,
    *,
    iterations: int = 40,
    share: float = DEFAULT_SHARE,
    origin: str = "repair_overlaps",
) -> Candidate:
    """Move overlapping shapes apart, and overflowing shapes back inside the arena.

    One pass asks the engine where the conflicts are. Both shapes of every
    overlapping pair are pushed along the reported axis, each absorbing ``share``
    of the depth in opposite directions; a shape that leaves the arena takes the
    whole translation back to the wall, since the wall does not move.

    The displacement of a shape is the *sum* of the pushes its conflicts ask for,
    not a sequence of moves: a shape pinned between two neighbours has to move
    once, in the direction the two pushes agree on.

    A pass is kept when it makes the candidate valid or lowers the total severity
    of its violations — the one thing a repair is for. It is not asked to keep the
    score: separating two shapes can grow the container they are measured in, and
    a repair that refused that price could never make such a candidate valid. The
    walk stops at the first pass that does not help, since the pass is a function
    of the state and the next one would be the same; ``iterations`` only bounds the
    work.
    """
    if iterations < 1:
        return candidate
    if not 0.0 < share <= 1.0:
        raise ValueError(f"share must be in (0, 1], got {share!r}")
    best = candidate
    best_evaluation: Evaluation = evaluate(problem, candidate, with_metrics=False)
    for _ in range(iterations):
        if best_evaluation.valid:
            break
        pushes = _separation_pushes(problem, best, share)
        if not pushes:
            break
        trial = displace(best, moves=pushes, origin=origin)
        trial_evaluation = evaluate(problem, trial, with_metrics=False)
        if not (
            trial_evaluation.valid
            or trial_evaluation.validation.severity < best_evaluation.validation.severity
        ):
            break
        best, best_evaluation = trial, trial_evaluation
    return best


def _separation_pushes(
    problem: Problem, candidate: Candidate, share: float
) -> dict[str, tuple[float, float]]:
    """Return, per shape, the displacement the reported conflicts ask for.

    The axes and depths come from the engine, in the domain's own units; nothing
    here recomputes them. A pair the geometry façade reports with a depth of
    exactly zero — two shapes that touch — is not in the list at all, so an exact
    packing is left alone.
    """
    facts = facts_for(problem, candidate)
    pushes: dict[str, list[float]] = {}
    for overlap in facts.overlaps:
        step = share * overlap.depth
        dx, dy = overlap.direction
        for shape_id, sign in ((overlap.first, -1.0), (overlap.second, 1.0)):
            current = pushes.setdefault(shape_id, [0.0, 0.0])
            current[0] += sign * step * dx
            current[1] += sign * step * dy
    for record in facts.containment:
        if record.inward is not None and record.inward != (0.0, 0.0):
            current = pushes.setdefault(record.shape_id, [0.0, 0.0])
            current[0] += record.inward[0]
            current[1] += record.inward[1]
    return {shape_id: (value[0], value[1]) for shape_id, value in pushes.items()}
