"""Build a structure of domv.c (upright diagram D, bands, V pairs) at given legs, as a lab candidate.

A V in band k at the corner of D with p-coordinate pm: two dominoes leaning together by delta from
the band normal, touching at the top on the axis and touching the outer edge of band k (depth k
below the hypotenuse); delta is the smallest angle with 2 cos(delta) - sin(delta) <= h - k, where h
is the depth of the corner. Upright dominoes are a maximum matching of D's cells; each band is
filled from the start of every free interval around D's cells and the V's.

Usage: python domvbuild.py S "11,9,8,8,6,5,5,3,2,2,1" lllllllll "0:-4.949747,0:-0.707107" N -o cand.json
S is the legs (a number); the V's are band:pm pairs.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from dombuild import EPS, R2, candidate, matching

HERE = Path(__file__).resolve().parent


def strip_extent(points, level, width):
    """p-extent of a convex polygon (u, v points) inside the open strip level < q < level + width."""
    poly = [((u - v) / R2, (u + v) / R2) for u, v in points]
    for side in (0, 1):
        clipped = []
        for k, (p, q) in enumerate(poly):
            p2, q2 = poly[(k + 1) % len(poly)]
            f = q - level if side == 0 else level + width - q
            f2 = q2 - level if side == 0 else level + width - q2
            if f >= 0:
                clipped.append((p, q))
            if (f >= 0) != (f2 >= 0):
                t = f / (f - f2)
                clipped.append((p + t * (p2 - p), q + t * (q2 - q)))
        poly = clipped
        if not poly:
            return None
    ps, qs = [p for p, _ in poly], [q for _, q in poly]
    if max(qs) - min(qs) < EPS or max(ps) - min(ps) < EPS:
        return None
    return min(ps), max(ps)


def fill(level, width, length, obstacles):
    blocked = sorted(filter(None, (strip_extent(o, level, width) for o in obstacles)))
    starts, x = [], -level
    for lo, hi in blocked + [(level, level)]:
        end = min(lo, level)
        while x + length <= end + EPS:
            starts.append(x)
            x += length
        x = max(x, hi)
    return starts


def corners(u, v, angle, length=2.0, width=1.0):
    r = math.radians(angle)
    c, s = math.cos(r), math.sin(r)
    return [(u + a * length / 2 * c - b * width / 2 * s, v + a * length / 2 * s + b * width / 2 * c)
            for a, b in ((1, 1), (-1, 1), (-1, -1), (1, -1))]


def vee(s, k, pm, h):
    """The two dominoes (u, v, degrees) of a V in band k straddling a corner at (pm, depth h)."""
    target = min(h - k, 2.0)
    lo, hi = 0.0, math.radians(30)
    g = lambda d: 2 * math.cos(d) - math.sin(d)
    if g(hi) > target:
        raise ValueError("corner too high for a V")
    if target >= 2 - EPS:
        delta = 0.0
    else:
        for _ in range(80):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if g(mid) > target else (lo, mid)
        delta = hi
    sd, cd = math.sin(delta), math.cos(delta)
    pc, depth = pm - sd - 0.5 * cd, k + cd + 0.5 * sd
    q = s / R2 - depth
    pieces = []
    for p, angle in ((pc, 45 - math.degrees(delta)), (2 * pm - pc, 45 + math.degrees(delta))):
        pieces.append(((p + q) / R2, (q - p) / R2, angle))
    return pieces, math.degrees(delta)


def build(s, heights, bands, vees):
    cells = {(i, j) for i, h in enumerate(heights) for j in range(h)}
    pieces = []
    for (i, j), (k, l) in matching(cells):
        pieces.append(((i + k) / 2 + 0.5, (j + l) / 2 + 0.5, 0.0 if j == l else 90.0))
    obstacles = [[(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)] for i, j in cells]
    padded = list(heights) + [0]
    for k, pm in vees:
        found = [i for i in range(len(heights)) if padded[i] > padded[i + 1]
                 and abs((i + 1 - padded[i]) / R2 - pm) < 1e-5]
        if not found:
            raise ValueError(f"no corner of D at p = {pm}")
        i = found[0]
        pm = (i + 1 - padded[i]) / R2   # the exact corner, not the rounded one of a listing
        h = s / R2 - (i + 1 + padded[i]) / R2
        pair, delta = vee(s, k, pm, h)
        print(f"V in band {k} at p = {pm:.6f}: corner depth {h:.6f}, delta {delta:.4f} degrees")
        for u, v, angle in pair:
            pieces.append((u, v, angle))
            obstacles.append(corners(u, v, angle))
    levels = [s / R2 - (k + 1) for k in range(len(bands))]
    k = 0
    while k < len(bands):
        if bands[k] == "l":
            for x in fill(levels[k], 1.0, 2.0, obstacles):
                p, q = x + 1, levels[k] + 0.5
                pieces.append(((p + q) / R2, (q - p) / R2, -45.0))
            k += 1
        else:
            for x in fill(levels[k + 1], 2.0, 1.0, obstacles):
                p, q = x + 0.5, levels[k + 1] + 1
                pieces.append(((p + q) / R2, (q - p) / R2, 45.0))
            k += 2
    return pieces


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("s", type=float)
    parser.add_argument("heights")
    parser.add_argument("bands")
    parser.add_argument("vees")
    parser.add_argument("n", type=int)
    parser.add_argument("-o", "--output", required=True)
    args = parser.parse_args()
    heights = [int(h) for h in args.heights.split(",") if h]
    vees = [(int(b), float(p)) for b, p in (item.split(":") for item in args.vees.split(",") if item)]
    pieces = build(args.s, heights, args.bands, vees)
    if len(pieces) < args.n:
        raise SystemExit(f"the structure holds {len(pieces)} dominoes, fewer than {args.n}")
    problem = json.loads((HERE / "problem.json").read_text(encoding="utf-8"))
    Path(args.output).write_text(json.dumps(candidate(problem, args.s, pieces[:args.n], shrink=0.0), indent=1))
    print(f"{args.n} of {len(pieces)} dominoes, legs {args.s:.9f}")


if __name__ == "__main__":
    main()
