"""The one chord count, the error it implies, and the table the document quotes.

The engine compiles a curved primitive to a circumscribed n-gon. These tests pin
the number (`domain/tessellation.CHORD_COUNT`), the closed form of the error,
and the fact that the **engine's own compiled arena** matches that closed form --
so a change of chord count cannot quietly change what a verdict means.
"""

from __future__ import annotations

import math

import pytest

from paper_obs.domain import Arena
from paper_obs.domain.tessellation import (
    CHORD_COUNT,
    chord_area_relative_error,
    chord_radius_relative_error,
)

#: The measured table of the precision document: (area relative error, radius
#: relative error) per chord count. The margins are generous -- these pin the
#: order of magnitude and the direction, not the last digit of an area.
MEASURED = {
    256: (5.020e-5, 7.530e-5),
    512: (1.255e-5, 1.883e-5),
    1024: (3.137e-6, 4.706e-6),
    2048: (7.844e-7, 1.177e-6),
    4096: (1.961e-7, 2.941e-7),
}


def test_the_chord_count_is_the_documented_one() -> None:
    assert CHORD_COUNT == 256
    # The engine's own buffer really produces that many corners, closing point
    # included; a constant nothing reads would be a comment, not a decision.
    assert len(Arena.disk(1.0).geometry.exterior.coords) == CHORD_COUNT + 1


@pytest.mark.parametrize("segments, expected", MEASURED.items())
def test_the_closed_forms_match_the_measured_table(segments: int, expected: tuple) -> None:
    area_error, radius_error = expected
    assert chord_area_relative_error(segments) == pytest.approx(area_error, rel=0.05)
    assert chord_radius_relative_error(segments) == pytest.approx(radius_error, rel=0.05)


def test_the_compiled_arena_matches_the_closed_form() -> None:
    """The engine's real polygon, not the formula: the formula must describe it."""
    arena = Arena.disk(1.0)
    compiled_error = arena.compiled_area / (math.pi * 1.0**2) - 1.0
    assert compiled_error == pytest.approx(chord_area_relative_error(), rel=0.02)
    # Circumscribed: the compiled outline is never smaller than the ideal disc.
    assert arena.compiled_area > arena.area
    assert arena.area == pytest.approx(math.pi)
