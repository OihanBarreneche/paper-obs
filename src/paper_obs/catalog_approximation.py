"""Reconstruct an arrangement from the only drawing a source publishes.

Most catalogue families publish no coordinates at all: the page shows a picture and the
size the arrangement reaches, and nothing else. That picture is still evidence. This
module reads it, finds where the copies are, and hands them to the engine to judge --
so a run can start from something near the record instead of from a grid.

How one figure is read
----------------------
A source figure is a small line drawing: the copies and the container are outlines on
white. The copies of a catalog family are equal, so one radius describes all of them,
and a Hough accumulator over a range of radii says which radius explains the drawing
best. The strongest peaks of that accumulator are the centres; each one is then refined
by a least-squares circle fit on the stroke pixels near it. The output is a set of
centres and a radius, in pixels.

From pixels to a problem
------------------------
Pixels mean nothing to the engine, so the arrangement is expressed in its own units: the
centres are moved to their centroid and divided by the measured copy radius, which makes
the copies unit discs. What is then left to find is the one common scale at which that
pattern fits the problem's container: the reading is settled against the arena first, and
grown by the engine's own scale operator until the container rejects it. The value the engine reads
is therefore a measurement of the figure, not a restatement of the number printed beside
it: the printed size is used for nothing here.

Two readers, one per kind of evidence
------------------------------------
A circle's outline is the same curve wherever it sits, so discs are found by the outlines
themselves: an accumulator over radii says which radius explains the drawing and where its
copies are. Nothing else has that invariant -- a square turned by ten degrees is a
different curve -- so every other shape is found by the regions its strokes enclose. A
copy's inside is a closed white region and equal copies are equal regions, which is what
tells them from the gaps and corners around them; each copy's own outline then chooses its
turn on the strokes, and the engine does the rest.

That reading covers the four disc families the collection lists and no archive covers
(`cirintri`, `cirintan`, `cirinel`, `cirinl`) and the square families whose drawings
it can read. A figure whose copies cannot be told from the space between them -- and a
drawing of copies that overlap so much that no enclosed region survives -- is reported as
unread and left alone.

Pillow is what decodes the GIF, and it is the `research` extra's own dependency; a run
without it is told so rather than failing inside the decoder.

Usage
-----
    python -m paper_obs.catalog_approximation --family cirintri
    python -m paper_obs.catalog_approximation --family cirintri --counts 3,4 --refresh

Every reconstruction that the engine accepts is written as
`approx-<family>-<n>.json` beside the other candidates, where
`paper_obs.catalog_verification` picks it up on its next run.
"""

from __future__ import annotations

import argparse
import json
import math
import urllib.request
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import shapely

from paper_obs.catalog_verification import (
    ASSET,
    REFERENCE_METRICS,
    ROOT,
    card_problem,
    counts_of,
    measure_of,
    reference_of,
)
from paper_obs.domain.candidate import Candidate
from paper_obs.domain.placement import Placement
from paper_obs.geometry.engine import evaluate
from paper_obs.geometry.view import build_view
from paper_obs.search.operators.polish import polish
from paper_obs.search.operators.relaxation import fit_layout_scale
from paper_obs.search.operators.repair import repair_overlaps
from paper_obs.storage.files import save_candidate

#: Where a source figure is cached once downloaded.
FIGURES = ROOT / "out" / "packing-figures"

#: The disc families the catalogue lists and no coordinate archive covers, so the drawing
#: is the only evidence there is. A family whose copies are not discs needs another reader.
DISC_FAMILIES = ("cirintri", "cirintan", "cirinl", "cirinel")

#: The narrowest and widest copy radius, in pixels, the accumulator looks for: below this
#: a stroke is thinner than the drawing's own line, above it a circle would not fit.
MIN_RADIUS = 6

#: How far a refined centre's radius may drift from the accumulator's before the reading
#: is refused: pixels are integers, so a little drift is the fit, a lot is a mistake.
RADIUS_DRIFT = 0.25

#: The smallest gap between two copies the reading accepts, in measured radii. Two equal
#: copies of a packing touch at 2; a reading that puts them closer than this has misread
#: the drawing, and the engine could never make the arrangement valid.
TOUCHING = 1.9

#: The scale a reading is settled at before the engine is asked how far it can grow: small
#: enough that the container cannot be what rejects it, large enough to be well
#: conditioned.
SEED_SCALE = 1e-2

#: Repair passes allowed to separate copies that touch in the drawing but come back a
#: fraction of a pixel too close to each other.
REPAIR_STEPS = 40

#: How far the settled reading is spread before it is grown, as a fraction of the copy
#: radius. A repair stops the moment the engine's tolerance accepts the arrangement, which
#: leaves a residual overlap of about the tolerance per copy radius; enlarging the reading
#: multiplies that residual, so a hair of room is added once, at the reading's own scale,
#: and the growth then has a margin at every scale. A hundredth of a thousandth of the
#: value is a price worth paying for a lap that cannot miss.
SEPARATION_SLACK = 1e-5

