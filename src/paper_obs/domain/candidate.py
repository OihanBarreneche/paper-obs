"""A candidate solution: pure data, no logic.

The candidate is the currency of the whole lab. It is what operators produce,
what the engine judges, what the blackboard stores, what the UI displays and
what gets compared between an algorithmic baseline and a team of agents. It is
therefore deliberately dumb: placements, a common scale, and the genealogy the
observability layer needs to draw the search tree.

Every candidate is JSON-serialisable in full, which is what makes runs
replayable, checkpoints portable and the blackboard storable on disk.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .placement import Placement
from .serde import JSON, as_float, as_int, require


def new_candidate_id(prefix: str = "c") -> str:
    """Return a fresh, short, unique candidate identifier."""
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


@dataclass(frozen=True)
class Candidate:
    """A set of placed shapes sharing one common scale.

    ``origin`` names whoever produced the candidate (an operator, a strategy, an
    agent) and ``parents`` its ancestors: together they form the genealogy the
    observability layer reports on. ``metadata`` is free-form and never read by
    the engine.
    """

    candidate_id: str
    problem_id: str
    scale: float
    placements: tuple[Placement, ...] = ()
    parents: tuple[str, ...] = ()
    origin: str = "unknown"
    generation: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.candidate_id:
            raise ValueError("candidate_id must not be empty")
        if not self.problem_id:
            raise ValueError("problem_id must not be empty")
        if not self.scale > 0.0:
            raise ValueError(f"candidate scale must be positive, got {self.scale!r}")
        identifiers = [placement.shape_id for placement in self.placements]
        if len(set(identifiers)) != len(identifiers):
            duplicates = sorted({name for name in identifiers if identifiers.count(name) > 1})
            raise ValueError(f"duplicate shape ids in candidate {self.candidate_id}: {duplicates}")

    @property
    def n_shapes(self) -> int:
        """Number of placed shapes."""
        return len(self.placements)

    @property
    def shape_ids(self) -> tuple[str, ...]:
        """Identifiers of the placed shapes, in placement order."""
        return tuple(placement.shape_id for placement in self.placements)

    def derive(
        self,
        *,
        placements: Iterable[Placement] | None = None,
        candidate_id: str | None = None,
        origin: str | None = None,
        generation: int | None = None,
        scale: float | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Candidate:
        """Return a child of this candidate, linking it to its parent.

        Operators use this instead of building a ``Candidate`` by hand, so that
        the genealogy (``parents``, ``generation``, ``origin``) stays correct
        without each operator having to remember it.
        """
        return Candidate(
            candidate_id=candidate_id or new_candidate_id(),
            problem_id=self.problem_id,
            scale=self.scale if scale is None else float(scale),
            placements=self.placements if placements is None else tuple(placements),
            parents=(self.candidate_id,),
            origin=self.origin if origin is None else origin,
            generation=self.generation + 1 if generation is None else generation,
            metadata=dict(self.metadata if metadata is None else metadata),
        )

    def to_dict(self) -> JSON:
        """Return the full JSON representation."""
        return {
            "kind": "candidate",
            "candidate_id": self.candidate_id,
            "problem_id": self.problem_id,
            "scale": self.scale,
            "origin": self.origin,
            "generation": self.generation,
            "parents": list(self.parents),
            "placements": [placement.to_dict() for placement in self.placements],
            "metadata": dict(self.metadata),
        }

    @staticmethod
    def from_dict(data: JSON) -> Candidate:
        """Decode a candidate from its JSON representation."""
        return Candidate(
            candidate_id=str(require(data, "candidate_id", "candidate")),
            problem_id=str(require(data, "problem_id", "candidate")),
            scale=as_float(require(data, "scale", "candidate"), "candidate.scale"),
            placements=tuple(
                Placement.from_dict(placement) for placement in data.get("placements", [])
            ),
            parents=tuple(str(parent) for parent in data.get("parents", [])),
            origin=str(data.get("origin", "unknown")),
            generation=as_int(data.get("generation", 0), "candidate.generation"),
            metadata=dict(data.get("metadata", {})),
        )
