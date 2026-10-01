"""Extend Cantrell's x.301 pattern (8, 12, 17, 23, 30) to n = 38 and refine it."""
import json, math, sys
sys.path.insert(0, '.')
import numpy as np
from polygons import Packing, MUS
H3 = math.sqrt(3) / 6
SQ3 = math.sqrt(3)
s = 10.301221331390193
sq = []  # (u, v, degrees) in triangle units
# corner gadget, as in n = 23 and n = 30
sq += [(1.0825, 0.5088, 0.0), (2.2259, 0.6354, 18.980), (3.2239, 1.2250, 0.0)]
# green strip along the left side: outer column 8, inner column 6
for k in range(8):
    v = 1.6759 + 0.8660 * k
    sq.append((1.5449 + 0.5 * k, v, 60.0))
for k in range(6):
    sq.append((3.1223 + 0.5 * k, 2.4080 + 0.8660 * k, 60.0))
# axis staircase: rows 6, 5, 4, 3, 2, 1
rows = [(0.5, 4.2239, 6), (1.503, 4.2239, 5), (2.503, 4.7148, 4), (3.503, 5.2277, 3), (4.503, 5.7152, 2), (5.503, 6.2152, 1)]
for v, u0, count in rows:
    for c in range(count):
        sq.append((u0 + c, v, 0.0))
print(len(sq))
x = np.array([u / s - 0.5 for u, v, a in sq]); y = np.array([v / s - H3 for u, v, a in sq]); th = np.radians([a for u, v, a in sq])
container = json.load(open('arenas.json'))['squintri']
local = json.load(open('shapes.json'))['squintri']['vertices']
p = Packing(local, container, len(sq))
a = p.refine(x.copy(), y.copy(), th.copy(), 0.97 / s)
b = p.refine(*p.optimise(x.copy(), y.copy(), th.copy(), 0.95 / s, mus=MUS[2:7]))
for name, r in (('refine', a), ('penalty+refine', b)):
    print(name, 1 / r[3] if r[3] else None)
best = max(a, b, key=lambda r: r[3])
json.dump({"slug": "squintri", "n": len(sq), "scale": best[3], "poses": [[float(p_), float(q), float(math.degrees(r))] for p_, q, r in zip(best[0], best[1], best[2])]},
          open('squintri-38-x301.json', 'w'))
