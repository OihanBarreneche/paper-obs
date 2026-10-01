"""Initialization operators: what they produce, and what they refuse to produce.

The assertions go through the engine rather than through the operator's own
arithmetic: what matters is that a lattice comes out *valid*, at the scale the
geometry says it should be, not that a particular loop ran.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from paper_obs.domain import (
    Arena,
    Circle,
    CoverRegion,
    MaximizeCount,
    MaximizeScale,
    MaximizeTotalPerimeter,
    Placement,
    Problem,
    RegularPolygon,
    RotationMode,
    RotationPolicy,
    l_tromino,
    right_isosceles_triangle,
    square,
)
from paper_obs.geometry import evaluate, facts_for
from paper_obs.storage import load_problem
from paper_obs.search import (
    cover_initialize,
    grid_initialize,
    random_initialize,
    staggered_initialize,
    tight_lattice_scale,
    varied_initialize,
)

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def test_a_fill_asked_for_more_than_it_holds_keeps_the_objectives_scale() -> None:
    """The shrink ladder may not descend below a scale the objective fixes.

    The ladder exists for a free scale, where a smaller candidate is still a
    candidate. Where the objective fixes the common scale, every rung below it is a
    contradiction *that objective* refuses: a descent would trade a usable candidate
    for an unusable one — 171 shapes at 0.625 where the same request reaches 81 at
    1.0 — and the reason for the refusal would be the operator's own invention
    rather than the arrangement.
    """
    problem = load_problem(EXAMPLES / "triangles_in_holed_rect.json")
    candidate = grid_initialize(problem, count=200)
    assert candidate.scale == problem.objective.preset_scale()
    assert evaluate(problem, candidate).valid


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 5, 7])
def test_a_scatter_never_lands_below_a_scale_the_objective_fixes(seed: int) -> None:
    """A scatter that keeps too few shapes must not answer with a smaller scale.

    The random initializer reaches the same ladder whenever it draws fewer shapes
    than the objective asks for, which is most seeds — so on a container instance it
    used to answer every second request with a candidate the objective calls a
    contradiction, and the interface's own random button was unusable there.
    """
    problem = load_problem(EXAMPLES / "circles_17_in_smallest_square.json")
    candidate = random_initialize(problem, generator=np.random.default_rng(seed))
    assert candidate.scale == problem.objective.preset_scale()


def _gridded_circle_problem(count: int, arena: Arena | None = None) -> Problem:
    return Problem(
        problem_id=f"circles-{count}",
        arena=arena or Arena.rectangle(10.0, 10.0),
        shape=Circle(),
        objective=MaximizeScale(count=count),
    )


def test_a_grid_of_circles_lands_on_the_optimal_lattice() -> None:
    problem = _gridded_circle_problem(25)
    candidate = grid_initialize(problem)
    evaluation = evaluate(problem, candidate)
    assert candidate.n_shapes == 25
    assert candidate.scale == pytest.approx(2.0)
    assert evaluation.valid
    assert evaluation.metrics["density"] == pytest.approx(0.7854, abs=1e-4)


def test_a_grid_of_squares_tiles_the_arena(square_problem) -> None:
    candidate = grid_initialize(square_problem)
    evaluation = evaluate(square_problem, candidate)
    assert candidate.scale == pytest.approx(2.5)
    assert evaluation.valid
    assert evaluation.metrics["density"] == pytest.approx(1.0)


def test_a_lattice_that_does_not_fit_is_shrunk_until_it_does() -> None:
    problem = _gridded_circle_problem(25, arena=Arena.disk(5.0))
    candidate = grid_initialize(problem)
    facts = facts_for(problem, candidate)
    assert candidate.n_shapes == 25
    assert all(containment.inside for containment in facts.containment)
    assert facts.overlaps == ()
    assert candidate.scale < tight_lattice_scale(problem.arena.bounds, 1.0, 1.0, 25)


def test_a_fixed_scale_fills_the_arena_instead_of_resizing() -> None:
    problem = Problem(
        problem_id="fill",
        arena=Arena.rectangle(10.0, 10.0),
        shape=Circle(),
        objective=MaximizeCount(scale=2.0),
    )
    candidate = grid_initialize(problem)
    assert candidate.scale == pytest.approx(2.0)
    assert candidate.n_shapes == 25
    assert evaluate(problem, candidate).valid


def test_balancing_the_grid_beats_a_naive_square_block() -> None:
    problem = Problem(
        problem_id="wide",
        arena=Arena.rectangle(30.0, 10.0),
        shape=Circle(),
        objective=MaximizeScale(count=18),
    )
    candidate = grid_initialize(problem)
    # 6 columns of 3 rows use the width, a 5 x 4 block would waste it.
    assert candidate.scale == pytest.approx(min(30.0 / 6.0, 10.0 / 3.0))


def test_the_staggered_lattice_is_reserved_for_discs(square_problem) -> None:
    with pytest.raises(ValueError, match="only defined for discs"):
        staggered_initialize(square_problem)


def test_the_staggered_lattice_is_tight_enough_to_touch_its_neighbours() -> None:
    problem = _gridded_circle_problem(30, arena=Arena.rectangle(12.0, 10.0))
    candidate = staggered_initialize(problem)
    assert candidate.n_shapes == 30
    evaluation = evaluate(problem, candidate)
    assert evaluation.valid
    gaps = sorted(clearance.distance for clearance in facts_for(problem, candidate).clearances(slack=1e-3))
    assert gaps[0] == pytest.approx(0.0, abs=1e-9)


def test_random_initialization_is_reproducible_from_the_seed() -> None:
    problem = Problem(
        problem_id="seeded",
        arena=Arena.rectangle(10.0, 10.0),
        shape=Circle(),
        objective=MaximizeCount(scale=1.0),
        seed=1234,
    )
    first = random_initialize(problem)
    second = random_initialize(problem)
    assert first.placements == second.placements
    assert first.n_shapes > 0


def test_random_initialization_keeps_only_shapes_that_fit() -> None:
    problem = Problem(
        problem_id="disk-fill",
        arena=Arena.disk(5.0),
        shape=Circle(),
        objective=MaximizeCount(scale=2.0),
        seed=99,
    )
    candidate = random_initialize(problem)
    facts = facts_for(problem, candidate)
    assert all(containment.inside for containment in facts.containment)
    assert facts.overlaps == ()


def test_an_operator_records_its_origin_and_its_placements() -> None:
    problem = _gridded_circle_problem(4)
    candidate = grid_initialize(problem)
    assert candidate.origin == "grid"
    assert candidate.problem_id == problem.problem_id
    assert [placement.shape_id for placement in candidate.placements] == [
        "s000",
        "s001",
        "s002",
        "s003",
    ]


def test_a_single_shape_is_placed_at_the_centre_of_the_arena() -> None:
    problem = Problem(
        problem_id="one",
        arena=Arena.rectangle(10.0, 10.0),
        shape=square(),
        objective=MaximizeScale(count=1),
    )
    candidate = grid_initialize(problem)
    assert candidate.placements == (Placement("s000", 0.0, 0.0),)
    assert candidate.scale == pytest.approx(10.0)
    assert evaluate(problem, candidate).valid


# -- the catalogue's pointed and dense families, rebuilt from the domain ------


def _unit_polygon(sides: int) -> Arena:
    """The collection's unit arena for a regular polygon: one side long."""
    return Arena.regular_polygon(sides, 1.0 / (2.0 * math.sin(math.pi / sides)))


