"""The engine façade: ranking, metrics, analysis and the scale interval."""

from __future__ import annotations

import math

import pytest

from paper_obs.domain import (
    Arena,
    Candidate,
    Circle,
    MaximizeCount,
    MaximizeScale,
    MinimizeContainer,
    Placement,
    Problem,
    RegularPolygon,
    RotationMode,
    RotationPolicy,
)
from paper_obs.geometry import analyze, evaluate, facts_for, inspect_shape, scale_bounds


def test_inspect_shape_reports_boundary_and_neighbours(circle_problem, lattice, make_candidate) -> None:
    candidate = make_candidate(circle_problem, lattice(2, 2, 5.0), scale=5.0)
    shape_id = candidate.placements[0].shape_id
    reading = inspect_shape(circle_problem, candidate, shape_id, distance=1.0)
    assert reading["shape_id"] == shape_id
    assert reading["boundary"]["inside"] is True
    assert reading["overlaps"] == []
    assert {item["shape_id"] for item in reading["nearby"]} <= set(candidate.shape_ids) - {shape_id}


def test_a_valid_candidate_outranks_a_better_scoring_invalid_one(
    circle_problem, lattice, make_candidate
) -> None:
    valid = evaluate(circle_problem, make_candidate(circle_problem, lattice(2, 2, 5.0), scale=5.0))
    placements = list(lattice(2, 2, 5.0))
    placements[0] = placements[0].moved(-2.5, 0.0)
    invalid = evaluate(
        circle_problem, make_candidate(circle_problem, placements, scale=9.0)
    )
    assert invalid.score.primary > valid.score.primary
    assert valid.is_better_than(invalid)
    assert not invalid.is_better_than(valid)


def test_metrics_describe_the_packing(square_problem, lattice, make_candidate) -> None:
    candidate = make_candidate(square_problem, lattice(4, 4, 2.5), scale=2.5)
    metrics = evaluate(square_problem, candidate).metrics
    assert metrics["n_shapes"] == 16.0
    assert metrics["packed_area"] == pytest.approx(100.0)
    assert metrics["arena_area"] == pytest.approx(100.0)
    # A perfect tiling is *exactly* the arena: the sums of shapely areas land a
    # quadrillionth of a square away, and reporting that residue as a void, with a
    # density above one, is arithmetic talking rather than a fact about the
    # packing. `compute_metrics` snaps it, so these three are exact and agree.
    assert metrics["packed_area"] == metrics["arena_area"]
    assert metrics["density"] == 1.0
    assert metrics["void_area"] == 0.0
    # The four squares of the inner 2 x 2 block touch no wall.
    assert metrics["boundary_contacts"] == 12.0


def test_a_disc_arena_reports_an_exact_area_and_sane_metrics(make_candidate) -> None:
    """The arena is pi*r**2, and the union-based metrics stay non-negative.

    The compiled arena is a circumscribed 256-gon, a hair larger than the ideal
    disc. The covered area, the void and the density are read against the exact
    declared area and the void is capped at it, so an empty candidate cannot report
    a negative covered area and the density cannot exceed one, even on the curve.
    """
    problem = Problem(
        problem_id="disc-metrics",
        arena=Arena.disk(2.0),
        shape=Circle(),
        objective=MaximizeCount(scale=1.0),
    )
    empty = evaluate(problem, make_candidate(problem, [], scale=1.0)).metrics

    assert empty["arena_area"] == pytest.approx(math.pi * 4.0)
    assert empty["void_area"] == pytest.approx(math.pi * 4.0)
    assert empty["covered_area"] == 0.0
    assert empty["density"] == 0.0

    packed = evaluate(
        problem, make_candidate(problem, [Placement("s000", 0.0, 0.0)], scale=1.0)
    ).metrics

    assert packed["covered_area"] >= 0.0
    assert packed["void_area"] >= 0.0
    assert packed["covered_area"] + packed["void_area"] == pytest.approx(packed["arena_area"])
    assert 0.0 <= packed["density"] <= 1.0


def test_disjoint_discs_cannot_cover_more_than_their_exact_area(
    circle_problem, lattice, make_candidate
) -> None:
    candidate = make_candidate(circle_problem, lattice(2, 2, 5.0), scale=5.0)
    verdict = evaluate(circle_problem, candidate)

    assert verdict.valid
    assert verdict.metrics["covered_area"] == pytest.approx(verdict.metrics["packed_area"])
    assert verdict.metrics["void_area"] == pytest.approx(
        verdict.metrics["arena_area"] - verdict.metrics["packed_area"]
    )


def test_metrics_are_optional(circle_problem, lattice, make_candidate) -> None:
    candidate = make_candidate(circle_problem, lattice(2, 2, 5.0), scale=5.0)
    assert evaluate(circle_problem, candidate, with_metrics=False).metrics == {}


