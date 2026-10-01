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

What it handles, and what it does not
-------------------------------------
Discs only, for now: a circle's outline is the same curve wherever it sits, which is what
makes the accumulator work. A rotated square, pentagon or tan has no such invariant, and
those families need a different reading of the same drawing. The families this module
serves are the disc families the catalogue lists and Packomania does not cover:
`cirintri`, `cirintan`, `cirinel` and `cirinl`.

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
POLISH_STEPS = 12

#: How far below its record a reading may land and still be kept, as a fraction of the
#: record. A drawing read this badly -- the copies found at the wrong radius, say -- is not
#: a starting point at all, and keeping it would only make the catalogue's own badges
#: worse. Nothing is written for it, and the run says so.
MAX_GAP = 0.5


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


def dark_mask(path: Path) -> np.ndarray:
    """Return the drawing's strokes as a boolean image."""
    try:
        from PIL import Image
    except ImportError as error:  # pragma: no cover - the extra is installed in CI
        raise ImportError(module_message(error)) from error
    with Image.open(path) as source:
        grey = np.asarray(source.convert("L"))
    return grey < 128


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


def unit_pattern(centres: list[tuple[float, float]], radius: float) -> np.ndarray:
    """Return the centres in copy radii, centred on their own centroid and turned upright.

    The drawing's y axis points down and the engine's points up, so the reading is flipped
    once, here, and nowhere else.
    """
    points = np.array([[cx, -cy] for cx, cy in centres], dtype=float)
    points -= points.mean(axis=0)
    return points / radius


def placed(problem_id: str, pattern: np.ndarray, scale: float, origin: str) -> Candidate:
    """Return the pattern as a candidate of a problem, at one common scale."""
    return Candidate(
        candidate_id=f"{problem_id}-figure",
        problem_id=problem_id,
        scale=scale,
        placements=tuple(
            Placement(shape_id=f"s{index:03d}", x=float(x) * scale, y=float(y) * scale)
            for index, (x, y) in enumerate(pattern)
        ),
        origin=origin,
    )


def fitted_scale(problem, pattern: np.ndarray) -> tuple[float, Candidate] | None:
    """Return the largest scale the engine accepts for a reading, and its candidate.

    A reading is never exact: two copies that touch in a drawing come back a fraction of a
    pixel closer than touching, and the engine rejects that at every scale, so the reading
    is settled before it is grown. The first pass is not a formality -- it is what turns a
    picture into a valid arrangement at all -- and the growth is the engine's own operator,
    which bisects on the verdict it alone can give.
    """
    seed = placed(problem.problem_id, pattern, SEED_SCALE, "source-derived-approximation")
    settled = repair_overlaps(
        problem, seed, iterations=REPAIR_STEPS, origin="source-derived-approximation"
    )
    if not evaluate(problem, settled).valid:
        return None
    # Back in copy radii, so the layout can be laid out again at any scale: the engine's
    # scale is a property of the copies, and positions only mean something beside it.
    layout = np.array(
        [[item.x / SEED_SCALE, item.y / SEED_SCALE] for item in settled.placements]
    ) * (1.0 + SEPARATION_SLACK)
    grown = fit_layout_scale(
        problem,
        placed(problem.problem_id, layout, SEED_SCALE, "source-derived-approximation"),
        origin="source-derived-approximation",
    )
    polished = polish(problem, grown, iterations=POLISH_STEPS, origin="source-derived-approximation")
    if evaluate(problem, polished).valid and polished.scale >= grown.scale:
        return polished.scale, polished
    if not evaluate(problem, grown).valid:
        return None
    return grown.scale, grown


def reconstruct(problem, path: Path, count: int) -> tuple[Candidate, dict[str, Any]] | None:
    """Return a candidate read off one drawing, and what the reading found."""
    reading = detect_discs(path, count)
    if reading is None:
        return None
    radius, centres, explained = reading
    pattern = unit_pattern(centres, radius)
    fitted = fitted_scale(problem, pattern)
    if fitted is None:
        return None
    scale, candidate = fitted
    candidate = replace(
        candidate,
        metadata={
            "figure": path.name,
            "detected_radius_px": radius,
            "explained_ink": round(explained, 4),
            "detected_centres": [[round(cx, 2), round(cy, 2)] for cx, cy in centres],
            "method": "Hough accumulator over stroke pixels, least-squares circle fit, "
            "bisection on the engine's verdict, then a short local search",
        },
    )
    return candidate, {"radius": radius, "scale": scale, "explained": explained}


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
            f"{slug} n={count}: radius {reading['radius']:.1f}px, ink {reading['explained']:.0%}, "
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
