"""A seeded generator of packing instances.

The lab needs more than four hand-written examples: a comparison between two
strategies is only convincing over a *family* of instances, and a family is only
usable if any of its members can be rebuilt from a number. This module draws a
problem from a seed and a small spec, and nothing else — the same seed and the
same spec give the same document, in any order, on any machine.

What it draws from is deliberately limited to what the domain already expresses:
the arena primitives the editor offers, and the shape families the catalogue
offers. A generated instance is therefore never a case the engine has not been
told about. Whether that instance is *solvable* is not this module's business —
the engine judges, and the instances nobody can solve are exactly the ones a test
suite asks for on purpose.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .arena import Arena
from .constraints import RotationMode, RotationPolicy
from .objectives import MaximizeCount, MaximizeScale
from .problem import Problem
from .serde import JSON, as_int, optional, require
from .shapes import PALETTE

#: Arena families the generator draws from. ``composite`` folds several
#: primitives together, which is what produces the arenas with holes.
ARENA_FAMILIES: tuple[str, ...] = ("rect", "disk", "regular_ngon", "composite")

#: Operations a composite arena may use to fold its next primitive in.
COMPOSITE_OPERATIONS: tuple[str, ...] = ("union", "difference", "intersection")

#: How many primitives a composite arena folds, the first one included.
COMPOSITE_SIZE: tuple[int, int] = (2, 4)

#: How many times a composite draw may be redrawn after the domain refuses it.
#: A difference that swallows the region it cuts into leaves nothing, and the
#: domain says so; redrawing is how the generator hears it instead of failing.
COMPOSITE_ATTEMPTS = 24

#: The shape families the catalogue offers, by the name a spec names them with.
PALETTE_BY_NAME = {name: shape for name, _label, shape in PALETTE}

#: The primitives a composite arena folds, in the order the generator draws them.
PRIMITIVE_FAMILIES: tuple[str, ...] = ("rect", "disk", "regular_ngon")

#: The rotation policies a generated problem may carry, by the mode's own value.
ROTATION_MODES: tuple[str, ...] = ("fixed", "discrete", "free")

#: Angles a discrete policy draws from, in degrees. They are the multiples of 15
#: that a person would try by hand, which keeps a generated instance readable.
DISCRETE_ANGLES: tuple[float, ...] = (15.0, 30.0, 45.0, 60.0, 90.0)


@dataclass(frozen=True)
class GeneratorSpec:
    """What to draw: the families to choose from, and the size of the instance.

    Both ends of every range are inclusive, and every choice is made from the
    seed alone, so the spec and the seed together name exactly one instance.
    """

    seed: int
    arenas: tuple[str, ...] = ARENA_FAMILIES
    shapes: tuple[str, ...] = tuple(PALETTE_BY_NAME)
    counts: tuple[int, int] = (4, 40)
    rotations: tuple[str, ...] = ("fixed",)
    objective: str = "maximize_scale"
    name_prefix: str = "generated"

    def __post_init__(self) -> None:
        for family in self.arenas:
            if family not in ARENA_FAMILIES:
                raise ValueError(
                    f"unknown arena family {family!r}; known families: {', '.join(ARENA_FAMILIES)}"
                )
        for name in self.shapes:
            if name not in PALETTE_BY_NAME:
                raise ValueError(
                    f"unknown shape family {name!r}; known families: "
                    f"{', '.join(PALETTE_BY_NAME)}"
                )
        for mode in self.rotations:
            if mode not in ROTATION_MODES:
                raise ValueError(
                    f"unknown rotation mode {mode!r}; known modes: {', '.join(ROTATION_MODES)}"
                )
        if self.objective not in ("maximize_scale", "maximize_count"):
            raise ValueError(
                f"unknown objective {self.objective!r}; known objectives: "
                "maximize_scale, maximize_count"
            )
        low, high = self.counts
        if low < 1 or high < low:
            raise ValueError(f"counts must be a non-empty range of at least one, got {self.counts!r}")

    def to_dict(self) -> JSON:
        """Return the spec as JSON, which is how a generated file records its recipe."""
        return {
            "seed": self.seed,
            "arenas": list(self.arenas),
            "shapes": list(self.shapes),
            "counts": list(self.counts),
            "rotations": list(self.rotations),
            "objective": self.objective,
            "name_prefix": self.name_prefix,
        }

    @staticmethod
    def from_dict(data: JSON) -> GeneratorSpec:
        """Decode a spec from its JSON representation."""
        counts = require(data, "counts", "spec")
        return GeneratorSpec(
            seed=as_int(require(data, "seed", "spec"), "spec.seed"),
            arenas=tuple(str(name) for name in optional(data, "arenas", ARENA_FAMILIES)),
            shapes=tuple(str(name) for name in optional(data, "shapes", list(PALETTE_BY_NAME))),
            counts=(as_int(counts[0], "spec.counts"), as_int(counts[1], "spec.counts")),
            rotations=tuple(str(mode) for mode in optional(data, "rotations", ["fixed"])),
            objective=str(optional(data, "objective", "maximize_scale")),
            name_prefix=str(optional(data, "name_prefix", "generated")),
        )


def generate(spec: GeneratorSpec) -> Problem:
    """Return the problem the spec names, reproducible from its seed alone.

    The draws happen in a fixed order — arena, shape family, count, rotation,
    objective — so that the spec and the seed determine the instance exactly.
    Changing the spec changes it, which is why a generated problem records the
    spec it came from in its own metadata: an instance whose recipe was lost
    would be an instance nobody can rebuild.
    """
    rng = np.random.default_rng(spec.seed)
    arena, arena_family = _draw_arena(spec, rng)
    shape_name = spec.shapes[int(rng.integers(len(spec.shapes)))]
    shape = PALETTE_BY_NAME[shape_name]
    count = int(rng.integers(spec.counts[0], spec.counts[1] + 1))
    rotation = _draw_rotation(spec, rng)
    objective: MaximizeScale | MaximizeCount = (
        MaximizeScale(count=count)
        if spec.objective == "maximize_scale"
        else MaximizeCount(scale=1.0)
    )
    problem_id = f"{spec.name_prefix}-{spec.seed}-{arena_family}-{shape_name}-{count}"
    return Problem(
        problem_id=problem_id,
        arena=arena,
        shape=shape,
        objective=objective,
        rotation=rotation,
        seed=spec.seed,
        name=problem_id,
        description=f"generated from seed {spec.seed}: {shape.describe()} in {arena.describe()}",
        metadata={"generator": spec.to_dict()},
    )


def _draw_rotation(spec: GeneratorSpec, rng: np.random.Generator) -> RotationPolicy:
    """Return the rotation policy the spec allows and the seed picked."""
    mode = spec.rotations[int(rng.integers(len(spec.rotations)))]
    if mode == "discrete":
        # Two to three allowed angles, drawn without replacement from the ones a
        # person would try by hand and kept in order: the policy is a set, and a
        # set that reads in ascending order is easier to compare between runs.
        how_many = int(rng.integers(2, 4))
        chosen = rng.choice(len(DISCRETE_ANGLES), size=how_many, replace=False)
        angles = tuple(sorted(float(DISCRETE_ANGLES[int(index)]) for index in chosen))
        return RotationPolicy(mode=RotationMode.DISCRETE, angles=angles)
    return RotationPolicy(mode=RotationMode(mode), angles=(0.0,))


def _draw_arena(spec: GeneratorSpec, rng: np.random.Generator) -> tuple[Arena, str]:
    """Return the arena the spec allows and the seed picked, with its family name.

    A composite draw is redrawn while the domain refuses it: folding a primitive
    into its predecessor can leave nothing, and the domain's own refusal is what
    the loop listens to rather than a test written here.
    """
    family = spec.arenas[int(rng.integers(len(spec.arenas)))]
    if family == "composite":
        for _ in range(COMPOSITE_ATTEMPTS):
            try:
                return _composite(spec, rng), family
            except (ValueError, TypeError):
                continue
        raise ValueError(
            f"a composite arena could not be drawn in {COMPOSITE_ATTEMPTS} attempts; "
            "widen the spec's arena families or use another seed"
        )
    return _primitive(family, rng), family


def _primitive(family: str, rng: np.random.Generator) -> Arena:
    """Return one arena from the seed: a rectangle, a disc, or a regular polygon."""
    if family == "rect":
        return Arena.rectangle(
            width=float(rng.uniform(4.0, 14.0)), height=float(rng.uniform(4.0, 14.0))
        )
    if family == "disk":
        return Arena.disk(radius=float(rng.uniform(3.0, 8.0)))
    if family == "regular_ngon":
        return Arena.regular_polygon(
            sides=int(rng.integers(3, 9)), circumradius=float(rng.uniform(3.0, 8.0))
        )
    raise ValueError(f"no primitive family is named {family!r}")


def _composite(spec: GeneratorSpec, rng: np.random.Generator) -> Arena:
    """Return a stack of primitives folded into one another, starting from a rectangle.

    The base is always a rectangle: a stack has to begin somewhere, and a
    rectangle is the only primitive every reader already knows the size of. The
    operations afterwards are drawn from :data:`COMPOSITE_OPERATIONS`, which is
    what makes an arena with a hole — a bar to pack around, rather than a box.
    """
    arena = Arena.rectangle(width=float(rng.uniform(6.0, 12.0)), height=float(rng.uniform(6.0, 12.0)))
    folds = int(rng.integers(COMPOSITE_SIZE[0], COMPOSITE_SIZE[1] + 1)) - 1
    for _ in range(folds):
        operation = COMPOSITE_OPERATIONS[int(rng.integers(len(COMPOSITE_OPERATIONS)))]
        primitive = _primitive(PRIMITIVE_FAMILIES[int(rng.integers(len(PRIMITIVE_FAMILIES)))], rng)
        arena = getattr(arena, operation)(primitive)
    return arena
