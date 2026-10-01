"""Tans in an L: refine Morandi's n=13 figure (s = 1.499+), then split every tan along its
altitude (a tan is two tans scaled by 1/sqrt 2) into n=26 at sqrt2 * s13, and refine again."""
import json
import math

import numpy as np

from lrefine import largest_valid, refine, valid

# 13.gif (216 x 215): per pink component, hypotenuse ends A, B and right-angle vertex C (px)
comps = [((73.5, 68.5), (1.5, 1.5), (4.5, 70.5)), ((106.5, 1.5), (8.5, 1.5), (57.5, 50.5)),
         ((107.5, 2.5), (107.5, 100.5), (58.5, 51.5)), ((71.5, 142.5), (2.5, 72.5), (71.5, 72.5)),
         ((142.5, 142.5), (73.5, 73.5), (73.5, 142.5)), ((69.5, 142.5), (1.5, 74.5), (1.5, 142.5)),
         ((213.5, 108.5), (115.5, 108.5), (164.5, 157.5)), ((214.5, 109.5), (214.5, 206.5), (166.5, 157.5)),
         ((214.5, 213.5), (147.5, 142.5), (145.5, 210.5)), ((71.5, 213.5), (2.5, 144.5), (71.5, 144.5)),
         ((143.5, 213.5), (74.5, 144.5), (143.5, 144.5)), ((69.5, 213.5), (1.5, 145.5), (1.5, 213.5)),
         ((141.5, 213.5), (73.5, 145.5), (73.5, 213.5))]
U = 106.75


def to_units(p):
    return np.array([(p[0] - 1.0) / U, (214.0 - p[1]) / U])


x, y, th = [], [], []
for A, B, C in comps:
    A, B, C = to_units(A), to_units(B), to_units(C)
    g = (A + B + C) / 3
    u1, u2 = A - C, B - C
    lead = u1 if u1[0] * u2[1] - u1[1] * u2[0] > 0 else u2
    x.append(g[0]); y.append(g[1]); th.append(math.atan2(lead[1], lead[0]))
x, y, th = np.array(x), np.array(y), np.array(th)

t = largest_valid(x, y, th, 1 / 1.499)
print("n=13 as read: s =", 1 / t)
for _ in range(3):
    x, y, th, t = refine(x, y, th, t)
    print("n=13 refined: s =", 1 / t, "(published 1.499+)")

# split: right angle at C, legs t*e1, t*e2; halves meet at the hypotenuse midpoint M
X, Y, TH = [], [], []
for xi, yi, a in zip(x, y, th):
    e1, e2 = np.array([math.cos(a), math.sin(a)]), np.array([-math.sin(a), math.cos(a)])
    C = np.array([xi, yi]) - t * (e1 + e2) / 3
    M = C + t * (e1 + e2) / 2
    for P, Q in ((C, C + t * e1), (C + t * e2, C)):  # each half: right angle at M, legs to P then Q (CCW)
        lead = P - M
        X.append((M[0] + P[0] + Q[0]) / 3); Y.append((M[1] + P[1] + Q[1]) / 3); TH.append(math.atan2(lead[1], lead[0]))
X, Y, TH = np.array(X), np.array(Y), np.array(TH)
T = largest_valid(X, Y, TH, t / math.sqrt(2))
print("n=26 split: s =", 1 / T, " sqrt2 * s13 =", math.sqrt(2) / t, " live record 3/sqrt2 =", 3 / math.sqrt(2))
for _ in range(3):
    X, Y, TH, T = refine(X, Y, TH, T)
    print("n=26 refined: s =", 1 / T)
print("valid:", valid(X, Y, TH, T))
json.dump({"n13": {"scale": t, "poses": np.stack([x, y, np.degrees(th)], 1).tolist()},
           "n26": {"scale": T, "poses": np.stack([X, Y, np.degrees(TH)], 1).tolist()}}, open("tan26.json", "w"))
