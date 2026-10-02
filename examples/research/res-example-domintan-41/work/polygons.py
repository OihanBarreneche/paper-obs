"""Equal convex polygons in a convex polygon: the largest common scale.

Every pair of copies carries its own separating line (angle phi, offset c) as extra
variables: copy i lies on one side, copy j on the other. Overlap and containment then
become smooth penalties, and `-t + mu * E` is minimised by L-BFGS for a rising mu.
The scale is finally cut back by bisection until an exact separating-axis check passes:
shrinking a convex copy about its own centre keeps it inside its old outline, so the
check is monotone in the scale.

Usage: python polygons.py <slug> <n> [<n> ...] --seconds S [--workers W] [--hop]
`--hop` starts every try from the best saved arrangement, shaken, instead of at random.
Writes results/<slug>-<n>.json with the best arrangement found.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from scipy.optimize import minimize


def be_gentle() -> None:
    """The searches share the owner's PC: idle priority, so interactive work always comes first.

    Worker processes started from an idle-priority process inherit that class on Windows.
    """
    if sys.platform == "win32":
        import ctypes
        kernel = ctypes.windll.kernel32
        kernel.GetCurrentProcess.restype = ctypes.c_void_p  # a 64-bit pseudo-handle
        kernel.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x40)  # IDLE_PRIORITY_CLASS
    else:
        os.nice(10)


be_gentle()

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
MUS = [1e1, 1e2, 1e3, 1e4, 1e5, 1e6, 1e7, 1e8, 1e9, 1e10]


def halfplanes(polygon):
    points = np.asarray(polygon, dtype=float)
    edges = np.roll(points, -1, 0) - points
    normals = np.stack([edges[:, 1], -edges[:, 0]], 1)
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    return normals, (normals * points).sum(1)


def polygon_area(points):
    x, y = np.asarray(points).T
    return 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


class Packing:
    def __init__(self, local, container, n):
        self.L = np.asarray(local, dtype=float)
        # A container is a convex polygon (list of points) or {"circle": R} centred on the origin.
        self.radius = container["circle"] if isinstance(container, dict) else None
        if self.radius is None:
            self.container = np.asarray(container, dtype=float)
            self.a, self.b = halfplanes(container)
        else:
            self.container = self.radius * np.array([[-1.0, -1.0], [1.0, -1.0], [1.0, 1.0], [-1.0, 1.0]])
        self.n = n
        self.iu, self.ju = np.triu_indices(n, 1)
        self.P = len(self.iu)
        self.axes_local = halfplanes(local)[0]  # outward edge normals of the copy at rotation 0

    def vertices(self, x, y, th, t):
        cos, sin = np.cos(th)[:, None], np.sin(th)[:, None]
        Lx, Ly = self.L[:, 0][None, :], self.L[:, 1][None, :]
        return x[:, None] + t * (cos * Lx - sin * Ly), y[:, None] + t * (sin * Lx + cos * Ly)

    def objective(self, z, mu, iu=None, ju=None):
        """-t + mu * (squared containment and pair violations), with its gradient.

        z = [x, y, th, phi, c, t] where (phi, c) is one separating line per listed pair
        (all pairs by default).
        """
        n = self.n
        iu = self.iu if iu is None else iu
        ju = self.ju if ju is None else ju
        P = len(iu)
        x, y, th = z[:n], z[n:2 * n], z[2 * n:3 * n]
        phi, c, t = z[3 * n:3 * n + P], z[3 * n + P:3 * n + 2 * P], z[-1]
        cos, sin = np.cos(th)[:, None], np.sin(th)[:, None]
        Lx, Ly = self.L[:, 0][None, :], self.L[:, 1][None, :]
        Vx = x[:, None] + t * (cos * Lx - sin * Ly)
        Vy = y[:, None] + t * (sin * Lx + cos * Ly)
        if self.radius is None:
            # Containment: every vertex on the inner side of every container edge.
            R = Vx[:, :, None] * self.a[:, 0] + Vy[:, :, None] * self.a[:, 1] - self.b
            h = np.maximum(R, 0.0)
            E = (h * h).sum()
            gVx = 2 * (h * self.a[:, 0]).sum(2)
            gVy = 2 * (h * self.a[:, 1]).sum(2)
        else:
            # Containment in a disc: every vertex within the radius.
            norm = np.sqrt(Vx * Vx + Vy * Vy) + 1e-300
            h = np.maximum(norm - self.radius, 0.0)
            E = (h * h).sum()
            gVx = 2 * h * Vx / norm
            gVy = 2 * h * Vy / norm
        # Pairs: copy i below its line, copy j above.
        ux, uy = np.cos(phi)[:, None], np.sin(phi)[:, None]
        Xi, Yi, Xj, Yj = Vx[iu], Vy[iu], Vx[ju], Vy[ju]
        hi = np.maximum(Xi * ux + Yi * uy - c[:, None], 0.0)
        hj = np.maximum(c[:, None] - (Xj * ux + Yj * uy), 0.0)
        E += (hi * hi).sum() + (hj * hj).sum()
        fx, fy = 2 * hi * ux, 2 * hi * uy
        gx_, gy_ = 2 * hj * ux, 2 * hj * uy
        for k in range(Vx.shape[1]):
            gVx[:, k] += np.bincount(iu, fx[:, k], n) - np.bincount(ju, gx_[:, k], n)
            gVy[:, k] += np.bincount(iu, fy[:, k], n) - np.bincount(ju, gy_[:, k], n)
        gphi = (2 * hi * (-Xi * uy + Yi * ux)).sum(1) - (2 * hj * (-Xj * uy + Yj * ux)).sum(1)
        gc = -2 * hi.sum(1) + 2 * hj.sum(1)
        dVx_dth = t * (-sin * Lx - cos * Ly)
        dVy_dth = t * (cos * Lx - sin * Ly)
        gx = gVx.sum(1)
        gy = gVy.sum(1)
        gth = (gVx * dVx_dth + gVy * dVy_dth).sum(1)
        gt = (gVx * (cos * Lx - sin * Ly) + gVy * (sin * Lx + cos * Ly)).sum()
        grad = mu * np.concatenate([gx, gy, gth, gphi, gc, [gt]])
        grad[-1] -= 1.0
        return -t + mu * E, grad

    def separators(self, x, y, th, t, iu=None, ju=None):
        """Per pair, the copies' edge axis with the widest gap (least overlap), line midway.

        The line between centres is a poor start for two tilted neighbours: its penalty then
        makes the first, strong mu shrink every copy instead of moving them.
        """
        iu = self.iu if iu is None else iu
        ju = self.ju if ju is None else ju
        Vx, Vy = self.vertices(x, y, th, t)
        cos, sin = np.cos(th)[:, None], np.sin(th)[:, None]
        Ax = cos * self.axes_local[:, 0] - sin * self.axes_local[:, 1]
        Ay = sin * self.axes_local[:, 0] + cos * self.axes_local[:, 1]
        axes_x = np.concatenate([Ax[iu], Ax[ju]], 1)
        axes_y = np.concatenate([Ay[iu], Ay[ju]], 1)
        pi = Vx[iu][:, :, None] * axes_x[:, None, :] + Vy[iu][:, :, None] * axes_y[:, None, :]
        pj = Vx[ju][:, :, None] * axes_x[:, None, :] + Vy[ju][:, :, None] * axes_y[:, None, :]
        forward = pj.min(1) - pi.max(1)  # i below j along the axis
        backward = pi.min(1) - pj.max(1)  # the reverse: use the opposite axis
        k = np.argmax(np.maximum(forward, backward), 1)
        rows = np.arange(len(iu))
        flip = backward[rows, k] > forward[rows, k]
        ax, ay = axes_x[rows, k], axes_y[rows, k]
        ax, ay = np.where(flip, -ax, ax), np.where(flip, -ay, ay)
        top_i = np.where(flip, -pi.min(1)[rows, k], pi.max(1)[rows, k])
        low_j = np.where(flip, -pj.max(1)[rows, k], pj.min(1)[rows, k])
        return np.arctan2(ay, ax), (top_i + low_j) / 2

    def valid(self, x, y, th, t, slack=0.0):
        """Exact check at scale t: copies inside, and every pair split by one of its edge axes."""
        Vx, Vy = self.vertices(x, y, th, t)
        if self.radius is not None:
            if (np.sqrt(Vx * Vx + Vy * Vy) - self.radius).max() > slack:
                return False
        elif (Vx[:, :, None] * self.a[:, 0] + Vy[:, :, None] * self.a[:, 1] - self.b).max() > slack:
            return False
        # Candidate axes: each copy's own edge normals, rotated with it.
        cos, sin = np.cos(th)[:, None], np.sin(th)[:, None]
        Ax = cos * self.axes_local[:, 0] - sin * self.axes_local[:, 1]
        Ay = sin * self.axes_local[:, 0] + cos * self.axes_local[:, 1]
        axes_x = np.concatenate([Ax[self.iu], Ax[self.ju]], 1)  # P x (mi + mj)
        axes_y = np.concatenate([Ay[self.iu], Ay[self.ju]], 1)
        pi = Vx[self.iu][:, :, None] * axes_x[:, None, :] + Vy[self.iu][:, :, None] * axes_y[:, None, :]
        pj = Vx[self.ju][:, :, None] * axes_x[:, None, :] + Vy[self.ju][:, :, None] * axes_y[:, None, :]
        gap = np.maximum(pj.min(1) - pi.max(1), pi.min(1) - pj.max(1))  # P x axes
        return bool((gap.max(1) >= -slack).all())

    def largest_valid(self, x, y, th, t):
        low, high = 0.0, t
        if self.valid(x, y, th, t):
            return t
        low = t * 0.98
        while not self.valid(x, y, th, low):
            low *= 0.98
            if low < 1e-6:
                return 0.0
        for _ in range(60):
            middle = (low + high) / 2
            if self.valid(x, y, th, middle):
                low = middle
            else:
                high = middle
        return low

    def near_pairs(self, x, y, t, factor=2.0):
        """Pairs whose centres are close enough to touch once copies move a little."""
        reach = 2 * np.hypot(*self.L.T).max() * t * factor
        d = np.hypot(x[self.ju] - x[self.iu], y[self.ju] - y[self.iu])
        keep = d < reach
        return self.iu[keep], self.ju[keep]

    def optimise(self, x, y, th, t, mus=MUS):
        """Penalty stages for a rising mu, the lines carried from stage to stage.

        Early stages (mu < 1e3) move copies far, so every pair carries a line; from 1e3 on,
        only pairs within reach keep one (chosen once, generously).
        """
        n = self.n
        iu = ju = None
        for mu in mus:
            if iu is None or (mu >= 1e3 and len(iu) == self.P):
                iu, ju = self.near_pairs(x, y, t) if mu >= 1e3 else (self.iu, self.ju)
                phi, c = self.separators(x, y, th, t, iu, ju)
            P = len(iu)
            z = np.concatenate([x, y, th, phi, c, [t]])
            final = mu >= 1e8
            z = minimize(self.objective, z, args=(mu, iu, ju), jac=True, method="L-BFGS-B",
                         options={"maxiter": 3000 if final else 600, "maxcor": 30,
                                  "ftol": 1e-16 if final else 1e-12, "gtol": 1e-12 if final else 1e-9}).x
            x, y, th, t = z[:n].copy(), z[n:2 * n].copy(), z[2 * n:3 * n].copy(), z[-1]
            phi, c = z[3 * n:3 * n + P].copy(), z[3 * n + P:3 * n + 2 * P].copy()
        return x, y, th, self.largest_valid(x, y, th, t)

    def contacts(self, x, y, th, t):
        """Near pairs and, for each, the axis that separates it best: (i, j, owner, direction).

        The axis is a direction d of the owner's local frame (an edge normal or its opposite)
        rotated with it; the other copy must lie beyond the owner's support along it.
        """
        reach = 2 * np.hypot(*self.L.T).max() * t * 1.15
        d = np.hypot(x[self.ju] - x[self.iu], y[self.ju] - y[self.iu])
        near = np.flatnonzero(d < reach)
        dirs = np.concatenate([self.axes_local, -self.axes_local])
        support = (dirs @ self.L.T).max(1)
        Vx, Vy = self.vertices(x, y, th, t)
        chosen = []
        for p in near:
            best = None
            for owner, other in ((self.iu[p], self.ju[p]), (self.ju[p], self.iu[p])):
                c, s = np.cos(th[owner]), np.sin(th[owner])
                nx, ny = c * dirs[:, 0] - s * dirs[:, 1], s * dirs[:, 0] + c * dirs[:, 1]
                gap = ((Vx[other][None, :] - x[owner]) * nx[:, None]
                       + (Vy[other][None, :] - y[owner]) * ny[:, None]).min(1) - t * support
                k = int(np.argmax(gap))
                if best is None or gap[k] > best[0]:
                    best = (gap[k], owner, other, k)
            chosen.append(best[1:])
        return chosen, dirs, support

    def refine(self, x, y, th, t, rounds=6):
        """Exact local maximum of the scale for a fixed choice of separating axes (SLSQP).

        Each pair stays split by the owner's rotated edge axis, a sufficient condition for
        disjointness, so every feasible point is a valid packing. The axes are re-chosen at
        the solution and the problem solved again until they no longer change.
        """
        n, L = self.n, self.L
        m = len(L)
        previous = None
        for _ in range(rounds):
            chosen, dirs, support = self.contacts(x, y, th, t)
            if not chosen and self.radius is None:
                break
            owners = np.array([c[0] for c in chosen], dtype=int)
            others = np.array([c[1] for c in chosen], dtype=int)
            ks = np.array([c[2] for c in chosen], dtype=int)
            D, hD = dirs[ks], support[ks]

            def unpack(z):
                return z[:n], z[n:2 * n], z[2 * n:3 * n], z[-1]

            def cons(z):
                x, y, th, t = unpack(z)
                Vx, Vy = self.vertices(x, y, th, t)
                c, s = np.cos(th[owners]), np.sin(th[owners])
                nx = c * D[:, 0] - s * D[:, 1]
                ny = s * D[:, 0] + c * D[:, 1]
                pair = ((Vx[others] - x[owners][:, None]) * nx[:, None]
                        + (Vy[others] - y[owners][:, None]) * ny[:, None] - t * hD[:, None])
                if self.radius is None:
                    wall = self.b - (Vx[:, :, None] * self.a[:, 0] + Vy[:, :, None] * self.a[:, 1])
                else:
                    wall = self.radius ** 2 - (Vx * Vx + Vy * Vy)
                return np.concatenate([pair.ravel(), wall.ravel()])

            def jac(z):
                x, y, th, t = unpack(z)
                Vx, Vy = self.vertices(x, y, th, t)
                cos, sin = np.cos(th)[:, None], np.sin(th)[:, None]
                Rx = cos * L[:, 0] - sin * L[:, 1]  # dV/dt
                Ry = sin * L[:, 0] + cos * L[:, 1]
                c, s = np.cos(th[owners]), np.sin(th[owners])
                nx = (c * D[:, 0] - s * D[:, 1])[:, None]
                ny = (s * D[:, 0] + c * D[:, 1])[:, None]
                P = len(owners)
                rows = np.arange(P * m)
                Jp = np.zeros((P * m, 3 * n + 1))
                o = np.repeat(owners, m)
                q = np.repeat(others, m)
                Jp[rows, q] += np.broadcast_to(nx, (P, m)).ravel()
                Jp[rows, n + q] += np.broadcast_to(ny, (P, m)).ravel()
                Jp[rows, o] -= np.broadcast_to(nx, (P, m)).ravel()
                Jp[rows, n + o] -= np.broadcast_to(ny, (P, m)).ravel()
                # The axis turns with its owner: dn/dth = (-ny, nx).
                dX, dY = Vx[others] - x[owners][:, None], Vy[others] - y[owners][:, None]
                Jp[rows, 2 * n + o] += (-ny * dX + nx * dY).ravel()
                Jp[rows, 2 * n + q] += (nx * (-t * Ry[others]) + ny * (t * Rx[others])).ravel()
                Jp[rows, -1] = (nx * Rx[others] + ny * Ry[others] - hD[:, None]).ravel()
                if self.radius is None:
                    E = len(self.b)
                    Jw = np.zeros((n * m * E, 3 * n + 1))
                    idx = np.arange(n * m * E).reshape(n, m, E)
                    ii = np.broadcast_to(np.arange(n)[:, None, None], (n, m, E))
                    ax, ay = self.a[:, 0][None, None, :], self.a[:, 1][None, None, :]
                    Jw[idx, ii] = -np.broadcast_to(ax, (n, m, E))
                    Jw[idx, n + ii] = -np.broadcast_to(ay, (n, m, E))
                    Jw[idx, 2 * n + ii] = -(ax * (-t * Ry)[:, :, None] + ay * (t * Rx)[:, :, None])
                    Jw[idx, np.full((n, m, E), 3 * n)] = -(ax * Rx[:, :, None] + ay * Ry[:, :, None])
                else:
                    Jw = np.zeros((n * m, 3 * n + 1))
                    idx = np.arange(n * m).reshape(n, m)
                    ii = np.broadcast_to(np.arange(n)[:, None], (n, m))
                    Jw[idx, ii] = -2 * Vx
                    Jw[idx, n + ii] = -2 * Vy
                    Jw[idx, 2 * n + ii] = -2 * (Vx * (-t * Ry) + Vy * (t * Rx))
                    Jw[idx, np.full((n, m), 3 * n)] = -2 * (Vx * Rx + Vy * Ry)
                return np.vstack([Jp, Jw])

            z0 = np.concatenate([x, y, th, [t]])
            goal = np.zeros(3 * n + 1)
            goal[-1] = -1.0
            result = minimize(lambda z: (-z[-1], goal), z0, jac=True, method="SLSQP",
                              constraints={"type": "ineq", "fun": cons, "jac": jac},
                              options={"maxiter": 300, "ftol": 1e-15})
            x, y, th, t = (part.copy() for part in unpack(result.x))
            key = [tuple(c) for c in chosen]
            if key == previous:
                break
            previous = key
        return x, y, th, self.largest_valid(x, y, th, t)

    def random_start(self, rng, t_area):
        low, high = self.container.min(0), self.container.max(0)
        points = []
        while len(points) < self.n:
            p = rng.uniform(low, high)
            inside = (np.hypot(*p) <= self.radius - 0.3 * t_area if self.radius is not None
                      else np.all(self.a @ p <= self.b - 0.3 * t_area))
            if inside:
                points.append(p)
        points = np.array(points)
        return points[:, 0], points[:, 1], rng.uniform(0, 2 * np.pi, self.n), 0.5 * t_area


def worker(args):
    local, container, n, seed, seconds, hop = args
    packing = Packing(local, container, n)
    rng = np.random.default_rng(seed)
    area = np.pi * container["circle"] ** 2 if isinstance(container, dict) else polygon_area(container)
    t_area = np.sqrt(0.75 * area / (n * polygon_area(local)))
    best = (0.0, None)
    if hop is not None:
        best = (hop[3], hop)
    tries = 0
    end = time.time() + seconds
    while time.time() < end:
        if hop is not None and best[1] is not None and rng.random() < 0.85:
            bx, by, bth, bt = best[1]
            size = bt * np.abs(packing.L).max()
            shake = rng.choice([0.05, 0.15, 0.4])
            moved = rng.random(n) < rng.choice([0.2, 0.5, 1.0])
            x = bx + moved * rng.normal(0, shake * size, n)
            y = by + moved * rng.normal(0, shake * size, n)
            th = bth + moved * rng.normal(0, shake, n)
            start = (x, y, th, bt * 0.97)
            mus = MUS[3:]
        else:
            start = packing.random_start(rng, t_area)
            mus = MUS
        x, y, th, t = packing.optimise(*start, mus=mus)
        if t > 0.95 * best[0]:
            x, y, th, t = packing.refine(x, y, th, t)
        tries += 1
        if t > best[0]:
            best = (t, (x, y, th, t))
    if best[1] is None:
        return 0.0, None, tries
    x, y, th, t = best[1]
    return t, [[float(a), float(b), float(np.degrees(c))] for a, b, c in zip(x, y, th)], tries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("slug")
    parser.add_argument("counts", type=int, nargs="+")
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--hop", action="store_true")
    args = parser.parse_args()
    container = json.loads((HERE / "arenas.json").read_text())[args.slug]
    local = json.loads((HERE / "shapes.json").read_text())[args.slug]["vertices"]
    RESULTS.mkdir(exist_ok=True)
    with Pool(args.workers) as pool:
        for n in args.counts:
            path = RESULTS / f"{args.slug}-{n}.json"
            saved = json.loads(path.read_text()) if path.exists() else None
            hop = None
            if args.hop and saved:
                poses = np.array(saved["poses"])
                hop = (poses[:, 0], poses[:, 1], np.radians(poses[:, 2]), saved["scale"])
            started = time.time()
            jobs = [(local, container, n, 7919 * n + w + int(started) % 9973, args.seconds, hop) for w in range(args.workers)]
            found = pool.map(worker, jobs)
            t, poses, _ = max(found, key=lambda item: item[0])
            tries = sum(item[2] for item in found)
            previous = saved["scale"] if saved else 0.0
            if poses is not None and t > previous:
                path.write_text(json.dumps({"slug": args.slug, "n": n, "scale": t, "poses": poses,
                                            "tries": tries + (saved or {}).get("tries", 0),
                                            "found": time.strftime("%Y-%m-%d %H:%M:%S")}))
            best = max(t, previous)
            print(f"{args.slug} n={n}: s = {1 / best if best else float('inf'):.6f}  "
                  f"(this pass {1 / t if t else float('inf'):.6f}, {tries} tries)", flush=True)


if __name__ == "__main__":
    main()
