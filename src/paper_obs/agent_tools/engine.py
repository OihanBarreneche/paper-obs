"""The engine, as tools a LangChain agent can call.

Every tool is a plain LangChain tool bound to one run's :class:`Workbench`: it reads the
arrangement under work, or replaces it with the one an operator of :mod:`paper_obs.search`
proposes, and answers the engine's verdict. A tool never judges anything itself.

A tool returns a string — a compact JSON document, or a sentence saying why it refused.
Nothing raises: a model that calls a tool wrongly reads the reason and tries again.
"""

from __future__ import annotations

import functools
import json
import multiprocessing
from collections.abc import Callable, Iterator
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Literal, NamedTuple

import numpy as np
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from paper_obs.domain.candidate import Candidate, new_candidate_id
from paper_obs.domain.placement import Placement
from paper_obs.domain.problem import Problem
from paper_obs.geometry.bounds import scale_bounds
from paper_obs.geometry.engine import Evaluation, analyze, evaluate, facts_for, inspect_shape
from paper_obs.geometry.transforms import rotate_selection
from paper_obs.search import operators

#: Objectives whose common scale is the free variable, rather than fixed by the problem.
FREE_SCALE = {"maximize_scale", "cover_region"}

#: The one objective that gives each shape its own size.
FREE_SIZES = "maximize_total_perimeter"

#: Violations and conflicts a reply lists before it only counts the rest.
LISTED = 12


class Judged(NamedTuple):
    """An arrangement and the engine's verdict on it."""

    candidate: Candidate
    evaluation: Evaluation


@dataclass
class Workbench:
    """What the tools of one run share: the arrangement under work and the best ones found.

    The run rebuilds its tools every turn, all bound to this one object, so the geometry lives
    here, where every tool reaches it, rather than in a graph channel holding a second copy.
    """

    problem: Problem
    candidate: Candidate | None = None
    #: The best valid arrangement of the whole run, kept as the tools produce arrangements:
    #: ``restore_best`` returns to it within the very turn that wandered off.
    best: Judged | None = None
    #: The best valid arrangement of the turn under way, which the trace records for that turn.
    turn_best: Judged | None = None
    #: The reason the agent gave when it ended the run, or None while the run goes on.
    gave_up: str | None = None
    #: Every arrangement produced, by identifier, so the trace can show what each call made.
    snapshots: dict[str, dict[str, Any]] = field(default_factory=dict)


class Spot(BaseModel):
    """Where one shape goes."""

    x: float = Field(description="world x of the shape centre")
    y: float = Field(description="world y of the shape centre")
    rotation: float = Field(default=0.0, description="degrees, counter-clockwise; 0 when omitted")
    size: float | None = Field(
        default=None,
        description="this shape's own size, only where the objective sizes shapes one by one",
    )


class Move(BaseModel):
    """A change to a shape that is already placed; what is left out is kept."""

    shape_id: str
    x: float | None = None
    y: float | None = None
    rotation: float | None = None
    size: float | None = Field(
        default=None,
        description="this shape's own size, only where the objective sizes shapes one by one",
    )


def problem_facts(problem: Problem) -> dict[str, Any]:
    """Return what the problem asks, without reading any candidate."""
    try:
        bounds = scale_bounds(problem)
        interval: dict[str, Any] = {"low": bounds.low, "high": bounds.high}
    except TypeError as error:
        interval = {"note": str(error)}
    return {
        "problem_id": problem.problem_id,
        "region": problem.describe_region(),
        "arena": None if problem.arena is None else problem.arena.to_dict(),
        "shape": problem.shape.describe(),
        "objective": problem.objective.describe(),
        "count": problem.objective.preset_count(),
        "scale_interval": interval,
    }


def _json(document: Any) -> str:
    """Return the compact JSON a tool hands back to a model."""
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"), default=str)


def _round(value: float) -> float:
    """Round a reported length or angle: six decimals are far below what a model can place."""
    return round(float(value), 6)


