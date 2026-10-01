"""Polish: a hill climb whose step follows the objective, and never walks downhill.

The tool battery in ``tests/agent_tools`` checks that every objective improves a loose
start; this file checks what the operators promise to any caller.
"""

from __future__ import annotations

import numpy as np
import pytest

from paper_obs.domain import (
    Arena,
    Candidate,
    Circle,
    CoverRegion,
    MaximizeScale,
    Placement,
    Problem,
    RegularPolygon,
    RotationMode,
    RotationPolicy,
    square,
)
from paper_obs.domain.objectives import _OBJECTIVE_BUILDERS
from paper_obs.geometry import evaluate
from paper_obs.search.operators import cover_initialize, fit_cover_scale, jitter, polish
from paper_obs.search.operators.polish import STEPS

SEED = 7


def _touching_circles() -> tuple[Problem, Candidate]:
    """Four discs that already touch each other and the walls: nothing is left to gain."""
    problem = Problem("polish-tight", Arena.rectangle(10.0, 10.0), Circle(), MaximizeScale(count=4), seed=SEED)
    candidate = Candidate(
        candidate_id="tight", problem_id=problem.problem_id, scale=5.0,
        placements=tuple(Placement(f"s{i:03d}", x, y) for i, (x, y) in
                         enumerate(((-2.5, -2.5), (2.5, -2.5), (-2.5, 2.5), (2.5, 2.5)))),
    )
    return problem, candidate


def test_every_objective_of_the_lab_has_a_polish_step() -> None:
    assert set(STEPS) == set(_OBJECTIVE_BUILDERS)


def test_polish_hands_back_the_input_itself_when_nothing_is_better() -> None:
    problem, candidate = _touching_circles()
    assert polish(problem, candidate, iterations=5, generator=np.random.default_rng(1)) is candidate


def test_polish_returns_a_child_of_its_input_when_it_improves() -> None:
    problem, tight = _touching_circles()
    loose = tight.derive(scale=3.0)
    polished = polish(problem, loose, iterations=3, generator=np.random.default_rng(1))
    assert polished.parents == (loose.candidate_id,) and polished.origin == "polish"
    assert evaluate(problem, polished).rank_key() > evaluate(problem, loose).rank_key()


def test_fit_cover_scale_lands_on_the_smallest_scale_that_covers() -> None:
    problem = Problem("fit-cover", Arena.disk(1.0), square(), CoverRegion(count=2),
                      rotation=RotationPolicy(mode=RotationMode.FREE))
    start = cover_initialize(problem)
    loose = start.derive(scale=start.scale * 1.5)
    fitted = fit_cover_scale(problem, loose)
    assert evaluate(problem, fitted).valid and fitted.scale < loose.scale
    assert not evaluate(problem, fitted.derive(scale=fitted.scale * (1 - 1e-4))).valid


def test_fit_cover_scale_grows_copies_that_do_not_cover_yet() -> None:
    problem = Problem("grow-cover", Arena.disk(1.0), square(), CoverRegion(count=2),
                      rotation=RotationPolicy(mode=RotationMode.FREE))
    start = cover_initialize(problem)
    short = start.derive(scale=start.scale * 0.5)
    assert not evaluate(problem, short).valid
    assert evaluate(problem, fit_cover_scale(problem, short)).valid


def test_a_jitter_without_turn_replays_as_before_and_one_with_turn_stays_in_bounds() -> None:
    problem, candidate = _touching_circles()
    plain = jitter(problem, candidate, amplitude=0.1, generator=np.random.default_rng(3))
    again = jitter(problem, candidate, amplitude=0.1, generator=np.random.default_rng(3), turn=0.0)
    assert plain.placements == again.placements
    turned = jitter(problem, candidate, amplitude=0.0, generator=np.random.default_rng(3), turn=12.0)
    assert all(abs(item.rotation) <= 12.0 for item in turned.placements)
    assert any(item.rotation != 0.0 for item in turned.placements)


@pytest.mark.parametrize(("shape", "period"), [(Circle(), 0.0), (RegularPolygon(sides=5), 72.0), (square(), 90.0)])
def test_a_shape_reports_the_rotation_that_maps_it_onto_itself(shape, period) -> None:
    assert shape.symmetry_period == pytest.approx(period)
