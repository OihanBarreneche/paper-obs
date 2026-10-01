"""Mutation operators: what moves, what is left alone, and what is refused.

Every assertion reads the placements or asks the engine. What matters is that a
jitter moves only what it was asked to and stays inside its amplitude, that a
removal drops the shapes the validator reported as colliding, and that a reseed
refuses the anchors the arena refuses — not that a particular loop ran.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest

from paper_obs.domain import (
    Arena,
    Candidate,
    Circle,
    MaximizeScale,
    Placement,
    Problem,
)
from paper_obs.geometry import validate
from paper_obs.search import (
    displace,
    grid_initialize,
    jitter,
    remove_shapes,
    reseed_region,
    translate_cluster,
)

SEED = 39182


def _circle_problem(count: int = 4) -> Problem:
    """Four circles in a 10 x 10 square, whose balanced grid is 2 x 2 at scale 5."""
    return Problem(
        problem_id=f"mutation-{count}",
        arena=Arena.rectangle(10.0, 10.0),
        shape=Circle(),
        objective=MaximizeScale(count=count),
        seed=SEED,
    )


def _gridded() -> tuple[Problem, Candidate]:
    """Return the reference problem and its valid lattice, anchors at (+-2.5, +-2.5)."""
    problem = _circle_problem()
    return problem, grid_initialize(problem)


def _overlapping(problem: Problem, grid: Candidate) -> Candidate:
    """Return a candidate whose first two shapes collide and whose last two do not."""
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


def test_a_jitter_of_zero_amplitude_returns_the_same_placements() -> None:
    problem, grid = _gridded()
    shaken = jitter(problem, grid, amplitude=0.0)
    assert shaken.placements == grid.placements
    assert shaken.scale == grid.scale


def test_a_jitter_displaces_only_the_number_of_shapes_asked_for() -> None:
    problem, grid = _gridded()
    shaken = jitter(problem, grid, amplitude=0.4, count=2)
    moved = [p.shape_id for p, q in zip(shaken.placements, grid.placements) if p != q]
    assert len(moved) == 2


def test_a_jitter_displaces_every_shape_by_default() -> None:
    problem, grid = _gridded()
    shaken = jitter(problem, grid, amplitude=0.4)
    assert all(p != q for p, q in zip(shaken.placements, grid.placements))


def test_a_jitter_stays_within_its_amplitude() -> None:
    problem, grid = _gridded()
    shaken = jitter(problem, grid, amplitude=0.4)
    for before, after in zip(grid.placements, shaken.placements):
        assert abs(after.x - before.x) <= 0.4
        assert abs(after.y - before.y) <= 0.4
        assert after.rotation == before.rotation
        assert after.scale == before.scale


def test_a_jitter_uses_the_problem_seed_by_default() -> None:
    problem, grid = _gridded()
    assert jitter(problem, grid, amplitude=0.4).placements == jitter(
        problem, grid, amplitude=0.4
    ).placements
    explicit = jitter(problem, grid, amplitude=0.4, generator=np.random.default_rng(problem.seed))
    assert explicit.placements == jitter(problem, grid, amplitude=0.4).placements


def test_a_jitter_refuses_more_shapes_than_the_candidate_has() -> None:
    problem, grid = _gridded()
    with pytest.raises(ValueError, match="count must be between"):
        jitter(problem, grid, amplitude=0.1, count=5)


def test_a_negative_amplitude_is_refused() -> None:
    problem, grid = _gridded()
    with pytest.raises(ValueError, match="must not be negative"):
        jitter(problem, grid, amplitude=-0.1)


def test_translate_cluster_moves_the_group_and_leaves_the_others_alone() -> None:
    problem, grid = _gridded()
    moved = translate_cluster(problem, grid, shape_ids=["s000", "s002"], dx=1.5, dy=-0.5)
    assert moved.placements[0] == Placement("s000", -1.0, -3.0)
    assert moved.placements[2] == Placement("s002", -1.0, 2.0)
    assert moved.placements[1] == grid.placements[1]
    assert moved.placements[3] == grid.placements[3]


def test_translate_cluster_refuses_a_shape_that_is_not_there() -> None:
    problem, grid = _gridded()
    with pytest.raises(ValueError, match="has no shape"):
        translate_cluster(problem, grid, shape_ids=["gone"], dx=1.0, dy=1.0)


def test_displace_refuses_an_empty_group() -> None:
    _, grid = _gridded()
    with pytest.raises(ValueError, match="at least one shape"):
        displace(grid, moves={}, origin="test")


def test_a_moved_placement_keeps_its_rotation_its_local_scale_and_its_colour() -> None:
    _, grid = _gridded()
    branded = grid.derive(
        placements=(
            Placement("s000", 0.0, 0.0, rotation=45.0, scale=1.0, color="#ff8800"),
            Placement("s001", 3.0, 0.0),
        ),
        origin="test",
    )
    moved = displace(branded, moves={"s000": (1.0, 2.0)}, origin="test")
    assert moved.placements[0] == Placement(
        "s000", 1.0, 2.0, rotation=45.0, scale=1.0, color="#ff8800"
    )
    assert moved.placements[1] == branded.placements[1]


def test_remove_shapes_prefers_the_shapes_the_engine_reports_as_overlapping() -> None:
    problem, grid = _gridded()
    broken = _overlapping(problem, grid)
    assert len(validate(problem, broken).collisions) == 1
    thinned = remove_shapes(problem, broken, count=1)
    assert set(broken.shape_ids) - set(thinned.shape_ids) <= {"s000", "s001"}
    assert thinned.n_shapes == 3


def test_remove_shapes_never_creates_an_overlap() -> None:
    problem, grid = _gridded()
    assert validate(problem, grid).collisions == ()
    thinned = remove_shapes(problem, grid, count=2)
    assert thinned.n_shapes == 2
    assert len(validate(problem, thinned).collisions) <= len(validate(problem, grid).collisions)


def test_remove_shapes_is_reproducible_from_the_problem_seed() -> None:
    problem, grid = _gridded()
    assert remove_shapes(problem, grid, count=3).placements == remove_shapes(
        problem, grid, count=3
    ).placements


def test_remove_shapes_refuses_to_drop_more_shapes_than_there_are() -> None:
    problem, grid = _gridded()
    with pytest.raises(ValueError, match="count must be between"):
        remove_shapes(problem, grid, count=9)


def test_reseed_region_replaces_only_the_anchors_inside_the_box() -> None:
    problem, grid = _gridded()
    reseeded = reseed_region(problem, grid, region=(-5.0, -5.0, 0.0, 0.0), count=2)
    # Only the lower-left anchor, s000 at (-2.5, -2.5), belongs to that quadrant.
    assert "s000" not in reseeded.shape_ids
    assert {"s001", "s002", "s003"} <= set(reseeded.shape_ids)
    fresh = [shape_id for shape_id in reseeded.shape_ids if shape_id not in grid.shape_ids]
    assert len(fresh) == 2


def test_reseed_region_keeps_the_shapes_it_cannot_replace() -> None:
    problem, grid = _gridded()
    reseeded = reseed_region(problem, grid, region=(100.0, 100.0, 200.0, 200.0), count=3)
    assert reseeded.placements == grid.placements


def test_reseed_region_is_reproducible_from_the_problem_seed() -> None:
    problem, grid = _gridded()
    region = (-5.0, -5.0, 0.0, 0.0)
    assert reseed_region(problem, grid, region=region, count=2).placements == reseed_region(
        problem, grid, region=region, count=2
    ).placements


def test_reseed_region_refuses_a_degenerate_box() -> None:
    problem, grid = _gridded()
    with pytest.raises(ValueError, match="min < max"):
        reseed_region(problem, grid, region=(0.0, 0.0, 0.0, 5.0), count=1)


@pytest.mark.parametrize(
    ("origin", "apply"),
    [
        ("jitter", lambda p, c: jitter(p, c, amplitude=0.25)),
        (
            "translate_cluster",
            lambda p, c: translate_cluster(p, c, shape_ids=["s000"], dx=0.25, dy=0.25),
        ),
        ("remove_shapes", lambda p, c: remove_shapes(p, c, count=1)),
        (
            "reseed_region",
            lambda p, c: reseed_region(p, c, region=(-5.0, -5.0, 0.0, 0.0), count=1),
        ),
    ],
)
def test_every_mutation_links_its_parent_and_names_itself(
    origin: str, apply: Callable[[Problem, Candidate], Candidate]
) -> None:
    problem, grid = _gridded()
    child = apply(problem, grid)
    assert child.problem_id == problem.problem_id
    assert child.parents == (grid.candidate_id,)
    assert child.generation == grid.generation + 1
    assert child.origin == origin
    assert child.scale == grid.scale
    assert len(set(child.shape_ids)) == child.n_shapes
