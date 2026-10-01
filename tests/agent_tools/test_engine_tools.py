"""The agent's tools, called the way a model calls them, on every objective of the lab.

Each test invokes a LangChain tool with the arguments a model would write, then asks the
engine — never the tool's own reply alone — whether the arrangement it left behind is the
one that was asked for. The problems are small so that the battery stays fast.
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
import pytest

pytest.importorskip("langchain")

from langchain_core.tools import BaseTool

from paper_obs.agent_tools.catalog import catalog
from paper_obs.agent_tools.engine import Workbench, basic_agent_tools, engine_tools, offered, worker_processes
from paper_obs.domain import (
    Arena,
    Candidate,
    Circle,
    CoverRegion,
    MaximizeCount,
    MaximizeCoveredSize,
    MaximizeScale,
    MaximizeTotalPerimeter,
    MinimizeContainer,
    Placement,
    Problem,
    RegularPolygon,
    RotationMode,
    RotationPolicy,
    new_candidate_id,
    square,
)
from paper_obs.geometry import evaluate
from paper_obs.geometry.engine import facts_for

SEED = 20260929
FREE = RotationPolicy(mode=RotationMode.FREE)

PROBLEMS: dict[str, Problem] = {
    "maximize_scale": Problem(
        "tools-scale", Arena.rectangle(10.0, 10.0), Circle(), MaximizeScale(count=4), seed=SEED,
    ),
    "maximize_count": Problem(
        "tools-count", Arena.rectangle(6.0, 6.0), Circle(), MaximizeCount(scale=2.0), seed=SEED,
    ),
    "minimize_container": Problem(
        "tools-container", None, RegularPolygon(sides=5), MinimizeContainer(count=3),
        rotation=FREE, seed=SEED,
    ),
    "cover_region": Problem(
        "tools-cover", Arena.disk(1.0), square(), CoverRegion(count=2), rotation=FREE, seed=SEED,
    ),
    "maximize_covered_size": Problem(
        "tools-covered", None, square(), MaximizeCoveredSize(count=3), rotation=FREE, seed=SEED,
    ),
    "maximize_total_perimeter": Problem(
        "tools-perimeter", Arena.disk(1.0), Circle(radius=1.0), MaximizeTotalPerimeter(count=3),
        rotation=FREE, seed=SEED,
    ),
}

#: A start each objective can clearly improve on: valid, but loose.
LOOSE: dict[str, tuple[float, list[tuple[float, float, float, float | None]]]] = {
    "maximize_scale": (3.0, [(-2.5, -2.5, 0, None), (2.5, -2.5, 0, None), (-2.5, 2.5, 0, None), (2.5, 2.5, 0, None)]),
    "maximize_count": (2.0, [(0.0, 0.0, 0, None)]),
    "minimize_container": (1.0, [(-2.0, 0.0, 0, None), (0.0, 0.0, 0, None), (2.0, 0.0, 0, None)]),
    "cover_region": (3.0, [(-0.5, 0.0, 0, None), (0.5, 0.0, 0, None)]),
    # Three squares a little apart: gathered into an L, their union holds a larger disc.
    "maximize_covered_size": (1.0, [(0.0, 0.0, 0, None), (1.1, 0.0, 0, None), (0.0, 1.1, 0, None)]),
    "maximize_total_perimeter": (1.0, [(-0.5, 0.0, 0, 0.2), (0.5, 0.0, 0, 0.2), (0.0, 0.5, 0, 0.2)]),
}


def candidate(problem: Problem, scale: float, spots: list[tuple[float, float, float, float | None]]) -> Candidate:
    """Build an arrangement directly, as a model's earlier call would have left it."""
    return Candidate(
        candidate_id=new_candidate_id("test"), problem_id=problem.problem_id, scale=scale,
        placements=tuple(
            Placement(f"s{index:03d}", x, y, rotation, size)
            for index, (x, y, rotation, size) in enumerate(spots)
        ),
    )


def tools_for(problem: Problem, start: Candidate | None = None) -> tuple[Workbench, dict[str, BaseTool]]:
    """Return a fresh run's working state and every engine tool bound to it."""
    bench = Workbench(problem=problem, candidate=start)
    return bench, {item.name: item for item in engine_tools(bench)}


