"""Cross-family bounds from dissections, checked against every catalog table.

Two exact facts turn one published packing into another:
  * copy containment: a unit B holds k unit A's, so s[A in X](k n) <= s[B in X](n);
  * container dissection: X(s) holds pieces Y_i(lam_i s), so
    s[A in X](n_1 + ... + n_m) <= max_i s[A in Y_i](n_i) / lam_i.
Every table entry above the best such bound is printed with the construction."""
import json
import math
import sys

R2 = math.sqrt(2)
c = json.load(open(sys.argv[1], encoding="utf-8"))
SHAPE = {"circle": "cir", "triangle": "tri", "square": "squ", "pentagon": "pen", "hexagon": "hex",
         "octagon": "oct", "tan": "tan", "domino": "dom", "L": "L"}
CONT = {"circle": "cir", "triangle": "tri", "square": "squ", "pentagon": "pen", "hexagon": "hex",
        "octagon": "oct", "tan": "tan", "domino": "dom", "l": "L"}
tables = {}
for f in c["families"]:
    if not f["supported"] or "R" in f["slug"] or "co" in f["slug"] or f["shape"] not in SHAPE or f["container"] not in CONT:
        continue
    scale = 0.5 if "long side" in f["intro"] else 1.0  # cirinl, squinl give the L's long side
    t = {}
    for i in f["instances"]:
        if i["value"] is not None:
            for n in i["counts"]:
                t[n] = (i["value"] * scale, i["attribution"], i["formula"])
    # a table must be non-decreasing in n: both ends of a violation are parse suspects
    bad = {n for n in t for m in t if (m < n and t[m][0] > t[n][0] + 1e-3) or (m > n and t[m][0] < t[n][0] - 1e-3)}
    if bad:
        print(f"# {f['slug']}: dropped non-monotone entries {sorted(bad)}")
    t = {n: e for n, e in t.items() if n not in bad}
    tables[(SHAPE[f["shape"]], CONT[f["container"]])] = (f["slug"], t)

# unit B holds k unit A's: CONTAINS[B] = {A: k}
CONTAINS = {"squ": {"tan": 2}, "dom": {"squ": 2, "tan": 4}, "L": {"squ": 3, "dom": 1, "tan": 6},
            "hex": {"tri": 6, "squ": 1}, "cir": {"squ": 1, "pen": 1, "hex": 1, "tri": 6, "tan": 4},
            "oct": {"dom": 1, "squ": 2, "tan": 4, "cir": 1, "hex": 1, "tri": 6, "pen": 1}, "pen": {"squ": 1, "tri": 1}}
# X(s) holds pieces Y(lam s)
DISSECT = {"squ": [[("tan", 1)] * 2, [("dom", .5)] * 2, [("squ", .5)] * 4, [("L", .5), ("squ", .5)]],
           "dom": [[("squ", 1)] * 2, [("dom", .5)] * 4, [("tan", 1)] * 4],
           "L": [[("squ", 1)] * 3, [("dom", 1), ("squ", 1)], [("L", .5)] * 4, [("tan", 1)] * 6],
           "tan": [[("tan", 1 / R2)] * 2, [("tan", .5)] * 4, [("squ", .5), ("tan", .5), ("tan", .5)]],
           "tri": [[("tri", .5)] * 4, [("hex", 1 / 3)] + [("tri", 1 / 3)] * 3],
           "hex": [[("tri", 1)] * 6]}


def value(a, x, n):
    entry = tables.get((a, x))
    if entry is None or n < 1:
        return None
    t = entry[1]
    # monotone: any listed m >= n bounds s(n)
    best = min((v for m, (v, _, _) in t.items() if m >= n), default=None)
    return best


def most(a, y, v):
    """Largest listed n with s[a in y](n) <= v."""
    entry = tables.get((a, y))
    if entry is None:
        return 0
    return max((m for m, (s, _, _) in entry[1].items() if s <= v + 1e-12), default=0)


for (a, x), (slug, t) in sorted(tables.items(), key=lambda kv: kv[1][0]):
    for n, (v, who, formula) in sorted(t.items()):
        bounds = []
        for b, ks in CONTAINS.items():
            if a in ks:
                k = ks[a]
                w = value(b, x, math.ceil(n / k))
                if w is not None:
                    bounds.append((w, f"{k} {a} per {b}: s[{b} in {x}]({math.ceil(n / k)})"))
        for pieces in DISSECT.get(x, []):
            cands = sorted({s / lam for y, lam in pieces for m, (s, _, _) in tables.get((a, y), ("", {}))[1].items()})
            for cand in cands:
                if sum(most(a, y, cand * lam) for y, lam in pieces) >= n:
                    split = "+".join(f"{y}({lam:.3g}s):{most(a, y, cand * lam)}" for y, lam in pieces)
                    bounds.append((cand, f"{x} = {split}"))
                    break
        if bounds:
            w, how = min(bounds)
            if w < v - 2e-3:
                print(f"{slug:9s} n={n:3d}: table {v:.5f} ({who}) > {w:.5f} via {how}")
