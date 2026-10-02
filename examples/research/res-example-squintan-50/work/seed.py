"""Write a lab candidate as a polygons.py result (results/squintan-<n>.json), refined exactly, so
`polygons.py squintan <n> --hop` starts from it.

Usage: python seed.py layers-50.json
"""
import json
import math
import sys
from pathlib import Path

import numpy as np

from polygons import Packing

HERE = Path(__file__).resolve().parent

candidate = json.loads(Path(sys.argv[1]).read_text())
places = candidate["placements"]
n = len(places)
packing = Packing(json.loads((HERE / "shapes.json").read_text())["squintan"]["vertices"],
                  json.loads((HERE / "arenas.json").read_text())["squintan"], n)
x = np.array([p["x"] for p in places])
y = np.array([p["y"] for p in places])
th = np.radians([p["rotation"] for p in places])
t0 = packing.largest_valid(x, y, th, candidate["scale"] * (1 + 1e-6))
x, y, th, t = packing.refine(x, y, th, t0)
print(f"start side {1 / t0:.9f}, refined {1 / t:.9f}")
best = (t, x, y, th) if t > t0 else (t0, *(np.array([p[k] for p in places]) for k in ("x", "y")), np.radians([p["rotation"] for p in places]))
t, x, y, th = best
(HERE / "results" / f"squintan-{n}.json").write_text(json.dumps({
    "slug": "squintan", "n": n, "scale": t,
    "poses": [[float(a), float(b), math.degrees(c)] for a, b, c in zip(x, y, th)], "tries": 0}))
