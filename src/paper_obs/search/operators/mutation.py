"""Mutation operators: displace anchors, drop shapes, replace a region.

An operator *proposes*, the engine *judges*. A mutation is the crudest way of
proposing something: move, drop or redraw a few shapes, and let the engine say
what the result is worth. None of the functions below builds an overlap test, a
containment test or a score of its own. The two places where a rule is genuinely
needed ask the engine: ranking the shapes by how badly they collide reads the
violations of the ``non_overlap`` constraint, and drawing a replacement anchor
asks :meth:`paper_obs.domain.arena.Arena.contains_point` — the arena's own
predicate, not a copy of it.

This is the half of the search that *disturbs* a candidate.
:mod:`paper_obs.search.operators.relaxation` and
:mod:`paper_obs.search.operators.repair` are the half that keeps what the
engine prefers.

Randomness always goes through an explicit ``numpy.random.Generator``, seeded
from the problem by default, so a run can be replayed exactly from its JSON file.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import replace

import numpy as np

from paper_obs.domain.candidate import Candidate
from paper_obs.domain.placement import Placement
from paper_obs.domain.problem import Problem

from paper_obs.geometry.engine import validate

#: How many replacement anchors ``reseed_region`` draws per shape it must place.
#: The region can lie partly outside the arena and the surplus is what makes the
#: operator still fill it; four is the same surplus ``random_initialize`` uses.
RESEED_ATTEMPTS = 4

#: The naming scheme of the initializers. Matched exactly, and on ASCII digits
#: only, so that an identifier written by someone else — ``left-disc``, ``s2²`` —
#: is never mistaken for one this module can continue.
_SHAPE_ID = re.compile(r"^s([0-9]+)$")

#: An axis-aligned box in world coordinates ``(min_x, min_y, max_x, max_y)``, the
#: shape :attr:`paper_obs.geometry.analysis.Void.bounds` already has.
Region = tuple[float, float, float, float]

#: Offsets to apply, keyed by shape identifier.
Moves = Mapping[str, tuple[float, float]]


def displace(candidate: Candidate, *, moves: Moves, origin: str) -> Candidate:
    """Return a child of ``candidate`` in which the named shapes are translated.

    ``moves`` maps a shape identifier to the offset applied to its anchor. This is
    the shared primitive of the mutating operators — :func:`jitter`,
    :func:`translate_cluster` and the repair loop of
    :mod:`paper_obs.search.operators.repair` all end up here — and the only
    place that has to know a moved placement keeps its rotation and its local
    scale.

    It takes no problem and calls no engine: an anchor plus an offset is data, not
    geometry. An empty group or an identifier the candidate does not have is
    refused rather than ignored, because a caller that names shapes it does not
    have is a caller holding a stale candidate.
    """
    if not moves:
        raise ValueError("displace needs at least one shape to move")
    unknown = sorted(set(moves) - set(candidate.shape_ids))
    if unknown:
        raise ValueError(f"candidate {candidate.candidate_id} has no shape(s) {', '.join(unknown)}")
    placements: list[Placement] = []
    for placement in candidate.placements:
        offset = moves.get(placement.shape_id)
        if offset is None:
            placements.append(placement)
            continue
        dx, dy = offset
        placements.append(placement.moved(placement.x + dx, placement.y + dy))
    return candidate.derive(placements=placements, origin=origin)


def jitter(
    problem: Problem,
    candidate: Candidate,
    *,
    amplitude: float,
    generator: np.random.Generator | None = None,
    count: int | None = None,
    turn: float = 0.0,
    origin: str = "jitter",
) -> Candidate:
    """Displace shapes by a bounded random amount.

    Each coordinate of a displaced anchor receives a uniform offset in
    ``[-amplitude, amplitude]``, in the length unit of the problem. Shapes are
    never resized: a jitter explores the neighbourhood of a candidate at a fixed
    scale, which is exactly what the relaxation and the repair loops need.

    ``turn``, in degrees, also turns each displaced shape by a uniform angle in
    ``[-turn, turn]``. Zero draws nothing, so a seeded caller that never turns
    replays exactly as before.

    ``count`` is how many shapes move, drawn without replacement; ``None`` moves
    every shape. Displacements that make the candidate invalid are not filtered
    out — proposing them is the point, and the engine is what rates them.
    """
    if amplitude < 0.0:
        raise ValueError(f"amplitude must not be negative, got {amplitude!r}")
    rng = generator if generator is not None else np.random.default_rng(problem.seed)
    shape_ids = list(candidate.shape_ids)
    if count is None:
        moved = shape_ids
    else:
        if not 1 <= count <= len(shape_ids):
            raise ValueError(
                f"count must be between 1 and {len(shape_ids)} for this candidate, got {count!r}"
            )
        drawn = rng.choice(len(shape_ids), size=count, replace=False)
        moved = [shape_ids[int(index)] for index in drawn]
    offsets = rng.uniform(-amplitude, amplitude, size=(len(moved), 2))
    moves = {shape_id: (float(dx), float(dy)) for shape_id, (dx, dy) in zip(moved, offsets)}
    if turn <= 0.0:
        return displace(candidate, moves=moves, origin=origin)
    angles = dict(zip(moved, rng.uniform(-turn, turn, size=len(moved))))
    return candidate.derive(
        placements=[
            replace(item.moved(item.x + moves[item.shape_id][0], item.y + moves[item.shape_id][1]),
                    rotation=item.rotation + float(angles[item.shape_id]))
            if item.shape_id in moves else item
            for item in candidate.placements
        ],
        origin=origin,
    )


def translate_cluster(
    problem: Problem,
    candidate: Candidate,
    *,
    shape_ids: Iterable[str],
    dx: float,
    dy: float,
    origin: str = "translate_cluster",
) -> Candidate:
    """Move a named group of shapes together, by one common offset.

    The whole group keeps its internal arrangement, which is what makes this the
    mutation a human performs on screen and the one an agent uses to slide a block
    out of the way without destroying what is already packed.

    ``problem`` is unused: the offset lands on anchors, which is arithmetic on
    data, and whether the result is still a packing is the engine's call. The
    parameter stays in the signature so that every operator of the library is
    called the same way.
    """
    moves = {shape_id: (dx, dy) for shape_id in shape_ids}
    if not moves:
        raise ValueError("translate_cluster needs at least one shape_id")
    return displace(candidate, moves=moves, origin=origin)


def remove_shapes(
    problem: Problem,
    candidate: Candidate,
    *,
    count: int,
    generator: np.random.Generator | None = None,
    origin: str = "remove_shapes",
) -> Candidate:
    """Drop shapes, preferring the ones the engine reports as overlapping.

    Every shape accumulates the depth of the overlaps it takes part in, as
    reported by the ``non_overlap`` constraint: the heavier it is, the more room
    removing it frees. A colliding shape never sorts below a shape that does not
    collide, so on a valid candidate — where nothing collides — the draw alone
    decides, and the removal is a plain random thinning.

    The count is not renegotiated. Removing shapes from a fixed-count objective
    makes the candidate invalid, and that verdict belongs to the engine, not here;
    reinsertion is what a caller pairs this with.
    """
    if not 1 <= count <= candidate.n_shapes:
        raise ValueError(
            f"count must be between 1 and {candidate.n_shapes} for this candidate, got {count!r}"
        )
    rng = generator if generator is not None else np.random.default_rng(problem.seed)
    depths = dict.fromkeys(candidate.shape_ids, 0.0)
    for violation in validate(problem, candidate).collisions:
        for shape_id in violation.shape_ids:
            depths[shape_id] += violation.magnitude
    # A permutation first, then a stable sort on the depth: ties are broken by the
    # draw rather than by the order the placements happen to be in.
    order = [candidate.shape_ids[int(index)] for index in rng.permutation(candidate.n_shapes)]
    order.sort(key=lambda shape_id: -depths[shape_id])
    dropped = set(order[:count])
    return candidate.derive(
        placements=[
            placement for placement in candidate.placements if placement.shape_id not in dropped
        ],
        origin=origin,
    )


def reseed_region(
    problem: Problem,
    candidate: Candidate,
    *,
    region: Region,
    count: int,
    generator: np.random.Generator | None = None,
    origin: str = "reseed_region",
) -> Candidate:
    """Delete the shapes inside a rectangular region and place new ones there.

    ``region`` is a world-coordinate box, the same shape as a void's bounds, so a
    caller can feed it straight from the analysis of a candidate. A shape belongs
    to the region when its **anchor** is in the box: the anchors are the
    candidate's own numbers, whereas a verdict on an outline is the engine's
    business.

    The replacements are drawn uniformly in the region and an anchor is kept only
    when the arena contains it — an anchor the arena refuses leads nowhere, so
    proposing it would waste a mutation. Replacements are not checked against each
    other or against their neighbours: the overlaps this creates are precisely
    what the engine reports and what the repair operators undo.

    Fewer than ``count`` shapes come back when the arena refuses part of the
    region, and none at all when the region lies outside the arena — the shapes
    it held are gone either way.
    """
    min_x, min_y, max_x, max_y = region
    if not (min_x < max_x and min_y < max_y):
        raise ValueError(f"region must be a box with min < max on both axes, got {region!r}")
    if count < 1:
        raise ValueError(f"count must be at least 1, got {count!r}")
    rng = generator if generator is not None else np.random.default_rng(problem.seed)
    kept = [
        placement
        for placement in candidate.placements
        if not (min_x <= placement.x <= max_x and min_y <= placement.y <= max_y)
    ]
    samples = rng.uniform((min_x, min_y), (max_x, max_y), size=(RESEED_ATTEMPTS * count, 2))
    identifiers = _fresh_shape_ids(candidate, count)
    placed: list[Placement] = []
    for x, y in samples:
        if len(placed) >= count:
            break
        if not problem.draft_region.contains_point(float(x), float(y)):
            continue
        placed.append(Placement(shape_id=identifiers[len(placed)], x=float(x), y=float(y)))
    return candidate.derive(placements=[*kept, *placed], origin=origin)


def _fresh_shape_ids(candidate: Candidate, count: int) -> list[str]:
    """Return ``count`` identifiers that no placement of ``candidate`` already uses.

    They continue the ``sNNN`` numbering after the highest one present, so the
    identifiers of a lineage stay sortable and a removed-then-reinserted shape
    never reuses the name of a shape that is still in the candidate.
    """
    highest = -1
    for shape_id in candidate.shape_ids:
        match = _SHAPE_ID.match(shape_id)
        if match is not None:
            highest = max(highest, int(match.group(1)))
    return [f"s{highest + 1 + offset:03d}" for offset in range(count)]