def _turned_outline(shape, *, scale: float = 1.0, angle: float = 0.0) -> Arena:
    """A custom outline as an arena, scaled and turned about the origin.

    The turn mirrors the catalogue's own workaround for a right triangle or an L,
    whose bounding-box centre falls on the boundary at their natural orientation.
    The initialiser must not depend on it: the same arenas are also exercised here
    through the placement search itself.
    """
    radians = math.radians(angle)
    cos, sin = math.cos(radians), math.sin(radians)
    points = [
        (x * cos - y * sin, x * sin + y * cos) for x, y in shape.vertices(scale)
    ]
    return Arena.polygon(points)


def _free_scale(arena: Arena, shape, count: int) -> Problem:
    """A fixed-count problem on a declared arena, the catalogue's template shape."""
    return Problem(
        problem_id=f"{shape.kind}-{count}",
        arena=arena,
        shape=shape,
        objective=MaximizeScale(count=count),
        seed=count,
    )


#: The eleven dense L counts the bounding-box lattice could never reach: the
#: octagon and domino instances whose published count sits above what the lattice
#: placed. They are the measured failure this operator was fixed for.
DENSE_L_CASES = [("octagon", count) for count in range(26, 31)] + [
    ("domino", count) for count in range(13, 19)
]


@pytest.mark.parametrize("container, count", DENSE_L_CASES)
def test_a_dense_lattice_of_concave_copies_meets_its_count(container: str, count: int) -> None:
    """Every requested concave copy is placed, and the engine calls the result valid.

    A concave outline's exact contacts are read back by the engine's polygon path
    as a hair of overlap, so a bounding-box lattice drops copies it had placed and
    the old four-width bracket never descended far enough to recover them. The
    anchored lattice reaches the count; the verdict is the engine's.
    """
    arena = Arena.rectangle(2.0, 1.0) if container == "domino" else _unit_polygon(8)
    problem = _free_scale(arena, l_tromino(), count)
    candidate = grid_initialize(problem)
    evaluation = evaluate(problem, candidate)
    assert candidate.n_shapes == count
    assert evaluation.valid