#: Local-search steps run from the reading, to let the engine settle what pixels only
#: approximate. Zero disables it.
POLISH_STEPS = 60

#: The placements a reading is tried at before the best is kept, in copy sizes. A drawing
#: shows its arrangement where the artist put it, and the engine only ever scales a layout
#: about the origin, so where a reading sits inside the container is a question the search
#: has to answer rather than one the pixels can.
SHIFT_REACH = 0.7
SHIFT_STEP = 0.2

#: How far below its record a reading may land and still be kept, as a fraction of the
#: record. A reading a tenth of a record away is a starting point; further off, a grid the
#: engine builds itself is as good, and keeping the file would only make the catalogue's own
#: badges worse. Nothing is written for such a reading, and the run says so.
MAX_GAP = 0.1


def module_message(error: ImportError) -> str:
    """Return the sentence a missing decoder deserves."""
    return (
        "reading source figures needs Pillow, which the research extra installs "
        f"(pip install 'paper-obs[research]'): {error}"
    )


def figure_file(page: str, name: str, *, refresh: bool = False) -> Path:
    """Return the cached path of one source figure, downloading it once."""
    FIGURES.mkdir(parents=True, exist_ok=True)
    slug = page.rstrip("/").rsplit("/", 1)[-1]
    path = FIGURES / f"{slug}-{name}"
    if path.exists() and not refresh:
        return path
    request = urllib.request.Request(page + name, headers={"User-Agent": "paper-obs catalog"})
    with urllib.request.urlopen(request, timeout=60) as answer:
        path.write_bytes(answer.read())
    return path


#: The darkest a drawing's ink is expected to be, on the usual black-on-white page. A page
#: whose strokes are pale grey yields almost nothing here, which is what the fallback below
#: is for.
PLAIN_INK = 128

#: The share of a page that must be inked before the plain threshold is believed.
PLAIN_SHARE = 0.005

#: How far below the paper the fallback threshold sits, as a fraction of the page's whole
#: range. A pale page needs its threshold near the paper, where its strokes are.
PALE_MARGIN = 0.15


def dark_mask(path: Path) -> np.ndarray:
    """Return the drawing's strokes as a boolean image.

    The pages are not drawn alike: one is black on white, another black on a light grey
    sheet, a third anti-aliased into a hundred shades. The paper is therefore read from the
    image's own border -- where nothing is drawn -- and the threshold sits halfway between
    it and the darkest ink the figure uses.
    """
    try:
        from PIL import Image
    except ImportError as error:  # pragma: no cover - the extra is installed in CI
        raise ImportError(module_message(error)) from error
    with Image.open(path) as source:
        grey = np.asarray(source.convert("L"))
    plain = grey < PLAIN_INK
    if float(plain.mean()) >= PLAIN_SHARE:
        return plain
    # A page drawn in pale grey: read the paper off its own border, where nothing is drawn,
    # and look for strokes just below it rather than at the bottom of the range.
    border = np.concatenate([grey[0, :], grey[-1, :], grey[:, 0], grey[:, -1]])
    paper = float(np.quantile(border, 0.9))
    darkest = float(grey.min())
    return grey < paper - PALE_MARGIN * (paper - darkest)


def hough(shape: tuple[int, int], dark: np.ndarray, radius: int) -> np.ndarray:
    """Return a centre-vote image for one radius, over the drawing's own stroke pixels."""
    height, width = shape
    ys, xs = np.nonzero(dark)
    accumulator = np.zeros((height, width), dtype=np.int32)
    angles = np.linspace(0.0, 2.0 * math.pi, 240, endpoint=False)
    cosines, sines = np.cos(angles), np.sin(angles)
    # Four half-pixel offsets recover the sub-pixel centre an integer raster cannot hold.
    for dy, dx in ((0.5, 0.0), (-0.5, 0.0), (0.0, 0.5), (0.0, -0.5)):
        cx = np.rint(xs[:, None] + dy + radius * cosines[None, :]).astype(np.int32).ravel()
        cy = np.rint(ys[:, None] + dx + radius * sines[None, :]).astype(np.int32).ravel()
        inside = (cx >= 0) & (cx < width) & (cy >= 0) & (cy < height)
        np.add.at(accumulator, (cy[inside], cx[inside]), 1)
    return accumulator


def peaks(accumulator: np.ndarray, count: int, distance: int) -> list[tuple[float, float, int]]:
    """Return the strongest well-separated centres of a vote image."""
    work = accumulator.copy()
    found: list[tuple[float, float, int]] = []
    for _ in range(count):
        index = int(np.argmax(work))
        y, x = divmod(index, work.shape[1])
        score = int(work[y, x])
        if score <= 0:
            break
        found.append((float(x), float(y), score))
        y0, y1 = max(0, y - distance), min(work.shape[0], y + distance + 1)
        x0, x1 = max(0, x - distance), min(work.shape[1], x + distance + 1)
        work[y0:y1, x0:x1] = 0
    return found


