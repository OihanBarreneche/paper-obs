"""Running a workflow on a problem, and writing the run down as it goes.

A run is one JSON file, like every other object of the lab, and it is written after each
turn rather than at the end: a run that takes two minutes has to be watchable while it
happens, and a run that fails has to leave behind what it had reached.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import Any

from paper_obs.domain.candidate import Candidate
from paper_obs.domain.problem import Problem
from paper_obs.domain.reference import record_gap
from paper_obs.domain.serde import dump
from paper_obs.storage.files import RUNS, RUNS_ENVIRONMENT, runs_directory
from paper_obs.llm.models import ModelConfig
from paper_obs.llm.redaction import (
    forget,
    install_log_scrubber,
    redact,
    redact_document,
    remember,
)

from . import registry
from .budget import Budget, Cost, Prices

#: The subfolder a deleted run moves to: out of the pickers, still counted in what the runs
#: spent, and restorable. Removing a file from it by hand drops it from the totals.
DELETED = "deleted"


#: What a run document says it is, so a candidate dump in the same folder is not one.
FILE_KIND = "agent-run"

#: Bumped only when a reader would have to branch on it.
FILE_FORMAT = 1

#: What a run says when the process writing it went away before it could finish.
ORPHAN_ERROR = "the lab stopped while this run was going"

#: What a run that has just started has spent.
EMPTY_SPEND: dict[str, Any] = {
    "llm_calls": 0,
    "tool_calls": 0,
    "seconds": 0.0,
    "tokens_in": 0,
    "tokens_out": 0,
    "tokens_cached": 0,
    "model_seconds": 0.0,
    "cost": None,
}


def new_run_id() -> str:
    """Return a short identifier for a run."""
    return f"run-{uuid.uuid4().hex[:10]}"


def validate_name(value: str) -> str:
    """Return a display name suitable for a saved run and its picker."""
    if not isinstance(value, str):
        raise ValueError("Run name must be text")
    name = value.strip()
    if not name or len(name) > 100 or any(ord(char) < 32 for char in name):
        raise ValueError("Run name must contain 1 to 100 printable characters")
    return name


def run(
    problem: Problem,
    *,
    workflow: str,
    config: ModelConfig,
    budget: Budget,
    settings: dict[str, Any] | None = None,
    api_key: str | None = None,
    directory: Path | None = None,
    run_id: str | None = None,
    name: str | None = None,
    stop_requested: Event | None = None,
) -> dict[str, Any]:
    """Run one workflow on one problem, writing the document after every turn.

    Blocking on purpose: the caller decides whether that means a background task, a
    thread, or a command line that waits. It is :func:`open_run` then :func:`carry_on`.
    """
    path = open_run(problem, workflow=workflow, config=config, budget=budget, settings=settings,
                    directory=directory, run_id=run_id, name=name)
    return carry_on(path, config=config, budget=budget, api_key=api_key, stop_requested=stop_requested)


def open_run(
    problem: Problem,
    *,
    workflow: str,
    config: ModelConfig,
    budget: Budget,
    settings: dict[str, Any] | None = None,
    directory: Path | None = None,
    run_id: str | None = None,
    name: str | None = None,
) -> Path:
    """Write a new run's document, saying it is running, and return its path.

    A server writes it before handing the run to another process, so a client that reads
    the run at once finds it going rather than missing.
    """
    identifier = new_run_id() if run_id is None else run_id
    workflow_name = registry.manifest(workflow)["name"]
    display_name = validate_name(name) if name is not None else f"{workflow_name} · {identifier[-6:]}"
    folder = runs_directory() if directory is None else directory
    path = folder / f"{identifier}.json"
    document: dict[str, Any] = {
        "kind": FILE_KIND,
        "format": FILE_FORMAT,
        "run_id": identifier,
        # The run dates itself: the picker sorts a history by it, and a name the owner edits
        # cannot take it away. Written in UTC so the order is the same everywhere.
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "name": display_name,
        "workflow": workflow,
        "workflow_name": workflow_name,
        "problem_id": problem.problem_id,
        "problem": problem.to_dict(),
        "model": config.to_dict(),
        "budget": budget.to_dict(),
        "settings": dict(settings or {}),
        "status": "running",
        "stopped_by": None,
        "error": None,
        "round": 0,
        "seconds": 0.0,
        "spend": dict(EMPTY_SPEND),
        "steps": [],
        "notes": [],
        "champion": None,
    }
    _write(path, document)
    return path


def resume(
    run_id: str,
    *,
    config: ModelConfig,
    budget: Budget,
    settings: dict[str, Any] | None = None,
    api_key: str | None = None,
    directory: Path | None = None,
    stop_requested: Event | None = None,
) -> dict[str, Any]:
    """Take a run up again where it stopped, in the same document.

    The run goes on from its best arrangement, its journal and its notes. ``budget`` is what
    the resumption may spend: its ceilings are added to what the run had already spent.
    It is :func:`reopen` then :func:`carry_on`.
    """
    path = reopen(run_id, config=config, settings=settings, directory=directory)
    return carry_on(path, config=config, budget=budget, api_key=api_key, stop_requested=stop_requested)


def reopen(
    run_id: str, *, config: ModelConfig, settings: dict[str, Any] | None = None,
    directory: Path | None = None,
) -> Path:
    """Mark a finished run as running again, dating the resumption, and return its path."""
    folder = runs_directory() if directory is None else directory
    path = _run_path(folder, run_id)
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("status") == "running":
        raise ValueError("this run is still going")
    document.update(status="running", stopped_by=None, error=None, model=config.to_dict(),
                    settings=dict(settings or {}))
    document.setdefault("resumed", []).append({
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "round": document["round"],
    })
    _write(path, document)
    return path


def carry_on(
    path: Path,
    *,
    config: ModelConfig,
    budget: Budget,
    api_key: str | None = None,
    stop_requested: Event | None = None,
) -> dict[str, Any]:
    """Run an opened document's workflow from where its trace ends, writing it after every turn.

    What the document had spent is what came before this execution; a new run has spent
    nothing. The graph and the guard count this execution alone against ``budget``, while the
    document shows the whole run against ceilings shifted by what came before.
    ``stop_requested`` is any event with ``is_set``, a process's as well as a thread's.
    """
    document = json.loads(path.read_text(encoding="utf-8"))
    problem = Problem.from_dict(document["problem"])
    earlier = Cost.from_dict(document["spend"])
    earlier_seconds = float(document.get("seconds") or 0.0)
    earlier_model_seconds = float(document["spend"].get("model_seconds") or 0.0)
    turns_before = int(document["round"])
    # The graph counts turns from the start of the run, and the rest from this execution.
    graph_budget = replace(budget, rounds=budget.rounds + turns_before if budget.rounds > 0 else 0)
    shown = replace(
        graph_budget,
        llm_calls=earlier.llm_calls + budget.llm_calls if budget.llm_calls > 0 else 0,
        tool_calls=earlier.tool_calls + budget.tool_calls if budget.tool_calls > 0 else 0,
        seconds=earlier_seconds + budget.seconds if budget.seconds > 0 else 0.0,
        max_cost=None if budget.max_cost is None else (earlier.cost or 0.0) + budget.max_cost,
    )
    document["budget"] = shown.to_dict()
    champion = document.get("champion")
    start = None if champion is None else Candidate.from_dict(champion)
    # max_tokens stays null unless the caller asked for a ceiling: a number invented here
    # would be this lab's guess at a limit the provider knows better.
    # The key is remembered for the length of the run only, in memory: an error message
    # or a log line can quote it, and both are scrubbed while it is known.
    secrets = (api_key,) if api_key else ()
    install_log_scrubber()
    _write(path, document, secrets=secrets)
    started = time.perf_counter()

    def clock() -> float:
        return round(earlier_seconds + time.perf_counter() - started, 3)

    try:
        # Remembered inside the try, so the finally below always forgets it — even when
        # the run fails before a model is ever built.
        remember(api_key)
        if stop_requested is not None and stop_requested.is_set():
            document["stopped_by"] = "user"
            document["status"] = "stopped"
            _write(path, document, secrets=secrets)
            return redact_document(document, secrets=secrets)
        # Imported inside the try: reading a run back must not need the agents extra, and
        # a run started without it has to leave a document saying why it stopped.
        from paper_obs.llm.chat import chat_model
        from .guard import RunGuard
        from .session import new_state

        prices = _prices(config)
        if budget.max_cost is not None and prices is None:
            raise ValueError("A cost ceiling requires both model token prices")

        def progress(guard: RunGuard) -> None:
            document["spend"].update(
                llm_calls=earlier.llm_calls + guard.calls,
                tokens_in=earlier.tokens_in + guard.tokens_in,
                tokens_out=earlier.tokens_out + guard.tokens_out,
                tokens_cached=earlier.tokens_cached + guard.tokens_cached,
                model_seconds=round(earlier_model_seconds + guard.model_seconds, 3),
            )
            if prices is not None:
                document["spend"]["cost"] = round((earlier.cost or 0.0) + guard.cost, 6)
            document["seconds"] = clock()
            _write(path, document, secrets=secrets)

        guard = RunGuard(
            budget, max_tokens=config.max_tokens, prices=prices,
            stop_requested=stop_requested, on_progress=progress,
        )
        graph = registry.build(
            document["workflow"], problem, chat_model(config, api_key=api_key), graph_budget,
            document["settings"], guard=guard, start=start,
        )
        state = new_state(problem.problem_id, run_id=document["run_id"], budget=graph_budget)
        state.update(round=turns_before, trace=list(document["steps"]), notes=list(document["notes"]))
        # One turn is one step of the outer graph, and LangGraph's own default of 25 would
        # end a long run early. The ceilings that matter are the budgets, checked above and in
        # the routing; this only has to be larger than the turns a run may take.
        for snapshot in graph.stream(
            state, stream_mode="values", config={"recursion_limit": _step_ceiling(graph_budget)}
        ):
            _absorb(document, snapshot, prices, earlier)
            document["spend"]["model_seconds"] = round(earlier_model_seconds + guard.model_seconds, 3)
            document["seconds"] = clock()
            _write(path, document, secrets=secrets)
            if guard.stop_reason is not None:
                document["stopped_by"] = guard.stop_reason
                break
            if stop_requested is not None and stop_requested.is_set():
                document["stopped_by"] = "user"
                break
            if document["round"] > turns_before and shown.max_cost is not None and document["spend"]["cost"] >= shown.max_cost:
                document["stopped_by"] = "max_cost"
                break
            if shown.seconds > 0 and document["round"] > turns_before and document["seconds"] >= shown.seconds:
                document["stopped_by"] = "seconds"
                break
        document["status"] = "stopped" if document["stopped_by"] == "user" else "done"
    except Exception as error:
        # A failed run is a run: it keeps the turns it had reached, and says why it stopped.
        document["status"] = "failed"
        # An exception can quote the request it failed on, so the message is redacted here
        # and the whole tree again before it is written: a run document is public.
        document["error"] = redact(f"{type(error).__name__}: {error}", secrets=secrets)
    finally:
        forget(api_key)
    document["seconds"] = clock()
    _write(path, document, secrets=secrets)
    return redact_document(document, secrets=secrets)


#: What an unbounded turn loop is given, so a long run is stopped by its own rules and not
#: by the graph. LangGraph counts steps, and `create_agent` uses the same order of magnitude.
UNBOUNDED_STEPS = 10_000


def _step_ceiling(budget: Budget) -> int:
    """Return how many steps the outer graph may take, for a run whose turns it bounds."""
    return budget.rounds + 8 if budget.rounds > 0 else UNBOUNDED_STEPS


def _prices(config: ModelConfig) -> Prices | None:
    """Return what a million tokens cost in and out, or None when no price was given.

    No price list ships with the lab: a price ages badly, and a stale dollar figure is worse
    than none. A caller that knows the price sends it with the run, and this is where the
    tokens the graph counted meet it. The estimate is therefore the caller's, not ours.
    """
    if config.cost_per_million_in is None or config.cost_per_million_out is None:
        return None
    return Prices(config.cost_per_million_in, config.cost_per_million_out, config.cost_per_million_cached)


def _absorb(
    document: dict[str, Any], state: dict[str, Any], prices: Prices | None, earlier: Cost
) -> None:
    """Copy what the run has reached out of the graph's state into the document.

    The state's spend is this execution's; ``earlier`` is what the run had spent before it.
    """
    document["round"] = state.get("round", 0)
    spend = state.get("spend")
    if spend is not None:
        document["spend"] = (earlier + spend).to_dict()
        if prices is not None:
            document["spend"]["cost"] = round((earlier.cost or 0.0) + prices.cost(
                spend.tokens_in, spend.tokens_out, spend.tokens_cached), 6)
    steps = state.get("trace") or []
    document["steps"] = steps
    document["notes"] = list(state.get("notes") or [])
    accepted = [step for step in steps if step.get("accepted") and step.get("valid")]
    document["champion"] = accepted[-1]["candidate"] if accepted else None


def _write(
    path: Path, document: dict[str, Any], secrets: tuple[str, ...] = ()
) -> None:
    """Write the document, creating the folder if this is the first run.

    The tree is redacted on the way out — every string, every mapping key — so a secret
    that reached a note, a tool reply or an error message cannot reach the file.
    """
    dump(redact_document(document, secrets=secrets), path)


def _run_path(folder: Path, run_id: str) -> Path:
    """Return the file of one run, refusing an identifier that could name another path."""
    if not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
        raise ValueError(f"invalid run id {run_id!r}")
    return folder / f"{run_id}.json"


def _file_time(path: Path) -> str:
    """Return when a document was last written, for a run that does not date itself."""
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return ""
    return datetime.fromtimestamp(stamp, tz=timezone.utc).isoformat(timespec="seconds")


def load(run_id: str, directory: Path | None = None) -> dict[str, Any]:
    """Return a run, filling optional fields omitted by earlier documents."""
    folder = runs_directory() if directory is None else directory
    path = _run_path(folder, run_id)
    document = json.loads(path.read_text(encoding="utf-8"))
    document.setdefault("name", document.get("workflow_name") or document.get("run_id", run_id))
    document.setdefault("created_at", _file_time(path))
    document.setdefault("notes", [])
    document.setdefault("settings", {})
    for step in document.get("steps", []):
        step.setdefault("notes", [])
        step.setdefault("tools", [])
    # A document written before this guarantee existed is scrubbed on the way out too:
    # the read path is the last place a leaked key could still be served.
    return redact_document(document)


#: Each listed file's line, by path, with the modification time and size it was read at.
_listed: dict[Path, tuple[tuple[int, int], dict[str, Any] | None]] = {}


def listing(directory: Path | None = None) -> list[dict[str, Any]]:
    """Return one line per run, newest first, for a run picker.

    The order is the run's own and not the folder's: a document dates itself once it is
    written, and one that predates the field is dated by the file it lives in, so an older
    history still sorts instead of coming back in whatever order the folder enumerates.
    A document is read again only when its file changed: a run's is several megabytes, and a
    client polls the listing while runs go on.
    """
    folder = runs_directory() if directory is None else directory
    if not folder.is_dir():
        return []
    lines = []
    for deleted, place in ((False, folder), (True, folder / DELETED)):
        for path in place.glob("*.json"):
            try:
                stat = path.stat()
            except OSError:
                continue
            version = (stat.st_mtime_ns, stat.st_size)
            known = _listed.get(path)
            if known is None or known[0] != version:
                known = (version, _line(path))
                _listed[path] = known
            if known[1] is not None:
                lines.append({**known[1], "deleted": deleted})
    return sorted(lines, key=lambda item: str(item["created"]), reverse=True)


def _line(path: Path) -> dict[str, Any] | None:
    """Return a run document's line in the listing, or None for a file that is not one."""
    document = _read(path)
    if document is None:
        return None
    accepted = [step for step in document.get("steps", []) if step.get("accepted") and step.get("valid")]
    last = accepted[-1] if accepted else None
    verdict = (last or {}).get("verdict") or {}
    created = document.get("created_at")
    created = created if isinstance(created, str) and created else _file_time(path)
    resumed = document.get("resumed") or [{}]
    model = document.get("model") or {}
    reference = ((document.get("problem") or {}).get("metadata") or {}).get("reference")
    return {
        "run_id": document.get("run_id", path.stem),
        "created": created,
        # When the run last started, first or resumed: how long a running one has been going.
        "started": resumed[-1].get("at") or created,
        "name": document.get("name") or document.get("workflow_name") or path.stem,
        "workflow": document.get("workflow", ""),
        "problem_id": document.get("problem_id", ""),
        "problem_name": (document.get("problem") or {}).get("name") or document.get("problem_id", ""),
        "status": document.get("status", ""),
        "round": document.get("round", 0),
        "seconds": document.get("seconds", 0.0),
        "spend": document.get("spend", EMPTY_SPEND),
        # The measurement the objective promotes reads more plainly than the primary score, which
        # is its inverse for a smallest container: the side, not one over it.
        "champion": None if last is None else {
            "valid": last.get("valid"), "primary": last.get("primary"),
            "measure": (verdict.get("metrics") or {}).get(verdict.get("promoted_metric") or "", last.get("primary")),
        },
        "provider": model.get("provider", ""),
        "model": model.get("model", ""),
        # How far the run's best is from the problem's published record; positive when ahead.
        "record_gap": None if last is None else record_gap(
            reference, last.get("primary"), (last.get("verdict") or {}).get("metrics") or {}),
        # Each new best as [turn index, score, gap to the record]: how the run progressed.
        "track": [[step.get("round", 0), step.get("primary"), record_gap(
            reference, step.get("primary"), (step.get("verdict") or {}).get("metrics") or {})] for step in accepted],
    }


