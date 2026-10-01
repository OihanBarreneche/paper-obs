"""Reading a published figure: what the reader finds, and what the engine then says.

A catalogue family that publishes no coordinates publishes a drawing, and the drawing is
the only evidence there is. These tests draw one themselves -- four unit discs in a 4 x 4
square, the one arrangement whose value is known -- so nothing here needs the network, and
they assert the two halves of the promise: the copies are found where they are drawn, and
the engine's own verdict on the reconstruction lands on the value the drawing shows.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from paper_obs.domain import (
    Arena,
    Candidate,
    Circle,
    MaximizeScale,
    Placement,
    Problem,
    RotationMode,
    RotationPolicy,
)
from paper_obs.geometry import evaluate
from paper_obs.search import fit_layout_scale

#: Decoding the drawing needs Pillow, which the research extra installs; without it the
#: reader cannot be exercised at all and the tests say so rather than failing.
pytest.importorskip("PIL")

from paper_obs import catalog_approximation  # noqa: E402  (after the Pillow check)

#: The drawing's side, in pixels, and how wide a unit is drawn in it. The copies are drawn
#: at the size the problem gives them, and the container is drawn a little wider than the
#: problem's own: a figure whose walls touch its copies would test the reader on a tangency
#: rather than on the copies.
SIDE = 220
UNIT = 42.0
WALL = 4.6

#: Centres of the four unit discs, in problem units.
CENTRES = ((-1.0, -1.0), (1.0, -1.0), (-1.0, 1.0), (1.0, 1.0))


def draw_square_of_discs(path: Path) -> float:
    """Draw four unit discs at the corners of a square, and return the drawn copy radius."""
    from PIL import Image, ImageDraw

    image = Image.new("L", (SIDE, SIDE), 255)
    draw = ImageDraw.Draw(image)
    radius = UNIT
    middle = SIDE / 2.0
    for x, y in CENTRES:
        cx, cy = middle + x * UNIT, middle - y * UNIT
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], outline=0, width=2)
    half = WALL / 2.0 * UNIT
    draw.rectangle([middle - half, middle - half, middle + half, middle + half], outline=0, width=2)
    image.save(path)
    return radius


def square_problem() -> Problem:
    """Four unit discs in a 4 x 4 square: the drawn arrangement reaches scale 1 exactly."""
    return Problem(
        "four-discs-in-a-square",
        Arena.rectangle(4.0, 4.0),
        Circle(),
        MaximizeScale(count=4),
        rotation=RotationPolicy(mode=RotationMode.FREE),
        seed=1,
    )


def test_the_reader_finds_the_copies_where_they_are_drawn(tmp_path: Path):
    path = tmp_path / "square.gif"
    radius = draw_square_of_discs(path)
    reading = catalog_approximation.detect_discs(path, 4)
    assert reading is not None
    measured, centres, explained = reading
    assert measured == pytest.approx(radius, rel=0.1)
    assert len(centres) == 4
    assert explained > 0.5
    # The four centres are the drawn ones: two rows of two, two radii apart, so the grid
    # they span two radii across in either direction.
    xs = sorted(x for x, _ in centres)
    ys = sorted(y for _, y in centres)
    assert xs[2] - xs[0] == pytest.approx(2.0 * measured, rel=0.1)
    assert ys[2] - ys[0] == pytest.approx(2.0 * measured, rel=0.1)


def test_a_drawing_round_trips_through_the_engine(tmp_path: Path):
    path = tmp_path / "square.gif"
    draw_square_of_discs(path)
    problem = square_problem()
    result = catalog_approximation.reconstruct(problem, path, 4)
    assert result is not None
    candidate, reading = result
    assert reading["explained"] > 0.5
    verdict = evaluate(problem, candidate)
    assert verdict.valid
    # The engine reads the drawing back: what it accepts scores at least what the drawn
    # arrangement itself scores, so no copy was lost or misplaced beyond repair. The ideal
    # is built here rather than assumed, so the assertion carries no convention of its own:
    # the short local search that follows the reading may legitimately improve on it.
    ideal = Candidate(
        "ideal",
        problem.problem_id,
        1.0,
        tuple(Placement(f"s{index:03d}", x, y) for index, (x, y) in enumerate(CENTRES)),
    )
    assert evaluate(problem, ideal).valid
    reached = evaluate(problem, fit_layout_scale(problem, ideal))
    assert verdict.primary >= reached.primary * (1.0 - 1e-6)


def test_a_reading_with_the_wrong_count_is_refused(tmp_path: Path):
    path = tmp_path / "square.gif"
    draw_square_of_discs(path)
    # Six circles cannot be read out of a drawing that shows four: the extra peaks find no
    # outline to stand on, and a reading that keeps them must not be handed to the engine.
    reading = catalog_approximation.detect_discs(path, 6)
    assert reading is None