def fit_circle(points: np.ndarray) -> tuple[float, float, float]:
    """Return the circle through points, by the algebraic least-squares fit."""
    x, y = points[:, 0], points[:, 1]
    matrix = np.column_stack([x, y, np.ones(len(x))])
    solution, *_ = np.linalg.lstsq(matrix, x**2 + y**2, rcond=None)
    cx, cy = float(solution[0]) / 2.0, float(solution[1]) / 2.0
    radius = math.sqrt(max(0.0, float(solution[2]) + cx * cx + cy * cy))
    return cx, cy, radius


def refine(dark: np.ndarray, centre: tuple[float, float, int], radius: float) -> tuple[float, float, float] | None:
    """Return one centre and its radius, fitted on the strokes that vote for it."""
    ys, xs = np.nonzero(dark)
    cx, cy, _ = centre
    distance = np.hypot(xs - cx, ys - cy)
    near = np.abs(distance - radius) <= 2.0
    if int(near.sum()) < 12:
        return None
    fitted_cx, fitted_cy, fitted = fit_circle(np.column_stack([xs[near], ys[near]]).astype(float))
    if not math.isfinite(fitted) or fitted <= 0.0:
        return None
    if abs(fitted - radius) > RADIUS_DRIFT * radius:
        return None
    return fitted_cx, fitted_cy, fitted


def separated(centres: list[tuple[float, float, float]]) -> bool:
    """Whether a reading puts every pair of copies at least a stroke apart."""
    for first in range(len(centres)):
        for second in range(first + 1, len(centres)):
            dx = centres[first][0] - centres[second][0]
            dy = centres[first][1] - centres[second][1]
            if math.hypot(dx, dy) < TOUCHING * max(centres[first][2], centres[second][2]):
                return False
    return True


#: The share of one copy's own circumference that must carry strokes before the reading
#: is believed: a real outline is mostly present, a wrong circle crosses a few lines.
CIRCLE_SUPPORT = 0.35

#: The share of the whole drawing's ink a reading must account for. A figure is mostly its
#: copies; a reading that explains a sixth of the strokes has found corners and crossings,
#: whatever its own circles look like.
MIN_EXPLAINED = 0.4

#: How far a stroke pixel may sit from a circle and still count as its outline.
STROKE_WIDTH = 1.5


