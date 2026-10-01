"""Repair: what it fixes, what it refuses to lose, and where it stops.

The assertions go through the engine for the same reason the operator does: a
repair is only worth anything if ``evaluate`` agrees, and the property that makes
the walk safe — it never returns something more broken than its input — is read
from the engine's severity rather than from the perturbations it applied.
"""

from __future__ import annotations

import pytest

from paper_obs.domain import (
    Arena,
    Candidate,
    Circle,
    MaximizeScale,
    MinimizeContainer,
    Placement,
    Problem,
    RegularPolygon,
    RotationMode,
    RotationPolicy,
)
from paper_obs.geometry import evaluate
from paper_obs.search import grid_initialize, jitter, repair_overlaps

SEED = 39182


def _circle_problem(count: int = 4) -> Problem:
    """A few circles in a 10 x 10 square."""
    return Problem(
        problem_id=f"repair-{count}",
        arena=Arena.rectangle(10.0, 10.0),
        shape=Circle(),
        objective=MaximizeScale(count=count),
        seed=SEED,
    )


def _roomy_problem(count: int = 25) -> Problem:
    """The same circles in a 12 x 12 square: a 10 x 10 packing leaves a margin."""
    return Problem(
        problem_id=f"roomy-{count}",
        arena=Arena.rectangle(12.0, 12.0),
        shape=Circle(),
        objective=MaximizeScale(count=count),
        seed=SEED,
    )


def _overlapping(problem: Problem, grid: Candidate) -> Candidate:
    """Return a candidate whose first two shapes overlap by one unit of length."""
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


def test_repair_reaches_validity_on_a_pair_left_overlapping() -> None:
    problem = _circle_problem()
    broken = _overlapping(problem, grid_initialize(problem))
    assert not evaluate(problem, broken).valid
    repaired = repair_overlaps(problem, broken, iterations=60)
    assert repaired is not broken
    assert evaluate(problem, repaired).valid
    assert repaired.scale == broken.scale


def test_repair_returns_the_candidate_it_was_given_when_nothing_is_broken() -> None:
    problem = _circle_problem()
    grid = grid_initialize(problem)
    assert evaluate(problem, grid).valid
    assert repair_overlaps(problem, grid, iterations=50) is grid


def test_repair_never_returns_a_candidate_the_engine_ranks_lower() -> None:
    problem = _circle_problem()
    grid = grid_initialize(problem)
    shaken = jitter(problem, grid, amplitude=1.0)
    assert 0.0 < evaluate(problem, shaken).validation.severity
    repaired = repair_overlaps(problem, shaken, iterations=30)
    assert evaluate(problem, repaired).rank_key() >= evaluate(problem, shaken).rank_key()
    assert evaluate(problem, repaired).validation.severity <= evaluate(
        problem, shaken
    ).validation.severity


def test_repair_links_its_parent_and_names_itself() -> None:
    problem = _circle_problem()
    broken = _overlapping(problem, grid_initialize(problem))
    repaired = repair_overlaps(problem, broken, iterations=60)
    # Each accepted move descends from the accepted one before it, so the result is
    # a descendant of the broken candidate rather than necessarily its direct child.
    assert len(repaired.parents) == 1
    assert repaired.generation > broken.generation
    assert repaired.origin == "repair_overlaps"
    assert repaired.problem_id == problem.problem_id


def _shaken_lattice(problem: Problem, amplitude: float = 0.4) -> Candidate:
    """A 5 x 5 lattice with room around it, shaken: only overlaps are broken.

    Built by hand rather than with :func:`grid_initialize`, which fills its arena
    to the walls, so that this test is about overlaps alone. The lattice here spans
    8 x 8 in a 12 x 12 arena at scale 2.0, so an amplitude of 0.4 cannot reach a
    wall, and every violation left is an overlap.
    """
    placements = tuple(
        Placement(f"s{row * 5 + column:03d}", -4.0 + 2.0 * column, -4.0 + 2.0 * row)
        for row in range(5)
        for column in range(5)
    )
    lattice = Candidate(
        candidate_id="c-lattice", problem_id=problem.problem_id, scale=2.0, placements=placements
    )
    return jitter(problem, lattice, amplitude=amplitude)


def test_repair_untangles_a_shaken_lattice_without_guessing() -> None:
    """What a blind jitter could not do: the axis says where to push.

    The operator used to move a pair by a uniform offset drawn in
    ``[-amplitude, amplitude]`` and keep it when the engine agreed. On a lattice
    whose shapes all press on their neighbours that walk stalls — measured, 800
    iterations of it left a 25-disc lattice invalid. Pushing along the reported
    axis resolves the same lattice, so this is the contract that keeps the
    direction wired to the operator.
    """
    problem = _roomy_problem(count=25)
    shaken = _shaken_lattice(problem)
    broken = evaluate(problem, shaken)
    assert not broken.valid
    # The premise of the test: nothing but overlaps is broken.
    assert {result.constraint for result in broken.validation.results if not result.valid} == {
        "non_overlap"
    }
    repaired = repair_overlaps(problem, shaken, iterations=100)
    assert evaluate(problem, repaired).valid


def test_repair_without_iterations_is_the_identity() -> None:
    problem = _circle_problem()
    broken = _overlapping(problem, grid_initialize(problem))
    assert repair_overlaps(problem, broken, iterations=0) is broken


def test_a_share_outside_the_unit_interval_is_refused() -> None:
    problem = _circle_problem()
    broken = _overlapping(problem, grid_initialize(problem))
    for share in (0.0, -0.5, 1.5):
        with pytest.raises(ValueError, match="share must be in"):
            repair_overlaps(problem, broken, iterations=5, share=share)


def test_repair_brings_a_shape_that_leaves_the_arena_back_inside() -> None:
    """The wall does not move, so the shape takes the whole translation the engine reports."""
    problem = _circle_problem()
    grid = grid_initialize(problem)
    broken = grid.derive(scale=2.0, placements=(
        Placement("s000", -3.0, -3.0), Placement("s001", 3.0, -3.0),
        Placement("s002", -3.0, 3.0), Placement("s003", 4.6, 3.0),
    ), origin="test")
    assert not evaluate(problem, broken).valid
    repaired = repair_overlaps(problem, broken, iterations=10)
    assert evaluate(problem, repaired).valid
    assert repaired.scale == broken.scale


def test_repair_makes_a_minimised_container_valid_even_when_the_container_grows() -> None:
    """Separating shapes lowers a container's score; the repair pays that price for validity."""
    problem = Problem(
        problem_id="repair-container", arena=None, shape=RegularPolygon(sides=5),
        objective=MinimizeContainer(count=2), rotation=RotationPolicy(mode=RotationMode.FREE),
        seed=SEED,
    )
    touching = 2.0 * RegularPolygon(sides=5).inradius(1.0)
    broken = Candidate(
        candidate_id="broken", problem_id=problem.problem_id, scale=1.0,
        placements=(Placement("s000", 0.0, 0.0), Placement("s001", 0.0, -touching + 1e-3, 180.0)),
    )
    before = evaluate(problem, broken)
    repaired = repair_overlaps(problem, broken, iterations=20)
    after = evaluate(problem, repaired)
    assert not before.valid and after.valid
    assert after.primary <= before.primary
