"""Hard requirements, expressed as structured feedback rather than booleans.

A constraint never answers ``True``/``False`` alone: it reports violations, each
naming the shapes involved and a magnitude. Search operators, repair loops and
the agents of the workflow all read that structure to know *what* is broken and
*how badly*, which a boolean cannot express.

Two constraints define what a packing is: :class:`ArenaContainment` and
:class:`NonOverlap`, the structural pair an objective returns by default. A
covering objective replaces both: its copies lie over the region and typically
overlap each other, so its one structural requirement is :class:`ArenaCovered`,
and the rotation policy is the only other rule. Whatever the objective, its own
requirements, the problem's extras and the rotation policy are composed in
:attr:`paper_obs.domain.problem.Problem.effective_constraints`.

Magnitudes are expressed in the unit that makes sense inside a constraint
(a length for overlaps and clearances, an area for an arena overflow, a count for
a shape count). They are comparable within one constraint, not across two, and
``ConstraintResult.severity`` inherits that limit.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, ClassVar

from .serde import JSON, as_float, as_int, discriminated, require

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps domain free of geometry
    from paper_obs.geometry.facts import Facts

#: Rotation tolerance in degrees: an angle within this of an allowed value passes.
ANGLE_TOLERANCE = 1e-6

#: Tolerance of the covering verdict, *relative to the arena area*.
#:
#: Covering is decided by an area comparison, so the verdict is never more
#: precise than the representation that area is read from. Two regimes, and the
#: constraint reads both:
#:
#: * when the arena and every footprint are discs, the covered area is closed
#:   form (:mod:`paper_obs.geometry.exact_discs`, through
#:   ``Facts.uncovered_area``) and this tolerance is a pure floating-point slack;
#: * otherwise a curved boundary is a circumscribed polygon, whose area carries
#:   ``tessellation.chord_area_relative_error()`` -- 5.0e-5 at the default chord
#:   count. ``Facts.coverage_resolution`` reports that bound, and
#:   :class:`ArenaCovered` uses the larger of it and this tolerance, so the
#:   judge never claims a precision the reading does not have.
#:
#: The declared 1e-6 is the lab's descriptive scale: on a curved wall the exact
#: tangent arrangements of the collection leave only a sliver of the polygon's
#: excess uncovered -- measured at 5.9e-7 of the arena for one square of side 2
#: on a unit disc, and the same for the two-square optimum ``r = 2 - sqrt(2)``.
#: The containment and overlap predicates stay exact and are not given this
#: tolerance. A real gap is of the order of a shape's own area -- an arena
#: divided by the shape count -- so it is never hidden by either bound.
COVERAGE_TOLERANCE = 1e-6


class RotationMode(str, Enum):
    """How a shape is allowed to rotate inside its problem."""

    FIXED = "fixed"
    DISCRETE = "discrete"
    FREE = "free"


@dataclass(frozen=True)
class Violation:
    """One concrete way a candidate breaks a constraint."""

    kind: str
    message: str = ""
    shape_ids: tuple[str, ...] = ()
    magnitude: float = 0.0

    def to_dict(self) -> JSON:
        """Return the JSON representation."""
        return {
            "kind": self.kind,
            "message": self.message,
            "shape_ids": list(self.shape_ids),
            "magnitude": self.magnitude,
        }

    @staticmethod
    def from_dict(data: JSON) -> Violation:
        """Decode a violation from its JSON representation."""
        return Violation(
            kind=str(require(data, "kind", "violation")),
            message=str(data.get("message", "")),
            shape_ids=tuple(str(shape_id) for shape_id in data.get("shape_ids", [])),
            magnitude=as_float(data.get("magnitude", 0.0), "violation.magnitude"),
        )


@dataclass(frozen=True)
class ConstraintResult:
    """The verdict of one constraint on one candidate."""

    constraint: str
    valid: bool
    violations: tuple[Violation, ...] = ()
    severity: float = 0.0
    message: str = ""

    @staticmethod
    def ok(constraint: str, message: str = "") -> ConstraintResult:
        """Return a passing result."""
        return ConstraintResult(constraint=constraint, valid=True, message=message)

    @staticmethod
    def failed(constraint: str, violations: tuple[Violation, ...], message: str = "") -> ConstraintResult:
        """Return a failing result whose severity is the total violation magnitude."""
        return ConstraintResult(
            constraint=constraint,
            valid=False,
            violations=violations,
            severity=float(sum(violation.magnitude for violation in violations)),
            message=message,
        )

    def to_dict(self) -> JSON:
        """Return the JSON representation."""
        return {
            "constraint": self.constraint,
            "valid": self.valid,
            "severity": self.severity,
            "message": self.message,
            "violations": [violation.to_dict() for violation in self.violations],
        }

    @staticmethod
    def from_dict(data: JSON) -> ConstraintResult:
        """Decode a result from its JSON representation."""
        return ConstraintResult(
            constraint=str(require(data, "constraint", "constraint_result")),
            valid=bool(require(data, "valid", "constraint_result")),
            violations=tuple(
                Violation.from_dict(violation) for violation in data.get("violations", [])
            ),
            severity=as_float(data.get("severity", 0.0), "constraint_result.severity"),
            message=str(data.get("message", "")),
        )


class Constraint(ABC):
    """Abstract requirement a candidate must satisfy."""

    #: Discriminator used in JSON documents.
    kind: ClassVar[str]

    @abstractmethod
    def evaluate(self, facts: Facts) -> ConstraintResult:
        """Judge one candidate, reading the geometry already computed for it."""

    @abstractmethod
    def to_dict(self) -> JSON:
        """Return the JSON representation, including the ``type`` discriminator."""

    def describe(self) -> str:
        """One-line description for logs, prompts and the UI."""
        return self.kind

    @staticmethod
    def from_dict(data: JSON) -> Constraint:
        """Decode a constraint from its JSON representation."""
        return discriminated("constraint", _CONSTRAINT_BUILDERS, data, "constraint")


@dataclass(frozen=True)
class ArenaContainment(Constraint):
    """Every shape must lie inside the arena, holes excluded."""

    kind: ClassVar[str] = "arena_containment"

    def evaluate(self, facts: Facts) -> ConstraintResult:
        violations = tuple(
            Violation(
                kind="outside_arena",
                shape_ids=(containment.shape_id,),
                magnitude=containment.overflow_area,
                message=containment.message,
            )
            for containment in facts.containment
            if not containment.inside
        )
        if not violations:
            return ConstraintResult.ok(self.kind, f"all {facts.candidate.n_shapes} shapes are inside the arena")
        return ConstraintResult.failed(
            self.kind, violations, f"{len(violations)} shape(s) leave the arena"
        )

    def to_dict(self) -> JSON:
        return {"type": self.kind}


@dataclass(frozen=True)
class NonOverlap(Constraint):
    """No two shapes may share area; touching is allowed."""

    kind: ClassVar[str] = "non_overlap"

    def evaluate(self, facts: Facts) -> ConstraintResult:
        violations = tuple(
            Violation(
                kind="overlap",
                shape_ids=(overlap.first, overlap.second),
                magnitude=overlap.depth,
                message=(
                    f"{overlap.first} and {overlap.second} overlap by {overlap.depth:.6g}"
                ),
            )
            for overlap in facts.overlaps
        )
        if not violations:
            return ConstraintResult.ok(self.kind, "no two shapes overlap")
        return ConstraintResult.failed(
            self.kind, violations, f"{len(violations)} overlapping pair(s)"
        )

    def to_dict(self) -> JSON:
        return {"type": self.kind}


@dataclass(frozen=True)
class ArenaCovered(Constraint):
    """The arena must lie inside the union of the shapes' footprints.

    This is the one structural rule of a covering problem, and it replaces both
    of the packing pair: nothing constrains the copies to stay inside the arena
    (they stick out), and nothing stops them from overlapping each other (they
    usually do). What is required is that *every point* of the arena is inside at
    least one copy, which the engine reads as an area: the arena minus the union
    of the footprints.

    The verdict is an area comparison, so it is no more precise than the
    representation the area is read from. When the arena and every footprint are
    discs, that area is closed form and the verdict is exact up to
    :data:`COVERAGE_TOLERANCE`; otherwise a curved boundary is a circumscribed
    polygon and the reading carries its chord error, which
    :meth:`Facts.coverage_resolution` reports and the violation names. The
    declared threshold stays at :data:`COVERAGE_TOLERANCE` -- deliberately
    tighter than that resolution, because it is what reaches the pinned covering
    optima -- so the engine may refuse an arrangement that covers a curved wall
    to within the chord bound; it never *accepts* one claiming a precision it
    does not have. The violation carries the uncovered area as its magnitude, in
    the arena's square units, so a repair loop or an agent can read how much is
    still missing.
    """

    tolerance: float = COVERAGE_TOLERANCE
    kind: ClassVar[str] = "arena_covered"

    def __post_init__(self) -> None:
        if self.tolerance < 0.0:
            raise ValueError(f"coverage tolerance must not be negative, got {self.tolerance!r}")

    def evaluate(self, facts: Facts) -> ConstraintResult:
        # The decision threshold is the declared tolerance, deliberately tighter
        # than the reading's resolution on a curved wall (see the class
        # docstring): the pinned covering optima are reached with it. The
        # resolution is what the reading *is*, so the violation names it rather
        # than letting the threshold read as a claim of that precision.
        arena_area = facts.arena.area
        uncovered = facts.uncovered_area()
        allowed = self.tolerance * arena_area
        if uncovered <= allowed:
            return ConstraintResult.ok(
                self.kind,
                f"the shapes cover the whole arena to within {self.tolerance:g} of its area",
            )
        fraction = uncovered / arena_area if arena_area > 0.0 else 0.0
        return ConstraintResult.failed(
            self.kind,
            (
                Violation(
                    kind="uncovered_arena",
                    magnitude=uncovered,
                    message=(
                        f"{uncovered:.6g} of the {facts.arena.describe()} is left uncovered "
                        f"({fraction:.4g} of the arena area; reading resolution "
                        f"{facts.coverage_resolution():.1e} of the arena area)"
                    ),
                ),
            ),
            f"{uncovered:.6g} of the arena is not covered",
        )

    def describe(self) -> str:
        return f"cover the whole arena (tolerance {self.tolerance:g} of its area)"

    def to_dict(self) -> JSON:
        return {"type": self.kind, "tolerance": self.tolerance}


@dataclass(frozen=True)
class RequiredShapeCount(Constraint):
    """The candidate must place exactly ``count`` shapes (a fixed-count objective)."""

    count: int
    kind: ClassVar[str] = "required_shape_count"

    def __post_init__(self) -> None:
        if self.count < 1:
            raise ValueError(f"required shape count must be at least 1, got {self.count!r}")

    def evaluate(self, facts: Facts) -> ConstraintResult:
        placed = facts.candidate.n_shapes
        if placed == self.count:
            return ConstraintResult.ok(self.kind, f"{placed} shapes as required")
        return ConstraintResult.failed(
            self.kind,
            (
                Violation(
                    kind="wrong_shape_count",
                    magnitude=float(abs(placed - self.count)),
                    message=f"expected {self.count} shapes, found {placed}",
                ),
            ),
            f"expected {self.count} shapes, found {placed}",
        )

    def describe(self) -> str:
        return f"exactly {self.count} shapes"

    def to_dict(self) -> JSON:
        return {"type": self.kind, "count": self.count}


@dataclass(frozen=True)
class CommonScale(Constraint):
    """The candidate's common scale must be the one fixed by the objective."""

    scale: float
    tolerance: float = 1e-9
    kind: ClassVar[str] = "common_scale"

    def __post_init__(self) -> None:
        if not self.scale > 0.0:
            raise ValueError(f"common scale must be positive, got {self.scale!r}")

    def evaluate(self, facts: Facts) -> ConstraintResult:
        deviation = abs(facts.candidate.scale - self.scale)
        if deviation <= self.tolerance:
            return ConstraintResult.ok(self.kind, f"common scale is {self.scale:g}")
        return ConstraintResult.failed(
            self.kind,
            (
                Violation(
                    kind="wrong_common_scale",
                    magnitude=deviation,
                    message=f"expected scale {self.scale:g}, found {facts.candidate.scale:g}",
                ),
            ),
            f"expected scale {self.scale:g}, found {facts.candidate.scale:g}",
        )

    def describe(self) -> str:
        return f"common scale fixed at {self.scale:g}"

    def to_dict(self) -> JSON:
        return {"type": self.kind, "scale": self.scale, "tolerance": self.tolerance}