def _report(problem: Problem, candidate: Candidate, evaluation: Evaluation) -> dict[str, Any]:
    """Return the lean answer of a geometry tool: did it hold, how good is it, and where is it."""
    sized = problem.objective.kind == FREE_SIZES
    violations = evaluation.validation.violations
    report: dict[str, Any] = {
        "candidate_id": candidate.candidate_id,
        "valid": evaluation.valid,
        # Every engine score is oriented so that larger is better — for a container objective
        # that means a smaller container. Said once per verdict, because it is read every time.
        "score": evaluation.primary,
        "score_label": evaluation.score.label,
        "larger_is_better": True,
        "measure": {evaluation.promoted_metric: evaluation.metrics.get(evaluation.promoted_metric)},
        "scale": candidate.scale,
        "violations": [item.to_dict() for item in violations[:LISTED]],
        "shape_columns": ["id", "x", "y", "rotation", *(["size"] if sized else [])],
        "shapes": [
            [item.shape_id, _round(item.x), _round(item.y), _round(item.rotation),
             *([_round(item.resolved_scale(candidate.scale))] if sized else [])]
            for item in candidate.placements
        ],
    }
    if len(violations) > LISTED:
        report["violations_not_listed"] = len(violations) - LISTED
    return report


def describe_state(bench: Workbench) -> dict[str, Any]:
    """Return the arrangement under work with its verdict, its conflicts and the run's best."""
    problem, candidate = bench.problem, bench.candidate
    assert candidate is not None
    facts = facts_for(problem, candidate)
    state = _report(problem, candidate, evaluate(problem, candidate))
    state["overlaps"] = [
        [item.first, item.second, _round(item.depth), [_round(v) for v in item.direction]]
        for item in facts.overlaps[:LISTED]
    ]
    state["outside"] = [
        [item.shape_id, [_round(v) for v in item.inward]]
        for item in facts.containment if item.inward is not None
    ][:LISTED]
    if bench.best is not None:
        state["run_best"] = {
            "candidate_id": bench.best.candidate.candidate_id,
            "score": bench.best.evaluation.primary,
        }
    return state


def _adopt(bench: Workbench, candidate: Candidate) -> str:
    """Put a produced arrangement under work, keep it when it is a best, and answer its verdict."""
    bench.candidate = candidate
    bench.snapshots[candidate.candidate_id] = candidate.to_dict()
    evaluation = evaluate(bench.problem, candidate)
    if evaluation.valid:
        if bench.best is None or evaluation.is_better_than(bench.best.evaluation):
            bench.best = Judged(candidate, evaluation)
        if bench.turn_best is None or evaluation.is_better_than(bench.turn_best.evaluation):
            bench.turn_best = Judged(candidate, evaluation)
    return _json(_report(bench.problem, candidate, evaluation))


def _placements(problem: Problem, raw: list[Spot], *, first: int = 0) -> tuple[Placement, ...]:
    """Build placements from what the model wrote, naming the shapes ourselves."""
    return tuple(
        Placement(
            shape_id=f"s{first + index:03d}", x=item.x, y=item.y, rotation=item.rotation,
            scale=_size(problem, item.size),
        )
        for index, item in enumerate(raw)
    )


def _size(problem: Problem, size: float | None) -> float | None:
    """Return a shape's own size, refusing one the objective has no use for."""
    if size is not None and problem.objective.kind != FREE_SIZES:
        raise ValueError(
            "every shape of this problem has the common size; `size` is only for an "
            "objective that sizes shapes one by one"
        )
    return size


def _common_scale(bench: Workbench, asked: float | None) -> float:
    """Return the common scale to build at: what was asked where it is free, else the current one."""
    fixed = bench.problem.objective.preset_scale()
    if asked is not None and fixed is not None and abs(asked - fixed) > 1e-12:
        raise ValueError(
            f"this problem fixes the common scale at {fixed:g}; leave `scale` out"
            + (" and give each shape its own `size`" if bench.problem.objective.kind == FREE_SIZES else "")
        )
    if asked is not None:
        return float(asked)
    if bench.candidate is not None:
        return bench.candidate.scale
    return 1.0 if fixed is None else float(fixed)


def _next_number(candidate: Candidate | None) -> int:
    """Return the first free shape number, so an added shape never collides."""
    highest = -1
    for shape_id in () if candidate is None else candidate.shape_ids:
        if shape_id.startswith("s") and shape_id[1:].isdigit():
            highest = max(highest, int(shape_id[1:]))
    return highest + 1