def call(tools: dict[str, BaseTool], name: str, **arguments: Any) -> Any:
    """Invoke a tool as an agent does, and read its JSON answer when it gave one."""
    answer = tools[name].invoke(arguments)
    assert isinstance(answer, str)
    try:
        return json.loads(answer)
    except json.JSONDecodeError:
        return answer


def rank(problem: Problem, arrangement: Candidate) -> tuple[float, float, float]:
    return evaluate(problem, arrangement, with_metrics=False).rank_key()


# -- the menu ---------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", PROBLEMS)
def test_every_objective_is_offered_the_levers_it_can_use_and_only_those(kind: str) -> None:
    names = {item.name for item in basic_agent_tools(Workbench(problem=PROBLEMS[kind]))}
    assert {"read_state", "place_shapes", "edit_shapes", "seed", "polish", "restore_best", "give_up"} <= names
    assert ("repair" in names) == (kind not in {"cover_region", "maximize_covered_size"})
    assert ("fit_scale" in names) == (kind in {"maximize_scale", "cover_region"})
    assert ("grow_sizes" in names) == (kind == "maximize_total_perimeter")
    assert ("fill_void" in names) == (kind == "maximize_count")


@pytest.mark.parametrize("kind", PROBLEMS)
def test_the_listed_catalogue_offers_each_objective_what_its_agent_receives(kind: str) -> None:
    """The interface's tool list is read from the catalogue: it must match the real menu."""
    listed = {
        item["name"] for item in catalog(offered)["tools"]
        if kind in item["objectives"]
    }
    assert listed == {item.name for item in basic_agent_tools(Workbench(problem=PROBLEMS[kind]))}
    assert set(PROBLEMS) == set(catalog(offered)["objectives"])


def test_every_tool_has_an_example_whose_reply_is_the_tools_own() -> None:
    """The viewer shows these replies as the tool's: none may be a refusal or an error."""
    for item in catalog(offered)["tools"]:
        example = item["example"]
        assert example is not None, item["name"]
        if item["name"] == "give_up":
            continue
        reply = json.loads(example["reply"])
        assert isinstance(reply, dict), (item["name"], example["reply"])


@pytest.mark.parametrize("kind", PROBLEMS)
def test_no_tool_raises_before_anything_is_placed(kind: str) -> None:
    """A model calls tools in any order; a tool that cannot act says so in a sentence."""
    arguments = {
        "inspect_neighborhood": {"shape_id": "s000"}, "place_shapes": {"placements": []},
        "move_cluster": {"shape_ids": ["s000"], "dx": 1.0}, "remove_overlapping": {"count": 1},
        "remember": {"note": "a note"}, "submit_solution": {"reason": "done"},
        "give_up": {"reason": "done"},
    }
    for name in [item.name for item in basic_agent_tools(Workbench(problem=PROBLEMS[kind]))]:
        _, tools = tools_for(PROBLEMS[kind])
        assert isinstance(tools[name].invoke(arguments.get(name, {})), str)


# -- reading ----------------------------------------------------------------------------------


def test_read_state_reports_every_conflict_with_the_direction_that_resolves_it() -> None:
    problem = PROBLEMS["maximize_scale"]
    broken = candidate(problem, 2.0, [(-1.0, 0.0, 0, None), (0.5, 0.0, 0, None),
                                      (-3.0, 3.0, 0, None), (4.5, 3.0, 0, None)])
    _, tools = tools_for(problem, broken)
    state = call(tools, "read_state")

    assert state["valid"] is False and evaluate(problem, broken).valid is False
    [(first, second, depth, direction)] = state["overlaps"]
    assert {first, second} == {"s000", "s001"}
    assert depth == pytest.approx(0.5, abs=1e-6)
    assert math.hypot(*direction) == pytest.approx(1.0, abs=1e-6)
    [(shape_id, inward)] = state["outside"]
    assert shape_id == "s003"
    # The reported translation is enough to bring the shape back to the wall.
    assert inward == pytest.approx([-0.5, 0.0], abs=1e-6)
    moved = call(tools, "edit_shapes", move=[{"shape_id": "s003", "x": 4.5 + inward[0], "y": 3.0 + inward[1]}])
    assert "s003" not in {name for item in moved["violations"] for name in item["shape_ids"]}


