"""The engine's tools as a model reads them, for an interface that lists them.

Each entry is a tool's own name, docstring and argument schema, converted exactly as a chat
model receives them, so the list follows the code. The one thing written by hand is an
example per tool — a small problem, the calls that set it up and the arguments a model could
send — and even there the reply shown is the tool's real answer, played when the list is asked
for.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.utils.function_calling import convert_to_openai_tool

from paper_obs.domain import (
    Arena,
    Circle,
    MaximizeCount,
    MaximizeScale,
    MaximizeTotalPerimeter,
    MinimizeContainer,
    Problem,
    RegularPolygon,
    RotationMode,
    RotationPolicy,
)
from paper_obs.domain.objectives import OBJECTIVE_KINDS

from .engine import Workbench, engine_tools
from .sandbox import sandbox_tools

FREE = RotationPolicy(mode=RotationMode.FREE)

#: The small problems the examples are played on.
PROBLEMS: dict[str, Problem] = {
    "pentagons": Problem(
        "example-pentagons", None, RegularPolygon(sides=5), MinimizeContainer(count=3),
        rotation=FREE, seed=1,
    ),
    "discs": Problem("example-discs", Arena.rectangle(10.0, 10.0), Circle(), MaximizeScale(count=4), seed=1),
    "count": Problem("example-count", Arena.rectangle(6.0, 6.0), Circle(), MaximizeCount(scale=2.0), seed=1),
    "sizes": Problem(
        "example-sizes", Arena.disk(1.0), Circle(radius=1.0), MaximizeTotalPerimeter(count=3),
        rotation=FREE, seed=1,
    ),
}

Calls = tuple[tuple[str, dict[str, Any]], ...]

#: Three pentagons in a row; the second and the third overlap.
ROW: Calls = (("place_shapes", {"placements": [{"x": -1.7, "y": 0.0}, {"x": 0.0, "y": 0.0}, {"x": 1.4, "y": 0.0}]}),)
#: The same row with the third pentagon moved clear: valid, and loose.
APART: Calls = (*ROW, ("edit_shapes", {"move": [{"shape_id": "s002", "x": 1.9}]}))
#: Four discs far apart at a small common scale: valid, and loose.
LOOSE: Calls = (("place_shapes", {"scale": 2.0, "placements": [
    {"x": -2.5, "y": -2.5}, {"x": 2.5, "y": -2.5}, {"x": -2.5, "y": 2.5}, {"x": 2.5, "y": 2.5},
]}),)
#: One disc of the fixed size in its corner of the square.
ONE: Calls = (("place_shapes", {"placements": [{"x": -1.5, "y": -1.5}]}),)
#: Three small discs, each with its own size.
SMALL: Calls = (("place_shapes", {"placements": [
    {"x": -0.5, "y": 0.0, "size": 0.2}, {"x": 0.5, "y": 0.0, "size": 0.2}, {"x": 0.0, "y": 0.5, "size": 0.2},
]}),)


@dataclass(frozen=True)
class Example:
    """A call a model could make, on one of the problems above, after the calls that set it up."""

    caption: str
    problem: str
    arguments: dict[str, Any]
    before: Calls = ()


EXAMPLES: dict[str, Example] = {
    "read_state": Example(
        "Three pentagons to pack into the smallest square; the second and third overlap.",
        "pentagons", {}, ROW),
    "read_voids": Example(
        "Discs of a fixed size in a 6 × 6 square, one placed so far: where is there room?",
        "count", {"limit": 3}, ONE),
    "inspect_neighborhood": Example(
        "The same three pentagons: look around the middle one.",
        "pentagons", {"shape_id": "s001"}, ROW),
    "place_shapes": Example(
        "Four discs in a 10 × 10 square, all at one common scale; nothing is placed yet.",
        "discs", {"scale": 2.4, "placements": [
            {"x": -2.4, "y": -2.4}, {"x": 2.4, "y": -2.4}, {"x": -2.4, "y": 2.4}, {"x": 2.4, "y": 2.4},
        ]}),
    "edit_shapes": Example(
        "The three pentagons: move the third one to the right and turn it by 36°.",
        "pentagons", {"move": [{"shape_id": "s002", "x": 1.9, "rotation": 36}]}, ROW),
    "seed": Example(
        "Four discs in a 10 × 10 square: start from a staggered lattice.",
        "discs", {"pattern": "hexagonal"}),
    "move_cluster": Example(
        "The three pentagons: shift the first two to the left together.",
        "pentagons", {"shape_ids": ["s000", "s001"], "dx": -0.4}, ROW),
    "repair": Example(
        "The three pentagons, two of them overlapping: separate them.",
        "pentagons", {"iterations": 20}, ROW),
    "relax_local": Example(
        "Three pentagons set apart: shake and turn them, keeping only what shrinks their square.",
        "pentagons", {"iterations": 20, "amplitude": 0.2, "turn_degrees": 20, "seed": 1}, APART),
    "polish": Example(
        "The three overlapping pentagons: repair them, then squeeze their square.",
        "pentagons", {"iterations": 8, "seed": 1}, ROW),
    "fit_scale": Example(
        "Four loose discs: take the largest common scale their positions allow.",
        "discs", {}, LOOSE),
    "grow_sizes": Example(
        "Three small discs sized one by one in a unit disc: grow the third one alone.",
        "sizes", {"shape_id": "s002"}, SMALL),
    "fill_void": Example(
        "Discs of a fixed size in a 6 × 6 square, one placed: add one in the largest void.",
        "count", {"void_index": 0, "seed": 1}, ONE),
    "remove_overlapping": Example(
        "Three discs of a fixed size, two of them overlapping: drop one.",
        "count", {"count": 1, "seed": 1},
        (("place_shapes", {"placements": [{"x": -1.5, "y": -1.5}, {"x": -0.8, "y": -1.5}, {"x": 1.5, "y": 1.5}]}),)),
    "restore_best": Example(
        "Four discs: a valid arrangement, then a move that makes two overlap; go back.",
        "discs", {}, (*LOOSE, ("edit_shapes", {"move": [{"shape_id": "s001", "x": -2.0}]}))),
    "give_up": Example(
        "The pentagons, after several turns that all ended on the same square.",
        "pentagons", {"reason": "Every row and tilt I tried squeezes back to the same square."}, ROW),
}


def catalog(menu: Callable[[str], set[str]], *, sandbox: bool = False) -> dict[str, Any]:
    """Return every engine tool as a model reads it, and the objectives whose menu offers it.

    ``menu`` names the tools a workflow offers on one objective; ``sandbox`` adds the Python
    sandbox, offered on every objective. The tools are built on a placeholder problem: what a
    model reads of a tool does not depend on the problem, only which tools it is offered does.
    """
    placeholder = Workbench(problem=Problem("catalog", Arena.rectangle(1.0, 1.0), Circle(), MaximizeScale(count=1)))
    extra = sandbox_tools(placeholder) if sandbox else []
    tools = []
    for item in [*engine_tools(placeholder), *extra]:
        read = convert_to_openai_tool(item)["function"]
        tools.append({
            "name": item.name,
            "description": paragraphs(read.get("description", "")),
            "parameters": read.get("parameters", {}),
            "objectives": [kind for kind in OBJECTIVE_KINDS if item in extra or item.name in menu(kind)],
            "example": played(item.name),
        })
    return {"objectives": list(OBJECTIVE_KINDS), "tools": tools}


@functools.cache
def played(name: str) -> dict[str, Any] | None:
    """Return a tool's example with the reply the tool really gives, or None without one.

    Played once per process: polishing takes a second, and the answer only changes with the
    code.
    """
    example = EXAMPLES.get(name)
    if example is None:
        return None
    bench = Workbench(problem=PROBLEMS[example.problem])
    tools = {item.name: item for item in engine_tools(bench)}
    for call, arguments in example.before:
        tools[call].invoke(arguments)
    reply = tools[name].invoke(example.arguments)
    return {
        "caption": example.caption,
        "arguments": example.arguments,
        "reply": str(reply),
    }


def paragraphs(text: str) -> list[str]:
    """Return a docstring's paragraphs, each on one line, as an interface lays them out."""
    return [" ".join(block.split()) for block in inspect.cleandoc(text).split("\n\n") if block.strip()]


__all__ = ["EXAMPLES", "PROBLEMS", "Example", "catalog", "paragraphs", "played"]
