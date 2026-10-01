"""Polish: tune the numbers of an arrangement while keeping its topology.

Deciding *which* arrangement to try — which shape sits next to which, turned which way,
which copy is the big one — is the creative half of a packing. Getting the last percent out
of it is continuous work: sliding every shape by a hair, trading size between copies,
closing a gap without opening an overlap. This operator does that half, with the move each
objective needs, and the engine judges every step.

:func:`polish` is a hill climb. Each step proposes a neighbour of the best arrangement so
far, and the neighbour replaces it only when :meth:`Evaluation.is_better_than` prefers it,
so the result is never ranked below the input. Randomness goes through the caller's
generator, so a seeded call replays exactly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import numpy as np

from paper_obs.domain.candidate import Candidate
from paper_obs.domain.constraints import RotationMode
from paper_obs.domain.problem import Problem
from paper_obs.geometry.engine import evaluate, validate

from .mutation import jitter, remove_shapes
from .relaxation import _largest_valid, fit_cover_scale, grow_sizes, increase_scale
from .repair import repair_overlaps
from .void_fill import fill_void

#: Separation passes a step may spend repairing what it broke.
REPAIR_PASSES = 40

#: Share of the steps that also turn one or two copies, where rotation is free.
TURN_SHARE = 0.5

#: Range of the factor a squeeze keeps of every distance to the centre.
SQUEEZE = (0.9, 0.998)

#: Range of the scale a stretch asks for, and the contraction that walks it back down.
STRETCH = (1.001, 1.02)
CONTRACTION = 0.997
DESCENT_ROUNDS = 6

#: Range of the factors a size trade grows one copy by and shrinks another by.
GROW = (1.02, 1.3)
SHRINK = (0.6, 0.98)

#: Smallest common factor :func:`_fit_sizes` shrinks every copy by to make room.
MIN_SIZE_FACTOR = 0.5

Step = Callable[[Problem, Candidate, np.random.Generator], Candidate]


def polish(
    problem: Problem,
    candidate: Candidate,
    *,
    iterations: int = 40,
    generator: np.random.Generator | None = None,
    origin: str = "polish",
) -> Candidate:
    """Return the best arrangement a short local search reaches from ``candidate``.

    The first proposal settles the input — a repair for a packing, the smallest covering
    scale for a covering — so a broken arrangement is worth polishing; every later one is the
    objective's own step (:data:`STEPS`). ``iterations`` bounds the steps, each of which costs
    from a handful to a few dozen engine calls. The input itself comes back when nothing was
    preferred; otherwise a child of it, so the genealogy skips the discarded trials.
    """
    if iterations < 1 or candidate.n_shapes == 0:
        return candidate
    rng = generator if generator is not None else np.random.default_rng(problem.seed)
    step = STEPS[problem.objective.kind]
    best, best_evaluation = candidate, evaluate(problem, candidate, with_metrics=False)
    for index in range(iterations):
        trial = _settle(problem, best, rng) if index == 0 else step(problem, best, rng)
        trial_evaluation = evaluate(problem, trial, with_metrics=False)
        if trial_evaluation.is_better_than(best_evaluation):
            best, best_evaluation = trial, trial_evaluation
    if best is candidate:
        return candidate
    return candidate.derive(placements=best.placements, scale=best.scale, origin=origin)


def _settle(problem: Problem, candidate: Candidate, rng: np.random.Generator) -> Candidate:
    """Bring the input to the nearest arrangement the objective can score as valid."""
    kind = problem.objective.kind
    if kind == "cover_region":
        return fit_cover_scale(problem, candidate)
    if kind == "maximize_covered_size":
        return candidate
    repaired = repair_overlaps(problem, candidate, iterations=REPAIR_PASSES, origin="polish")
    if kind == "maximize_scale":
        return increase_scale(problem, repaired)
    if kind == "maximize_total_perimeter":
        return _fit_sizes(problem, repaired, rng)
    return repaired


def _squeeze(problem: Problem, candidate: Candidate, rng: np.random.Generator) -> Candidate:
    """Container: pull every copy towards the middle, sometimes turn one, then repair."""
    trial = _turned(problem, candidate, rng)
    trial = _squeezed(trial, float(rng.uniform(*SQUEEZE)))
    return repair_overlaps(problem, trial, iterations=REPAIR_PASSES, origin="polish")


def _stretch(problem: Problem, candidate: Candidate, rng: np.random.Generator) -> Candidate:
    """Common scale: ask for more scale than fits, repair into it, keep the largest that holds."""
    size = problem.shape.circumradius(candidate.scale)
    trial = jitter(
        problem, _turned(problem, candidate, rng), amplitude=0.02 * size, generator=rng,
        count=max(1, candidate.n_shapes // 4), origin="polish",
    )
    trial = trial.derive(scale=trial.scale * float(rng.uniform(*STRETCH)))
    for _ in range(DESCENT_ROUNDS):
        trial = repair_overlaps(problem, trial, iterations=REPAIR_PASSES, origin="polish")
        if validate(problem, trial).valid:
            return increase_scale(problem, trial)
        trial = trial.derive(scale=trial.scale * CONTRACTION)
    return trial


def _trade(problem: Problem, candidate: Candidate, rng: np.random.Generator) -> Candidate:
    """Free sizes: grow one copy, shrink another, shake, repair, then regrow every copy."""
    placements = list(candidate.placements)
    if len(placements) < 2:
        return _fit_sizes(problem, candidate, rng)
    grown, shrunk = (int(index) for index in rng.choice(len(placements), size=2, replace=False))
    sizes = [item.resolved_scale(candidate.scale) for item in placements]
    placements[grown] = replace(placements[grown], scale=sizes[grown] * float(rng.uniform(*GROW)))
    placements[shrunk] = replace(placements[shrunk], scale=sizes[shrunk] * float(rng.uniform(*SHRINK)))
    trial = jitter(
        problem, candidate.derive(placements=placements), amplitude=0.05 * sizes[grown],
        generator=rng, count=int(rng.integers(1, len(placements) + 1)), origin="polish",
    )
    trial = repair_overlaps(problem, trial, iterations=REPAIR_PASSES, origin="polish")
    return _fit_sizes(problem, trial, rng)


def _shift(problem: Problem, candidate: Candidate, rng: np.random.Generator) -> Candidate:
    """Covering: move and turn a few copies, then take the smallest scale that still covers."""
    size = problem.shape.circumradius(candidate.scale)
    trial = jitter(
        problem, candidate, amplitude=float(rng.choice((0.02, 0.1))) * size, generator=rng,
        count=int(rng.integers(1, candidate.n_shapes + 1)), turn=_turn_amplitude(problem, rng),
        origin="polish",
    )
    return fit_cover_scale(problem, trial)


def _spread(problem: Problem, candidate: Candidate, rng: np.random.Generator) -> Candidate:
    """Derived covering: gather the copies, or move and turn one or two of them."""
    if rng.random() < 1.0 / 3.0:
        return _squeezed(candidate, float(rng.uniform(0.9, 0.99)))
    size = problem.shape.circumradius(candidate.scale)
    return jitter(
        problem, candidate, amplitude=0.05 * size, generator=rng,
        count=int(rng.integers(1, min(2, candidate.n_shapes) + 1)),
        turn=_turn_amplitude(problem, rng), origin="polish",
    )


def _fill(problem: Problem, candidate: Candidate, rng: np.random.Generator) -> Candidate:
    """Count: drop the most conflicted copy while broken, else try one more in a void."""
    if not validate(problem, candidate).valid:
        return remove_shapes(problem, candidate, count=1, generator=rng, origin="polish")
    try:
        return fill_void(problem, candidate, void_index=int(rng.integers(0, 3)), generator=rng)
    except ValueError:  # fewer voids than the index drawn
        return candidate


#: The step each objective climbs with. What stays free differs: positions for a container
#: or a derived covering, the common scale for a scale or a covering, each copy's size for a
#: total perimeter, and the count for a count.
STEPS: dict[str, Step] = {
    "minimize_container": _squeeze,
    "maximize_scale": _stretch,
    "maximize_total_perimeter": _trade,
    "cover_region": _shift,
    "maximize_covered_size": _spread,
    "maximize_count": _fill,
}


def _fit_sizes(problem: Problem, candidate: Candidate, rng: np.random.Generator) -> Candidate:
    """Shrink every copy by one factor until the engine accepts them, then regrow each in turn.

    The regrowth order is drawn, because the copy that grows first takes the room the others
    would have used. Placements the engine refuses even at :data:`MIN_SIZE_FACTOR` come back
    as they are.
    """
    sizes = [item.resolved_scale(candidate.scale) for item in candidate.placements]

    def resized(factor: float) -> Candidate:
        return candidate.derive(placements=[
            replace(item, scale=size * factor) for item, size in zip(candidate.placements, sizes)
        ])

    trial = candidate
    if not validate(problem, candidate).valid:
        if not validate(problem, resized(MIN_SIZE_FACTOR)).valid:
            return candidate
        trial = resized(_largest_valid(
            MIN_SIZE_FACTOR, 1.0, lambda factor: validate(problem, resized(factor)).valid, 20,
        ))
    for index in rng.permutation(trial.n_shapes):
        trial = grow_sizes(problem, trial, shape_id=trial.placements[int(index)].shape_id)
    return trial


def _turn_amplitude(problem: Problem, rng: np.random.Generator) -> float:
    """Return how far a step may turn a copy: nothing unless the rotation is free."""
    period = problem.shape.symmetry_period
    if problem.rotation.mode is not RotationMode.FREE or period <= 0.0:
        return 0.0
    # Half a period reaches every distinct orientation; a twelfth adjusts the one it has.
    return period / 2.0 if rng.random() < 0.5 else period / 12.0


def _turned(problem: Problem, candidate: Candidate, rng: np.random.Generator) -> Candidate:
    """Turn one or two copies in place, on :data:`TURN_SHARE` of the steps."""
    amplitude = _turn_amplitude(problem, rng)
    if amplitude <= 0.0 or rng.random() >= TURN_SHARE:
        return candidate
    count = int(rng.integers(1, min(2, candidate.n_shapes) + 1))
    return jitter(problem, candidate, amplitude=0.0, generator=rng, count=count, turn=amplitude,
                  origin="polish")


def _squeezed(candidate: Candidate, factor: float) -> Candidate:
    """Return the arrangement pulled towards its centroid, every distance times ``factor``."""
    centre_x = sum(item.x for item in candidate.placements) / candidate.n_shapes
    centre_y = sum(item.y for item in candidate.placements) / candidate.n_shapes
    return candidate.derive(placements=[
        item.moved(centre_x + (item.x - centre_x) * factor, centre_y + (item.y - centre_y) * factor)
        for item in candidate.placements
    ], origin="polish")


__all__ = ["STEPS", "polish"]
