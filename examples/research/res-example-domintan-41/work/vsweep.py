"""Refine every structure listed by `domv list` and keep the best: each structure is built at the
smallest legs where it still holds n (bisection on domvbuild.build), then refined exactly with
polygons.py (SLSQP with fixed separating axes, re-chosen until stable).

Usage: python vsweep.py results/list41.txt 41 13.70 --workers 8 --refine 48
All structures are bisected first; only the --refine best of them by bisected legs are refined.
Prints the best sides; writes results/sweep-<n>.json (frame of polygons.py) for the best one.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import re
from multiprocessing import Pool
from pathlib import Path

import numpy as np

from domvbuild import build
from polygons import Packing

HERE = Path(__file__).resolve().parent


def parse(line):
    heights = [int(h) for h in re.search(r"D=\[([0-9,]*)\]", line).group(1).split(",") if h]
    bands = re.search(r"bands=(\w+)", line).group(1)
    vees = [(int(b), float(p)) for b, p, _ in re.findall(r"\((\d+),(-?[0-9.]+),([0-9.]+)\)", line)]
    return heights, bands, vees


def holds(s, n, heights, bands, vees):
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return len(build(s, heights, bands, vees)) >= n
    except ValueError:
        return False


def bisect(args):
    """The smallest legs (within 3 %) where the structure still holds n, or inf."""
    line, n, s_hi = args
    heights, bands, vees = parse(line)
    if not holds(s_hi, n, heights, bands, vees):
        return math.inf, line
    lo, hi = s_hi * 0.97, s_hi
    if holds(lo, n, heights, bands, vees):
        return math.inf, line
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if holds(mid, n, heights, bands, vees) else (mid, hi)
    return hi, line


def work(args):
    hi, line, n = args
    heights, bands, vees = parse(line)
    with contextlib.redirect_stdout(io.StringIO()):
        pieces = build(hi, heights, bands, vees)[:n]
    t = 1 / hi
    x = np.array([-1 / 3 + u * t for u, v, a in pieces])
    y = np.array([-1 / 3 + v * t for u, v, a in pieces])
    th = np.radians([a for u, v, a in pieces])
    packing = Packing(json.loads((HERE / "shapes.json").read_text())["domintan"]["vertices"],
                      json.loads((HERE / "arenas.json").read_text())["domintan"], n)
    t0 = packing.largest_valid(x, y, th, t * 1.0001)
    x2, y2, th2, t2 = packing.refine(x, y, th, t0)
    if t2 < t0:
        x2, y2, th2, t2 = x, y, th, t0
    return 1 / t2, [[float(a), float(b), float(np.degrees(c))] for a, b, c in zip(x2, y2, th2)], line


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("listing")
    parser.add_argument("n", type=int)
    parser.add_argument("s", type=float)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--refine", type=int, default=48)
    args = parser.parse_args()
    lines = [l.strip() for l in Path(args.listing).read_text().splitlines() if l.strip()]
    with Pool(args.workers) as pool:
        legs = sorted(pool.map(bisect, [(l, args.n, args.s) for l in lines]))
        legs = [(s, l) for s, l in legs if s < math.inf][:args.refine]
        results = sorted(pool.map(work, [(s, l, args.n) for s, l in legs]), key=lambda r: r[0])
    if not results:
        print("inf  no structure holds n below the given legs")
        return
    for side, _, line in results[:8]:
        print(f"{side:.6f}  {line[:160]}")
    side, poses, line = results[0]
    if poses is not None:
        (HERE / "results" / f"sweep-{args.n}.json").write_text(json.dumps(
            {"n": args.n, "side": side, "scale": 1 / side, "poses": poses, "structure": line}))


if __name__ == "__main__":
    main()