#: Pointed arenas where the bounding-box centre is not where a shape fits deepest.
#: optimum is the printed size of the smallest container, when it has a closed
#: form; before is what the old lattice reached, so a smaller number is progress.
POINTED_CASES = (
    (
        "circle in a triangle",
        _unit_polygon(3),
        Circle(radius=1.0),
        2.0 * math.sqrt(3.0),
        4.62,
    ),
    (
        "circle in a tan",
        _turned_outline(right_isosceles_triangle(), angle=135.0),
        Circle(radius=1.0),
        2.0 + math.sqrt(2.0),
        4.00,
    ),
    (
        "square in an L",
        _turned_outline(l_tromino(), scale=0.5, angle=135.0),
        square(),
        None,
        2.83,
    ),
    # The same pointed arenas at their natural orientation. They are here to show
    # the initialiser no longer needs the catalogue's 135-degree turn: the corner
    # of the L and the right angle of the tan are found from the region itself.
    (
        "square in an unturned tan",
        _turned_outline(right_isosceles_triangle()),
        square(),
        2.0,
        None,
    ),
    (
        "square in an unturned L",
        _turned_outline(l_tromino(), scale=0.5),
        square(),
        2.0,
        None,
    ),
)


@pytest.mark.parametrize("label, arena, shape, optimum, before", POINTED_CASES)
def test_a_pointed_arena_initialises_tighter_than_the_bounding_box_did(
    label: str, arena: Arena, shape, optimum: float | None, before: float | None
) -> None:
    """The first candidate is strictly tighter than the bounding-box one, and valid.

    The container is the reciprocal of the common scale a free-scale fixed-arena
    problem maximises, so a larger scale is a smaller container. For a circle the
    deepest point of the region is the centre of its largest inscribed circle, so
    the construction is expected to reach that optimum; for the turned square in an
    L there is no closed form and the recorded before is the contract.
    """
    problem = _free_scale(arena, shape, 1)
    candidate = grid_initialize(problem)
    evaluation = evaluate(problem, candidate)
    container = 1.0 / candidate.scale
    assert evaluation.valid, f"{label}: {evaluation.validation.summary()}"
    if before is not None:
        assert container < before, f"{label}: still {container}"
    if optimum is not None:
        assert container <= optimum * (1.0 + 1e-2), f"{label}: {container} above {optimum}"


#: Regions with no symmetry the bounding box could exploit: three regular
#: containers and one hand-drawn concave outline.
NON_SQUARE_ARENAS = (
    ("pentagon", lambda: _unit_polygon(5)),
    ("hexagon", lambda: _unit_polygon(6)),
    ("domino", lambda: Arena.rectangle(2.0, 1.0)),
    (
        "arbitrary polygon",
        lambda: Arena.polygon(
            ((0.0, 0.0), (3.0, 0.0), (3.0, 1.0), (1.0, 1.0), (1.0, 3.0), (0.0, 3.0))
        ),
    ),
)


@pytest.mark.parametrize("label, build_arena", NON_SQUARE_ARENAS)
@pytest.mark.parametrize("count", [1, 3, 5])
def test_a_non_square_arena_places_every_requested_copy(
    label: str, build_arena, count: int
) -> None:
    """A lattice on a pentagon, a hexagon, a domino or an arbitrary outline is valid.

    None of these has the bounding box of a rectangle, which is what the operator
    used to lay out in; the engine still reports every copy inside and free.
    """
    problem = _free_scale(build_arena(), square(), count)
    candidate = grid_initialize(problem)
    evaluation = evaluate(problem, candidate)
    assert candidate.n_shapes == count, label
    assert evaluation.valid, f"{label}: {evaluation.validation.summary()}"


def test_the_anchored_lattice_repeats_for_the_same_problem() -> None:
    """The construction is a function of the problem, so two calls agree.

    The anchor search draws no random number: it is a deterministic walk over the
    arena's own distances, so a problem replays exactly without its seed.
    """
    problem = _free_scale(_unit_polygon(3), Circle(radius=1.0), 3)
    first = grid_initialize(problem)
    second = grid_initialize(problem)
    assert first.placements == second.placements
    assert first.scale == second.scale


