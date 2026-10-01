"""Free research sessions: an outside agent searches as it likes, the lab judges and keeps the log.

A session is one problem, one journal and the best arrangement so far, written to
``runs/research/<session_id>/session.json`` beside a ``work/`` folder the agent fills with
its own programs, logs and notes. The agent drives: it submits arrangements, which the
engine judges, and writes notes. Nothing here searches, schedules or limits the agent; the
contract it follows is docs/research-mode.md.

A submission is measured in the unit of the record the problem carries when there is one
(the container side, for most catalog problems), so every number a session shows can be
compared with the published value as it is.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paper_obs.domain.candidate import Candidate
from paper_obs.domain.problem import Problem
from paper_obs.domain.reference import record_gap, record_measure
from paper_obs.domain.serde import dump
from paper_obs.geometry.engine import Evaluation, evaluate
from paper_obs.storage.files import runs_directory

#: What a session document says it is.
FILE_KIND = "research-session"
#: Bumped only when a reader would have to branch on it.
FILE_FORMAT = 1
#: The statuses an agent can give its session.
STATUSES = ("active", "paused", "done")
#: The plural a catalog problem is named with, as the web app's cards name it.
NOUNS = {"circle": "circles", "triangle": "triangles", "square": "squares", "pentagon": "pentagons",
         "hexagon": "hexagons", "octagon": "octagons", "tan": "tans", "domino": "dominoes", "l": "L's"}
#: The catalog the web app ships, read by :func:`catalog_problem` in a source checkout.
CATALOG = Path(__file__).resolve().parents[2] / "apps/web/public/catalog/packing_equal_copies.json"


def sessions_directory() -> Path:
    """Return the folder sessions live in: research/ inside the runs folder."""
    return runs_directory() / "research"


def start(problem: Problem, *, name: str, agent: str, goal: str = "") -> dict[str, Any]:
    """Open a session on a problem and return its document; ``work/`` is created empty."""
    session_id = f"res-{uuid.uuid4().hex[:10]}"
    folder = sessions_directory() / session_id
    (folder / "work").mkdir(parents=True)
    now = _now()
    document = {
        "kind": FILE_KIND, "format": FILE_FORMAT, "session_id": session_id,
        "created_at": now, "updated_at": now, "name": name.strip() or session_id,
        "agent": agent.strip(), "goal": goal.strip(), "status": "active",
        "problem_id": problem.problem_id, "problem": problem.to_dict(),
        "journal": [], "best": None, "champion": None,
    }
    _write(document)
    return document


def load(session_id: str) -> dict[str, Any]:
    """Return a session's document."""
    return json.loads(_path(session_id).read_text(encoding="utf-8"))


def submit(session_id: str, candidate: Candidate, note: str = "") -> dict[str, Any]:
    """Judge an arrangement, log it, keep it if it beats the session's best; return the entry.

    Only an improvement keeps its arrangement and full verdict in the journal, so a search
    that submits often does not bloat the file; every submission keeps its measure.
    """
    document = load(session_id)
    problem = Problem.from_dict(document["problem"])
    verdict = evaluate(problem, candidate)
    champion = document["champion"]
    accepted = verdict.valid and (
        champion is None or verdict.is_better_than(evaluate(problem, Candidate.from_dict(champion))))
    measure, metric = _measure(problem, verdict)
    entry = {
        "kind": "submission", "at": _now(), "index": sum(item["kind"] == "submission" for item in document["journal"]),
        "note": note.strip(), "valid": verdict.valid, "primary": verdict.primary, "measure": measure, "metric": metric,
        "record_gap": record_gap(problem.metadata.get("reference"), verdict.primary, verdict.metrics),
        "accepted": accepted, "violations": [str(item) for item in verdict.validation.violations[:3]],
        "candidate": candidate.to_dict() if accepted else None,
        "verdict": verdict.to_dict() if accepted else None,
    }
    document["journal"].append(entry)
    if accepted:
        document["champion"] = candidate.to_dict()
        document["best"] = {key: entry[key] for key in ("at", "index", "measure", "metric", "record_gap", "primary")}
    _write(document)
    return entry


def add_note(session_id: str, text: str) -> dict[str, Any]:
    """Append a note (an idea, a dead end, a method, a machine plan) and return it."""
    document = load(session_id)
    entry = {"kind": "note", "at": _now(), "text": text.strip()}
    document["journal"].append(entry)
    _write(document)
    return entry


