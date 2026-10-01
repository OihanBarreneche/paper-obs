"""Relaxation operators: what they squeeze out, and what they refuse to lose.

The two properties worth asserting are asymmetric. ``increase_scale`` must find a
scale the *validator* accepts and never exceed the bound it was given, and
``local_relax`` must never hand back a candidate the engine ranks below its
input. Both are read through ``Evaluation``, never through arithmetic copied from
the operator.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from paper_obs.domain import (
    Arena,
    Candidate,
    Circle,
    MaximizeCount,
    MaximizeScale,
    Placement,
    Problem,
)
from paper_obs.geometry import evaluate, scale_bounds
from paper_obs.search import (
    compact,
    contract_scale,
    fit_layout_scale,
    grid_initialize,
    grow_sizes,
    increase_scale,
    jitter,
    local_relax,
    random_initialize,
)


def _free_sizes_problem(count: int = 2) -> Problem:
    """Circles sized one by one inside a unit disc: the total-perimeter family.

    Its objective fixes the common scale at 1 and scores the sum of the copies' own sizes,
    so the only lever an operator may pull is the local scale of a placement.
    """
    return Problem.from_dict({
        "problem_id": "free-sizes",
        "shape": {"type": "circle", "radius": 1.0},
        "objective": {"type": "maximize_total_perimeter", "count": count},
        "rotation": {"type": "rotation_policy", "mode": "free", "angles": [0.0]},
        "constraints": [],
        "arena": {"name": "", "shape": {"type": "disk", "radius": 1.0}},
    })


def _sized(problem: Problem, scales: tuple[float, ...]) -> Candidate:
    """A candidate whose copies sit either side of the centre, each at its own size."""
    spread = 0.25
    return Candidate(
        candidate_id="free", problem_id=problem.problem_id, scale=1.0,
        placements=tuple(
            Placement(f"s{index:03d}", -spread + index * 2 * spread, 0.0, 0.0, scale)
            for index, scale in enumerate(scales)
        ),
    )


def test_grow_sizes_enlarges_one_named_copy_and_leaves_the_others_alone() -> None:
    problem = _free_sizes_problem(count=2)
    start = _sized(problem, (0.2, 0.2))
    grown = grow_sizes(problem, start, shape_id="s000")

    before = evaluate(problem, start, with_metrics=True)
    after = evaluate(problem, grown, with_metrics=True)
    assert after.valid, "a grown copy the engine refuses is never returned"
    assert grown.placements[0].scale > 0.2
    assert grown.placements[1].scale == 0.2
    assert after.metrics["total_scale"] > before.metrics["total_scale"]


def test_grow_sizes_inflates_every_copy_keeping_its_proportions() -> None:
    problem = _free_sizes_problem(count=2)
    start = _sized(problem, (0.1, 0.2))
    grown = grow_sizes(problem, start)

    assert evaluate(problem, grown).valid
    assert grown.placements[0].scale > 0.1
    assert grown.placements[0].scale / grown.placements[1].scale == pytest.approx(0.5, rel=1e-6)


def test_grow_sizes_leaves_a_candidate_without_local_sizes_untouched() -> None:
    """A common-scale family has nothing here to grow: the objective owns that number."""
    problem = _circle_problem(count=2)
    start = Candidate(candidate_id="grid", problem_id=problem.problem_id, scale=1,
                      placements=(Placement("s000", -3, 0), Placement("s001", 3, 0)))
    assert grow_sizes(problem, start) is start
    assert grow_sizes(problem, start, shape_id="s000") is start


def test_grow_sizes_refuses_a_shape_the_candidate_does_not_hold() -> None:
    problem = _free_sizes_problem(count=2)
    with pytest.raises(KeyError):
        grow_sizes(problem, _sized(problem, (0.2, 0.2)), shape_id="s999")


def test_compact_moves_a_loose_pair_inward_without_losing_validity() -> None:
    problem = _circle_problem(count=2)
    start = Candidate(candidate_id="loose", problem_id=problem.problem_id, scale=1,
                      placements=(Placement("s000", -3, 0), Placement("s001", 3, 0)))
    result = compact(problem, start, factor=0.1, passes=3)
    assert evaluate(problem, result).valid
    assert result.placements[0].x > -3
    assert result.placements[1].x < 3
from paper_obs.storage import load_problem

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"

SEED = 39182


@pytest.fixture(scope="module")
def reference() -> Problem:
    """The reference instance: 25 circles whose optimal arrangement is the 5 x 5 grid."""
    return load_problem(EXAMPLES / "circle_25_in_square.json")


def _circle_problem(count: int = 4) -> Problem:
    """Four circles in a 10 x 10 square."""
    return Problem(
        problem_id=f"relaxation-{count}",
        arena=Arena.rectangle(10.0, 10.0),
        shape=Circle(),
        objective=MaximizeScale(count=count),
        seed=SEED,
    )


def _overlapping(problem: Problem, grid: Candidate) -> Candidate:
    """Return a valid-scale candidate whose first two shapes collide."""
    return grid.derive(
        scale=2.0,
        placements=(
            Placement("s000", 0.0, 0.0),
            Placement("s001", 1.0, 0.0),
            Placement("s002", 3.0, 0.0),
            Placement("s003", -3.0, 0.0),
        ),
        origin="test",
    )


def test_increase_scale_leaves_an_optimal_packing_untouched(reference: Problem) -> None:
    grid = grid_initialize(reference)
    assert grid.scale == pytest.approx(2.0)
    assert increase_scale(reference, grid) is grid


def test_increase_scale_grows_a_shrunken_packing_back_to_its_best(reference: Problem) -> None:
    grid = grid_initialize(reference)
    shrunken = grid.derive(scale=1.0, origin="test")
    grown = increase_scale(reference, shrunken)
    assert grown.scale > shrunken.scale
    assert grown.scale == pytest.approx(2.0, abs=1e-6)
    assert grown.scale <= scale_bounds(reference).high
    assert evaluate(reference, grown).valid
    assert grown.placements == shrunken.placements


def test_increase_scale_improves_a_loose_candidate_and_stays_valid(reference: Problem) -> None:
    start = random_initialize(reference)
    grown = increase_scale(reference, start)
    assert grown.scale > start.scale
    assert evaluate(reference, grown).valid


def test_increase_scale_never_passes_the_upper_bound_it_was_given(reference: Problem) -> None:
    shrunken = grid_initialize(reference).derive(scale=1.0, origin="test")
    grown = increase_scale(reference, shrunken, upper=1.5)
    assert 1.5 - 1e-6 <= grown.scale <= 1.5
    assert evaluate(reference, grown).valid


def test_increase_scale_cannot_grow_a_scale_the_objective_fixes() -> None:
    problem = Problem(
        problem_id="fixed-scale",
        arena=Arena.rectangle(10.0, 10.0),
        shape=Circle(),
        objective=MaximizeCount(scale=1.0),
        seed=SEED,
    )
    candidate = grid_initialize(problem)
    assert evaluate(problem, candidate).valid
    assert increase_scale(problem, candidate) is candidate


def test_increase_scale_leaves_an_invalid_candidate_alone() -> None:
    problem = _circle_problem()
    broken = _overlapping(problem, grid_initialize(problem))
    assert increase_scale(problem, broken) is broken


def test_increase_scale_links_the_child_it_grows(reference: Problem) -> None:
    shrunken = grid_initialize(reference).derive(scale=1.0, origin="test")
    grown = increase_scale(reference, shrunken)
    assert grown.problem_id == reference.problem_id
    assert grown.parents == (shrunken.candidate_id,)
    assert grown.generation == shrunken.generation + 1
    assert grown.origin == "increase_scale"


def test_local_relax_never_returns_a_candidate_the_engine_ranks_lower() -> None:
    problem = _circle_problem()
    grid = grid_initialize(problem)
    for candidate in (grid, _overlapping(problem, grid)):
        relaxed = local_relax(problem, candidate, iterations=25, amplitude=0.5)
        assert evaluate(problem, relaxed).rank_key() >= evaluate(problem, candidate).rank_key()


def test_local_relax_repairs_a_broken_candidate_at_the_same_scale() -> None:
    problem = _circle_problem()
    broken = _overlapping(problem, grid_initialize(problem))
    relaxed = local_relax(problem, broken, iterations=60, amplitude=1.0)
    assert relaxed is not broken
    assert evaluate(problem, relaxed).valid
    assert relaxed.scale == broken.scale
    # An accepted move descends from the accepted one before it, so the result is a
    # descendant of the broken candidate rather than necessarily its direct child.
    assert len(relaxed.parents) == 1
    assert relaxed.generation > broken.generation
    assert relaxed.origin == "local_relax"
    assert relaxed.problem_id == problem.problem_id


def test_local_relax_without_iterations_is_the_identity() -> None:
    problem = _circle_problem()
    grid = grid_initialize(problem)
    assert local_relax(problem, grid, iterations=0, amplitude=1.0) is grid


def test_local_relax_is_reproducible_from_the_problem_seed() -> None:
    problem = _circle_problem()
    broken = _overlapping(problem, grid_initialize(problem))
    first = local_relax(problem, broken, iterations=40, amplitude=1.0)
    second = local_relax(problem, broken, iterations=40, amplitude=1.0)
    assert first.placements == second.placements


def test_contracting_the_scale_keeps_the_arrangement() -> None:
    """The lever that a wall-tight packing needs: room bought with scale."""
    problem = _circle_problem()
    grid = grid_initialize(problem)
    smaller = contract_scale(problem, grid)
    assert smaller.scale == pytest.approx(grid.scale * 0.95)
    assert smaller.placements == grid.placements, "the anchors do not move, only the shapes"
    assert smaller.origin == "contract_scale"
    assert smaller.parents == (grid.candidate_id,)


def test_a_contraction_stops_at_the_problems_own_floor() -> None:
    problem = _circle_problem()
    grid = grid_initialize(problem)
    bottom = scale_bounds(problem).low
    assert contract_scale(problem, grid, factor=0.001).scale == pytest.approx(bottom)
    at_floor = contract_scale(problem, grid, factor=0.001)
    assert contract_scale(problem, at_floor) is at_floor


def test_a_contraction_opens_room_for_a_wall_tight_packing() -> None:
    """What a repair alone cannot do: an overlap inside a full arena has nowhere to go."""
    problem = _circle_problem(count=25)
    shaken = jitter(problem, grid_initialize(problem), amplitude=0.4)
    before = evaluate(problem, shaken)
    after = evaluate(problem, contract_scale(problem, shaken))
    assert not before.valid and not after.valid
    assert after.validation.severity < before.validation.severity
    assert after.score.primary < before.score.primary, "room costs scale, and the score says so"


def test_a_factor_outside_the_unit_interval_is_refused() -> None:
    problem = _circle_problem()
    grid = grid_initialize(problem)
    for factor in (0.0, 1.0, 1.5):
        with pytest.raises(ValueError, match="factor must be in"):
            contract_scale(problem, grid, factor=factor)


def _layout_problem() -> Problem:
    """Four unit discs in a 4 x 4 square: a 2 x 2 layout reaches scale 1 exactly."""
    return Problem(
        "layout-square",
        Arena.rectangle(4.0, 4.0),
        Circle(),
        MaximizeScale(count=4),
        seed=1,
    )


def test_fit_layout_scale_grows_a_layout_about_the_origin() -> None:
    """The anchors move with the scale: this fits a layout, not a set of copies."""
    problem = _layout_problem()
    corners = ((-1.0, -1.0), (1.0, -1.0), (-1.0, 1.0), (1.0, 1.0))
    seeded = Candidate(
        "reading",
        problem.problem_id,
        scale=0.25,
        placements=tuple(
            Placement(f"s{index:03d}", x * 0.25, y * 0.25) for index, (x, y) in enumerate(corners)
        ),
    )
    assert evaluate(problem, seeded).valid
    grown = fit_layout_scale(problem, seeded)
    after = evaluate(problem, grown)
    assert after.valid
    assert after.primary > evaluate(problem, seeded).primary
    # Growing the layout as one keeps the reading: the far corner is still the far corner.
    assert grown.placements[3].x == pytest.approx(grown.placements[3].y, rel=1e-9)
    assert grown.placements[3].x > grown.placements[0].x


def test_fit_layout_scale_leaves_an_invalid_layout_alone() -> None:
    """No scale is known to be good for a broken reading, so none is guessed."""
    problem = _layout_problem()
    overlapping = Candidate(
        "overlapping",
        problem.problem_id,
        scale=0.5,
        placements=(Placement("s000", 0.0, 0.0), Placement("s001", 0.2, 0.0)),
    )
    assert not evaluate(problem, overlapping).valid
    assert fit_layout_scale(problem, overlapping) is overlapping