def test_a_verdict_carries_the_arrangement_it_judged() -> None:
    problem = PROBLEMS["maximize_total_perimeter"]
    start = candidate(problem, 1.0, LOOSE["maximize_total_perimeter"][1])
    bench, tools = tools_for(problem, start)
    state = call(tools, "read_state")

    assert state["shape_columns"] == ["id", "x", "y", "rotation", "size"]
    for (shape_id, x, y, rotation, size), placement in zip(state["shapes"], start.placements):
        assert shape_id == placement.shape_id
        assert (x, y, rotation, size) == pytest.approx((placement.x, placement.y, placement.rotation, placement.scale))
    assert state["score"] == pytest.approx(evaluate(problem, start).primary)


def test_read_voids_finds_the_room_a_count_can_still_use() -> None:
    problem = PROBLEMS["maximize_count"]
    _, tools = tools_for(problem, candidate(problem, 2.0, [(-2.0, 0.0, 0, None)]))
    voids = call(tools, "read_voids", limit=3)["voids"]
    assert voids and voids[0]["area"] > math.pi  # a whole disc of radius 1 still fits


# -- placing and editing ----------------------------------------------------------------------


def test_place_shapes_names_the_shapes_and_reports_the_engine_verdict() -> None:
    problem = PROBLEMS["maximize_scale"]
    bench, tools = tools_for(problem)
    spots = [{"x": x, "y": y} for x, y in ((-2.5, -2.5), (2.5, -2.5), (-2.5, 2.5), (2.5, 2.5))]
    report = call(tools, "place_shapes", placements=spots, scale=5.0)

    assert [row[0] for row in report["shapes"]] == ["s000", "s001", "s002", "s003"]
    verdict = evaluate(problem, bench.candidate)
    assert report["valid"] is verdict.valid is True
    assert report["score"] == pytest.approx(verdict.primary) == pytest.approx(5.0)


@pytest.mark.parametrize("kind", ["minimize_container", "maximize_total_perimeter", "maximize_count"])
def test_a_common_scale_the_problem_fixes_is_refused_and_nothing_changes(kind: str) -> None:
    bench, tools = tools_for(PROBLEMS[kind])
    answer = call(tools, "place_shapes", placements=[{"x": 0.0, "y": 0.0}], scale=3.0)
    assert isinstance(answer, str) and "fixes the common scale" in answer
    assert bench.candidate is None


def test_a_shape_size_is_accepted_only_where_the_objective_sizes_shapes_one_by_one() -> None:
    bench, tools = tools_for(PROBLEMS["maximize_total_perimeter"])
    report = call(tools, "place_shapes", placements=[
        {"x": -0.5, "y": 0.0, "size": 0.4}, {"x": 0.5, "y": 0.0, "size": 0.3}, {"x": 0.0, "y": 0.7, "size": 0.2},
    ])
    assert [item.scale for item in bench.candidate.placements] == [0.4, 0.3, 0.2]
    assert report["valid"] is True

    bench, tools = tools_for(PROBLEMS["minimize_container"])
    answer = call(tools, "place_shapes", placements=[{"x": 0.0, "y": 0.0, "size": 2.0}])
    assert isinstance(answer, str) and bench.candidate is None


def test_edit_shapes_changes_exactly_what_it_names() -> None:
    problem = PROBLEMS["maximize_scale"]
    start = candidate(problem, 3.0, LOOSE["maximize_scale"][1])
    bench, tools = tools_for(problem, start)
    call(tools, "edit_shapes", move=[{"shape_id": "s001", "x": 3.0, "rotation": 30.0}],
         add=[{"x": 0.0, "y": 0.0}], remove=["s003"])

    after = {item.shape_id: item for item in bench.candidate.placements}
    before = {item.shape_id: item for item in start.placements}
    assert set(after) == {"s000", "s001", "s002", "s004"}
    assert after["s000"] == before["s000"] and after["s002"] == before["s002"]
    assert (after["s001"].x, after["s001"].y, after["s001"].rotation) == (3.0, before["s001"].y, 30.0)
    assert (after["s004"].x, after["s004"].y) == (0.0, 0.0)
    assert bench.candidate.scale == start.scale


def test_edit_shapes_refuses_an_unknown_shape_and_keeps_the_arrangement() -> None:
    problem = PROBLEMS["maximize_scale"]
    start = candidate(problem, 3.0, LOOSE["maximize_scale"][1])
    bench, tools = tools_for(problem, start)
    answer = call(tools, "edit_shapes", move=[{"shape_id": "s099", "x": 1.0}])
    assert isinstance(answer, str) and "s099" in answer
    assert bench.candidate is start


