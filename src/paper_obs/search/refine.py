"""Exact contact refinement: the largest common scale an arrangement's contacts allow.

For a ``maximize_scale`` problem with equal convex polygonal copies, a search usually stops
a hair short of the arrangement it found: contacts are nearly closed but not exactly. This
operator closes them. Every pair of nearby copies is kept apart by one fixed separating
axis (an edge normal of one of them, turning with it), every copy stays inside the arena,
and SLSQP maximises the scale under those smooth constraints. A fixed axis is a sufficient
condition for disjointness, so every feasible point is a packing; the axes are chosen
again at the solution until they stop changing.

A non-convex arena (an L, a frame, an arena with holes) is its convex hull minus convex
obstacles: the copies stay in the hull, and each copy is split from each obstacle by an
axis of either. A disc arena is its exact circle; another curved arena is the polygon the
engine compiles it to.

The optimiser only proposes. The engine judges the result, and the scale is cut back
by bisection until the engine accepts it: shrinking a convex copy about its centre keeps
it inside its old outline, so validity is monotone in the scale. Needs scipy (the
``research`` extra).
"""

from __future__ import annotations

import numpy as np

from paper_obs.domain.candidate import Candidate
from paper_obs.domain.constraints import RotationMode
from paper_obs.domain.objectives import MaximizeScale
from paper_obs.domain.problem import Problem
from paper_obs.geometry.engine import evaluate
from paper_obs.geometry.exact_check import convex_parts

#: Copies whose centres are closer than this many circumradii get a separating axis.
REACH = 2.3


def exact_refine(problem: Problem, candidate: Candidate, rounds: int = 6) -> Candidate:
    """Return the candidate with its contacts closed and the largest scale the engine accepts.

    Raises ValueError for a problem the method does not cover: another objective, round or
    non-convex copies, or copies with their own scale.
    """
    from scipy.optimize import minimize

    local = _check(problem, candidate)
    m = len(local)
    normals = _normals(local)
    support = (normals @ local.T).max(1)  # how far the unit copy reaches along each normal
    hull, obstacles, radius = _container(problem)
    n = len(candidate.placements)
    turning = problem.rotation.mode is RotationMode.FREE
    x = np.array([[item.x, item.y] for item in candidate.placements])
    th = np.radians([item.rotation for item in candidate.placements])
    t = candidate.scale

    def corners(x, th, t):
        c, s = np.cos(th)[:, None], np.sin(th)[:, None]
        return x[:, None, :] + t * np.stack([c * local[:, 0] - s * local[:, 1], s * local[:, 0] + c * local[:, 1]], 2)

    def turned(th, k):  # the copies' k-th normals in the world, one per given angle
        c, s = np.cos(th), np.sin(th)
        return np.stack([c * normals[k, 0] - s * normals[k, 1], s * normals[k, 0] + c * normals[k, 1]], -1)

    previous = None
    for _ in range(rounds):
        axes = _choose_axes(corners(x, th, t), x, th, t, local, normals, support, obstacles, turned)
        pairs, copy_owned, obstacle_owned = axes

        def unpack(z):
            return z[:2 * n].reshape(n, 2), z[2 * n:3 * n] if turning else th, z[-1]

        def gaps(z):
            x, th, t = unpack(z)
            v = corners(x, th, t)
            out = []
            if pairs:
                owner, other, k = (np.array(column) for column in zip(*pairs))
                axis = turned(th[owner], k)
                out.append((np.einsum("pmd,pd->pm", v[other] - x[owner][:, None], axis) - t * support[k][:, None]).ravel())
            for i, o, k in copy_owned:
                axis = turned(th[i], k)
                out.append((obstacles[o] - x[i]) @ axis - t * support[k])
            for i, o, k in obstacle_owned:
                normal, reach = _normals(obstacles[o])[k], (obstacles[o] @ _normals(obstacles[o])[k]).max()
                out.append(v[i] @ normal - reach)
            if radius is None:
                out.append((hull[1] - v.reshape(-1, 2) @ hull[0].T).ravel())
            else:
                out.append(radius ** 2 - (v ** 2).sum(-1).ravel())
            return np.concatenate(out)

        z0 = np.concatenate([x.ravel(), th if turning else [], [t]])
        result = minimize(lambda z: -z[-1], z0, jac=lambda z: -np.eye(len(z))[-1], method="SLSQP",
                          constraints={"type": "ineq", "fun": gaps}, options={"maxiter": 300, "ftol": 1e-15})
        x, th, t = (np.array(part, dtype=float) for part in unpack(result.x))
        t = float(t)
        if axes == previous:
            break
        previous = axes
    return _largest_accepted(problem, candidate, x, np.degrees(th), t)