@dataclass(frozen=True)
class MinimumClearance(Constraint):
    """Shapes must stay at least ``distance`` apart, not merely not overlap."""

    distance: float
    kind: ClassVar[str] = "minimum_clearance"

    def __post_init__(self) -> None:
        if self.distance < 0.0:
            raise ValueError(f"minimum clearance must not be negative, got {self.distance!r}")

    def evaluate(self, facts: Facts) -> ConstraintResult:
        violations = tuple(
            Violation(
                kind="clearance_too_small",
                shape_ids=(clearance.first, clearance.second),
                magnitude=self.distance - clearance.distance,
                message=(
                    f"{clearance.first} and {clearance.second} are {clearance.distance:.6g} apart, "
                    f"less than {self.distance:g}"
                ),
            )
            for clearance in facts.clearances(slack=self.distance)
            if clearance.distance < self.distance
        )
        if not violations:
            return ConstraintResult.ok(self.kind, f"clearance of at least {self.distance:g} everywhere")
        return ConstraintResult.failed(
            self.kind, violations, f"{len(violations)} pair(s) below the required clearance"
        )

    def describe(self) -> str:
        return f"minimum clearance {self.distance:g}"

    def to_dict(self) -> JSON:
        return {"type": self.kind, "distance": self.distance}


@dataclass(frozen=True)
class RotationPolicy(Constraint):
    """Which rotations the shapes of a problem may use."""

    mode: RotationMode = RotationMode.FIXED
    angles: tuple[float, ...] = (0.0,)
    kind: ClassVar[str] = "rotation_policy"

    def __post_init__(self) -> None:
        if self.mode is RotationMode.DISCRETE and not self.angles:
            raise ValueError("a discrete rotation policy needs at least one allowed angle")

    def allows(self, rotation: float) -> bool:
        """Whether a single rotation, in degrees, is permitted."""
        if self.mode is RotationMode.FREE:
            return True
        if self.mode is RotationMode.FIXED:
            return abs(_normalise_angle(rotation) - _normalise_angle(self.angles[0])) <= ANGLE_TOLERANCE
        return any(
            abs(_normalise_angle(rotation) - _normalise_angle(angle)) <= ANGLE_TOLERANCE
            for angle in self.angles
        )

    def evaluate(self, facts: Facts) -> ConstraintResult:
        violations = tuple(
            Violation(
                kind="forbidden_rotation",
                shape_ids=(instance.shape_id,),
                magnitude=float(instance.rotation),
                message=f"{instance.shape_id} is rotated by {instance.rotation:g} degrees, which the policy forbids",
            )
            for instance in facts.instances
            if not self.allows(instance.rotation)
        )
        if not violations:
            return ConstraintResult.ok(self.kind, f"all rotations follow the {self.mode.value} policy")
        return ConstraintResult.failed(
            self.kind, violations, f"{len(violations)} shape(s) with a forbidden rotation"
        )

    def describe(self) -> str:
        if self.mode is RotationMode.FREE:
            return "free rotation"
        if self.mode is RotationMode.FIXED:
            return f"rotation fixed at {self.angles[0]:g} degrees"
        return f"rotation restricted to {', '.join(f'{angle:g}' for angle in self.angles)} degrees"

    def to_dict(self) -> JSON:
        return {"type": self.kind, "mode": self.mode.value, "angles": list(self.angles)}