def delete(run_id: str, directory: Path | None = None) -> None:
    """Move one run's file to the deleted runs.

    A deleted run leaves the pickers but not the history: what it spent still counts, and
    :func:`restore` brings it back. A missing file is reported rather than ignored: a caller
    that asked to delete a run and deleted nothing should hear it.
    """
    folder = runs_directory() if directory is None else directory
    source = _run_path(folder, run_id)
    if not source.is_file():
        raise ValueError(f"unknown run {run_id!r}")
    (folder / DELETED).mkdir(exist_ok=True)
    source.replace(_run_path(folder / DELETED, run_id))


def restore(run_id: str, directory: Path | None = None) -> None:
    """Bring a deleted run back among the runs, refusing to overwrite one of the same name."""
    folder = runs_directory() if directory is None else directory
    source, target = _run_path(folder / DELETED, run_id), _run_path(folder, run_id)
    if not source.is_file() or target.exists():
        raise ValueError(f"no deleted run {run_id!r} to restore")
    source.rename(target)


def close_orphans(directory: Path | None = None) -> list[str]:
    """Mark every run still saying it is going as failed, and return their identifiers.

    A run is written by the process that started it and nothing else can finish it: a lab
    that is stopped, or crashes, leaves a document saying "running" forever, and a client
    polling it would wait for a turn nobody will ever write. Called when the lab starts, so
    a run file does not outlive the process that could have finished it.
    """
    folder = runs_directory() if directory is None else directory
    if not folder.is_dir():
        return []
    closed = []
    for path in folder.glob("*.json"):
        document = _read(path)
        if document is None or document.get("status") != "running":
            continue
        document["status"] = "failed"
        document["error"] = ORPHAN_ERROR
        _write(path, document)
        closed.append(str(document.get("run_id", path.stem)))
    return closed


def _read(path: Path) -> dict[str, Any] | None:
    """Return a run document, or None for anything in the folder that is not one."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(document, dict) and document.get("kind") == FILE_KIND:
        return redact_document(document)
    return None


__all__ = [
    "FILE_FORMAT",
    "FILE_KIND",
    "ORPHAN_ERROR",
    "RUNS",
    "RUNS_ENVIRONMENT",
    "carry_on",
    "close_orphans",
    "DELETED",
    "delete",
    "listing",
    "load",
    "restore",
    "new_run_id",
    "open_run",
    "reopen",
    "resume",
    "run",
    "runs_directory",
]
