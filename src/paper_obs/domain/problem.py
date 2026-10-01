"""A packing problem: a region, a shape family, an objective and constraints.

This module is the top of the domain layer and the only object a search
workflow, a baseline or an agent needs in order to act. It is frozen and fully
serialisable: one JSON file describes a problem completely, which is what makes
an experiment reproducible from a single artefact.

The dimensions of the problem are deliberately *not* baked into the objective:
the objective says what is maximised, the constraints say what is allowed, and
neither of them knows anything about circles, squares or lattices.
"""

from __future__ import annotations

import math

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .arena import Arena
from .constraints import Constraint, RequiredShapeCount, RotationPolicy
from .objectives import Objective
from .serde import JSON, as_int, optional, require
from .shapes import PackableShape


@dataclass(frozen=True)
class Problem:
    """A complete description of what has to be packed, and how well.

    ``constraints`` holds the problem's *extra* requirements. The structural
    ones — declared by the objective itself — and that objective's own
    requirements are added by :attr:`effective_constraints`, so a problem file
    never repeats them.

    ``arena`` is the region the shapes must stay in, and it is absent exactly
    when the objective measures that region instead of being handed it: a
    minimised container is derived from the arrangement, so there is nothing for
    the file to declare, and declaring one anyway would leave a reader believing
    a region that nothing reads.
    """

    problem_id: str
    arena: Arena | None
    shape: PackableShape
    objective: Objective
    rotation: RotationPolicy = RotationPolicy()
    constraints: tuple[Constraint, ...] = ()
    seed: int | None = None
    name: str = ""
    description: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.problem_id:
            raise ValueError("problem_id must not be empty")
        if self.arena is None and not self.objective.derives_region:
            raise ValueError(
                f"{self.objective.kind} packs into an arena, which this problem does not declare"
            )
        if self.arena is not None and self.objective.derives_region:
            raise ValueError(
                f"{self.objective.kind} measures its own region from the arrangement; "
                "the declared arena would be ignored, so declare none"
            )

    @property
    def effective_constraints(self) -> tuple[Constraint, ...]:
        """Every constraint the engine applies, in evaluation order.

        Structural first — is it a packing at all, and against which region —
        then the problem's own extras, then the rotation policy, then what the
        objective implies.

        A count the objective fixes is a requirement of the *problem*, not a
        private detail of whoever wrote it: when the composed list names none, one
        is added here. Every objective of the lab already declares its own, so the
        order above is unchanged for all of them; the guarantee is what keeps a
        family that fixes a count through Objective.preset_count and omits the
        constraint from being scored as valid anyway. A problem that fixes no count
        — the composer's, and every "maximise as many as fit" family — gets none,
        which is what keeps an arrangement of any size legitimate there.
        """
        constraints = (
            *self.objective.structural_constraints(self),
            *self.constraints,
            self.rotation,
            *self.objective.constraints(self),
        )
        count = self.objective.preset_count()
        if count is None or any(
            constraint.kind == RequiredShapeCount.kind for constraint in constraints
        ):
            return constraints
        return (*constraints, RequiredShapeCount(count))

    @property
    def draft_region(self) -> Arena:
        """The region a construction lays shapes out in, when the problem declares none.

        It is the arena itself for every problem that has one. A problem whose
        objective measures its own container declares no arena, and a construction
        still has to put the shapes *somewhere* before anything can be measured:
        the draft is then a square large enough to hold ``preset_count()`` shapes
        of the objective's own scale side by side in a grid.

        A draft is a starting point, never a constraint — nothing validates against
        it, and the region a candidate is actually judged against is the one the
        engine measures (:attr:`paper_obs.geometry.facts.Facts.arena`).
        """
        if self.arena is not None:
            return self.arena
        count = self.objective.preset_count() or 1
        scale = self.objective.preset_scale() or 1.0
        # One cell per shape, a cell being the diameter of the shape's bounding
        # circle: a row of them touches, and touching is enough to start from.
        side = math.ceil(math.sqrt(count)) * 2.0 * self.shape.circumradius(scale)
        return Arena.rectangle(side, side)

    @property
    def title(self) -> str:
        """Display name, falling back to the identifier."""
        return self.name or self.problem_id

    def describe_region(self) -> str:
        """One line naming the region this problem is judged against.

        The declared arena's own description, or the sentence that says where the
        region comes from when the objective measures it. Every summary of a
        problem has to say something true about its region, and only the domain
        knows which of the two it is.
        """
        if self.arena is None:
            if self.objective.covered_target is not None:
                return "measured from the union of the copies, at its largest"
            return "measured from the arrangement, minimally"
        return self.arena.describe()

    def describe(self) -> str:
        """Multi-line summary used by the CLI, the UI and the analyst prompt."""
        lines = [
            f"problem     {self.title} ({self.problem_id})",
            f"arena       {self.describe_region()}",
            f"shape       {self.shape.describe()}",
            f"objective   {self.objective.describe()}",
            f"rotation    {self.rotation.describe()}",
        ]
        for constraint in self.constraints:
            lines.append(f"constraint  {constraint.describe()}")
        if self.seed is not None:
            lines.append(f"seed        {self.seed}")
        return "\n".join(lines)

    def to_dict(self) -> JSON:
        """Return the full JSON representation of the problem.

        ``arena`` is written only when the problem has one; an objective that
        measures its own region leaves the key out, and :meth:`from_dict` reads
        that absence back as ``None``.
        """
        data: JSON = {
            "problem_id": self.problem_id,
            "name": self.name,
            "description": self.description,
            "seed": self.seed,
            "shape": self.shape.to_dict(),
            "objective": self.objective.to_dict(),
            "rotation": self.rotation.to_dict(),
            "constraints": [constraint.to_dict() for constraint in self.constraints],
            "metadata": dict(self.metadata),
        }
        if self.arena is not None:
            data["arena"] = self.arena.to_dict()
        return data

    @staticmethod
    def from_dict(data: JSON) -> Problem:
        """Decode a problem from its JSON representation."""
        rotation = optional(data, "rotation")
        seed = optional(data, "seed")
        arena = optional(data, "arena")
        return Problem(
            problem_id=str(require(data, "problem_id", "problem")),
            arena=None if arena is None else Arena.from_dict(arena),
            shape=PackableShape.from_dict(require(data, "shape", "problem")),
            objective=Objective.from_dict(require(data, "objective", "problem")),
            rotation=RotationPolicy() if rotation is None else RotationPolicy.from_dict(rotation),
            constraints=tuple(
                Constraint.from_dict(constraint) for constraint in data.get("constraints", [])
            ),
            seed=None if seed is None else as_int(seed, "problem.seed"),
            name=str(data.get("name", "")),
            description=str(data.get("description", "")),
            metadata=dict(data.get("metadata", {})),
        )


__all__ = ["Problem"]