def set_status(session_id: str, status: str) -> dict[str, Any]:
    """Mark a session active, paused or done, and return its document."""
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    document = load(session_id)
    document["status"] = status
    _write(document)
    return document


def listing(problem_id: str | None = None) -> list[dict[str, Any]]:
    """Return one line per session, newest first, optionally only one problem's."""
    folder = sessions_directory()
    lines = []
    for path in folder.glob("*/session.json") if folder.is_dir() else ():
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if document.get("kind") != FILE_KIND or (problem_id and document.get("problem_id") != problem_id):
            continue
        submissions = [item for item in document["journal"] if item["kind"] == "submission"]
        lines.append({
            "session_id": document["session_id"], "name": document["name"], "agent": document["agent"],
            "status": document["status"], "created": document["created_at"], "updated": document["updated_at"],
            "problem_id": document["problem_id"], "problem_name": document["problem"].get("name", ""),
            "submissions": len(submissions), "best": document["best"],
            # Each new best as [submission index, measure, gap to the record]: how the session progressed.
            "track": [[item["index"], item["measure"], item["record_gap"]] for item in submissions if item["accepted"]],
        })
    return sorted(lines, key=lambda line: line["created"], reverse=True)


def catalog_problem(slug: str, count: int, catalog: Path | None = None) -> Problem:
    """Return a Packing Equal Copies problem of the shipped catalog, with its published record.

    The same composition as the web app's catalog cards: the family's template at ``count``
    copies, and the record of that count (value, unit, author, figure) as its reference.
    """
    document = json.loads((catalog or CATALOG).read_text(encoding="utf-8"))
    family = next((item for item in document["families"] if item["slug"] == slug), None)
    if family is None or family.get("problem_template") is None:
        raise ValueError(f"no launchable catalog family {slug!r}")
    if family.get("section") != "Packing Equal Copies":
        raise ValueError(f"{slug} is not an equal-copies family; export it from the web app instead")
    instance = next((item for item in family["instances"] if count in item["counts"]), None)
    template = json.loads(json.dumps(family["problem_template"]))
    nouns = NOUNS.get(family["shape"], family["shape"])
    container = "L" if family["container"] == "l" else family["container"]
    template.update(
        problem_id=f"{nouns}-{count}-in-smallest-{family['container']}", seed=count,
        name=f"{count} {nouns} in the smallest {container}",
        description=f"Pack {count} unit {nouns} inside the smallest possible {container}.",
        objective={**template["objective"], "count": count})
    if instance is not None and instance.get("value") is not None:
        symbol = instance.get("symbol") or "s"
        template["metadata"] = {**template.get("metadata", {}), "reference": {
            "status": instance["status"], "value": instance["value"],
            "unit": f"container {'radius' if symbol == 'r' else 'area' if symbol == 'a' else 'side'}",
            "note": " · ".join(part for part in (instance["attribution"], instance.get("formula", "")) if part),
            "verified_on": document.get("generated", ""),
            "preview": family["page"] + instance["figure"] if instance.get("figure") else "",
            "sources": [{"label": f"{family['title']} · Erich Friedman's Packing Center", "url": family["page"]}],
        }}
    return Problem.from_dict(template)


def _measure(problem: Problem, verdict: Evaluation) -> tuple[float | None, str]:
    """Return a verdict's headline measure and what it is: the record's unit when the problem
    carries a comparable record, else the engine metric that names the container best."""
    reference = problem.metadata.get("reference")
    measured = record_measure(reference, verdict.primary, verdict.metrics)
    if measured is not None:
        return measured, str(reference["unit"])
    for name in ("equivalent_container_side", verdict.promoted_metric):
        if name in verdict.metrics:
            return verdict.metrics[name], name
    return verdict.primary, "primary"


def _path(session_id: str) -> Path:
    if not session_id or Path(session_id).name != session_id or session_id in {".", ".."}:
        raise ValueError(f"invalid session id {session_id!r}")
    path = sessions_directory() / session_id / "session.json"
    if not path.is_file():
        raise ValueError(f"unknown session {session_id!r}")
    return path


def _write(document: dict[str, Any]) -> None:
    document["updated_at"] = _now()
    dump(document, sessions_directory() / document["session_id"] / "session.json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


__all__ = ["FILE_KIND", "STATUSES", "add_note", "catalog_problem", "listing", "load", "set_status",
           "sessions_directory", "start", "submit"]
