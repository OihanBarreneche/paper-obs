"""Where a packing is empty and how its shapes touch.

Validation answers "is this allowed"; analysis answers "what should be tried
next". It is deliberately separate from the metrics: a metric describes a
candidate for a human, an analysis is an *input to a decision*.

The first decision it feeds is the obvious one — a void is where a shape can be
added, or where a region can be reseeded. The empty regions are computed on the
tessellated outline of the shapes (a circumscribed polygon for a circle), so a
void adjacent to a disc is slightly underestimated, never invented.
"""

from __future__ import annotations

from dataclasses import dataclass

import shapely

from paper_obs.domain.serde import JSON

from .facts import CONTACT_TOLERANCE, Facts

#: A region smaller than this fraction of the arena is numerical dust, not a void.
MIN_VOID_AREA_RATIO = 1e-9


@dataclass(frozen=True)
class Void:
    """One connected empty region of the arena."""

    area: float
    centroid: tuple[float, float]
    bounds: tuple[float, float, float, float]

    def to_dict(self) -> JSON:
        """Return the JSON representation."""
        return {
            "area": self.area,
            "centroid": list(self.centroid),
            "bounds": list(self.bounds),
        }


@dataclass(frozen=True)
class CandidateAnalysis:
    """The structural reading of a candidate."""

    voids: tuple[Void, ...]
    mean_contacts: float

    @property
    def largest_void(self) -> Void | None:
        """The biggest empty region, or ``None`` when the shapes cover the arena."""
        return self.voids[0] if self.voids else None

    def to_dict(self) -> JSON:
        """Return the JSON representation.

        Only the reported regions are listed: they are capped by the limit the
        caller asked for, and the exact empty area is a metric, not an analysis.
        """
        return {
            "voids": [void.to_dict() for void in self.voids],
            "mean_contacts": self.mean_contacts,
        }


def find_voids(facts: Facts, *, limit: int = 5, min_area_ratio: float = MIN_VOID_AREA_RATIO) -> tuple[Void, ...]:
    """Return the largest empty regions of the arena, biggest first.

    Regions below ``min_area_ratio`` of the arena are dropped: a perfect tiling
    leaves slivers of a few square nanometres along every shared edge, and
    reporting them as voids would bury the regions that can actually hold a
    shape.
    """
    covered = shapely.union_all(list(facts.iter_footprints()))
    remaining = facts.arena.geometry.difference(covered)
    if remaining.is_empty:
        return ()
    floor = min_area_ratio * facts.arena.area
    polygons = [
        part
        for part in shapely.get_parts(remaining)
        if part.geom_type == "Polygon" and part.area > floor
    ]
    polygons.sort(key=lambda polygon: polygon.area, reverse=True)
    voids = []
    for polygon in polygons[: max(0, limit)]:
        centroid = polygon.centroid
        voids.append(
            Void(
                area=float(polygon.area),
                centroid=(float(centroid.x), float(centroid.y)),
                bounds=tuple(float(value) for value in polygon.bounds),
            )
        )
    return tuple(voids)


def analyze_facts(
    facts: Facts,
    *,
    void_limit: int = 5,
    contact_tolerance: float = CONTACT_TOLERANCE,
) -> CandidateAnalysis:
    """Read the structure of a candidate: empty regions and neighbour counts.

    Neighbour counts come from the same pairwise clearances the constraints use,
    with a slack of ``contact_tolerance``: a shape is only counted as touching
    another one when the gap between them is below that tolerance, so the number
    stays meaningful across shape families.
    """
    contacts: dict[str, int] = {instance.shape_id: 0 for instance in facts.instances}
    for clearance in facts.clearances(slack=contact_tolerance):
        contacts[clearance.first] += 1
        contacts[clearance.second] += 1
    mean_contacts = (sum(contacts.values()) / len(contacts)) if contacts else 0.0
    return CandidateAnalysis(
        voids=find_voids(facts, limit=void_limit),
        mean_contacts=mean_contacts,
    )


def shape_neighborhood(facts: Facts, shape_id: str, *, distance: float = 5.0, limit: int = 8) -> dict:
    """Describe one shape's boundary and neighbours in world units.

    Positive clearances are exact for discs and convex polygons. A non-convex
    polygon uses the same approximation as the engine's other diagnostics.
    """
    instance = facts.instance(shape_id)
    containment = next(item for item in facts.containment if item.shape_id == shape_id)
    overlaps = [
        {
            "shape_id": item.second if item.first == shape_id else item.first,
            "depth": item.depth,
            "direction": list(item.direction if item.second == shape_id else (-item.direction[0], -item.direction[1])),
        }
        for item in facts.overlaps if shape_id in (item.first, item.second)
    ]
    nearby = [
        {"shape_id": item.second if item.first == shape_id else item.first, "clearance": item.distance}
        for item in facts.clearances(slack=distance) if shape_id in (item.first, item.second)
    ]
    nearby.sort(key=lambda item: item["clearance"])
    return {
        "shape_id": shape_id,
        "center": list(instance.center),
        "rotation": instance.rotation,
        "scale": instance.scale,
        "boundary": {"inside": containment.inside, "margin": containment.margin, "overflow_area": containment.overflow_area},
        "overlaps": overlaps[:limit],
        "nearby": nearby[:limit],
    }
