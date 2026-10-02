"""Build the arrangement of a domlayers.c structure and write it as a lab candidate.

Tan units: right angle at the origin, legs along u and v, hypotenuse u + v = s. The upright
dominoes are a maximum matching of the cells of the Young diagram D (columns of the given
heights); each band along the hypotenuse is filled from the start of every free interval, lying
dominoes in a band of width 1, standing ones in a pair of bands. A free interval is what the cells
of D and the stacks leave of the band's inner edge, between the legs.

Usage: python dombuild.py A C "8,8,8,7,6,5,4,4,4,4,3,2,1" lllllllll N -o cand.json
       [--apex V2] [--corner H1]
The legs are A + C/sqrt2; N keeps the first N dominoes (upright ones first).
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

R2 = math.sqrt(2)
HERE = Path(__file__).resolve().parent
EPS = 1e-9


def matching(cells: set[tuple[int, int]]) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """A maximum set of disjoint dominoes on the cells (Kuhn's augmenting paths)."""
    black = [c for c in cells if (c[0] + c[1]) % 2 == 0]
    mate: dict[tuple[int, int], tuple[int, int]] = {}

    def augment(cell, seen):
        i, j = cell
        for other in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
            if other in cells and other not in seen:
                seen.add(other)
                if other not in mate or augment(mate[other], seen):
                    mate[other] = cell
                    return True
        return False

    for cell in sorted(black):
        augment(cell, set())
    return [(b, w) for w, b in mate.items()]


def strip_extent(rect, level, width):
    """p-extent of the rectangle (u0, u1, v0, v1) inside the open strip level < q < level + width."""
    u0, u1, v0, v1 = rect
    points = [((u - v) / R2, (u + v) / R2) for u, v in ((u0, v0), (u1, v0), (u1, v1), (u0, v1))]
    for side in (0, 1):
        clipped = []
        for k, (p, q) in enumerate(points):
            p2, q2 = points[(k + 1) % len(points)]
            f = q - level if side == 0 else level + width - q
            f2 = q2 - level if side == 0 else level + width - q2
            if f >= 0:
                clipped.append((p, q))
            if (f >= 0) != (f2 >= 0):
                t = f / (f - f2)
                clipped.append((p + t * (p2 - p), q + t * (q2 - q)))
        points = clipped
        if not points:
            return None
    ps, qs = [p for p, _ in points], [q for _, q in points]
    if max(qs) - min(qs) < EPS or max(ps) - min(ps) < EPS:
        return None
    return min(ps), max(ps)


def fill(level, width, length, obstacles):
    """Starts of the pieces of the given length packed from the left of each free interval."""
    blocked = sorted(filter(None, (strip_extent(r, level, width) for r in obstacles)))
    starts, x = [], -level
    for lo, hi in blocked + [(level, level)]:
        end = min(lo, level)
        while x + length <= end + EPS:
            starts.append(x)
            x += length
        x = max(x, hi)
    return starts


def stacks(s, apex, corner):
    """Upright dominoes pushed into the acute corners: (u, v, degrees) and their rectangles."""
    pieces = []
    if apex:
        kind, n = apex[0], int(apex[1:])
        for k in range(n):
            if kind == "V":   # vertical dominoes in column 0, the top one under the hypotenuse
                pieces.append((0.5, s - 2 - 2 * k, 90.0, (0, 1, s - 3 - 2 * k, s - 1 - 2 * k)))
            else:             # horizontal dominoes over columns 0 and 1
                pieces.append((1.0, s - 2.5 - k, 0.0, (0, 2, s - 3 - k, s - 2 - k)))
    if corner:
        kind, n = corner[0], int(corner[1:])
        for k in range(n):
            if kind == "H":   # horizontal dominoes in row 0, the last one under the hypotenuse
                pieces.append((s - 2 - 2 * k, 0.5, 0.0, (s - 3 - 2 * k, s - 1 - 2 * k, 0, 1)))
            else:             # vertical dominoes over rows 0 and 1
                pieces.append((s - 2.5 - k, 1.0, 90.0, (s - 3 - k, s - 2 - k, 0, 2)))
    return pieces


def build(a, c, heights, bands, apex=None, corner=None):
    s = a + c / R2
    cells = {(i, j) for i, h in enumerate(heights) for j in range(h)}
    pieces = []
    for (i, j), (k, l) in matching(cells):
        pieces.append(((i + k) / 2 + 0.5, (j + l) / 2 + 0.5, 0.0 if j == l else 90.0))
    obstacles = [(i, i + 1, j, j + 1) for i, j in cells]
    for u, v, angle, rect in stacks(s, apex, corner):
        pieces.append((u, v, angle))
        obstacles.append(rect)
    levels = [s / R2 - (k + 1) for k in range(len(bands))]
    k = 0
    while k < len(bands):
        if bands[k] == "l":
            for x in fill(levels[k], 1.0, 2.0, obstacles):
                p, q = x + 1, levels[k] + 0.5
                pieces.append(((p + q) / R2, (q - p) / R2, -45.0))
            k += 1
        else:   # a standing pair: bands k and k + 1, inner edge of band k + 1
            for x in fill(levels[k + 1], 2.0, 1.0, obstacles):
                p, q = x + 0.5, levels[k + 1] + 1
                pieces.append(((p + q) / R2, (q - p) / R2, 45.0))
            k += 2
    return s, pieces


def candidate(problem, s, pieces, shrink=1e-9):
    return {"candidate_id": f"layers-{len(pieces)}", "problem_id": problem["problem_id"], "scale": (1 - shrink) / s,
            "placements": [{"shape_id": f"d{i:03d}", "x": -1 / 3 + u / s, "y": -1 / 3 + v / s, "rotation": angle}
                           for i, (u, v, angle) in enumerate(pieces)]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("a", type=int)
    parser.add_argument("c", type=int)
    parser.add_argument("heights")
    parser.add_argument("bands")
    parser.add_argument("n", type=int)
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("--apex")
    parser.add_argument("--corner")
    args = parser.parse_args()
    heights = [int(h) for h in args.heights.split(",") if h]
    s, pieces = build(args.a, args.c, heights, args.bands, args.apex, args.corner)
    if len(pieces) < args.n:
        raise SystemExit(f"the structure holds {len(pieces)} dominoes, fewer than {args.n}")
    problem = json.loads((HERE / "problem.json").read_text(encoding="utf-8"))
    Path(args.output).write_text(json.dumps(candidate(problem, s, pieces[:args.n]), indent=1))
    print(f"{args.n} of {len(pieces)} dominoes, legs {s:.6f}")


if __name__ == "__main__":
    main()
