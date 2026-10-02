"""Refine a lab candidate of dominoes in a tan exactly with polygons.py and write it back as a
lab candidate, its scale shrunk by 1e-9 so that the contacts the optimiser closes stay legal.

Usage: python refine_cand.py v41.json v41-refined.json
"""
import json
import sys
from pathlib import Path

import numpy as np

from polygons import Packing

HERE = Path(__file__).resolve().parent
cand = json.loads(Path(sys.argv[1]).read_text())
places = cand["placements"]
n = len(places)
packing = Packing(json.loads((HERE / "shapes.json").read_text())["domintan"]["vertices"],
                  json.loads((HERE / "arenas.json").read_text())["domintan"], n)
x = np.array([p["x"] for p in places])
y = np.array([p["y"] for p in places])
th = np.radians([p["rotation"] for p in places])
t0 = packing.largest_valid(x, y, th, cand["scale"] * 1.0001)
x, y, th, t = packing.refine(x, y, th, t0)
if t < t0:
    x = np.array([p["x"] for p in places]); y = np.array([p["y"] for p in places])
    th = np.radians([p["rotation"] for p in places]); t = t0
print(f"start side {1 / t0:.9f}, refined side {1 / t:.9f}")
cand["scale"] = t * (1 - 1e-9)
cand["placements"] = [{"shape_id": p["shape_id"], "x": float(a), "y": float(b), "rotation": float(np.degrees(c))}
                      for p, a, b, c in zip(places, x, y, th)]
Path(sys.argv[2]).write_text(json.dumps(cand, indent=1))
