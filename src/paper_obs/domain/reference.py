"""How an engine measurement compares with a published record.

A problem may carry the record its source published, in ``metadata["reference"]``, with
the unit the source states. This module reads an evaluation in that unit and says how far
it is from the record; it computes nothing geometric, it only picks the engine's metric.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: How a published record's unit maps to a measurement the engine takes of a candidate, and
#: whether a larger one is better. A unit that is not here is quoted as the source states it
#: and never compared: a silent conversion would invent a comparison the source never made.
REFERENCE_METRICS: dict[str, tuple[str, bool]] = {
    "container side": ("container_side", False),
    "container radius": ("container_radius", False),
    # A scale objective has no separate measurement for its size: the engine's score is it.
    "packing scale": ("primary", True),
    "sum of radii": ("total_scale", True),
    "sum of sides": ("total_scale", True),
    "covered side": ("covered_size", True),
    "covered radius": ("covered_size", True),
}

#: A fixed arena measures the container a published side names as the side equivalent to
#: the copies' scale, under its own name: the smallest container is derived only for a
#: square or a circle.
SAME_QUANTITY = {"container_side": "equivalent_container_side"}


def record_measure(reference: Any, primary: float | None, metrics: Mapping[str, Any]) -> float | None:
    """Return the engine's measure of an arrangement in a published record's unit.

    ``primary`` and ``metrics`` are an evaluation's. None where the record's unit is not one the
    engine measures, or the evaluation lacks that measure.
    """
    if not isinstance(reference, Mapping):
        return None
    compared = REFERENCE_METRICS.get(str(reference.get("unit") or ""))
    if compared is None:
        return None
    name = compared[0]
    measured = primary if name == "primary" else metrics.get(name, metrics.get(SAME_QUANTITY.get(name, "")))
    return float(measured) if isinstance(measured, (int, float)) and not isinstance(measured, bool) else None


def record_gap(reference: Any, primary: float | None, metrics: Mapping[str, Any]) -> float | None:
    """Return how far an arrangement is from a published record, as a signed fraction of it.

    Positive when the arrangement beats the record, negative when it falls short, whichever way
    the record's unit improves. None when there is no comparable record or measure.
    """
    measured = record_measure(reference, primary, metrics)
    value = reference.get("value") if isinstance(reference, Mapping) else None
    if measured is None or not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        return None
    larger_is_better = REFERENCE_METRICS[str(reference["unit"])][1]
    return (measured - value) / value * (1 if larger_is_better else -1)


__all__ = ["REFERENCE_METRICS", "record_gap", "record_measure"]
