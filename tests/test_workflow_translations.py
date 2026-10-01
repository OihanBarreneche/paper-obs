"""Every sentence a workflow hands the interface has a French one to read.

The interface translates by looking the English string up, so a sentence it does not know falls
through to English on a French page. A manifest carries its own French map, which the interface
adds to its own; the tool labels a trace shows are in the interface's map. This is the one place
that can catch a gap: the maps and the strings sit on opposite sides of the API.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from paper_obs.domain.problem import Problem
from paper_obs.agent_tools.engine import Workbench, engine_tools
from paper_obs.workflows import registry

ROOT = Path(__file__).resolve().parents[1]
I18N = ROOT / "apps" / "web" / "src" / "i18n.tsx"


def _french_keys() -> set[str]:
    """Return the English strings the French map knows, read from the interface's own map."""
    return set(re.findall(r'"([^"]+)"\s*:', I18N.read_text(encoding="utf-8")))


def _freely_sized_problem() -> Problem:
    return Problem.from_dict({
        "problem_id": "probe",
        "shape": {"type": "circle", "radius": 1.0},
        "objective": {"type": "maximize_scale", "count": 4},
        "rotation": {"type": "rotation_policy", "mode": "free", "angles": [0.0]},
        "constraints": [],
        "arena": {"name": "", "shape": {"type": "rect", "width": 10.0, "height": 10.0}},
    })


def test_every_string_a_workflow_shows_has_a_french_sentence_in_its_manifest() -> None:
    """A workflow carries its own French, so adding one never touches the interface's map."""
    missing: list[str] = []
    for manifest in registry.manifests():
        keys = set(manifest.get("translations", {}).get("fr", {}))
        shown = [manifest["name"], manifest["description"]]
        for parameter in manifest.get("parameters", []):
            shown += [parameter["label"], parameter.get("help", "")]
        for node in manifest.get("nodes", []):
            shown += [node["label"], node.get("help", ""), *node.get("details", [])]
        missing += [f"{manifest['id']}: {text}" for text in shown if text and text not in keys]
    assert missing == [], f"a manifest has no French sentence for: {missing}"


def test_every_tool_label_a_trace_can_show_has_a_french_sentence() -> None:
    keys = _french_keys()
    names = [item.name for item in engine_tools(Workbench(problem=_freely_sized_problem()))]
    missing = [name.replace("_", " ") for name in names if name.replace("_", " ") not in keys]
    assert missing == [], f"the French map has no sentence for: {missing}"


def _descriptions(schema: Any) -> list[str]:
    """Return every description a JSON schema carries, at any depth."""
    if isinstance(schema, dict):
        return [
            text for key, value in schema.items()
            for text in ([value] if key == "description" and isinstance(value, str) else _descriptions(value))
        ]
    if isinstance(schema, list):
        return [text for value in schema for text in _descriptions(value)]
    return []


def test_every_sentence_the_tool_viewer_shows_has_a_french_sentence() -> None:
    """The viewer reads the docstrings themselves: a changed one needs its French again."""
    keys = _french_keys()
    missing: list[str] = []
    for workflow_id in registry.WORKFLOWS:
        for item in registry.tools(workflow_id)["tools"]:
            shown = [*item["description"], *_descriptions(item["parameters"])]
            if item["example"] is not None:
                shown.append(item["example"]["caption"])
            missing += [text for text in shown if text not in keys]
    assert missing == [], f"the French map has no sentence for: {sorted(set(missing))}"