def _check(problem: Problem, candidate: Candidate) -> np.ndarray:
    if not isinstance(problem.objective, MaximizeScale) or problem.arena is None:
        raise ValueError("exact refinement covers maximize_scale problems in a fixed arena")
    local = problem.shape.vertices(1.0)
    if local is None or not problem.shape.is_convex:
        raise ValueError("exact refinement needs convex polygonal copies")
    if any(item.scale is not None for item in candidate.placements):
        raise ValueError("exact refinement needs copies that share the common scale")
    local = np.asarray(local, dtype=float)
    x, y = local.T
    return local if np.dot(x, np.roll(y, -1)) > np.dot(y, np.roll(x, -1)) else local[::-1]  # counter-clockwise


def _normals(polygon: np.ndarray) -> np.ndarray:
    """Outward unit edge normals of a counter-clockwise polygon."""
    edges = np.roll(polygon, -1, 0) - polygon
    out = np.stack([edges[:, 1], -edges[:, 0]], 1)
    return out / np.linalg.norm(out, axis=1)[:, None]


def _container(problem: Problem):
    """Return the hull as half-planes (normals, offsets), the convex obstacles, and a disc radius."""
    corners, obstacles, radius = convex_parts(problem.arena)
    if corners is None:
        return None, [], radius
    normals = _normals(corners)
    return (normals, (normals * corners).sum(1)), obstacles, None


def _choose_axes(v, x, th, t, local, normals, support, obstacles, turned):
    """For each nearby pair and each copy-obstacle pair, the axis that separates it best."""
    reach = REACH * np.linalg.norm(local, axis=1).max() * t
    pairs, copy_owned, obstacle_owned = [], [], []
    count = len(x)
    for i in range(count):
        for j in range(i + 1, count):
            if np.linalg.norm(x[i] - x[j]) > reach:
                continue
            best = max(((((v[other] - x[owner]) @ turned(th[owner], k)).min() - t * support[k], owner, other, k)
                        for owner, other in ((i, j), (j, i)) for k in range(len(normals))))
            pairs.append(best[1:])
    for o, corners in enumerate(obstacles):
        own = _normals(corners)
        for i in range(count):
            by_copy = max(((((corners - x[i]) @ turned(th[i], k)).min() - t * support[k], k) for k in range(len(normals))))
            by_obstacle = max((((v[i] @ own[k]).min() - (corners @ own[k]).max(), k) for k in range(len(own))))
            if by_copy[0] >= by_obstacle[0]:
                copy_owned.append((i, o, by_copy[1]))
            else:
                obstacle_owned.append((i, o, by_obstacle[1]))
    return pairs, copy_owned, obstacle_owned


def _largest_accepted(problem: Problem, start: Candidate, x, degrees, t: float) -> Candidate:
    """The refined arrangement at the largest scale the engine judges valid (bisection)."""
    placements = [item.moved(float(a), float(b)).rotated(float(r)) for item, (a, b), r in zip(start.placements, x, degrees)]
    shaped = lambda scale: start.derive(placements=placements, scale=scale, origin="exact_refine")  # noqa: E731
    low, high = 0.0, t
    if evaluate(problem, shaped(high)).valid:
        return shaped(high)
    for _ in range(60):
        middle = (low + high) / 2
        if evaluate(problem, shaped(middle)).valid:
            low = middle
        else:
            high = middle
    if low <= 0.0:
        raise ValueError("the refined arrangement is not valid at any scale")
    return shaped(low)
