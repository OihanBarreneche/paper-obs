"""A void can be acted on without guessing its world coordinates."""

import numpy as np
import pytest

from paper_obs.domain import Arena, Candidate, Circle, MaximizeCount, MaximizeScale, Placement, Problem
from paper_obs.geometry import evaluate
from paper_obs.search import fill_void


def test_fill_void_adds_a_valid_shape_for_a_count_objective() -> None:
    problem = Problem(problem_id="void-count", arena=Arena.rectangle(10, 10), shape=Circle(),
                      objective=MaximizeCount(scale=1), seed=7)
    start = Candidate(candidate_id="start", problem_id=problem.problem_id, scale=1, placements=())
    filled = fill_void(problem, start, generator=np.random.default_rng(7))
    assert filled.n_shapes == 1
    assert evaluate(problem, filled).valid
    assert evaluate(problem, filled).primary > evaluate(problem, start).primary


def test_fixed_count_requires_a_shape_to_move() -> None:
    problem = Problem(problem_id="void-scale", arena=Arena.rectangle(10, 10), shape=Circle(),
                      objective=MaximizeScale(count=1), seed=7)
    start = Candidate(candidate_id="start", problem_id=problem.problem_id, scale=1,
                      placements=(Placement("s000", 0, 0),))
    with pytest.raises(ValueError, match="move_shape_id"):
        fill_void(problem, start, generator=np.random.default_rng(7))