def test_an_evaluation_round_trips_through_json(circle_problem, lattice, make_candidate) -> None:
    from paper_obs.geometry import Evaluation

    candidate = make_candidate(circle_problem, lattice(2, 2, 5.0), scale=5.0)
    evaluation = evaluate(circle_problem, candidate)
    assert Evaluation.from_dict(evaluation.to_dict()) == evaluation


def test_analysis_splits_the_empty_region_around_a_ring_of_circles(
    lattice, make_candidate
) -> None:
    wide = Problem(
        problem_id="wide",
        arena=Arena.rectangle(20.0, 20.0),
        shape=Circle(),
        objective=MaximizeScale(count=4),
    )
    candidate = make_candidate(wide, lattice(2, 2, 5.0), scale=5.0)
    analysis = analyze(wide, candidate)
    covered = 4 * math.pi * 2.5**2
    assert sum(void.area for void in analysis.voids) == pytest.approx(400.0 - covered, rel=1e-4)
    assert analysis.largest_void is not None
    # Four touching circles enclose a small pocket, so the emptiness has two parts.
    assert len(analysis.voids) == 2
    assert analysis.mean_contacts == pytest.approx(2.0)


def test_a_perfect_tiling_reports_no_void(square_problem, lattice, make_candidate) -> None:
    """The slivers floating-point arithmetic leaves along shared edges are not voids."""
    candidate = make_candidate(square_problem, lattice(4, 4, 2.5), scale=2.5)
    assert analyze(square_problem, candidate).voids == ()


def test_voids_are_sorted_by_area(make_candidate) -> None:
    from paper_obs.domain import Placement

    problem = Problem(
        problem_id="two-gaps",
        arena=Arena.rectangle(20.0, 10.0).difference(Arena.rectangle(1.0, 10.0)),
        shape=Circle(),
        objective=MaximizeScale(count=1),
    )
    candidate = make_candidate(problem, (Placement("s000", -5.0, 0.0),), scale=2.0)
    voids = analyze(problem, candidate).voids
    assert len(voids) == 2
    assert voids[0].area > voids[1].area
    assert voids[0].area == pytest.approx(95.0)


def test_scale_bounds_come_from_the_perfect_packing_bound() -> None:
    problem = Problem(
        problem_id="bound",
        arena=Arena.rectangle(10.0, 10.0),
        shape=Circle(),
        objective=MaximizeScale(count=25),
    )
    bounds = scale_bounds(problem)
    expected = (100.0 / (25 * math.pi * 0.25)) ** 0.5
    assert bounds.high == pytest.approx(expected)
    assert bounds.low == pytest.approx(expected / 64.0)


def test_scale_bounds_are_degenerate_when_the_scale_is_fixed(circle_problem) -> None:
    from dataclasses import replace

    from paper_obs.domain import MaximizeCount

    fixed = replace(circle_problem, objective=MaximizeCount(scale=2.0))
    bounds = scale_bounds(fixed)
    assert bounds.low == bounds.high == 2.0


