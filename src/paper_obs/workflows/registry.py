"""The workflows the lab can run, found by their folders.

A workflow is a folder of this package holding a ``manifest.json`` and a ``graph.py`` whose
``build`` returns the compiled graph; its identifier is the folder's name. Adding a workflow is
adding a folder — the API and the interface read this one listing, so neither of them
learns a workflow's name. ``docs/writing-a-workflow.md`` describes the contract.
"""

from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path
from typing import Any

from paper_obs.domain.problem import Problem
from paper_obs.workflows.budget import Budget

FOLDER = Path(__file__).parent

#: The workflows the lab knows, by identifier: every folder here that holds a manifest.
WORKFLOWS: dict[str, Path] = {path.parent.name: path.parent for path in sorted(FOLDER.glob("*/manifest.json"))}


def _folder(workflow_id: str) -> Path:
    """Return the folder of a workflow, or raise KeyError naming the known ones."""
    try:
        return WORKFLOWS[workflow_id]
    except KeyError as error:
        known = ", ".join(sorted(WORKFLOWS))
        raise KeyError(f"unknown workflow {workflow_id!r}; known workflows: {known}") from error


def manifest(workflow_id: str) -> dict[str, Any]:
    """Return the manifest of one workflow, with its identifier: its name, parameters and topology."""
    return {"id": workflow_id, **json.loads((_folder(workflow_id) / "manifest.json").read_text(encoding="utf-8"))}


def manifests() -> list[dict[str, Any]]:
    """Return every manifest, sorted by the name it shows: a "W1 · " prefix sets the order."""
    return sorted((manifest(name) for name in WORKFLOWS), key=lambda item: item["name"])


def build(
    workflow_id: str,
    problem: Problem,
    model: Any,
    budget: Budget,
    settings: dict[str, Any] | None = None,
    *,
    guard: Any = None,
    start: Any = None,
) -> Any:
    """Return the compiled graph of one workflow, ready to invoke.

    The graph module is imported here rather than at the top: listing the workflows must not
    pull an agent framework in, which is what lets the API offer the list without the agents
    extra. ``settings`` are the parameters a workflow declares beyond the shared ceilings;
    which of them mean anything is the workflow's own business. ``start`` is the candidate a
    resumed run had kept.
    """
    graph = import_module(f"{__package__}.{_folder(workflow_id).name}.graph")
    return graph.build(problem, model=model, budget=budget, settings=settings or {}, guard=guard, start=start)


def tools(workflow_id: str) -> dict[str, Any]:
    """Return the tools a workflow's agents may call, as a model reads them, per objective.

    Every workflow's agents hold the engine's tools, and a workflow with a ``sandbox`` parameter
    also the Python sandbox. Like building, listing them needs the agents extra: without it this
    raises ImportError.
    """
    from paper_obs.agent_tools.catalog import catalog
    from paper_obs.agent_tools.engine import offered

    parameters = manifest(workflow_id).get("parameters", [])
    return catalog(offered, sandbox=any(item["name"] == "sandbox" for item in parameters))


__all__ = ["FOLDER", "WORKFLOWS", "build", "manifest", "manifests", "tools"]
