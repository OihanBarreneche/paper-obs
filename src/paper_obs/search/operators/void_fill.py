"""Try locations inside one engine-reported empty region."""

from __future__ import annotations

import numpy as np

from paper_obs.domain.candidate import Candidate
from paper_obs.domain.placement import Placement
from paper_obs.domain.problem import Problem
from paper_obs.geometry.engine import analyze, evaluate


def fill_void(
    problem: Problem,
    candidate: Candidate,
    *,
    void_index: int = 0,
    move_shape_id: str | None = None,
    trials: int = 24,
    generator: np.random.Generator,
) -> Candidate:
    """Propose placements in a void and return the engine's highest-ranked trial.

    With a fixed-count objective, ``move_shape_id`` is required. With a count
    objective it may be omitted to add one shape. Invalid proposals are allowed;
    only the engine compares them. The centroid is tried first, then seeded
    points in the void's bounding box. No claim is made that every box point is
    inside the void: evaluation determines that.
    """
    if trials < 1:
        raise ValueError("trials must be positive")
    if move_shape_id is None and problem.objective.kind != "maximize_count":
        raise ValueError("move_shape_id is required for a fixed-count objective")
    if move_shape_id is not None and move_shape_id not in candidate.shape_ids:
        raise ValueError(f"unknown shape_id {move_shape_id!r}")
    voids = analyze(problem, candidate, void_limit=void_index + 1).voids
    if not 0 <= void_index < len(voids):
        raise ValueError(f"void_index {void_index} is unavailable; found {len(voids)} voids")
    void = voids[void_index]
    x0, y0, x1, y1 = void.bounds
    points = [void.centroid, *generator.uniform((x0, y0), (x1, y1), size=(trials - 1, 2))]
    current = evaluate(problem, candidate, with_metrics=False)
    best = candidate
    for x, y in points:
        if move_shape_id is None:
            used = set(candidate.shape_ids)
            index = candidate.n_shapes
            while f"s{index:03d}" in used:
                index += 1
            placements = (*candidate.placements, Placement(shape_id=f"s{index:03d}", x=float(x), y=float(y)))
        else:
            placements = tuple(
                item.moved(float(x), float(y)) if item.shape_id == move_shape_id else item
                for item in candidate.placements
            )
        trial = candidate.derive(placements=placements, origin="fill_void")
        verdict = evaluate(problem, trial, with_metrics=False)
        if verdict.is_better_than(current):
            best, current = trial, verdict
    return best