def test_a_declared_length_gives_any_fixed_arena_an_equivalent_side() -> None:
    """An L arena of short side 1 holding three squares at scale 1/2 reads as an L of side 2.

    The scale is what the engine optimises; the published number is the container
    around unit copies, the declared length divided by the scale. An arena that
    declares no length (and is no regular polygon) has no such reading.
    """
    outline = [(0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (1.0, 1.0), (1.0, 2.0), (0.0, 2.0)]
    square = RegularPolygon(sides=4, side=1.0)
    placements = tuple(Placement(f"s{i}", x, y) for i, (x, y) in enumerate([(0.5, 0.5), (1.5, 0.5), (0.5, 1.5)]))
    candidate = Candidate(candidate_id="l", problem_id="l", scale=0.5, placements=placements)

    def problem(arena: Arena) -> Problem:
        return Problem(problem_id="l", arena=arena, shape=square, objective=MaximizeScale(count=3))

    measured = evaluate(problem(Arena(shape=Arena.polygon(outline).shape, reference_length=1.0)), candidate)
    assert measured.valid
    assert measured.metrics["equivalent_container_side"] == pytest.approx(2.0)
    plain = evaluate(problem(Arena.polygon(outline)), candidate)
    assert "equivalent_container_side" not in plain.metrics


def test_the_container_is_the_longest_side_of_the_arrangement() -> None:
    """A minimal-enclosure region is measured, not given: the box, made square on its longest side.

    Four unit squares in a row occupy a 4 x 1 box, so the smallest square holding
    them has side 4 and sits centred on that box. Both halves are observable — the
    side is what the score reads and the bounds are what every containment fact and
    the canvas are read against — and a rule that took the first extent, or that
    forgot the centring, would still produce a number.
    """
    problem = Problem(
        problem_id="row",
        arena=None,
        shape=RegularPolygon(sides=4, side=1.0),
        objective=MinimizeContainer(count=4),
    )
    placements = tuple(Placement(f"s{index:03d}", float(index), 0.0) for index in range(4))
    candidate = Candidate(candidate_id="row", problem_id="row", scale=1.0, placements=placements)

    verdict = evaluate(problem, candidate)

    assert verdict.valid
    assert verdict.metrics["container_side"] == 4.0
    # The row spans x in [-0.5, 3.5] and y in [-0.5, 0.5]; its box is centred on
    # (1.5, 0), so the square reaches two units either side of that.
    assert facts_for(problem, candidate).arena.bounds == (-0.5, -2.0, 3.5, 2.0)


def test_the_engine_measures_the_published_packing_of_five_squares() -> None:
    """The one proved case of the family, and the reason the box rule must read rotations.

    Goebel's packing of five unit squares — four in the corners, one turned 45
    degrees — has side 2 + sqrt(2)/2 exactly. The engine recovers that number from
    the coordinates alone; nothing here claims optimality, it pins the measurement
    against a published one, which another run of the same code could never do.
    """
    problem = Problem(
        problem_id="five",
        arena=None,
        shape=RegularPolygon(sides=4, side=1.0),
        objective=MinimizeContainer(count=5),
        # The packing turns one square, so the problem has to allow it: the default
        # policy fixes every shape at zero degrees and would call this invalid.
        rotation=RotationPolicy(mode=RotationMode.FREE),
    )
    corner = 2.0 + 2**0.5 / 2.0 - 0.5
    middle = 1.0 + 2**0.5 / 4.0
    candidate = Candidate(
        candidate_id="five",
        problem_id="five",
        scale=1.0,
        placements=(
            Placement("s000", corner, 0.5),
            Placement("s001", 0.5, corner),
            Placement("s002", corner, corner),
            Placement("s003", 0.5, 0.5),
            Placement("s004", middle, middle, rotation=45.0),
        ),
    )

    verdict = evaluate(problem, candidate)

    assert verdict.valid
    assert verdict.metrics["container_side"] == 2.0 + 2**0.5 / 2.0
    assert verdict.score.primary == 1.0 / (2.0 + 2**0.5 / 2.0)
    assert verdict.promoted_metric == "container_side"


def test_a_circle_container_measures_the_smallest_circle_around_the_shapes() -> None:
    """Three unit discs, each touching the other two, need 0.5 + 1/sqrt(3) exactly."""
    problem = Problem(
        problem_id="ring",
        arena=None,
        shape=Circle(radius=0.5),
        objective=MinimizeContainer(count=3, container="circle"),
    )
    # Their centres sit on an equilateral triangle of side 1, whose circumradius is
    # 1/sqrt(3); a disc adds its own radius to that. Nothing here is fitted: the
    # measurement is the circle through the three centres, grown by the radius.
    candidate = Candidate(
        candidate_id="ring",
        problem_id="ring",
        scale=1.0,
        placements=(
            Placement("s000", 0.0, 0.0),
            Placement("s001", 1.0, 0.0),
            Placement("s002", 0.5, 3**0.5 / 2.0),
        ),
    )

    verdict = evaluate(problem, candidate)

    assert verdict.valid
    assert verdict.metrics["container_radius"] == pytest.approx(0.5 + 1 / 3**0.5, abs=1e-9)
    assert verdict.score.primary == pytest.approx(1 / (0.5 + 1 / 3**0.5))
    # The number the family asks to read leads the panel, as the side does for a square.
    assert verdict.promoted_metric == "container_radius"


def test_a_circle_container_reads_the_corners_of_a_turned_shape() -> None:
    """A lone unit square is held by the circle through its corners, whatever its angle."""
    problem = Problem(
        problem_id="one",
        arena=None,
        shape=RegularPolygon(sides=4, side=1.0),
        objective=MinimizeContainer(count=1, container="circle"),
        rotation=RotationPolicy(mode=RotationMode.FREE),
    )
    candidate = Candidate(
        candidate_id="one",
        problem_id="one",
        scale=1.0,
        placements=(Placement("s000", 0.0, 0.0, rotation=30.0),),
    )

    verdict = evaluate(problem, candidate)

    # The diagonal of a unit square is sqrt(2), so the circle through its four corners
    # has radius sqrt(2)/2 — a number an axis-aligned box measurement could not give.
    assert verdict.valid
    assert verdict.metrics["container_radius"] == pytest.approx(2**0.5 / 2.0, abs=1e-9)



def test_a_container_problem_has_nothing_to_enclose_without_a_shape() -> None:
    """An empty arrangement encloses nothing, and the engine says so instead of inventing a box.

    It is the one case with no honest measurement: a container of side zero has no
    area, so every metric that divides by it would be arithmetic talking. Refusing
    is also why this cannot be a zero score — the count constraint reports the
    candidate invalid anyway, and a score nobody can compare is worse than an error.
    """
    problem = Problem(
        problem_id="empty", arena=None, shape=Circle(), objective=MinimizeContainer(count=3)
    )
    with pytest.raises(ValueError, match="has nothing to enclose"):
        evaluate(problem, Candidate(candidate_id="empty", problem_id="empty", scale=1.0))
