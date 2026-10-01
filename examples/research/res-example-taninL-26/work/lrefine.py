"""Equal convex copies in an L (the box [0,2]^2 minus the obstacle [1,2]^2; short side 1).

refine(): SLSQP maximises the copies' scale t with every pair split by a fixed edge axis
of one of them, every copy inside the box, and every copy split from the obstacle by an
axis of either; axes are re-chosen until stable. largest_valid(): exact SAT bisection.
"""
import math

import numpy as np
from scipy.optimize import minimize

TAN = np.array([[-1 / 3, -1 / 3], [2 / 3, -1 / 3], [-1 / 3, 2 / 3]])
BOX = 2.0
OBST = np.array([[1, 1], [2, 1], [2, 2], [1, 2]], dtype=float)


def verts(x, y, th, t, local=TAN):
    c, s = np.cos(th)[:, None], np.sin(th)[:, None]
    return x[:, None] + t * (c * local[:, 0] - s * local[:, 1]), y[:, None] + t * (s * local[:, 0] + c * local[:, 1])


def normals(local):
    e = np.roll(local, -1, 0) - local
    n = np.stack([e[:, 1], -e[:, 0]], 1)
    return n / np.linalg.norm(n, axis=1)[:, None]


def sat_gap(P, Q, axes):
    """Largest separation of P and Q over the given axes (>= 0: disjoint or touching)."""
    best = -np.inf
    for a in axes:
        p, q = P @ a, Q @ a
        best = max(best, q.min() - p.max(), p.min() - q.max())
    return best


def axes_of(poly):
    e = np.roll(poly, -1, 0) - poly
    n = np.stack([e[:, 1], -e[:, 0]], 1)
    return n / np.linalg.norm(n, axis=1)[:, None]


def valid(x, y, th, t, local=TAN, slack=0.0):
    Vx, Vy = verts(x, y, th, t, local)
    if Vx.min() < -slack or Vy.min() < -slack or Vx.max() > BOX + slack or Vy.max() > BOX + slack:
        return False
    polys = [np.stack([Vx[i], Vy[i]], 1) for i in range(len(x))]
    oa = axes_of(OBST)
    for i, P in enumerate(polys):
        if sat_gap(P, OBST, np.concatenate([axes_of(P), oa])) < -slack:
            return False
        for j in range(i):
            if sat_gap(P, polys[j], np.concatenate([axes_of(P), axes_of(polys[j])])) < -slack:
                return False
    return True


def largest_valid(x, y, th, t, local=TAN):
    if valid(x, y, th, t, local):
        return t
    low = t
    while not valid(x, y, th, low, local):
        low *= 0.999
    high = t
    for _ in range(60):
        mid = (low + high) / 2
        low, high = (mid, high) if valid(x, y, th, mid, local) else (low, mid)
    return low


def choose(x, y, th, t, local):
    """Separator per pair (owner, other, local axis k) and per copy against the obstacle."""
    n = len(x)
    N = normals(local)
    h = (N @ local.T).max(1)
    Vx, Vy = verts(x, y, th, t, local)
    pairs = []
    reach = 2.5 * np.hypot(*local.T).max() * t
    for i in range(n):
        for j in range(i):
            if math.hypot(x[i] - x[j], y[i] - y[j]) > reach:
                continue
            best = None
            for o, q in ((i, j), (j, i)):
                c, s = math.cos(th[o]), math.sin(th[o])
                for k, (a, b) in enumerate(N):
                    nx, ny = c * a - s * b, s * a + c * b
                    gap = ((Vx[q] - x[o]) * nx + (Vy[q] - y[o]) * ny).min() - t * h[k]
                    if best is None or gap > best[0]:
                        best = (gap, o, q, k)
            pairs.append(best[1:])
    walls = []
    for i in range(n):
        options = [(1 - Vx[i].max(), ("x",)), (1 - Vy[i].max(), ("y",))]
        c, s = math.cos(th[i]), math.sin(th[i])
        for k, (a, b) in enumerate(N):
            nx, ny = c * a - s * b, s * a + c * b
            options.append((((OBST[:, 0] - x[i]) * nx + (OBST[:, 1] - y[i]) * ny).min() - t * h[k], ("edge", k)))
        walls.append(max(options)[1])
    return pairs, walls, N, h


def refine(x, y, th, t, local=TAN, rounds=12):
    n = len(x)
    previous = None
    for _ in range(rounds):
        pairs, walls, N, h = choose(x, y, th, t, local)

        def cons(z):
            x, y, th, t = z[:n], z[n:2 * n], z[2 * n:3 * n], z[-1]
            Vx, Vy = verts(x, y, th, t, local)
            out = [Vx.ravel(), Vy.ravel(), (BOX - Vx).ravel(), (BOX - Vy).ravel()]
            for o, q, k in pairs:
                c, s = math.cos(th[o]), math.sin(th[o])
                nx, ny = c * N[k, 0] - s * N[k, 1], s * N[k, 0] + c * N[k, 1]
                out.append((Vx[q] - x[o]) * nx + (Vy[q] - y[o]) * ny - t * h[k])
            for i, w in enumerate(walls):
                if w[0] == "x":
                    out.append(1 - Vx[i])
                elif w[0] == "y":
                    out.append(1 - Vy[i])
                else:
                    k = w[1]
                    c, s = math.cos(th[i]), math.sin(th[i])
                    nx, ny = c * N[k, 0] - s * N[k, 1], s * N[k, 0] + c * N[k, 1]
                    out.append((OBST[:, 0] - x[i]) * nx + (OBST[:, 1] - y[i]) * ny - t * h[k])
            return np.concatenate(out)

        z0 = np.concatenate([x, y, th, [t]])
        res = minimize(lambda z: -z[-1], z0, method="SLSQP", constraints={"type": "ineq", "fun": cons},
                       options={"maxiter": 500, "ftol": 1e-16})
        z = res.x
        x, y, th, t = z[:n].copy(), z[n:2 * n].copy(), z[2 * n:3 * n].copy(), z[-1]
        key = (pairs, walls)
        if key == previous:
            break
        previous = key
    return x, y, th, largest_valid(x, y, th, t, local)
