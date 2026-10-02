"""Turn a squares-in-a-tan figure read by page_reader.js into an exact arrangement, and draw it.

The figure fills its image: the right angle sits on the bottom-left pixel centre and the legs
run along the left and bottom pixel rows, image y pointing down. Lines drawn in the fill colour
(components on the image border) and fragments much smaller than the median are not copies.
The squares get the published side's scale, the penalty optimiser of polygons.py removes the
pixel overlaps from a tan 2 % larger, and the exact refinement closes the contacts; the side
reached should be the published one. Writes results/<file>.json (frame of polygons.py) and
drawings/<file>.png, upright squares blue, 45-degree squares purple, others grey.

Usage: python tan_read.py figures/42.json
"""
import json
import math
import sys
from pathlib import Path

import numpy as np

from polygons import MUS, Packing

HERE = Path(__file__).resolve().parent
COLOURS = {0: "#9ecae1", 45: "#c994c7"}


def to_units(poses, t):
    """Frame of polygons.py (unit tan, right angle at (-1/3, -1/3)) to tan units (u, v, degrees)."""
    return [((x + 1 / 3) / t, (y + 1 / 3) / t, a) for x, y, a in poses]


def draw(units, s, path, labels=True):
    import resvg_py
    k = 50.0
    size = s * k + 20
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{size:.0f}" height="{size:.0f}">',
           '<rect width="100%" height="100%" fill="white"/>',
           f'<polygon points="10,10 10,{s * k + 10:.1f} {s * k + 10:.1f},{s * k + 10:.1f}" '
           'fill="none" stroke="black" stroke-width="1.5"/>']
    for i, (u, v, a) in enumerate(units):
        r = math.radians(a)
        corners = [(u + 0.5 * (cx * math.cos(r) - cy * math.sin(r)), v + 0.5 * (cx * math.sin(r) + cy * math.cos(r)))
                   for cx, cy in ((1, 1), (-1, 1), (-1, -1), (1, -1))]
        mod = a % 90
        key = min(COLOURS, key=lambda c: min(abs(mod - c), 90 - abs(mod - c)))
        colour = COLOURS[key] if min(abs(mod - key), 90 - abs(mod - key)) < 1.5 else "#e7e7e7"
        points = " ".join(f"{x * k + 10:.1f},{(s - y) * k + 10:.1f}" for x, y in corners)
        out.append(f'<polygon points="{points}" fill="{colour}" stroke="#333" stroke-width="0.8"/>')
        if labels:
            out.append(f'<text x="{u * k + 10:.1f}" y="{(s - v) * k + 14:.1f}" font-size="11" '
                       f'text-anchor="middle" font-family="sans-serif">{i}</text>')
    out.append("</svg>")
    Path(path).write_bytes(bytes(resvg_py.svg_to_bytes(svg_string="\n".join(out))))


def main():
    figure = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    w, h, s = figure["w"], figure["h"], figure["side"]
    inside = [c for c in figure["comps"] if 1.5 < c[0] < w - 1.5 and 1.5 < c[1] < h - 1.5]
    comps = [c for c in inside if c[3] > 0.5 * np.median([c[3] for c in inside])]
    us = np.array([(cx - 0.5) / (w - 1) * s for cx, cy, a, _ in comps])
    vs = np.array([(h - 0.5 - cy) / (h - 1) * s for cx, cy, a, _ in comps])
    th = np.radians([(-a) % 90 for *_, a, _ in comps])
    packing = Packing(json.loads((HERE / "shapes.json").read_text())["squintan"]["vertices"],
                      json.loads((HERE / "arenas.json").read_text())["squintan"], len(comps))
    x, y, th, t = packing.optimise(-1 / 3 + us / s, -1 / 3 + vs / s, th, 0.98 / s, mus=MUS[2:8])
    x, y, th, t = packing.refine(x, y, th, t)
    name = Path(figure["file"]).stem
    poses = [[float(p), float(q), math.degrees(r) % 90] for p, q, r in zip(x, y, th)]
    (HERE / "results" / f"{name}.json").write_text(json.dumps({"n": len(comps), "side": 1 / t, "scale": t, "poses": poses}))
    print(f"{name}: {len(comps)} squares, side {1 / t:.6f} (published {s:.6f})")
    units = to_units(poses, t)
    if "--draw" in sys.argv:
        draw(units, 1 / t, HERE / "drawings" / f"{name}.png")
    for i, (u, v, a) in sorted(enumerate(units), key=lambda e: (round(e[1][1], 1), e[1][0])):
        print(f"   {i:2d}  ({u:6.3f}, {v:6.3f})  {a:6.2f}")


if __name__ == "__main__":
    main()