def _rng(bench: Workbench, seed: int | None) -> np.random.Generator:
    """Return the generator of a call: the seed asked for, else one drawn from the run so far.

    The default is the problem's seed and the number of arrangements the run has produced, so
    a replayed run draws the same numbers and two calls of one turn still draw different ones.
    """
    if seed is not None:
        return np.random.default_rng(seed)
    base = 0 if bench.problem.seed is None else int(bench.problem.seed)
    return np.random.default_rng([base, len(bench.snapshots)])


#: The worker processes the tools' operators run in, while :func:`worker_processes` holds them.
_workers: ProcessPoolExecutor | None = None


@contextmanager
def worker_processes(count: int | None = None) -> Iterator[None]:
    """Run every tool's operator in a pool of worker processes while the block lasts.

    Agents working at once, such as a workflow's parallel explorers, are threads of one Python
    interpreter, which computes for one thread at a time: their tools would share one core. A
    worker process of its own gives each computation a core. Workers start when first needed,
    up to ``count`` (the machine's cores by default), and stop with the block.
    """
    global _workers
    try:
        with ProcessPoolExecutor(max_workers=count, mp_context=multiprocessing.get_context("spawn")) as _workers:
            yield
    finally:
        _workers = None


def _computed(operator: Callable[..., Candidate], *arguments: Any, **options: Any) -> Candidate:
    """Return what an operator produces, computed in a worker process when a pool is set up."""
    if _workers is None:
        return operator(*arguments, **options)
    return _workers.submit(operator, *arguments, **options).result()


