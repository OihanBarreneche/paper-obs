"""One placed shape: the atom of a packing solution.

A placement holds no geometry, only the numbers a shape needs to be positioned.
``scale`` is optional and normally ``None``: a homogeneous packing shares one
scale at candidate level, so repeating it on every placement would multiply the
size of every saved candidate for nothing. An explicit per-placement scale is
kept for future heterogeneous problems.

``color`` is optional decoration, never geometry: it says how to paint the shape,
not where it is. It is a lower-case ``#rrggbb`` string, and ``None`` — the
default — means "whatever the theme paints a shape with". Validation is a hard
verdict, so a shape a violation names keeps the violation colours whatever it is
painted with.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .serde import JSON, as_float, optional, require

#: The only colour form the domain accepts: lower-case ``#rrggbb``.
COLOR_PATTERN = re.compile(r"#[0-9a-f]{6}")


@dataclass(frozen=True)
class Placement:
    """Position, rotation, optional local scale and optional colour of one shape."""

    shape_id: str
    x: float
    y: float
    rotation: float = 0.0
    scale: float | None = None
    color: str | None = None

    def __post_init__(self) -> None:
        if not self.shape_id:
            raise ValueError("placement shape_id must not be empty")
        if self.scale is not None and not self.scale > 0.0:
            raise ValueError(f"placement scale must be positive, got {self.scale!r}")
        # ``isinstance`` before the pattern: a document may carry any JSON value
        # under ``color``, and a number must be refused like any other string.
        if self.color is not None and (
            not isinstance(self.color, str) or not COLOR_PATTERN.fullmatch(self.color)
        ):
            raise ValueError(
                f"placement color must be a lower-case #rrggbb colour, got {self.color!r}"
            )

    def resolved_scale(self, common_scale: float) -> float:
        """Return the local scale if set, else the candidate's common scale."""
        return common_scale if self.scale is None else self.scale

    def to_dict(self) -> JSON:
        """Return the JSON representation, omitting fields left at their default."""
        data: JSON = {"shape_id": self.shape_id, "x": self.x, "y": self.y}
        if self.rotation:
            data["rotation"] = self.rotation
        if self.scale is not None:
            data["scale"] = self.scale
        if self.color is not None:
            data["color"] = self.color
        return data

    @staticmethod
    def from_dict(data: JSON) -> Placement:
        """Decode a placement from its JSON representation."""
        scale = optional(data, "scale")
        return Placement(
            shape_id=str(require(data, "shape_id", "placement")),
            x=as_float(require(data, "x", "placement"), "placement.x"),
            y=as_float(require(data, "y", "placement"), "placement.y"),
            rotation=as_float(data.get("rotation", 0.0), "placement.rotation"),
            scale=None if scale is None else as_float(scale, "placement.scale"),
            color=optional(data, "color"),
        )

    def moved(self, x: float, y: float) -> Placement:
        """Return the same placement translated to ``(x, y)``."""
        return Placement(
            shape_id=self.shape_id,
            x=x,
            y=y,
            rotation=self.rotation,
            scale=self.scale,
            color=self.color,
        )

    def rotated(self, rotation: float) -> Placement:
        """Return the same placement with another rotation, in degrees."""
        return Placement(
            shape_id=self.shape_id,
            x=self.x,
            y=self.y,
            rotation=rotation,
            scale=self.scale,
            color=self.color,
        )
