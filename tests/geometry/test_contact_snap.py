"""Contact guides are small, directional and judged by the normal engine."""

from __future__ import annotations

import pytest

from paper_obs.domain import (
    Arena, Candidate, Circle, MaximizeCount, MaximizeTotalPerimeter,
    Placement, Problem, RegularPolygon,
)
from paper_obs.geometry.contact_snap import snap_to_contact


def _problem() -> Problem:
    return Problem(
        problem_id="manual-snap",
        arena=Arena.rectangle(10.0, 10.0),
        shape=Circle(),
        objective=MaximizeCount(scale=1.0),
    )


def _candidate(*placements: Placement) -> Candidate:
    return Candidate(
        candidate_id="hand", problem_id="manual-snap", scale=1.0,
        placements=placements,
    )


def test_a_disc_moving_toward_a_wall_gets_exactly_to_contact() -> None:
    problem = _problem()
    candidate = _candidate(Placement("s0", 4.485, 0.0))
    guided = snap_to_contact(problem, candidate, ("s0",), 0.02, (0.3, 0.0))
    assert guided.placements[0].x == pytest.approx(4.5)
    assert guided.candidate_id == candidate.candidate_id


def test_moving_away_from_a_contact_is_never_pulled_back() -> None:
    problem = _problem()
    candidate = _candidate(Placement("s0", 4.485, 0.0))
    guided = snap_to_contact(problem, candidate, ("s0",), 0.02, (-0.015, 0.0))
    assert guided is candidate


def test_a_neighbour_is_a_guide_only_within_the_screen_distance() -> None:
    problem = _problem()
    candidate = _candidate(Placement("s0", 0.0, 0.0), Placement("s1", 1.015, 0.0))
    assert snap_to_contact(problem, candidate, ("s1",), 0.01, (-0.2, 0.0)) is candidate
    guided = snap_to_contact(problem, candidate, ("s1",), 0.02, (-0.2, 0.0))
    assert guided.placements[1].x == pytest.approx(1.0)


def test_an_invalid_candidate_is_left_where_the_user_put_it() -> None:
    problem = _problem()
    overlap = _candidate(Placement("s0", 0.0, 0.0), Placement("s1", 0.99, 0.0))
    assert snap_to_contact(problem, overlap, ("s1",), 0.02, (-0.2, 0.0)) is overlap


def test_variable_size_copies_snap_only_to_real_polygon_contact() -> None:
    problem = Problem(
        problem_id="perimeter-contact", arena=Arena.rectangle(10, 10),
        shape=RegularPolygon(sides=4), objective=MaximizeTotalPerimeter(count=2),
    )
    candidate = Candidate(
        candidate_id="sizes", problem_id=problem.problem_id, scale=1,
        placements=(
            Placement("s0", 0, 0, scale=1),
            Placement("s1", 1.515, 0, scale=2),
        ),
    )
    guided = snap_to_contact(problem, candidate, ("s1",), 0.02, (-0.2, 0))
    assert guided.placements[1].x == pytest.approx(1.5)
    assert guided.placements[1].scale == 2