def engine_tools(bench: Workbench) -> list[BaseTool]:
    """Return every tool of the engine, bound to the run's working candidate."""
    problem = bench.problem

    def producer(needs_candidate: bool) -> Callable[[Callable[..., Candidate]], BaseTool]:
        """Make a tool from a function that returns the next arrangement.

        The shared part of every geometry tool lives here: refuse once the run is over or when
        there is nothing to change yet, turn an operator's refusal into a sentence, and adopt
        and judge what it returns.
        """

        def decorate(function: Callable[..., Candidate]) -> BaseTool:
            @functools.wraps(function)
            def run(**arguments: Any) -> str:
                if bench.gave_up is not None:
                    return "this run is over: geometry is no longer accepted."
                if needs_candidate and bench.candidate is None:
                    return "there is no arrangement yet: place or seed one first."
                try:
                    return _adopt(bench, function(**arguments))
                except (KeyError, ValueError) as error:
                    return str(error)

            return tool(run)

        return decorate

    edits = producer(needs_candidate=True)
    builds = producer(needs_candidate=False)

    @tool
    def read_state() -> str:
        """The arrangement under work and the engine's verdict on it, with every conflict.

        Each overlap comes with its depth and the unit direction that separates the pair, and
        each shape that leaves the arena with the translation that brings it back inside.
        """
        if bench.candidate is None:
            return "there is no arrangement yet: place or seed one first."
        return _json(describe_state(bench))

    @tool
    def read_voids(limit: int = 5) -> str:
        """The empty regions of the arena, largest first: where there is still room.

        For a covering, an empty region is a part of the target no copy covers yet.
        """
        if bench.candidate is None:
            return "there is no arrangement yet: place or seed one first."
        return _json(analyze(problem, bench.candidate, void_limit=limit).to_dict())

    @tool
    def inspect_neighborhood(shape_id: str, distance: float = 5.0, limit: int = 8) -> str:
        """One shape's margin to the arena wall, its overlaps with directions, and nearby gaps."""
        if bench.candidate is None:
            return "there is no arrangement yet: place or seed one first."
        try:
            return _json(inspect_shape(problem, bench.candidate, shape_id, distance=distance, limit=limit))
        except (KeyError, ValueError) as error:
            return str(error)

    @builds
    def place_shapes(placements: list[Spot], scale: float | None = None) -> Candidate:
        """Replace the whole arrangement with these placements and judge it.

        Give one spot per shape; the shapes are named s000, s001, ... for you. Use this for a
        fresh idea and edit_shapes to adjust what is there. `scale` is the common scale, only
        where the objective leaves it free.
        """
        common = _common_scale(bench, scale)
        if bench.candidate is None:
            return Candidate(
                candidate_id=new_candidate_id("placed"), problem_id=problem.problem_id,
                scale=common, placements=_placements(problem, placements), origin="place_shapes",
            )
        return bench.candidate.derive(
            placements=_placements(problem, placements), scale=common, origin="place_shapes"
        )

    @edits
    def edit_shapes(
        move: list[Move] | None = None,
        add: list[Spot] | None = None,
        remove: list[str] | None = None,
        scale: float | None = None,
    ) -> Candidate:
        """Move, turn, resize, add or drop shapes of the arrangement, and judge the result.

        Anything left out is kept as it is. `scale` is the common scale, only where the
        objective leaves it free.
        """
        current = bench.candidate
        doomed = set(remove or [])
        by_id = {item.shape_id: item for item in current.placements if item.shape_id not in doomed}
        for change in move or []:
            if change.shape_id not in by_id:
                raise ValueError(
                    f"the arrangement holds no shape {change.shape_id!r}; it holds "
                    f"{', '.join(sorted(by_id)) or 'none'}"
                )
            before = by_id[change.shape_id]
            by_id[change.shape_id] = Placement(
                shape_id=before.shape_id,
                x=before.x if change.x is None else change.x,
                y=before.y if change.y is None else change.y,
                rotation=before.rotation if change.rotation is None else change.rotation,
                scale=before.scale if change.size is None else _size(problem, change.size),
            )
        added = _placements(problem, add or [], first=_next_number(current))
        return current.derive(
            placements=(*by_id.values(), *added), scale=_common_scale(bench, scale),
            origin="edit_shapes",
        )

    @builds
    def seed(pattern: Literal["grid", "hexagonal", "varied", "cover"] = "grid") -> Candidate:
        """Replace the arrangement with a construction, and judge it.

        grid: an axis-aligned lattice, for any problem. hexagonal: a staggered lattice of
        discs. varied: one large shape and the rest smaller, for an objective that sizes shapes
        one by one. cover: copies laid over the target until they cover it, for a covering.
        """
        if pattern == "grid":
            return _computed(operators.grid_initialize, problem)
        if pattern == "hexagonal":
            if not problem.shape.is_circle:
                raise ValueError("the hexagonal seed places discs only")
            return _computed(operators.staggered_initialize, problem)
        if pattern == "varied":
            if problem.objective.kind != FREE_SIZES:
                raise ValueError("the varied seed is for an objective that sizes shapes one by one")
            return _computed(operators.varied_initialize, problem)
        return _computed(operators.cover_initialize, problem)

    @edits
    def move_cluster(shape_ids: list[str], dx: float = 0.0, dy: float = 0.0, rotation: float = 0.0) -> Candidate:
        """Move a named group of shapes together, keeping its internal arrangement.

        `rotation`, in degrees, first turns the group about its own centre.
        """
        moved = bench.candidate
        if rotation:
            moved = rotate_selection(problem, moved, tuple(shape_ids), rotation)
        if dx or dy:
            moved = _computed(operators.translate_cluster, problem, moved, shape_ids=shape_ids, dx=dx, dy=dy)
        return moved.derive(origin="move_cluster")

    @edits
    def repair(iterations: int = 40) -> Candidate:
        """Push overlapping shapes apart and bring overflowing shapes back inside the arena.

        Along the directions the engine reports, pass after pass while the conflicts shrink.
        It can grow a measured container: validity comes first.
        """
        return _computed(
            operators.repair_overlaps, problem, bench.candidate, iterations=iterations, origin="repair",
        )

    @edits
    def relax_local(
        iterations: int = 20, amplitude: float = 0.05, turn_degrees: float = 0.0,
        seed: int | None = None,
    ) -> Candidate:
        """Shake a quarter of the shapes at a time and keep only what the engine ranks higher.

        `amplitude` is the largest move, in world units; `turn_degrees` also turns the shaken
        shapes, where rotation is free.
        """
        return _computed(
            operators.local_relax,
            problem, bench.candidate, iterations=iterations, amplitude=amplitude,
            turn=turn_degrees, generator=_rng(bench, seed),
        )

    @edits
    def polish(iterations: int = 40, seed: int | None = None) -> Candidate:
        """Tune the arrangement you hold without changing its idea, and keep only improvements.

        A short local search with the move this objective needs: it repairs a broken start,
        then squeezes a container, stretches a common scale, trades size between shapes, or
        shifts a covering. Choose the arrangement; let this find its last digits. Each call
        takes a few seconds; call it again to go further.
        """
        return _computed(
            operators.polish, problem, bench.candidate, iterations=iterations, generator=_rng(bench, seed),
        )

    @edits
    def fit_scale() -> Candidate:
        """Set the common scale to the best one the engine accepts for these positions.

        The largest for a scale objective, the smallest that still covers for a covering.
        """
        kind = problem.objective.kind
        if kind == "maximize_scale":
            return _computed(operators.increase_scale, problem, bench.candidate)
        if kind == "cover_region":
            return _computed(operators.fit_cover_scale, problem, bench.candidate)
        raise ValueError("this problem fixes the common scale: there is nothing to fit")

    @edits
    def grow_sizes(shape_id: str | None = None) -> Candidate:
        """Enlarge one shape's own size, or every shape's together, as far as the engine accepts.

        Name a shape to grow that one alone; leave it out to grow the whole arrangement,
        keeping its proportions.
        """
        return _computed(operators.grow_sizes, problem, bench.candidate, shape_id=shape_id)

    @edits
    def fill_void(
        void_index: int = 0, move_shape_id: str | None = None, trials: int = 24,
        seed: int | None = None,
    ) -> Candidate:
        """Try positions in a numbered empty region: add a shape, or move a named one there."""
        return _computed(
            operators.fill_void,
            problem, bench.candidate, void_index=void_index, move_shape_id=move_shape_id,
            trials=trials, generator=_rng(bench, seed),
        )

    @edits
    def remove_overlapping(count: int, seed: int | None = None) -> Candidate:
        """Drop shapes, preferring the ones the engine reports as overlapping."""
        return _computed(operators.remove_shapes, problem, bench.candidate, count=count, generator=_rng(bench, seed))

    @tool
    def restore_best() -> str:
        """Return to the best valid arrangement this run has reached."""
        if bench.gave_up is not None:
            return "this run is over: geometry is no longer accepted."
        if bench.best is None:
            return "there is no valid arrangement to restore yet."
        bench.candidate = bench.best.candidate
        return _json(_report(problem, *bench.best))

    @tool
    def give_up(reason: str) -> str:
        """End the whole run, not only this turn: nothing left is worth trying. Say why."""
        bench.gave_up = reason
        return "the run ends here: nothing better will be proposed."

    return [
        read_state, read_voids, inspect_neighborhood, place_shapes, edit_shapes, seed,
        move_cluster, repair, relax_local, polish, fit_scale, grow_sizes, fill_void,
        remove_overlapping, restore_best, give_up,
    ]


