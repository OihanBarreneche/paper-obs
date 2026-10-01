"""A workflow's diagram is its compiled graph: the manifest cannot drift from the code."""

from __future__ import annotations

import pytest

pytest.importorskip("langgraph")

from langgraph.graph.state import CompiledStateGraph  # noqa: E402

from paper_obs.domain import Arena, Circle, MaximizeScale, Problem  # noqa: E402
from paper_obs.workflows import registry  # noqa: E402
from paper_obs.workflows.budget import Budget  # noqa: E402

ENDS = {"__start__": "start", "__end__": "end"}


@pytest.mark.parametrize("workflow_id", sorted(registry.WORKFLOWS))
def test_the_manifest_draws_the_compiled_graph(workflow_id: str) -> None:
    """Every arrow of the diagram is an edge of the graph, labelled with the router's answer.

    A step of kind ``route`` draws the router of the step before it: its arrows are the
    conditional edges leaving that step. The arrow from the start is drawn by the interface.
    """
    problem = Problem("diagram", Arena.rectangle(1.0, 1.0), Circle(), MaximizeScale(count=1))
    drawn = registry.build(workflow_id, problem, None, Budget()).get_graph()
    compiled = {
        (ENDS.get(edge.source, edge.source), ENDS.get(edge.target, edge.target), edge.data or "")
        for edge in drawn.edges
    }
    # A step that is a compiled graph of its own is drawn as its steps, named "step:inner".
    nodes = set(drawn.nodes) - set(ENDS)
    for name, node in list(drawn.nodes.items()):
        if not isinstance(node.data, CompiledStateGraph):
            continue
        inner = node.data.get_graph()
        inside = {(f"{name}:{edge.source}", f"{name}:{edge.target}", edge.data or "") for edge in inner.edges}
        first = next(target for source, target, _ in inside if source == f"{name}:__start__")
        last = next(source for source, target, _ in inside if target == f"{name}:__end__")
        compiled = {
            (last if source == name else source, first if target == name else target, label)
            for source, target, label in compiled
        } | {edge for edge in inside if "__" not in edge[0] + edge[1]}
        nodes = nodes - {name} | {f"{name}:{key}" for key in inner.nodes if key not in ENDS}

    manifest = registry.manifest(workflow_id)
    routes = {node["id"] for node in manifest["nodes"] if node["kind"] == "route"}
    routed = {edge["to"]: edge["from"] for edge in manifest["edges"] if edge["to"] in routes}
    by_hand = {("start", manifest["nodes"][0]["id"], "")} | {
        (routed.get(edge["from"], edge["from"]), edge["to"], edge["label"])
        for edge in manifest["edges"] if edge["to"] not in routes
    }
    assert by_hand == compiled
    # A step drawn as parallel copies names the parameter that says how many run.
    declared = {parameter["name"] for parameter in manifest["parameters"]}
    assert {node["parallel"] for node in manifest["nodes"] if "parallel" in node} <= declared
    assert {node["id"] for node in manifest["nodes"]} - routes == nodes
