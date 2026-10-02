"""Squares in a tan: a staircase of upright squares in the corner, b bands of 45-degree squares
along the hypotenuse, and the counts these layers give.

Triangle units: the right angle at the origin, legs along u and v, hypotenuse u + v = s.
- A staircase in a tan of legs m holds T(m - 1) = m(m - 1)/2 upright squares, row j holding
  m - 1 - j of them.
- A band of width 1 along the hypotenuse, between u + v = c and u + v = c + sqrt2, holds
  floor(c * sqrt2) squares turned by 45 degrees: the legs cut it at 45 degrees, so its inner
  edge, of length c * sqrt2, is the binding one.
So legs m + b * sqrt2 hold T(m - 1) + b * floor(m * sqrt2) + b(b - 1) squares.

More generally a tan of legs s splits into a strip along a leg (floor(s - 1) upright squares)
and a tan of legs s - 1, or into a band along the hypotenuse (floor(s * sqrt2 - 2) squares) and a
tan of legs s - sqrt2. `table` gives the smallest legs this recursion reaches for each count,
over legs a + c / sqrt2.

Usage: python bands.py table                  # recursion against the live values
       python bands.py build M B N -o cand.json  # the first N squares of layers (M, B)
"""
from __future__ import annotations

import argparse
import json
import math
from functools import lru_cache
from pathlib import Path

R2 = math.sqrt(2)
HERE = Path(__file__).resolve().parent
# The live page, read on 2026-10-01 (Joshua Wolk, September 2026, for 29 to 50).
LIVE = {29: 2 + 9 / R2, 30: 7 + R2, 31: 6 * R2, 32: 1 + 11 / R2, 33: 6 + 2 * R2, 34: 4 + 7 / R2,
        35: 9, 36: 9, 37: 5 + 3 * R2, 38: 8 + R2, 39: 8 + R2, 40: 2 + 11 / R2, 41: 7 + 2 * R2,
        42: 7 + 2 * R2, 43: 7 * R2, 44: 10, 45: 10, 46: 6 + 3 * R2, 47: 9 + R2, 48: 9 + R2,
        49: 15 / R2, 50: 3 + 11 / R2}


@lru_cache(maxsize=None)
def count(a: int, c: int) -> int:
    """Squares the strip and band recursion fits in legs a + c / sqrt2 (a, c integers)."""
    s = a + c / R2
    if s < 2 - 1e-12:
        return 0
    strip = math.floor(s - 1 + 1e-12) + count(a - 1, c)
    band = math.floor(s * R2 - 2 + 1e-12) + count(a, c - 2) if s - R2 >= -1e-12 else 0
    return max(strip, band)


def table() -> None:
    best: dict[int, tuple[float, int, int]] = {}
    for a in range(0, 16):
        for c in range(0, 24):
            s = a + c / R2
            if s > 12:
                continue
            for n in range(1, count(a, c) + 1):
                if n not in best or s < best[n][0] - 1e-12:
                    best[n] = (s, a, c)
    for n in sorted(LIVE):
        s, a, c = best[n]
        mark = "  <-- below the live value" if s < LIVE[n] - 1e-9 else ""
        print(f"{n:3d}  recursion {s:9.5f} = {a} + {c}/sqrt2   live {LIVE[n]:9.5f}{mark}")


def layers(m: int, b: int) -> tuple[float, list[tuple[float, float, float]]]:
    """Legs m + b * sqrt2 and the squares (u, v, degrees) of the staircase and the bands."""
    s = m + b * R2
    squares = [(i + 0.5, j + 0.5, 0.0) for j in range(m - 1) for i in range(m - 1 - j)]
    for k in range(b):
        c = m + k * R2  # inner edge of the band, innermost first
        length = c * R2
        fit = math.floor(length + 1e-12)
        spare = (length - fit) / (fit + 1)  # share the slack evenly, ends included
        for i in range(fit):
            p = spare * (i + 1) + i + 0.5  # centre's position along the inner edge from the u = 0 leg
            u, v = p / R2, c - p / R2
            squares.append((u + 0.5 / R2, v + 0.5 / R2, 45.0))
    return s, squares


def candidate(problem: dict, s: float, squares, shrink: float = 1e-9) -> dict:
    """The problem's frame: the unit tan with its right angle at (-1/3, -1/3), scale 1/s."""
    return {
        "candidate_id": f"layers-{len(squares)}", "problem_id": problem["problem_id"],
        "scale": (1 - shrink) / s,
        "placements": [{"shape_id": f"s{i:03d}", "x": -1 / 3 + u / s, "y": -1 / 3 + v / s, "rotation": a}
                       for i, (u, v, a) in enumerate(squares)],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("table")
    build = sub.add_parser("build")
    build.add_argument("m", type=int)
    build.add_argument("b", type=int)
    build.add_argument("n", type=int)
    build.add_argument("-o", "--output", required=True)
    args = parser.parse_args()
    if args.command == "table":
        table()
        return
    s, squares = layers(args.m, args.b)
    if len(squares) < args.n:
        raise SystemExit(f"layers ({args.m}, {args.b}) hold {len(squares)} squares, fewer than {args.n}")
    problem = json.loads((HERE / "problem.json").read_text(encoding="utf-8"))
    Path(args.output).write_text(json.dumps(candidate(problem, s, squares[:args.n]), indent=1))
    print(f"{args.n} of {len(squares)} squares, legs {s:.6f}")


if __name__ == "__main__":
    main()
