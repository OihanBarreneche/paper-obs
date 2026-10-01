"""Refine every stored squintri figure and keep exact record arrangements in records_squintri.json."""
import json, math, sys
sys.path.insert(0, '.')
from figure_seed import figure
from polygons import Packing, MUS
from draw import svg, page
arenas = json.load(open('arenas.json'))
container = arenas['squintri']
local = json.load(open('shapes.json'))['squintri']['vertices']
keys = sys.argv[2:]
recs = {}
try:
    recs = json.load(open('records_squintri.json'))
except Exception:
    pass
items = []
for key in keys:
    poses, t = figure("squintri", key)
    p = Packing(local, container, len(poses))
    x, y, th, t = p.refine(*poses.T.copy(), t * 0.97)
    pz = [[float(a), float(b), float(math.degrees(c))] for a, b, c in zip(x, y, th)]
    recs[key] = {"scale": t, "poses": pz}
    items.append(svg(container, pz, t, f"n={len(pz)} s={1 / t:.6f}", 420))
json.dump(recs, open('records_squintri.json', 'w'))
open(sys.argv[1], 'w').write(page(items))