def _normalise_angle(angle: float) -> float:
    """Fold an angle in degrees into ``[-180, 180)``."""
    return (angle + 180.0) % 360.0 - 180.0


_CONSTRAINT_BUILDERS = {
    ArenaContainment.kind: lambda payload: ArenaContainment(),
    NonOverlap.kind: lambda payload: NonOverlap(),
    ArenaCovered.kind: lambda payload: ArenaCovered(
        tolerance=as_float(payload.get("tolerance", COVERAGE_TOLERANCE), "constraint.tolerance")
    ),
    RequiredShapeCount.kind: lambda payload: RequiredShapeCount(
        count=as_int(require(payload, "count", "constraint.required_shape_count"), "constraint.count")
    ),
    CommonScale.kind: lambda payload: CommonScale(
        scale=as_float(require(payload, "scale", "constraint.common_scale"), "constraint.scale"),
        tolerance=as_float(payload.get("tolerance", 1e-9), "constraint.tolerance"),
    ),
    MinimumClearance.kind: lambda payload: MinimumClearance(
        distance=as_float(require(payload, "distance", "constraint.minimum_clearance"), "constraint.distance")
    ),
    RotationPolicy.kind: lambda payload: RotationPolicy(
        mode=RotationMode(str(require(payload, "mode", "constraint.rotation_policy"))),
        angles=tuple(
            as_float(angle, "constraint.rotation_policy.angles") for angle in payload.get("angles", [0.0])
        ),
    ),
}

__all__ = [
    "ANGLE_TOLERANCE",
    "COVERAGE_TOLERANCE",
    "ArenaContainment",
    "ArenaCovered",
    "CommonScale",
    "Constraint",
    "ConstraintResult",
    "MinimumClearance",
    "NonOverlap",
    "RequiredShapeCount",
    "RotationMode",
    "RotationPolicy",
    "Violation",
]