def detect_discs(path: Path, count: int) -> tuple[float, list[tuple[float, float]], float] | None:
    """Return the copy radius, centres and explained share a drawing shows, or None.

    Which radius is right cannot be read off the vote image alone: a small circle collects
    votes from every stroke that happens to cross it, so votes per radius would always
    prefer the smallest. What separates the true reading is how much of the drawing it
    explains -- the copies' own outlines are most of a figure's ink -- so each candidate
    reading is scored by the share of stroke pixels that lie on one of its circles, and
    only a reading whose circles are each mostly supported, and do not overlap, is kept.
    """
    dark = dark_mask(path)
    ys, xs = np.nonzero(dark)
    points = np.column_stack([xs, ys]).astype(float)
    best: tuple[float, float, list[tuple[float, float]]] | None = None
    for radius in range(MIN_RADIUS, min(dark.shape) // 2 + 1):
        votes = peaks(hough(dark.shape, dark, radius), count, max(3, int(radius * 0.9)))
        if len(votes) < count:
            continue
        fitted = [refine(dark, vote, float(radius)) for vote in votes]
        centres = [item for item in fitted if item is not None]
        if len(centres) < count:
            continue
        measured = sum(item[2] for item in centres) / len(centres)
        if not separated([(cx, cy, measured) for cx, cy, _ in centres]):
            continue
        covered = np.zeros(len(points), dtype=bool)
        supported = True
        for cx, cy, own in centres:
            near = np.abs(np.hypot(points[:, 0] - cx, points[:, 1] - cy) - own) <= STROKE_WIDTH
            if int(near.sum()) < CIRCLE_SUPPORT * 2.0 * math.pi * own:
                supported = False
                break
            covered |= near
        if not supported:
            continue
        explained = float(covered.sum()) / float(len(points))
        if explained < MIN_EXPLAINED:
            continue
        if best is None or explained > best[0]:
            best = (explained, measured, [(cx, cy) for cx, cy, _ in centres])
    if best is None:
        return None
    return best[1], best[2], best[0]


# --------------------------------------------------------------------------------------
# A drawing of polygonal copies
#
# A circle is found by its outline alone, which is the same curve wherever it sits. A
# square, a pentagon or a tan is not: it has to be found with its own turn. What a drawing
# gives instead is its enclosed regions. Every copy of a line drawing is a closed white
# region, and equal copies are equal regions, so the copies of a figure are the group of
# enclosed regions that share one area -- the corners and gaps between them do not. Once a
# region names a copy's centre, its turn and its size come from the strokes themselves: the
# copy's own outline, taken from the geometry layer, is placed until it lies on them.
# --------------------------------------------------------------------------------------

#: How much two enclosed regions may differ in area and still be called copies.
AREA_TOLERANCE = 0.12

#: Turns a copy is tried at, in degrees, before the first refinement and during it. A
#: regular polygon is only tried over one of its symmetry periods, since a square turned by
#: ninety degrees is the same square.
COARSE_TURN = 5.0
FINE_TURN = 1.0

#: How much of a copy the interior check looks at, and what a stroke under it costs. A
#: drawing's copies are closed regions, so their insides are white: an outline turned the
#: wrong way by ten degrees still lies near plenty of strokes when the copies touch, but its
#: interior then covers a neighbour's edge, which is what settles the turn.
INTERIOR_SHRINK = 0.6
INTERIOR_WEIGHT = 4.0

#: How far a copy's size may be wrong before the turn search, as a fraction of the area's
#: reading: the strokes cover part of the copy, so the enclosed region is always smaller.
SIZE_WINDOW = 0.2


def distance_to_ink(ink: np.ndarray) -> np.ndarray:
    """Return every pixel's distance to the nearest stroke, by a chamfer sweep."""
    height, width = ink.shape
    distance = np.where(ink, 0.0, 1e9)
    straight, diagonal = 1.0, math.sqrt(2.0)
    for y in range(height):
        for x in range(width):
            best = distance[y, x]
            if best == 0.0:
                continue
            if y > 0:
                best = min(best, distance[y - 1, x] + straight)
            if x > 0:
                best = min(best, distance[y, x - 1] + straight)
            if y > 0 and x > 0:
                best = min(best, distance[y - 1, x - 1] + diagonal)
            if y > 0 and x < width - 1:
                best = min(best, distance[y - 1, x + 1] + diagonal)
            distance[y, x] = best
    for y in range(height - 1, -1, -1):
        for x in range(width - 1, -1, -1):
            best = distance[y, x]
            if best == 0.0:
                continue
            if y < height - 1:
                best = min(best, distance[y + 1, x] + straight)
            if x < width - 1:
                best = min(best, distance[y, x + 1] + straight)
            if y < height - 1 and x < width - 1:
                best = min(best, distance[y + 1, x + 1] + diagonal)
            if y < height - 1 and x > 0:
                best = min(best, distance[y + 1, x - 1] + diagonal)
            distance[y, x] = best
    return distance


def enclosed_regions(ink: np.ndarray) -> list[np.ndarray]:
    """Return the coordinates of every white region the strokes enclose.

    The region touching the image's edge is the paper around the figure, and is dropped:
    what is left is the copies' insides and the space between them, and the two are told
    apart by their size rather than by their position.
    """
    light = ~ink
    height, width = light.shape
    seen = np.zeros((height, width), dtype=bool)
    regions: list[np.ndarray] = []
    for y in range(height):
        for x in range(width):
            if not light[y, x] or seen[y, x]:
                continue
            stack = [(y, x)]
            seen[y, x] = True
            pixels: list[tuple[int, int]] = []
            touches_edge = False
            while stack:
                cy, cx = stack.pop()
                pixels.append((cx, cy))
                if cx in (0, width - 1) or cy in (0, height - 1):
                    touches_edge = True
                for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                    if 0 <= ny < height and 0 <= nx < width and light[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            if not touches_edge:
                regions.append(np.asarray(pixels, dtype=float))
    return regions


def equal_regions(regions: list[np.ndarray], count: int) -> list[np.ndarray] | None:
    """Return the regions of nearly one area, or None when no group of them has the count.

    The copies are the only congruent thing in a figure: the gaps between them and the
    corners of the container vary with the arrangement, while every copy's inside is the
    same shape at the same size.
    """
    best: tuple[float, list[np.ndarray]] | None = None
    for region in regions:
        area = float(len(region))
        group = [other for other in regions if abs(len(other) - area) <= AREA_TOLERANCE * area]
        if len(group) != count:
            continue
        areas = np.array([len(item) for item in group], dtype=float)
        spread = float(areas.std() / areas.mean())
        if best is None or spread < best[0]:
            best = (spread, group)
    return None if best is None else best[1]


def base_outline(problem) -> np.ndarray:
    """Return one copy's outline at size one, straight from the geometry layer.

    Nothing here decides what a copy looks like: the domain's own shape is asked for the
    corners a drawing would show, through the same view a canvas is drawn from.
    """
    probe = Candidate(
        candidate_id="outline",
        problem_id=problem.problem_id,
        scale=1.0,
        placements=(Placement(shape_id="s000", x=0.0, y=0.0),),
    )
    primitive = build_view(problem, probe, with_violations=False).shapes[0]
    if primitive.kind == "circle":
        steps = np.linspace(0.0, 2.0 * math.pi, 24, endpoint=False)
        return np.column_stack([np.cos(steps), np.sin(steps)]) * float(primitive.radius or 0.0)
    return np.asarray(primitive.points, dtype=float)


def outline_at(base: np.ndarray, size: float, turn: float, centre: tuple[float, float]) -> np.ndarray:
    """Return the outline of one copy, at a size and a turn, around a centre."""
    radians = math.radians(turn)
    cosine, sine = math.cos(radians), math.sin(radians)
    turned = np.column_stack([
        base[:, 0] * cosine - base[:, 1] * sine,
        base[:, 0] * sine + base[:, 1] * cosine,
    ])
    return turned * size + np.asarray(centre, dtype=float)


def sampled(distance: np.ndarray, points: np.ndarray) -> np.ndarray:
    """Return the distance-to-stroke of every sampled point, clamped to the drawing."""
    height, width = distance.shape
    xs = np.clip(np.rint(points[:, 0]).astype(int), 0, width - 1)
    ys = np.clip(np.rint(points[:, 1]).astype(int), 0, height - 1)
    return distance[ys, xs]


def stroke_cost(distance: np.ndarray, points: np.ndarray) -> float:
    """Return the mean distance from an outline to the nearest stroke."""
    return float(sampled(distance, points).mean())


def copy_cost(
    distance: np.ndarray, base: np.ndarray, size: float, turn: float, centre: tuple[float, float]
) -> float:
    """Return what a copy at a size and a turn costs: its outline against the strokes, and
    the strokes its own inside would cover."""
    outline = sampled(distance, outline_at(base, size, turn, centre))
    inside = sampled(distance, outline_at(base, size * INTERIOR_SHRINK, turn, centre))
    return float(outline.mean()) + INTERIOR_WEIGHT * float((inside <= 1.0).mean())


def symmetry_period(problem) -> float:
    """Return the turn after which a copy looks the same, in degrees."""
    sides = getattr(problem.shape, "sides", None)
    return 360.0 / float(sides) if sides else 360.0


#: The share of a region's longest hull edge that an edge must reach to be read as one of
#: the copy's own sides rather than as one of the staircase steps a raster leaves behind.
EDGE_SHARE = 0.3


def template_edge_offset(base: np.ndarray) -> float:
    """Return the angle of one copy's first edge at no turn, in degrees."""
    return math.degrees(math.atan2(float(base[1][1] - base[0][1]), float(base[1][0] - base[0][0])))


def region_turn(pixels: np.ndarray, period: float, offset: float) -> float:
    """Return a region's turn, read from the directions of its own sides.

    The stroke fit alone is flat for a regular polygon: near the right turn, moving the
    outline a couple of degrees leaves it about as close to the same strokes, so it can
    settle ten degrees away and cost the arrangement a tenth of its value. The region's own
    outline is not flat. A copy's inside is that copy shrunk by the stroke that draws it, so
    its sides are parallel to the copy's sides, and the long edges of its convex hull are
    those sides: their directions, folded into one symmetry period, say where the copy is
    turned. Short edges are the staircase a raster leaves on a slanted side and are dropped.
    """
    hull = shapely.geometry.MultiPoint(pixels).convex_hull
    ring = np.asarray(hull.exterior.coords, dtype=float)
    if len(ring) < 4:
        return 0.0
    edges = np.diff(ring, axis=0)
    lengths = np.hypot(edges[:, 0], edges[:, 1])
    keep = lengths >= EDGE_SHARE * float(lengths.max())
    if not bool(keep.any()):
        return 0.0
    angles = np.degrees(np.arctan2(edges[keep, 1], edges[keep, 0]))
    folded = np.radians([(angle - offset) % period for angle in angles])
    turn = math.degrees(math.atan2(float(np.sin(folded).mean()), float(np.cos(folded).mean())))
    return turn % period


def fit_copy(
    distance: np.ndarray,
    base: np.ndarray,
    centre: tuple[float, float],
    guess: float,
    period: float,
    turn_guess: float | None = None,
) -> tuple[float, float]:
    """Return the size and the turn whose outline lies best on the drawing's strokes.

    The guess comes from the region's area, which the strokes have eaten into, so the size
    is searched around it and the turn over the copy's own symmetry period -- a square
    turned by ninety degrees being the same square, and nothing else being.
    """
    # The region's own sides give a turn to start from, but they only fix it up to the
    # copy's symmetry: a triangle's edges say as much about the copy turned by sixty degrees
    # as about the copy itself. The guess is therefore tried beside the coarse grid rather
    # than instead of it, and the cost -- which sees the strokes a wrong turn would put under
    # the copy -- decides between them.
    candidates = [float(turn) for turn in np.arange(0.0, period, COARSE_TURN)]
    if turn_guess is not None:
        candidates.append(float(turn_guess) % period)
    best: tuple[float, float, float] | None = None
    for turn in candidates:
        cost = copy_cost(distance, base, guess, turn, centre)
        if best is None or cost < best[0]:
            best = (cost, guess, turn)
    span = SIZE_WINDOW / 3.0
    for _ in range(4):
        _, size, turn = best  # type: ignore[misc]
        for candidate_size in np.linspace(size * (1.0 - span), size * (1.0 + span), 7):
            for candidate_turn in np.arange(turn - 2.0 * FINE_TURN, turn + 2.0 * FINE_TURN + 1e-9, FINE_TURN):
                cost = copy_cost(distance, base, candidate_size, candidate_turn, centre)
                if cost < best[0]:
                    best = (cost, candidate_size, float(candidate_turn))
    return best[1], best[2]


#: How far a stroke may sit from a copy's outline and still count as explained by it.
OUTLINE_REACH = 1.5


def explained_ink(ink: np.ndarray, outlines: np.ndarray) -> float:
    """Return the share of a drawing's strokes that lie on the copies' own outlines.

    The container's outline is drawn too, and a reading of copies is not expected to explain
    it: what this measures is how much of the figure the reading accounts for, which is what
    tells a good reading of a busy drawing from a lucky one.
    """
    stamp = np.zeros(ink.shape, dtype=bool)
    height, width = ink.shape
    xs = np.clip(np.rint(outlines[:, 0]).astype(int), 0, width - 1)
    ys = np.clip(np.rint(outlines[:, 1]).astype(int), 0, height - 1)
    stamp[ys, xs] = True
    near = distance_to_ink(~stamp) <= OUTLINE_REACH
    return float((ink & near).sum()) / float(max(int(ink.sum()), 1))


def detect_copies(
    path: Path, count: int, problem
) -> tuple[float, np.ndarray, list[float], float] | None:
    """Return the copy size, the layout, the turns and the explained ink of a drawing.

    The layout comes back in copy sizes with the engine's own axes, and the turns in
    degrees: together they are the reading, and the engine is what says whether it is a
    packing and what it is worth.
    """
    ink = dark_mask(path)
    distance = distance_to_ink(ink)
    group = equal_regions(enclosed_regions(ink), count)
    if group is None:
        return None
    base = base_outline(problem)
    period = symmetry_period(problem)
    unit_area = float(problem.shape.area(1.0))
    if unit_area <= 0.0:
        return None
    centres = [(float(item[:, 0].mean()), float(item[:, 1].mean())) for item in group]
    guesses = [math.sqrt(len(item) / unit_area) for item in group]
    # The layout's own unit is the region's reading and not the fitted one. The strokes eat
    # into every region, so that reading is a little small, and a small unit spreads the
    # layout: the value the engine then reports is a little worse than the drawing's own,
    # which is the direction a reading should err in. The fit is kept for the turns, where
    # the strokes are what tells one copy's corner from another's.
    common = float(np.median(guesses))
    offset = template_edge_offset(base)
    fitted: list[tuple[float, float]] = []
    for region, centre, guess in zip(group, centres, guesses):
        # A regular polygon's own sides say where it is turned, and the strokes refine it
        # from there; a shape with no rotational symmetry has no such reading to start from.
        turn_guess = region_turn(region, period, offset) if period < 360.0 else None
        fitted.append(fit_copy(distance, base, centre, guess, period, turn_guess))
    turns: list[float] = []
    settled: list[tuple[float, float]] = []
    for centre, (_, turn) in zip(centres, fitted):
        best = (stroke_cost(distance, outline_at(base, common, turn, centre)), turn, centre)
        for offset in (-1.0, 0.0, 1.0):
            for shift_x in (-1.0, 0.0, 1.0):
                for shift_y in (-1.0, 0.0, 1.0):
                    moved = (centre[0] + shift_x, centre[1] + shift_y)
                    cost = stroke_cost(distance, outline_at(base, common, turn + offset * FINE_TURN, moved))
                    if cost < best[0]:
                        best = (cost, turn + offset * FINE_TURN, moved)
        turns.append(float(best[1]) % 360.0)
        settled.append(best[2])
    mean_x = float(np.mean([centre[0] for centre in settled]))
    mean_y = float(np.mean([centre[1] for centre in settled]))
    layout = np.array([[(cx - mean_x) / common, -(cy - mean_y) / common] for cx, cy in settled])
    outlines = [
        outline_at(base, common, turn, centre) for centre, turn in zip(settled, turns)
    ]
    return common, layout, turns, explained_ink(ink, np.vstack(outlines))


def unit_pattern(centres: list[tuple[float, float]], radius: float) -> np.ndarray:
    """Return the centres in copy radii, centred on their own centroid and turned upright.

    The drawing's y axis points down and the engine's points up, so the reading is flipped
    once, here, and nowhere else.
    """
    points = np.array([[cx, -cy] for cx, cy in centres], dtype=float)
    points -= points.mean(axis=0)
    return points / radius


def placed(
    problem_id: str, pattern: np.ndarray, scale: float, origin: str, turns: list[float] | None = None
) -> Candidate:
    """Return the pattern as a candidate of a problem, at one common scale.

    The turns travel with the reading: a square found at forty degrees is placed at forty
    degrees, and only its scale and the anchors of the whole layout are the engine's to set.
    """
    return Candidate(
        candidate_id=f"{problem_id}-figure",
        problem_id=problem_id,
        scale=scale,
        placements=tuple(
            Placement(
                shape_id=f"s{index:03d}",
                x=float(x) * scale,
                y=float(y) * scale,
                rotation=0.0 if turns is None else float(turns[index]),
            )
            for index, (x, y) in enumerate(pattern)
        ),
        origin=origin,
    )


def settled_layout(
    problem, pattern: np.ndarray, turns: list[float] | None
) -> np.ndarray | None:
    """Return a reading's layout with its copies pulled apart, or None when they cannot be.

    A reading is never exact: two copies that touch in a drawing come back a fraction of a
    pixel closer than touching, and the engine rejects that at every scale. The layout comes
    back in copy sizes and a hair wider than it was, so the copies have room at every scale
    the search will try.
    """
    seed = placed(problem.problem_id, pattern, SEED_SCALE, "source-derived-approximation", turns)
    settled = repair_overlaps(
        problem, seed, iterations=REPAIR_STEPS, origin="source-derived-approximation"
    )
    if not evaluate(problem, settled).valid:
        return None
    layout = np.array([[item.x / SEED_SCALE, item.y / SEED_SCALE] for item in settled.placements])
    return layout * (1.0 + SEPARATION_SLACK)


def fitted_scale(
    problem, pattern: np.ndarray, turns: list[float] | None = None
) -> tuple[float, Candidate] | None:
    """Return the largest scale the engine accepts for a reading, and its candidate.

    A reading is never exact: two copies that touch in a drawing come back a fraction of a
    pixel closer than touching, and the engine rejects that at every scale, so the reading
    is settled before it is grown. The first pass is not a formality -- it is what turns a
    picture into a valid arrangement at all -- and the growth is the engine's own operator,
    which bisects on the verdict it alone can give.
    """
    layout = settled_layout(problem, pattern, turns)
    if layout is None:
        return None
    # The engine scales a layout about the origin and never moves it, so the placement the
    # drawing happens to give is searched over rather than trusted: the best of a coarse
    # grid is worth several percent of the value, and the local search then refines it.
    best: Candidate | None = None
    for shift_x in np.arange(-SHIFT_REACH, SHIFT_REACH + 1e-9, SHIFT_STEP):
        for shift_y in np.arange(-SHIFT_REACH, SHIFT_REACH + 1e-9, SHIFT_STEP):
            shifted = layout + np.array([shift_x, shift_y])
            seed = placed(problem.problem_id, shifted, SEED_SCALE, "source-derived-approximation", turns)
            if not evaluate(problem, seed).valid:
                continue
            grown = fit_layout_scale(problem, seed, origin="source-derived-approximation")
            if best is None or grown.scale > best.scale:
                best = grown
    if best is None:
        return None
    polished = polish(problem, best, iterations=POLISH_STEPS, origin="source-derived-approximation")
    if evaluate(problem, polished).valid and polished.scale >= best.scale:
        best = polished
    if not evaluate(problem, best).valid:
        return None
    return best.scale, best


def derived_reading(
    problem, pattern: np.ndarray, turns: list[float] | None = None
) -> tuple[float, Candidate] | None:
    """Return a reading of a problem that measures its own container.

    A container the engine derives -- a smallest square, a smallest circle -- is measured
    from the arrangement, in the copies' own size. Such a problem fixes nothing about the
    scale, so the reading is the arrangement itself: the copies stay at size one and the
    layout carries all of it, in copy sizes, which is the unit the value is printed in.
    There is no scale to search and no placement to search either: translating a derived
    container does not change it, so the reading is settled and then left to the local
    search that knows the objective's own steps.
    """
    # Such a problem fixes the copies' size: the value is what the arrangement needs per
    # unit copy, so a candidate at any other scale is not an arrangement of this problem at
    # all. The reading is therefore laid out at size one, and the repair has only to
    # separate copies the drawing puts a little too close.
    unit = placed(problem.problem_id, pattern, 1.0, "source-derived-approximation", turns)
    settled = repair_overlaps(
        problem, unit, iterations=REPAIR_STEPS, origin="source-derived-approximation"
    )
    if not evaluate(problem, settled).valid:
        return None
    unit = settled
    polished = polish(problem, unit, iterations=POLISH_STEPS, origin="source-derived-approximation")
    best = unit
    if evaluate(problem, polished).valid and evaluate(problem, polished).is_better_than(
        evaluate(problem, unit)
    ):
        best = polished
    return best.scale, best


def reconstruct(problem, path: Path, count: int) -> tuple[Candidate, dict[str, Any]] | None:
    """Return a candidate read off one drawing, and what the reading found.

    A figure of discs is read by its outlines, which are the same curve wherever they sit.
    A figure of anything else is read by the regions its strokes enclose: a copy's inside is
    a closed region and equal copies are equal regions, which is what a rotated square, a
    pentagon or a tan has instead of an invariant outline. Both readings come back as a
    layout in copy sizes and, for the second, the turn of every copy -- all the engine needs
    to be asked what the arrangement is worth.
    """
    turns: list[float] | None = None
    if bool(getattr(problem.shape, "is_circle", False)):
        reading = detect_discs(path, count)
        if reading is None:
            return None
        size, centres, explained = reading
        pattern = unit_pattern(centres, size)
    else:
        copies = detect_copies(path, count, problem)
        if copies is None:
            return None
        size, pattern, turns, explained = copies
    if bool(getattr(problem.objective, "derives_region", False)):
        fitted = derived_reading(problem, pattern, turns)
    else:
        fitted = fitted_scale(problem, pattern, turns)
    if fitted is None:
        return None
    scale, candidate = fitted
    # The local search hands back a child with a fresh identifier, which would make two runs
    # of the same reading two different documents. A reading is a function of a drawing, so
    # its identifier says which card it belongs to and nothing else.
    candidate = replace(
        candidate,
        candidate_id=f"{problem.problem_id}-figure",
        metadata={
            "figure": path.name,
            "detected_size_px": round(size, 2),
            "detected_turns": [] if turns is None else [round(turn, 2) for turn in turns],
            "explained_ink": round(explained, 4),
            "detected_layout": [[round(float(x), 3), round(float(y), 3)] for x, y in pattern],
            "method": "copies found by their outlines (discs) or by the regions they enclose, "
            "their turn from the fit or from the corners, then the engine's own scale fit "
            "over a grid of placements and a local search",
        },
    )
    return candidate, {"size": size, "scale": scale, "explained": explained}


def cards(family: dict[str, Any]) -> list[tuple[int, dict[str, Any]]]:
    """Return every card of a family, with the instance that printed it."""
    return [
        (count, instance)
        for instance in family.get("instances", [])
        for count in counts_of(instance)
    ]


def reconstruct_family(family: dict[str, Any], counts: list[int], *, refresh: bool) -> int:
    """Write one candidate per readable drawing of a family; return how many were written.

    Every reading this module owns for the family is cleared first, so a drawing that can no
    longer be read leaves no candidate behind: what a run leaves on disk is what that run
    read, never a mixture of a reading and its own past.
    """
    slug = str(family.get("slug") or "")
    written = 0
    for stale in sorted((ASSET.parent / "candidates").glob(f"approx-{slug}-*.json")):
        stale.unlink()
    for count, instance in cards(family):
        if counts and count not in counts:
            continue
        if instance.get("value") is None or not str(instance.get("figure") or ""):
            continue
        try:
            path = figure_file(str(family["page"]), str(instance["figure"]), refresh=refresh)
        except Exception as error:
            print(f"{slug} n={count}: the figure could not be fetched: {error}")
            continue
        problem = card_problem(family, instance, count)
        try:
            result = reconstruct(problem, path, count)
        except ImportError as error:
            print(error)
            return -1
        if result is None:
            print(f"{slug} n={count}: the drawing could not be read")
            continue
        candidate, reading = result
        verdict = evaluate(problem, candidate)
        reference = reference_of(family, instance)
        compared = REFERENCE_METRICS.get(str(reference.get("unit") or ""))
        measured = measure_of(reference, verdict)
        value = reference.get("value")
        gap = None
        if measured is not None and compared is not None and isinstance(value, (int, float)) and value:
            gap = (measured - value) / abs(value) * (1.0 if compared[1] else -1.0)
        if gap is not None and gap < -MAX_GAP:
            print(f"{slug} n={count}: the reading is too far off its record ({gap:.1%}), dropped")
            continue
        save_candidate(candidate, ASSET.parent / "candidates" / f"approx-{slug}-{count}.json")
        written += 1
        print(
            f"{slug} n={count}: size {reading['size']:.1f}px, ink {reading['explained']:.0%}, "
            f"scale {reading['scale']:.6g}, {'valid' if verdict.valid else 'invalid'}, "
            f"gap {gap if gap is None else round(gap, 6)}"
        )
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--family", default="", help="a catalog slug; empty means every disc family")
    parser.add_argument("--counts", default="", help="comma-separated counts to read")
    parser.add_argument("--refresh", action="store_true", help="re-download the figures")
    args = parser.parse_args(argv)
    catalog = json.loads(ASSET.read_text(encoding="utf-8"))
    wanted = [args.family] if args.family else list(DISC_FAMILIES)
    counts = [int(item) for item in args.counts.split(",") if item.strip()]
    families = {family["slug"]: family for family in catalog["families"]}
    total = 0
    for slug in wanted:
        family = families.get(slug)
        if family is None:
            print(f"{slug}: no such family")
            continue
        if not family.get("problem_template"):
            print(f"{slug}: the lab cannot build this family")
            continue
        written = reconstruct_family(family, counts, refresh=args.refresh)
        if written < 0:
            return 1
        total += written
    print(f"wrote {total} approximations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
