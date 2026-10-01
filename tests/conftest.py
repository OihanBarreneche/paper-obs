"""Fixtures shared by the test modules.

The two problems below are small enough to be checked by hand and are reused
everywhere a candidate has to mean something: four circles in a square, where
the 2 x 2 lattice of radius 2.5 is exactly touching, and sixteen squares, where
a perfect packing exists.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

import pytest

from paper_obs.domain import (
    Arena,
    Candidate,
    Circle,
    MaximizeScale,
    Placement,
    Problem,
    new_candidate_id,
    square,
)


@pytest.fixture
def circle_problem() -> Problem:
    """Four circles, as large as possible, in a 10 x 10 square."""
    return Problem(
        problem_id="test-four-circles",
        arena=Arena.rectangle(10.0, 10.0),
        shape=Circle(),
        objective=MaximizeScale(count=4),
    )


@pytest.fixture
def square_problem() -> Problem:
    """Sixteen unit squares in a 10 x 10 square, a perfect packing at scale 2.5."""
    return Problem(
        problem_id="test-sixteen-squares",
        arena=Arena.rectangle(10.0, 10.0),
        shape=square(),
        objective=MaximizeScale(count=16),
    )


@pytest.fixture
def make_candidate() -> Callable[..., Candidate]:
    """Return a factory building a candidate from raw placements."""

    def _make(
        problem: Problem,
        placements: Iterable[Placement],
        *,
        scale: float | None = None,
        origin: str = "test",
    ) -> Candidate:
        resolved = scale if scale is not None else problem.objective.preset_scale()
        if resolved is None:
            raise ValueError("pass an explicit scale for an objective that does not fix one")
        return Candidate(
            candidate_id=new_candidate_id("test"),
            problem_id=problem.problem_id,
            scale=resolved,
            placements=tuple(placements),
            origin=origin,
        )

    return _make


@pytest.fixture
def lattice() -> Callable[..., tuple[Placement, ...]]:
    """Return a factory building a lattice of placements centred on the origin."""

    def _lattice(
        columns: int, rows: int, spacing: float, *, rotation: float = 0.0
    ) -> tuple[Placement, ...]:
        placements = []
        for row in range(rows):
            for column in range(columns):
                placements.append(
                    Placement(
                        shape_id=f"s{len(placements):03d}",
                        x=(column - (columns - 1) / 2.0) * spacing,
                        y=((rows - 1) / 2.0 - row) * spacing,
                        rotation=rotation,
                    )
                )
        return tuple(placements)

    return _lattice
