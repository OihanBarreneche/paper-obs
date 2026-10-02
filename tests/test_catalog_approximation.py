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

import math

from paper_obs.domain import (
    Arena,
    Candidate,
    Circle,
    MaximizeTotalPerimeter,
    MinimizeContainer,
    MaximizeScale,
    Placement,
    Problem,
    RegularPolygon,
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

#: The drawing of a triangle of squares: the container is an equilateral triangle of this
#: side in pixels, and its three squares have this side. Two sit on the base and one rests
#: between them, which is a packing at any size the reader recovers.
TRIANGLE_SIDE = 140.0
TRIANGLE_BASE = 200.0
SQUARE_SIDE = 40.0


def triangle_squares_problem() -> Problem:
    """Three unit squares inside the smallest equilateral triangle, as the catalogue asks it."""
    return Problem(
        "three-squares-in-a-triangle",
        Arena.regular_polygon(3, 1.0 / math.sqrt(3.0)),
        RegularPolygon(sides=4, side=1.0),
        MaximizeScale(count=3),
        rotation=RotationPolicy(mode=RotationMode.FREE),
        seed=1,
    )


def draw_triangle_of_squares(path: Path) -> None:
    """Draw two squares on a triangle's base and one resting between them."""
    from PIL import Image, ImageDraw

    image = Image.new("L", (240, 240), 255)
    draw = ImageDraw.Draw(image)
    middle = 120.0
    half = TRIANGLE_SIDE / 2.0
    apex = TRIANGLE_BASE - TRIANGLE_SIDE * math.sqrt(3.0) / 2.0
    draw.polygon(
        [(middle, apex), (middle - half, TRIANGLE_BASE), (middle + half, TRIANGLE_BASE)],
        outline=0,
        width=2,
    )
    side = SQUARE_SIDE
    for centre_x, centre_y in (
        (middle - side / 2.0, TRIANGLE_BASE - side / 2.0),
        (middle + side / 2.0, TRIANGLE_BASE - side / 2.0),
        (middle, TRIANGLE_BASE - side - side / 2.0),
    ):
        draw.rectangle(
            [centre_x - side / 2.0, centre_y - side / 2.0, centre_x + side / 2.0, centre_y + side / 2.0],
            outline=0,
            width=2,
        )
    image.save(path)


def test_the_reader_finds_polygonal_copies(tmp_path: Path):
    path = tmp_path / "triangle.gif"
    draw_triangle_of_squares(path)
    problem = triangle_squares_problem()
    reading = catalog_approximation.detect_copies(path, 3, problem)
    assert reading is not None
    size, layout, turns, explained = reading
    assert size == pytest.approx(SQUARE_SIDE, rel=0.12)
    assert len(layout) == 3
    # The three squares are what a reading explains; the container's own outline is the
    # part of the drawing it does not.
    assert explained > 0.5
    # A drawn square is axis-aligned, and a square turned by ninety degrees is the same
    # square: every turn the reader may report is a multiple of a quarter turn.
    for turn in turns:
        quarter = turn % 90.0
        assert min(quarter, 90.0 - quarter) < 8.0


def test_a_polygonal_reading_round_trips_through_the_engine(tmp_path: Path):
    path = tmp_path / "triangle.gif"
    draw_triangle_of_squares(path)
    problem = triangle_squares_problem()
    result = catalog_approximation.reconstruct(problem, path, 3)
    assert result is not None
    candidate, _ = result
    verdict = evaluate(problem, candidate)
    assert verdict.valid
    # The engine reads the drawn container back: the figure draws a triangle a little over
    # three and a half square sides wide, and what the reading reaches is that container,
    # measured rather than restated.
    assert verdict.metrics["equivalent_container_side"] == pytest.approx(
        TRIANGLE_SIDE / SQUARE_SIDE, rel=0.06
    )

#: The drawing of a two-by-two block of squares: four squares whose sides touch, drawn at
#: this side in pixels. Nothing draws a container: the problem the reading serves measures
#: the smallest square the arrangement needs, so the arrangement itself is all there is.
BLOCK_SIDE = 40.0


def square_container_problem() -> Problem:
    """Four unit squares in the smallest square that holds them: two by two."""
    return Problem(
        "four-squares-in-smallest-square",
        None,
        RegularPolygon(sides=4, side=1.0),
        MinimizeContainer(count=4, container="square"),
        rotation=RotationPolicy(mode=RotationMode.FREE),
        seed=1,
    )


def draw_grid_of_squares(path: Path) -> None:
    """Draw four squares in a two-by-two block, their sides touching."""
    from PIL import Image, ImageDraw

    image = Image.new("L", (200, 200), 255)
    draw = ImageDraw.Draw(image)
    side = BLOCK_SIDE
    for centre_x in (100.0 - side / 2.0, 100.0 + side / 2.0):
        for centre_y in (100.0 - side / 2.0, 100.0 + side / 2.0):
            draw.rectangle(
                [centre_x - side / 2.0, centre_y - side / 2.0, centre_x + side / 2.0, centre_y + side / 2.0],
                outline=0,
                width=2,
            )
    image.save(path)


def test_a_derived_container_is_measured_from_the_reading(tmp_path: Path):
    path = tmp_path / "block.gif"
    draw_grid_of_squares(path)
    problem = square_container_problem()
    result = catalog_approximation.reconstruct(problem, path, 4)
    assert result is not None
    candidate, _ = result
    verdict = evaluate(problem, candidate)
    assert verdict.valid
    # A container the problem derives is measured in the copies' own size, so the candidate
    # holds unit copies and the layout carries everything.
    assert candidate.scale == pytest.approx(1.0)
    # Four unit squares in a two-by-two block need a square of side two, and the engine reads
    # that back from the arrangement the drawing shows rather than from anything printed.
    assert verdict.metrics["container_side"] == pytest.approx(2.0, rel=0.15)

#: The drawing of two squares that differ in size: side by side, each this many pixels, with
#: nothing drawn around them. A total-perimeter page draws copies of different sizes, so the
#: copies are what has to be told from the space between them, and here there is no space.
VARIED_SIDE = 50.0


def total_perimeter_problem() -> Problem:
    """Two unit squares in a unit square, their sides added up and maximised."""
    return Problem(
        "two-squares-total-perimeter",
        Arena.rectangle(1.0, 1.0),
        RegularPolygon(sides=4, side=1.0),
        MaximizeTotalPerimeter(count=2),
        rotation=RotationPolicy(mode=RotationMode.FREE),
        seed=1,
    )


def draw_two_squares(path: Path) -> None:
    """Draw two squares of equal size, their sides touching."""
    from PIL import Image, ImageDraw

    image = Image.new("L", (200, 200), 255)
    draw = ImageDraw.Draw(image)
    side = VARIED_SIDE
    for index in range(2):
        left = 50.0 + index * side
        draw.rectangle([left, 50.0, left + side, 50.0 + side], outline=0, width=2)
    image.save(path)


def test_a_reading_of_copies_that_differ_in_size(tmp_path: Path):
    path = tmp_path / "two-squares.gif"
    draw_two_squares(path)
    problem = total_perimeter_problem()
    result = catalog_approximation.reconstruct(problem, path, 2)
    assert result is not None
    candidate, _ = result
    verdict = evaluate(problem, candidate)
    assert verdict.valid
    # The reading keeps each copy's own size: two squares side by side filling a unit square
    # have sides of a half each, and the objective adds them up.
    assert verdict.metrics["total_scale"] == pytest.approx(1.0, rel=0.15)

def test_a_reading_that_came_back_overlapping_is_spread_until_it_packs():
    """A centre read off a bitmap is an estimate; half a pixel can make two copies overlap."""
    problem = square_container_problem()
    corners = ((-1.0, -1.0), (1.0, -1.0), (-1.0, 1.0), (1.0, 1.0))
    # Four unit squares read a tenth of a side too close: at any scale they overlap, and a
    # derived container is rejected outright.
    tight = Candidate(
        "tight",
        problem.problem_id,
        1.0,
        tuple(
            Placement(f"s{index:03d}", x * 0.45, y * 0.45)
            for index, (x, y) in enumerate(corners)
        ),
    )
    assert not evaluate(problem, tight).valid
    spread = catalog_approximation.spread_until_valid(problem, tight)
    assert spread is not None
    assert evaluate(problem, spread).valid
    # The correction is the smallest that packs: the two-by-two block comes back at its own
    # size, touching and no more.
    assert spread.placements[3].x == pytest.approx(0.5, rel=0.02)