@pytest.mark.parametrize(("kind", "pattern", "works"), [
    ("maximize_scale", "grid", True),
    ("maximize_scale", "hexagonal", True),
    ("minimize_container", "grid", True),
    ("minimize_container", "hexagonal", False),
    ("maximize_total_perimeter", "varied", True),
    ("maximize_scale", "varied", False),
    ("cover_region", "cover", True),
    ("maximize_scale", "cover", False),
])
def test_seed_lays_a_construction_where_its_pattern_applies(kind: str, pattern: str, works: bool) -> None:
    problem = PROBLEMS[kind]
    bench, tools = tools_for(problem)
    report = call(tools, "seed", pattern=pattern)
    if not works:
        assert isinstance(report, str) and bench.candidate is None
        return
    assert report["valid"] is True and evaluate(problem, bench.candidate).valid
    assert bench.candidate.n_shapes == problem.objective.preset_count()


def test_move_cluster_translates_a_group_and_leaves_the_rest() -> None:
    problem = PROBLEMS["maximize_scale"]
    start = candidate(problem, 3.0, LOOSE["maximize_scale"][1])
    bench, tools = tools_for(problem, start)
    call(tools, "move_cluster", shape_ids=["s000", "s001"], dx=0.5, dy=-0.25)
    for before, after in zip(start.placements, bench.candidate.placements):
        shift = (0.5, -0.25) if before.shape_id in {"s000", "s001"} else (0.0, 0.0)
        assert (after.x, after.y) == pytest.approx((before.x + shift[0], before.y + shift[1]))


def test_move_cluster_turns_a_group_about_its_own_centre() -> None:
    problem = Problem("tools-squares", None, square(), MinimizeContainer(count=2), rotation=FREE)
    start = candidate(problem, 1.0, [(-1.0, 0.0, 0, None), (1.0, 0.0, 0, None)])
    bench, tools = tools_for(problem, start)
    call(tools, "move_cluster", shape_ids=["s000", "s001"], rotation=90.0)
    first, second = bench.candidate.placements
    assert (first.x, first.y, first.rotation) == pytest.approx((0.0, -1.0, 90.0), abs=1e-9)
    assert (second.x, second.y, second.rotation) == pytest.approx((0.0, 1.0, 90.0), abs=1e-9)


# -- repairing, relaxing, polishing -----------------------------------------------------------


def test_repair_separates_a_container_packing_even_when_its_container_grows() -> None:
    """The case the old ranking refused: pushing shapes apart lowers a container's score."""
    problem = PROBLEMS["minimize_container"]
    touching = 2.0 * RegularPolygon(sides=5).inradius(1.0)
    broken = candidate(problem, 1.0, [(0.0, 0.0, 0, None), (touching - 1e-4, 0.0, 180, None),
                                      (0.0, 2.0, 0, None)])
    bench, tools = tools_for(problem, broken)
    assert not evaluate(problem, broken).valid
    report = call(tools, "repair")
    assert report["valid"] is True and evaluate(problem, bench.candidate).valid


def test_repair_brings_a_shape_back_inside_the_arena() -> None:
    problem = PROBLEMS["maximize_scale"]
    broken = candidate(problem, 4.0, [(-2.5, -2.5, 0, None), (2.5, -2.5, 0, None),
                                      (-2.5, 2.5, 0, None), (3.5, 2.5, 0, None)])
    bench, tools = tools_for(problem, broken)
    assert call(tools, "repair")["valid"] is True
    assert bench.candidate.scale == broken.scale


@pytest.mark.parametrize("kind", ["maximize_scale", "minimize_container", "maximize_total_perimeter"])
def test_repair_never_leaves_an_arrangement_more_broken(kind: str) -> None:
    problem = PROBLEMS[kind]
    scale, spots = LOOSE[kind]
    rng = np.random.default_rng(SEED)
    for _ in range(5):
        shaken = candidate(problem, scale * 1.4 if kind == "maximize_scale" else scale, [
            (x * 0.5 + rng.uniform(-0.2, 0.2), y * 0.5 + rng.uniform(-0.2, 0.2), rotation,
             None if size is None else size * 2.5)
            for x, y, rotation, size in spots
        ])
        bench, tools = tools_for(problem, shaken)
        call(tools, "repair")
        before = evaluate(problem, shaken).validation.severity
        after = evaluate(problem, bench.candidate).validation.severity
        assert after <= before