def offered(kind: str) -> set[str]:
    """Return the names of the tools that make sense for an objective, and no others.

    Every tool offered is one more schema in every model call and one more thing to choose
    between, so a problem gets only the levers its objective can use.
    """
    names = {
        "read_state", "place_shapes", "edit_shapes", "seed", "move_cluster", "relax_local",
        "polish", "restore_best", "give_up",
    }
    if kind not in {"cover_region", "maximize_covered_size"}:
        names |= {"repair", "inspect_neighborhood"}
    if kind in FREE_SCALE:
        names.add("fit_scale")
    if kind in {"maximize_scale", "maximize_count", FREE_SIZES, "cover_region"}:
        names.add("read_voids")
    if kind == "maximize_count":
        names |= {"fill_void", "remove_overlapping"}
    if kind == FREE_SIZES:
        names.add("grow_sizes")
    return names


def basic_agent_tools(bench: Workbench) -> list[BaseTool]:
    """Return the tools the basic agent loop offers on this problem: see :func:`offered`."""
    names = offered(bench.problem.objective.kind)
    return [item for item in engine_tools(bench) if item.name in names]


__all__ = [
    "Judged", "Move", "Spot", "Workbench", "basic_agent_tools", "describe_state", "engine_tools",
    "offered", "problem_facts",
]
