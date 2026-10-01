"""What a packing tries to achieve, and how it is scored.

Two objectives cover the whole MVP and both make the primary score a single
increasing number, which is what lets an algorithmic baseline, a human editing
by hand and a team of agents be compared without translation:

``maximize_scale``
    ``N`` shapes are placed, and their common scale is maximised. The score moves
    continuously, which makes progress visible at every iteration.
``maximize_count``
    The common scale is fixed, and the number of placed shapes is maximised.
``minimize_container``
    A fixed number of unit shapes are placed freely, and the container that
    encloses them is made as small as possible. Here the region is the *answer*
    rather than the question: nothing constrains the shapes to an arena, the
    engine measures what the arrangement occupies, and the objective asks for
    that measurement to fall.
``cover_region``
    The arena is the *target*, and a fixed number of copies cover it at the
    smallest common scale. The score is the reciprocal of that scale, so it is
    the size of the largest target the copies cover at their unit size -- which
    is the number the covering pages of the reference collection publish. Its
    copies overlap and stick out by definition, so it has no containment and no
    non-overlap rule: its one structural requirement is that the union of the
    footprints contains the whole arena.
``maximize_total_perimeter``
    A fixed number of copies of *independent* sizes are packed inside the arena,
    and the sum of their perimeters is maximised. The common scale is fixed at
    one -- every placement carries its own local scale, which is the family's one
    degree of freedom -- so the score is the total perimeter the engine builds.
    With the reference collection's unit copies (a circle of radius 1, a regular
    polygon of side 1) the sum of the local scales is exactly the number the
    pages print, the sum of the radii or of the sides. Unlike a covering, the
    copies still stay inside the arena and never share area, so the structural
    pair applies unchanged.

The objective also declares the constraints it implies — a fixed-count objective
requires exactly that many shapes — so that a candidate of the wrong shape is
reported as a violation rather than silently scored.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar

from .constraints import (
    ArenaContainment,
    ArenaCovered,
    CommonScale,
    Constraint,
    NonOverlap,
    RequiredShapeCount,
)
from .serde import JSON, as_float, as_int, discriminated, require

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .candidate import Candidate
    from .problem import Problem


@dataclass(frozen=True)
class ObjectiveScore:
    """The value of a candidate under one objective.

    ``primary`` always increases with quality, so comparing two candidates is a
    plain ``>``. ``secondary`` carries descriptive numbers for the UI, the logs
    and the prompts; it never takes part in the comparison.
    """

    primary: float
    label: str
    secondary: Mapping[str, float] = field(default_factory=dict)

    def is_better_than(self, other: ObjectiveScore) -> bool:
        """Whether this score beats ``other`` on the primary value."""
        return self.primary > other.primary

    def to_dict(self) -> JSON:
        """Return the JSON representation."""
        return {"primary": self.primary, "label": self.label, "secondary": dict(self.secondary)}

    @staticmethod
    def from_dict(data: JSON) -> ObjectiveScore:
        """Decode a score from its JSON representation."""
        return ObjectiveScore(
            primary=as_float(require(data, "primary", "objective_score"), "objective_score.primary"),
            label=str(require(data, "label", "objective_score")),
            secondary={str(key): float(value) for key, value in data.get("secondary", {}).items()},
        )

    def __str__(self) -> str:
        return f"{self.label}={self.primary:.6g}"


class Objective(ABC):
    """Abstract goal of a packing problem."""

    #: Discriminator used in JSON documents.
    kind: ClassVar[str]

    #: Metric the interface puts in front of the others, when the engine has it.
    promoted_metric: ClassVar[str] = "density"

    @abstractmethod
    def evaluate(
        self,
        problem: Problem,
        candidate: Candidate,
        measurements: Mapping[str, float] | None = None,
    ) -> ObjectiveScore:
        """Score one candidate. Validity is the engine's business, not the objective's.

        ``measurements`` carries what the engine measured on the arrangement and
        what the domain cannot compute by itself — the size of the container that
        encloses every shape, for the objective that minimises it. An objective
        that scores from the arrangement rather than from a field of the
        candidate raises when it is not given them, because scoring it from a
        guess would be worse than refusing.
        """

    @abstractmethod
    def constraints(self, problem: Problem) -> tuple[Constraint, ...]:
        """Return the constraints this objective implies for the whole problem."""

    @property
    def enclosing_container(self) -> str | None:
        """Container the engine measures around the arrangement, or ``None``.

        This is the objective's one geometric request: the engine answers it by
        measuring, never by guessing, and hands the measurement back to
        :meth:`evaluate`. An objective that reads a field of the candidate has
        nothing to ask for.
        """
        return None

    @property
    def covered_target(self) -> str | None:
        """Target shape the engine derives from the union of the copies, or ``None``.

        The twin of :attr:`enclosing_container`: an objective whose region is the
        largest target *inside* the arrangement asks for it here, and the engine
        answers with the measured region and its size. An objective that reads a
        declared arena, or a container around the shapes, has nothing to ask for.
        """
        return None

    @property
    def derives_region(self) -> bool:
        """Whether the objective's own measurement, not the problem, is the region.

        A problem carries an arena so that a candidate can be judged against it.
        An objective that measures a container around the shapes, or the largest
        target inside their union, has no such region to declare — it has one to
        compute — and a problem must not claim both, or a reader of the file would
        believe an arena that nothing reads.
        """
        return self.enclosing_container is not None or self.covered_target is not None

    @property
    def arena_is_fixed(self) -> bool:
        """Whether the declared arena is part of the problem's definition.

        Some families ask a question *about* their region rather than merely
        packing into it: a covering's arena is the target the copies must cover,
        and a total-perimeter packing's arena is the container the source
        publishes. Editing such an arena would change the question, so the engine
        reports it as fixed and the interface keeps it read-only. A family whose
        arena is only the sandbox the user chose — maximising a common scale or a
        count — leaves this False and its arena editable. An objective that
        derives its region from the arrangement (:attr:`derives_region`) has no
        declared arena to fix in the first place.
        """
        return False

    def structural_constraints(self, problem: Problem) -> tuple[Constraint, ...]:
        """Return the constraints that make a candidate a packing at all.

        The default is what every arrangement so far has obeyed: the shapes stay
        inside the arena and never overlap. An objective whose *question* is the
        region — minimising the container around the shapes — replaces the first
        one, because there is no arena to be inside of; what is left is the rule
        that two shapes never share area.
        """
        return (ArenaContainment(), NonOverlap())

    @abstractmethod
    def to_dict(self) -> JSON:
        """Return the JSON representation, including the ``type`` discriminator."""

    def preset_count(self) -> int | None:
        """Number of shapes the objective fixes, or ``None`` when it is free."""
        return None

    def preset_scale(self) -> float | None:
        """Common scale the objective fixes, or ``None`` when it is free."""
        return None

    def describe(self) -> str:
        """One-line description for logs, prompts and the UI."""
        return self.kind

    @staticmethod
    def from_dict(data: JSON) -> Objective:
        """Decode an objective from its JSON representation."""
        return discriminated("objective", _OBJECTIVE_BUILDERS, data, "objective")


@dataclass(frozen=True)
class MaximizeScale(Objective):
    """Place exactly ``count`` shapes and maximise their common scale."""

    count: int
    kind: ClassVar[str] = "maximize_scale"
    promoted_metric: ClassVar[str] = "common_scale"

    def __post_init__(self) -> None:
        if self.count < 1:
            raise ValueError(f"maximize_scale needs at least one shape, got {self.count!r}")

    def evaluate(
        self,
        problem: Problem,
        candidate: Candidate,
        measurements: Mapping[str, float] | None = None,
    ) -> ObjectiveScore:
        # ``measurements`` is ignored: this objective scores a field of the
        # candidate, and the engine measures the arrangement for the family that
        # has no such field.
        scale = candidate.scale
        return ObjectiveScore(
            primary=scale,
            label="common_scale",
            secondary={
                "shape_area": problem.shape.area(scale),
                "inradius": problem.shape.inradius(scale),
                "circumradius": problem.shape.circumradius(scale),
                "n_shapes": float(candidate.n_shapes),
            },
        )

    def constraints(self, problem: Problem) -> tuple[Constraint, ...]:
        return (RequiredShapeCount(self.count),)

    def preset_count(self) -> int | None:
        return self.count

    def describe(self) -> str:
        return f"maximise the common scale of {self.count} shapes"

    def to_dict(self) -> JSON:
        return {"type": self.kind, "count": self.count}


@dataclass(frozen=True)
class MaximizeCount(Objective):
    """Place as many shapes as possible at a fixed common scale."""

    scale: float
    kind: ClassVar[str] = "maximize_count"
    promoted_metric: ClassVar[str] = "n_shapes"

    def __post_init__(self) -> None:
        if not self.scale > 0.0:
            raise ValueError(f"maximize_count needs a positive scale, got {self.scale!r}")

    def evaluate(
        self,
        problem: Problem,
        candidate: Candidate,
        measurements: Mapping[str, float] | None = None,
    ) -> ObjectiveScore:
        # See MaximizeScale.evaluate: the measurements belong to another family.
        return ObjectiveScore(
            primary=float(candidate.n_shapes),
            label="shape_count",
            secondary={
                "scale": self.scale,
                "shape_area": problem.shape.area(self.scale),
                "inradius": problem.shape.inradius(self.scale),
            },
        )

    def constraints(self, problem: Problem) -> tuple[Constraint, ...]:
        return (CommonScale(self.scale),)

    def preset_scale(self) -> float | None:
        return self.scale

    def describe(self) -> str:
        return f"maximise the number of shapes at common scale {self.scale:g}"

    def to_dict(self) -> JSON:
        return {"type": self.kind, "scale": self.scale}


#: Containers a ``minimize_container`` objective can enclose its shapes in.
#:
#: The square is the axis-aligned box of the arrangement: a maximum over extents,
#: exact and free. The circle is the smallest circle through every corner and every
#: centre (``geometry.facts.minimal_enclosing_circle``), exact too while the shapes
#: share a size, which is what one family places. The other containers of the
#: reference collection — a regular pentagon, a domino, an L, a tan — may be turned
#: around the arrangement, and the smallest of *those* is an optimisation of its own:
#: they become containers the day that search is written, and not before, rather
#: than a fixed orientation dressed up as a measurement.
CONTAINERS = ("square", "circle")


@dataclass(frozen=True)
class MinimizeContainer(Objective):
    """Place exactly ``count`` unit shapes, and minimise the container around them.

    The container is derived, never declared: the engine measures the axis-aligned
    box of the arrangement, takes its longest side, centres a square of that side
    on it, and the score is the reciprocal of that side — so the primary still
    grows with quality, and one ranking still orders every objective of the lab.
    The reciprocal of the side is also exactly the common scale of the same
    problem read on a unit arena, which is what makes the two readings of a
    minimal-enclosure problem comparable number for number.

    ``RequiredShapeCount`` fixes how many shapes are placed and ``CommonScale``
    fixes their size, so the only thing a solver can do is move them.
    """

    count: int
    container: str = "square"
    kind: ClassVar[str] = "minimize_container"
    promoted_metric: ClassVar[str] = "container_side"
    """The measurement this family puts in front: the side, or the radius for a circle."""

    def __post_init__(self) -> None:
        if self.count < 1:
            raise ValueError(f"minimize_container needs at least one shape, got {self.count!r}")
        if self.container not in CONTAINERS:
            raise ValueError(
                f"unknown container {self.container!r}; known containers: "
                f"{', '.join(CONTAINERS)}"
            )
        # Which number leads the panel follows the container, not the class: a circle
        # problem has no container_side to show, and a panel left promoting it would
        # fall back to density and hide the radius the family asks to read.
        object.__setattr__(self, "promoted_metric", self.size_measurement)

    @property
    def enclosing_container(self) -> str | None:
        return self.container

    @property
    def size_measurement(self) -> str:
        """Name of the engine measurement this objective scores."""
        return f"container_{'side' if self.container == 'square' else 'radius'}"

    def evaluate(
        self,
        problem: Problem,
        candidate: Candidate,
        measurements: Mapping[str, float] | None = None,
    ) -> ObjectiveScore:
        size = None if measurements is None else measurements.get(self.size_measurement)
        if size is None:
            raise ValueError(
                f"{self.kind} is scored from the engine's measurement "
                f"{self.size_measurement!r}; score it through the engine"
            )
        # An arrangement with no shape encloses nothing, and the count constraint
        # reports it as invalid anyway; a zero primary keeps the ranking defined.
        primary = 0.0 if size <= 0.0 else 1.0 / size
        return ObjectiveScore(
            primary=primary,
            label="container_scale",
            secondary={
                "container_size": float(size),
                "shape_area": problem.shape.area(1.0),
                "n_shapes": float(candidate.n_shapes),
            },
        )

    def constraints(self, problem: Problem) -> tuple[Constraint, ...]:
        return (RequiredShapeCount(self.count), CommonScale(1.0))

    def structural_constraints(self, problem: Problem) -> tuple[Constraint, ...]:
        return (NonOverlap(),)

    def preset_count(self) -> int | None:
        return self.count

    def preset_scale(self) -> float | None:
        return 1.0

    def describe(self) -> str:
        # "At scale 1" rather than "unit": the objective fixes the common scale at one,
        # and a family's natural size is its own — a circle of radius 1 is two units
        # across — so naming the scale is the honest sentence for every family.
        return f"minimise the {self.container} containing {self.count} shapes at scale 1"

    def to_dict(self) -> JSON:
        return {"type": self.kind, "count": self.count, "container": self.container}


@dataclass(frozen=True)
class CoverRegion(Objective):
    """Cover the arena with exactly ``count`` shapes, at the smallest common scale.

    This is the covering family of the reference collection read in this lab's
    frame. The source asks for the largest region a fixed number of unit copies
    can cover; normalised, the arena *is* that region at its published unit size
    (a unit disc of radius 1, a unit triangle or square of side 1), the copies are
    ``count`` shapes of one family at a common scale, free to rotate, and the
    objective minimises that scale. The primary score is its reciprocal, so it
    grows with quality like every other objective here, and it equals the
    published number exactly: one unit square covering a unit disc needs scale 2,
    and the score comes back as the published radius 1/2.

    Unlike a packing, a covering has **neither containment nor non-overlap**: the
    copies lie over the region and typically overlap each other, and some of them
    stick out. :meth:`structural_constraints` therefore returns nothing at all --
    the rotation policy is the only rule the problem adds on top -- and the one
    requirement of the family, :class:`ArenaCovered`, arrives as an objective
    constraint beside the fixed count.

    The panel promotes ``covered_size``, the reciprocal of the scale: the size of
    the largest target the copies cover, the number the source publishes. The
    search interval the initialisers and the interface ask for is derived by
    :func:`paper_obs.geometry.bounds.scale_bounds`, which documents the two
    bounds -- the area a covering cannot beat below, and a scale at which a
    covering is certain.
    """

    count: int
    kind: ClassVar[str] = "cover_region"
    promoted_metric: ClassVar[str] = "covered_size"

    def __post_init__(self) -> None:
        if self.count < 1:
            raise ValueError(f"cover_region needs at least one shape, got {self.count!r}")

    def evaluate(
        self,
        problem: Problem,
        candidate: Candidate,
        measurements: Mapping[str, float] | None = None,
    ) -> ObjectiveScore:
        # See MaximizeScale.evaluate: the measurements belong to another family.
        scale = candidate.scale
        # An empty arrangement covers nothing and the count constraint reports it;
        # a zero primary keeps the ranking defined rather than dividing by zero.
        primary = 0.0 if scale <= 0.0 else 1.0 / scale
        return ObjectiveScore(
            primary=primary,
            label="covered_size",
            secondary={
                "common_scale": scale,
                "shape_area": problem.shape.area(scale),
                "n_shapes": float(candidate.n_shapes),
            },
        )

    def constraints(self, problem: Problem) -> tuple[Constraint, ...]:
        return (RequiredShapeCount(self.count), ArenaCovered())

    def structural_constraints(self, problem: Problem) -> tuple[Constraint, ...]:
        # A covering is not a packing: ArenaContainment and NonOverlap would both
        # reject the very arrangements the family is about, so neither applies.
        return ()

    @property
    def arena_is_fixed(self) -> bool:
        # The arena *is* the target: it is what the copies are asked to cover, so
        # rewriting it rewrites the question rather than the answer.
        return True

    def preset_count(self) -> int | None:
        return self.count

    def describe(self) -> str:
        return (
            f"cover the arena with {self.count} shapes at the smallest common scale"
        )

    def to_dict(self) -> JSON:
        return {"type": self.kind, "count": self.count}


#: Target shapes the derived covering reading names.
#:
#: ``circle`` is the largest disc the union of the copies contains, read from the
#: pole of inaccessibility; ``square`` is the largest axis-aligned square, found by
#: a bounded deterministic scan; ``triangle`` is the largest equilateral triangle
#: of fixed orientation -- one edge horizontal, apex up -- found by the same kind of
#: scan, which tests the whole triangle against the union rather than its three
#: vertices. Each of the three is a lower bound on the tested grid, never an
#: over-estimate, and the measured size is the side length for a triangle.
COVER_TARGETS = ("circle", "square", "triangle")


@dataclass(frozen=True)
class MaximizeCoveredSize(Objective):
    """Derive the largest target the union of the copies contains, and maximise it.

    This is the twin reading of :class:`CoverRegion` -- the same duality as
    ``minimize_container`` against ``maximize_scale``. ``cover_region`` fixes the
    target as its arena and shrinks ``count`` copies until they cover it; here the
    copies are fixed at their unit size (the common scale is pinned at 1) and the
    target is *derived from the union of their footprints*: the largest target of
    ``target``'s family that lies entirely inside that union, its orientation
    fixed. The score is that derived size, a length -- the radius of a disc, the
    side of a square, the side of an equilateral triangle. Overlapping copies
    therefore shrink the target, which is the interactive reading of the covering
    question, while spreading them grows it.

    The copies are free to overlap and to stick out, so there is no structural
    constraint at all: :meth:`structural_constraints` returns nothing, and the
    objective adds only the fixed count and the fixed common scale. The target is
    measured in the geometry layer and handed back as ``Facts.arena``, so the
    canvas draws the derived shape and the panel shows the derived size.

    The fixed reading stays exactly where it was: ``cover_region`` is what the
    catalogue's published numbers are read from, and this twin does not replace it.
    """

    count: int
    target: str = "circle"
    kind: ClassVar[str] = "maximize_covered_size"
    promoted_metric: ClassVar[str] = "covered_size"
    """The derived size, in the units the source prints for that target family."""

    def __post_init__(self) -> None:
        if self.count < 1:
            raise ValueError(f"maximize_covered_size needs at least one shape, got {self.count!r}")
        if self.target not in COVER_TARGETS:
            raise ValueError(
                f"unknown cover target {self.target!r}; known targets: "
                f"{', '.join(COVER_TARGETS)}"
            )

    @property
    def covered_target(self) -> str | None:
        return self.target

    def evaluate(
        self,
        problem: Problem,
        candidate: Candidate,
        measurements: Mapping[str, float] | None = None,
    ) -> ObjectiveScore:
        size = None if measurements is None else measurements.get(self.promoted_metric)
        if size is None:
            raise ValueError(
                "maximize_covered_size is scored from the engine's measurement "
                "'covered_size'; score it through the engine"
            )
        # An empty union scores zero and its count constraint reports it invalid;
        # a zero primary keeps the ranking defined.
        return ObjectiveScore(
            primary=float(size),
            label="covered_size",
            secondary={
                "common_scale": candidate.scale,
                "n_shapes": float(candidate.n_shapes),
            },
        )

    def constraints(self, problem: Problem) -> tuple[Constraint, ...]:
        return (RequiredShapeCount(self.count), CommonScale(1.0))

    def structural_constraints(self, problem: Problem) -> tuple[Constraint, ...]:
        # A derived covering is a union, not a packing: the copies may overlap and
        # stick out, and the target is measured inside that union, so neither
        # containment nor non-overlap has anything to say.
        return ()

    def preset_count(self) -> int | None:
        return self.count

    def preset_scale(self) -> float | None:
        return 1.0

    def describe(self) -> str:
        return (
            f"maximise the largest {self.target} contained in the union of "
            f"{self.count} unit shapes"
        )

    def to_dict(self) -> JSON:
        return {"type": self.kind, "count": self.count, "target": self.target}


@dataclass(frozen=True)
class MaximizeTotalPerimeter(Objective):
    """Pack fixed-size copies of independent sizes, and maximise their perimeters.

    This is the reference collection's "Packing Copies to Maximize Total
    Perimeter" family read in this lab's frame. The source packs ``count`` copies
    of *independent* sizes into a container at its own unit length -- a unit
    square, a unit circle, a unit triangle, a unit pentagon -- and prints the
    largest sum of their radii (circles) or of their sides (regular polygons).
    The degree of freedom is therefore not one common scale but each copy's own
    size, which the model already carries:
    :attr:`paper_obs.domain.placement.Placement.scale` is the local scale the
    engine builds that copy at, and :meth:`Placement.resolved_scale` falls back to
    the candidate's common scale only when it is absent.

    The common scale is fixed at **1**, through :class:`CommonScale` like any
    other objective that pins it, so the interface's scale control reads a fixed
    value and every copy's size lives on its placement. The primary score is the
    total perimeter the engine builds -- a length that grows with quality like
    every other objective here, so one ranking still orders the whole lab. The
    promoted metric is ``total_scale``, the sum of the copies' local scales: with
    the source's unit copies that sum *is* the number the page prints, ``Σ r`` for
    circles and ``Σ s`` for regular polygons, while the primary is that number
    times the unit copy's own perimeter (``2*pi`` for a circle of radius 1, the
    side count for a regular polygon of side 1). The interface therefore shows the
    published sum directly, and a reader can compare it card for card.

    A total-perimeter packing is still a packing: the copies stay inside the arena
    and never share area, so :meth:`structural_constraints` keeps the structural
    pair -- which is exactly what separates this family from a covering. Its own
    constraints add the fixed count and the fixed common scale.
    """

    count: int
    kind: ClassVar[str] = "maximize_total_perimeter"
    promoted_metric: ClassVar[str] = "total_scale"

    def __post_init__(self) -> None:
        if self.count < 1:
            raise ValueError(
                f"maximize_total_perimeter needs at least one shape, got {self.count!r}"
            )

    def total_scale(self, candidate: Candidate) -> float:
        """Return the sum of the copies' resolved scales.

        It is the source's own printed quantity for the unit copies of that
        collection, and the objective computes it from the candidate alone so the
        score never depends on which measurements a caller happened to ask for.
        """
        return float(
            sum(placement.resolved_scale(candidate.scale) for placement in candidate.placements)
        )

    def evaluate(
        self,
        problem: Problem,
        candidate: Candidate,
        measurements: Mapping[str, float] | None = None,
    ) -> ObjectiveScore:
        # See MaximizeScale.evaluate: the measurements belong to the container
        # family. The total is exact and costs one pass over the placements.
        total_scale = self.total_scale(candidate)
        return ObjectiveScore(
            primary=problem.shape.perimeter(1.0) * total_scale,
            label="total_perimeter",
            secondary={
                "total_scale": total_scale,
                "unit_perimeter": problem.shape.perimeter(1.0),
                "n_shapes": float(candidate.n_shapes),
            },
        )

    def constraints(self, problem: Problem) -> tuple[Constraint, ...]:
        return (RequiredShapeCount(self.count), CommonScale(1.0))

    @property
    def arena_is_fixed(self) -> bool:
        # The copies move *inside* the container the source publishes, and the
        # structural pair keeps them there; the container is part of the question,
        # so it is fixed like a covering's target.
        return True

    def preset_count(self) -> int | None:
        return self.count

    def preset_scale(self) -> float | None:
        # The common scale is a constraint of the family, reported to the
        # interface so its scale control shows the fixed value rather than
        # offering to search a number nothing reads.
        return 1.0

    def describe(self) -> str:
        return (
            f"maximise the total perimeter of {self.count} shapes sized freely "
            "inside the arena (common scale fixed at 1)"
        )

    def to_dict(self) -> JSON:
        return {"type": self.kind, "count": self.count}


_OBJECTIVE_BUILDERS = {
    MinimizeContainer.kind: lambda payload: MinimizeContainer(
        count=as_int(
            require(payload, "count", "objective.minimize_container"), "objective.count"
        ),
        container=str(payload.get("container", "square")),
    ),
    MaximizeScale.kind: lambda payload: MaximizeScale(
        count=as_int(require(payload, "count", "objective.maximize_scale"), "objective.count")
    ),
    MaximizeCount.kind: lambda payload: MaximizeCount(
        scale=as_float(require(payload, "scale", "objective.maximize_count"), "objective.scale")
    ),
    CoverRegion.kind: lambda payload: CoverRegion(
        count=as_int(require(payload, "count", "objective.cover_region"), "objective.count")
    ),
    MaximizeCoveredSize.kind: lambda payload: MaximizeCoveredSize(
        count=as_int(
            require(payload, "count", "objective.maximize_covered_size"), "objective.count"
        ),
        target=str(payload.get("target", "circle")),
    ),
    MaximizeTotalPerimeter.kind: lambda payload: MaximizeTotalPerimeter(
        count=as_int(
            require(payload, "count", "objective.maximize_total_perimeter"), "objective.count"
        )
    ),
}

#: Every objective a problem may declare, by its ``type`` in a problem document.
OBJECTIVE_KINDS: tuple[str, ...] = tuple(_OBJECTIVE_BUILDERS)

__all__ = [
    "CONTAINERS",
    "COVER_TARGETS",
    "OBJECTIVE_KINDS",
    "CoverRegion",
    "MaximizeCount",
    "MaximizeCoveredSize",
    "MaximizeScale",
    "MaximizeTotalPerimeter",
    "MinimizeContainer",
    "Objective",
    "ObjectiveScore",
]