@pytest.mark.parametrize("kind", PROBLEMS)
def test_relax_local_never_hands_back_a_worse_arrangement(kind: str) -> None:
    problem = PROBLEMS[kind]
    start = candidate(problem, *LOOSE[kind])
    bench, tools = tools_for(problem, start)
    call(tools, "relax_local", iterations=8, amplitude=0.1, turn_degrees=10.0, seed=3)
    assert rank(problem, bench.candidate) >= rank(problem, start)


@pytest.mark.parametrize("kind", PROBLEMS)
def test_polish_improves_a_loose_start_and_never_hands_back_worse(kind: str) -> None:
    problem = PROBLEMS[kind]
    start = candidate(problem, *LOOSE[kind])
    assert evaluate(problem, start).valid
    bench, tools = tools_for(problem, start)
    report = call(tools, "polish", iterations=12, seed=1)

    after = evaluate(problem, bench.candidate)
    assert report["valid"] is after.valid is True
    assert after.primary > evaluate(problem, start).primary
    assert rank(problem, bench.candidate) > rank(problem, start)


def test_polish_turns_a_broken_sketch_into_a_valid_arrangement() -> None:
    problem = PROBLEMS["minimize_container"]
    sketch = candidate(problem, 1.0, [(0.0, 0.0, 0, None), (0.3, 0.0, 36, None), (0.0, 0.3, 0, None)])
    bench, tools = tools_for(problem, sketch)
    assert call(tools, "polish", iterations=4, seed=2)["valid"] is True


def test_worker_processes_compute_what_the_tools_compute_in_place() -> None:
    problem = PROBLEMS["minimize_container"]
    start = candidate(problem, *LOOSE["minimize_container"])
    runs = []
    for workers in (None, 1):
        bench, tools = tools_for(problem, start)
        if workers is None:
            call(tools, "polish", iterations=6, seed=11)
        else:
            with worker_processes(workers):
                call(tools, "polish", iterations=6, seed=11)
                # An operator's refusal still comes back as the tool's sentence.
                assert "must not be negative" in call(tools, "relax_local", amplitude=-1.0)
        runs.append(bench.candidate.placements)
    assert runs[0] == runs[1]


def test_polish_replays_with_a_seed_and_varies_without_one() -> None:
    problem = PROBLEMS["minimize_container"]
    start = candidate(problem, *LOOSE["minimize_container"])
    runs = []
    for _ in range(2):
        bench, tools = tools_for(problem, start)
        call(tools, "polish", iterations=6, seed=11)
        runs.append(bench.candidate.placements)
    assert runs[0] == runs[1]

    bench, tools = tools_for(problem, start)
    call(tools, "polish", iterations=6)
    first = bench.candidate
    bench.candidate = start  # the same arrangement again, one call later
    call(tools, "polish", iterations=6)
    assert bench.candidate.placements != first.placements


def test_polish_respects_a_fixed_rotation() -> None:
    problem = Problem("tools-fixed", None, square(), MinimizeContainer(count=3), seed=SEED)
    start = candidate(problem, 1.0, [(-1.5, 0.0, 0, None), (0.0, 0.0, 0, None), (1.5, 0.0, 0, None)])
    bench, tools = tools_for(problem, start)
    call(tools, "polish", iterations=10, seed=4)
    assert {item.rotation for item in bench.candidate.placements} == {0.0}
    assert evaluate(problem, bench.candidate).valid


# -- sizes and scales -------------------------------------------------------------------------


def test_fit_scale_takes_the_largest_scale_a_packing_holds() -> None:
    problem = PROBLEMS["maximize_scale"]
    bench, tools = tools_for(problem, candidate(problem, *LOOSE["maximize_scale"]))
    report = call(tools, "fit_scale")
    fitted = bench.candidate
    assert report["valid"] is True and fitted.scale == pytest.approx(5.0, abs=1e-6)
    assert not evaluate(problem, fitted.derive(scale=fitted.scale * (1 + 1e-6))).valid


def test_fit_scale_takes_the_smallest_scale_a_covering_holds() -> None:
    problem = PROBLEMS["cover_region"]
    bench, tools = tools_for(problem, candidate(problem, *LOOSE["cover_region"]))
    assert call(tools, "fit_scale")["valid"] is True
    fitted = bench.candidate
    assert fitted.scale < 3.0
    assert not evaluate(problem, fitted.derive(scale=fitted.scale * (1 - 1e-4))).valid


