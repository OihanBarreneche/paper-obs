"""Smallest legs at which a domv.c structure still holds n dominoes (bisection on the builder),
then the structure at those legs as a lab candidate.

Usage: python vbisect.py N LO HI "D" bands "vees" -o cand.json
"""
import argparse
import contextlib
import io
import json
from pathlib import Path

from dombuild import candidate
from domvbuild import HERE, build

parser = argparse.ArgumentParser()
parser.add_argument("n", type=int)
parser.add_argument("lo", type=float)
parser.add_argument("hi", type=float)
parser.add_argument("heights")
parser.add_argument("bands")
parser.add_argument("vees")
parser.add_argument("-o", "--output", required=True)
args = parser.parse_args()
heights = [int(h) for h in args.heights.split(",") if h]
vees = [(int(b), float(p)) for b, p in (item.split(":") for item in args.vees.split(",") if item)]


def holds(s):
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return len(build(s, heights, args.bands, vees)) >= args.n
    except ValueError:
        return False


lo, hi = args.lo, args.hi
assert holds(hi) and not holds(lo), (holds(lo), holds(hi))
for _ in range(50):
    mid = (lo + hi) / 2
    lo, hi = (lo, mid) if holds(mid) else (mid, hi)
pieces = build(hi, heights, args.bands, vees)[:args.n]
problem = json.loads((HERE / "problem.json").read_text(encoding="utf-8"))
Path(args.output).write_text(json.dumps(candidate(problem, hi, pieces, shrink=0.0), indent=1))
print(f"{args.n} dominoes from legs {hi:.9f}")
