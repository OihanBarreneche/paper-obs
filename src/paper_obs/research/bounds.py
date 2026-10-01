"""Leads for a record hunt: published entries that a construction from other entries beats.

Exact facts turn one published packing into another, in the catalog's own units:

* **a copy holds copies.** A unit square holds two unit tans, a tan of leg 2 holds four
  unit tans (a rep-tile), and so on: with ``count`` unit A's inside a B of size ``ratio``,
  ``s[A in X](count * n) <= ratio * s[B in X](n)``;
* **a container splits into containers.** A square of side s is two tans of leg s, a
  triangle of side 2s is four of side s: ``s[A in X](n_1 + ... + n_k)`` is at most the
  side at which each piece holds its share.

Every catalog entry above the best such bound is a lead: the construction is a valid
packing at the bound's size, which an exact refinement can then improve. A printed value
is truncated, even beside its closed form, so a construction uses its upper end: 1.414
stands for up to 1.415. A value with fewer than three decimals is taken as exact. A lead is a hint
for a person or an agent, not a record: the catalog is a snapshot and the live page decides.
"""

from __future__ import annotations

import math
from typing import Any

from paper_obs.domain.arena import Arena

#: (outer, inner, count, ratio): an outer copy of size ``ratio`` holds ``count`` unit inner copies.
HOLDS = [
    ("square", "tan", 2, 1), ("domino", "square", 2, 1), ("domino", "tan", 4, 1),
    ("l", "square", 3, 1), ("l", "domino", 1, 1), ("l", "tan", 6, 1),
    ("hexagon", "triangle", 6, 1), ("hexagon", "square", 1, 1), ("pentagon", "square", 1, 1),
    ("pentagon", "triangle", 1, 1), ("circle", "square", 1, 1), ("circle", "pentagon", 1, 1),
    ("circle", "hexagon", 1, 1), ("circle", "triangle", 6, 1), ("circle", "tan", 4, 1),
    ("octagon", "domino", 1, 1), ("octagon", "square", 2, 1), ("octagon", "tan", 4, 1),
    ("octagon", "circle", 1, 1), ("octagon", "hexagon", 1, 1), ("octagon", "triangle", 6, 1),
    ("octagon", "pentagon", 1, 1),
    # Rep-tiles: a copy k times larger is k * k unit copies; a tan is also two tans 1/sqrt 2 its size.
    *((shape, shape, k * k, k) for shape in ("triangle", "square", "domino", "l", "tan") for k in (2, 3, 4)),
    ("tan", "tan", 2, math.sqrt(2)),
]
#: A container of side s splits into pieces (container, side / s).
SPLITS = {
    "square": [[("tan", 1)] * 2, [("domino", .5)] * 2, [("square", .5)] * 4, [("l", .5), ("square", .5)]],
    "domino": [[("square", 1)] * 2, [("domino", .5)] * 4, [("tan", 1)] * 4],
    "l": [[("square", 1)] * 3, [("domino", 1), ("square", 1)], [("l", .5)] * 4, [("tan", 1)] * 6],
    "tan": [[("tan", 1 / math.sqrt(2))] * 2, [("tan", .5)] * 4, [("square", .5), ("tan", .5), ("tan", .5)]],
    "triangle": [[("triangle", .5)] * 4, [("hexagon", 1 / 3)] + [("triangle", 1 / 3)] * 3],
    "hexagon": [[("triangle", 1)] * 6],
}


def leads(catalog: dict[str, Any], margin: float = 1e-5) -> list[dict[str, Any]]:
    """Return the entries a construction beats by more than ``margin``, the largest gain first.

    Each lead names the family, the count, the published value, the bound in the same unit,
    and the construction. Only equal-copies families measured by a container size are read.
    """
    tables = _tables(catalog)
    found = []
    for (shape, container), (slug, table, unit) in tables.items():
        for count, (published, _) in sorted(table.items()):
            bounds = []
            for outer, inner, holds, ratio in HOLDS:
                if inner == shape and (value := _at_least(tables, outer, container, -(-count // holds))) is not None:
                    bounds.append((ratio * value, f"{holds} {inner} per {outer} of size {ratio:.4g}: "
                                   f"{ratio:.4g} x s[{outer} in {container}]({-(-count // holds)})"))
            for pieces in SPLITS.get(container, []):
                if (bound := _split_bound(tables, shape, pieces, count)) is not None:
                    bounds.append(bound)
            if bounds:
                bound, how = min(bounds)
                if bound < published - margin:
                    found.append({"slug": slug, "count": count, "published": published / unit,
                                  "bound": bound / unit, "gain": (published - bound) / published, "construction": how})
    return sorted(found, key=lambda lead: -lead["gain"])


def _tables(catalog: dict[str, Any]) -> dict[tuple[str, str], tuple[str, dict[int, tuple[float, str]], float]]:
    """The published values per (copy, container), in the container's short-side unit.

    A table is non-decreasing in the count; both ends of a violation are parse suspects and
    are dropped. ``unit`` converts back to the value as the page prints it.
    """
    tables = {}
    for family in catalog["families"]:
        if family.get("section") != "Packing Equal Copies" or not family.get("supported") or not family.get("problem_template"):
            continue
        unit = _printed_unit(family)
        table = {count: (item["value"] * unit, _upper(item) * unit)
                 for item in family["instances"] if item.get("value") is not None for count in item["counts"]}
        suspects = {n for n in table for m in table
                    if (m < n and table[m][0] > table[n][0] + 1e-3) or (m > n and table[m][0] < table[n][0] - 1e-3)}
        tables[(family["shape"], family["container"])] = (
            family["slug"], {n: entry for n, entry in table.items() if n not in suspects}, unit)
    return tables


def _upper(item: dict[str, Any]) -> float:
    """The largest true value a printed one may stand for: the next unit of its last digit."""
    value = float(item["value"])
    digits = len(repr(value).partition(".")[2])
    return value if digits < 3 else value + 10.0 ** -digits


def _printed_unit(family: dict[str, Any]) -> float:
    """The short side of an L container per printed length: 1/2 where the page prints the long side."""
    if family["container"] != "l":
        return 1.0
    arena = Arena.from_dict(family["problem_template"]["arena"])
    ring = list(arena.geometry.exterior.coords)
    shortest = min(math.dist(a, b) for a, b in zip(ring, ring[1:]))
    return shortest / (arena.reference_length or shortest)


def _at_least(tables, shape: str, container: str, count: int) -> float | None:
    """The smallest published value for ``count`` or more copies: a table is monotone."""
    entry = tables.get((shape, container))
    return min((upper for n, (_, upper) in entry[1].items() if n >= count), default=None) if entry and count >= 1 else None


def _split_bound(tables, shape: str, pieces, count: int) -> tuple[float, str] | None:
    """The smallest side at which the container's pieces hold ``count`` copies together."""
    def most(container: str, side: float) -> int:
        entry = tables.get((shape, container))
        return max((n for n, (_, upper) in entry[1].items() if upper <= side + 1e-12), default=0) if entry else 0
    sides = sorted({upper / ratio for container, ratio in pieces
                    for _, upper in tables.get((shape, container), ("", {}, 1))[1].values()})
    for side in sides:
        if sum(most(container, side * ratio) for container, ratio in pieces) >= count:
            split = " + ".join(f"{container}({ratio:.3g}s): {most(container, side * ratio)}" for container, ratio in pieces)
            return side, f"split: {split}"
    return None


__all__ = ["HOLDS", "SPLITS", "leads"]