def test_fit_scale_is_refused_where_the_problem_fixes_the_scale() -> None:
    problem = PROBLEMS["minimize_container"]
    start = candidate(problem, *LOOSE["minimize_container"])
    bench, tools = tools_for(problem, start)
    assert isinstance(call(tools, "fit_scale"), str)
    assert bench.candidate is start


def test_grow_sizes_grows_the_named_shape_alone_or_every_shape_together() -> None:
    problem = PROBLEMS["maximize_total_perimeter"]
    start = candidate(problem, *LOOSE["maximize_total_perimeter"])
    bench, tools = tools_for(problem, start)
    call(tools, "grow_sizes", shape_id="s001")
    sizes = [item.scale for item in bench.candidate.placements]
    assert sizes[0] == sizes[2] == 0.2 and sizes[1] > 0.2
    assert evaluate(problem, bench.candidate).valid

    bench, tools = tools_for(problem, start)
    call(tools, "grow_sizes")
    factors = {round(item.scale / 0.2, 9) for item in bench.candidate.placements}
    assert len(factors) == 1 and factors.pop() > 1.0
    assert evaluate(problem, bench.candidate).valid


# -- counting ---------------------------------------------------------------------------------


def test_fill_void_adds_a_shape_where_there_is_room() -> None:
    problem = PROBLEMS["maximize_count"]
    start = candidate(problem, 2.0, [(-2.0, 0.0, 0, None)])
    bench, tools = tools_for(problem, start)
    report = call(tools, "fill_void", seed=1)
    assert report["valid"] is True and bench.candidate.n_shapes == 2


def test_remove_overlapping_drops_a_shape_that_overlaps_first() -> None:
    problem = PROBLEMS["maximize_count"]
    start = candidate(problem, 2.0, [(-2.0, -2.0, 0, None), (1.0, 1.0, 0, None), (1.5, 1.0, 0, None)])
    bench, tools = tools_for(problem, start)
    call(tools, "remove_overlapping", count=1, seed=1)
    assert "s000" in bench.candidate.shape_ids and bench.candidate.n_shapes == 2
    assert evaluate(problem, bench.candidate).valid


# -- the run's own state ----------------------------------------------------------------------


def test_restore_best_returns_to_the_best_valid_arrangement() -> None:
    problem = PROBLEMS["maximize_scale"]
    bench, tools = tools_for(problem)
    spots = [{"x": x, "y": y} for x, y in ((-2.5, -2.5), (2.5, -2.5), (-2.5, 2.5), (2.5, 2.5))]
    good = call(tools, "place_shapes", placements=spots, scale=5.0)["candidate_id"]
    call(tools, "place_shapes", placements=[{"x": 0.0, "y": 0.0}] * 4, scale=5.0)
    assert call(tools, "restore_best")["candidate_id"] == good
    assert bench.candidate.candidate_id == good


def test_geometry_is_refused_once_the_run_is_over() -> None:
    problem = PROBLEMS["maximize_scale"]
    start = candidate(problem, *LOOSE["maximize_scale"])
    bench, tools = tools_for(problem, start)
    call(tools, "give_up", reason="nothing left")
    for name, arguments in (("polish", {}), ("seed", {}), ("repair", {}), ("restore_best", {})):
        assert "over" in call(tools, name, **arguments)
    assert bench.candidate is start
    assert call(tools, "read_state")["candidate_id"] == start.candidate_id


def test_every_geometry_reply_matches_what_the_engine_says_of_the_arrangement() -> None:
    """Whatever the tool, the verdict it answers is the engine's verdict on what it left."""
    for kind, problem in PROBLEMS.items():
        bench, tools = tools_for(problem, candidate(problem, *LOOSE[kind]))
        for name in ("relax_local", "polish", "restore_best"):
            report = call(tools, name, **({"iterations": 3, "seed": 0} if name != "restore_best" else {}))
            verdict = evaluate(problem, bench.candidate)
            assert report["candidate_id"] == bench.candidate.candidate_id
            assert report["valid"] is verdict.valid
            assert report["score"] == pytest.approx(verdict.primary)
            facts = facts_for(problem, bench.candidate)
            assert len(report["shapes"]) == len(facts.instances)