def _total_perimeter(count: int, *, arena: Arena | None = None, shape=None) -> Problem:
    """A total-perimeter problem with the collection's unit copy."""
    return Problem(
        problem_id=f"total-perimeter-{count}",
        arena=arena or Arena.rectangle(1.0, 1.0),
        shape=shape or Circle(radius=1.0),
        objective=MaximizeTotalPerimeter(count=count),
        rotation=RotationPolicy(mode=RotationMode.FREE),
    )


def test_a_varied_start_gives_one_copy_its_own_larger_size() -> None:
    """The family's degree of freedom is each copy's size, so the start uses it."""
    problem = _total_perimeter(4)
    candidate = varied_initialize(problem)
    evaluation = evaluate(problem, candidate)
    scales = [placement.scale for placement in candidate.placements]

    assert candidate.n_shapes == 4
    assert candidate.scale == 1.0
    assert all(scale is not None and scale > 0.0 for scale in scales)
    largest = max(scale for scale in scales if scale is not None)
    assert scales[0] == pytest.approx(largest)
    assert len({round(scale, 9) for scale in scales if scale is not None}) == 2
    assert evaluation.valid, evaluation.validation.summary()
    assert evaluation.metrics["total_scale"] == pytest.approx(
        sum(scale for scale in scales if scale is not None)
    )


def test_a_varied_start_keeps_every_copy_inside_a_disc_arena() -> None:
    problem = _total_perimeter(7, arena=Arena.disk(1.0))
    candidate = varied_initialize(problem)
    facts = facts_for(problem, candidate)

    assert all(containment.inside for containment in facts.containment)
    assert facts.overlaps == ()


def test_a_varied_start_serves_a_polygon_family_too() -> None:
    problem = _total_perimeter(
        3, arena=Arena.disk(1.0), shape=RegularPolygon(sides=3, side=1.0)
    )
    candidate = varied_initialize(problem)
    evaluation = evaluate(problem, candidate)

    assert candidate.n_shapes == 3
    assert evaluation.valid, evaluation.validation.summary()
    assert evaluation.promoted_metric == "total_scale"


def test_a_varied_start_repeats_for_the_same_problem() -> None:
    """The construction draws no random number, so a problem replays exactly."""
    problem = _total_perimeter(5)
    first = varied_initialize(problem)
    second = varied_initialize(problem)

    assert first.placements == second.placements
    assert first.scale == second.scale


def _covering(count: int, *, arena: Arena | None = None, shape=None) -> Problem:
    return Problem(
        problem_id=f"covering-{count}",
        arena=arena or Arena.disk(1.0),
        shape=shape or square(),
        objective=CoverRegion(count=count),
        rotation=RotationPolicy(mode=RotationMode.FREE),
    )


def test_a_covering_start_is_a_valid_covering_the_engine_scored() -> None:
    """The covering start proposes, the engine judges: the verdict is what matters."""
    for count in (1, 2, 3, 4):
        problem = _covering(count)
        candidate = cover_initialize(problem)
        evaluation = evaluate(problem, candidate)

        assert candidate.n_shapes == count
        assert evaluation.valid, evaluation.validation.summary()
        assert evaluation.promoted_metric == "covered_size"


def test_a_covering_start_refuses_a_packing_objective() -> None:
    """The operator answers the covering question and says so for any other."""
    problem = Problem(
        problem_id="packing",
        arena=Arena.disk(1.0),
        shape=square(),
        objective=MaximizeScale(count=1),
    )
    with pytest.raises(ValueError, match="cover_region"):
        cover_initialize(problem)


def test_a_covering_start_repeats_for_the_same_problem() -> None:
    """The construction draws no random number, so a problem replays exactly."""
    problem = _covering(3)
    first = cover_initialize(problem)
    second = cover_initialize(problem)

    assert first.placements == second.placements
    assert first.scale == second.scale


def test_a_covering_start_covers_a_rectangle_arena_at_its_own_scale() -> None:
    """A unit square arena is covered by one unit square, and the score says one."""
    problem = _covering(1, arena=Arena.rectangle(1.0, 1.0))
    candidate = cover_initialize(problem)
    evaluation = evaluate(problem, candidate)

    assert candidate.scale == pytest.approx(1.0, rel=1e-3)
    assert evaluation.valid, evaluation.validation.summary()
    assert evaluation.primary == pytest.approx(1.0, rel=1e-3)


def test_a_covering_start_honours_an_explicit_scale() -> None:
    """A scale the caller fixes skips the search and is what the candidate carries."""
    problem = _covering(2)
    candidate = cover_initialize(problem, scale=3.0)

    assert candidate.scale == 3.0
    assert evaluate(problem, candidate).valid
