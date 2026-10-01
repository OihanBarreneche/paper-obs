"""Record what a turn of an agent workflow did, as the run file keeps it.

This adapter is shared run infrastructure, not a node in the teaching graph: it opens a turn
on the run's best arrangement, turns the messages the turn ended on into one trace step, keeps
the note the agent ended on, and adds up what the turn cost. A workflow decides *when* a turn
happens; this decides what survives of it.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, ToolMessage

from paper_obs.agent_tools.engine import Judged, Workbench
from paper_obs.domain.problem import Problem
from paper_obs.geometry.engine import Evaluation, evaluate

from .budget import Budget, Cost, usage
from .trace import model_messages, tool_events

#: Longest note kept from a turn, in characters: the next turn reads it in full.
NOTE_CHARS = 1500


def new_state(problem_id: str, *, run_id: str, budget: Budget) -> dict[str, Any]:
    """Start the persisted run before any proposal has been judged."""
    return {
        "problem_id": problem_id,
        "run_id": run_id,
        "budget": budget,
        "spend": Cost(),
        "round": 0,
        "trace": [],
        "notes": [],
    }


def spent(messages: list[Any], seconds: float = 0.0) -> Cost:
    """Return what an agent's messages cost: the replies paid for, the tools run, the tokens.

    A tool call a ceiling blocked never ran, so the run does not pay for it; the request the
    model made stays visible in the trace either way.
    """
    reports = [usage(message) for message in messages]
    return Cost(
        llm_calls=sum(1 for message in messages if _answered(message)),
        tool_calls=sum(1 for message in messages if isinstance(message, ToolMessage)
                       and getattr(message, "status", "success") != "error"),
        seconds=seconds,
        tokens_in=sum(item[0] for item in reports),
        tokens_out=sum(item[1] for item in reports),
        tokens_cached=sum(item[2] for item in reports),
    )


def _answered(message: Any) -> bool:
    """Whether a message is a reply the model actually produced.

    A limit middleware or the run guard can end a turn with a message of its own; those carry
    neither usage nor provider metadata, and a reply the run did not pay for is not counted.
    """
    return (
        isinstance(message, AIMessage)
        and bool(message.usage_metadata or message.response_metadata)
        and not message.response_metadata.get("run_guard_stop")
    )


def note_of(messages: list[Any]) -> str:
    """Return the text the turn ended on, which is the agent's note to the next turn."""
    last = next((item for item in reversed(messages) if _answered(item)), None)
    if last is None or last.tool_calls:
        return ""
    return last.text.strip()[:NOTE_CHARS]


class AgentSession:
    """Open each turn on the run's best arrangement, and write down what the turn did."""

    def __init__(self, problem: Problem, bench: Workbench) -> None:
        self.problem = problem
        self.bench = bench
        #: The run's best when the turn opened: the turn improved the run if it no longer is.
        self.start: Judged | None = None
        #: Each parallel agent's own best verdict so far, by name, for its personal record.
        self.lanes: dict[str, Evaluation] = {}

    def open_turn(self) -> None:
        """Start the turn on the run's best arrangement, with no turn best yet.

        A turn that ended on a worse experiment must not hand it to the next one: the next turn
        starts from what the run keeps, which is also what its opening message describes. A
        resumed run hands over the arrangement it had kept, which the engine judges again.
        """
        if self.bench.best is None and self.bench.candidate is not None:
            evaluation = evaluate(self.problem, self.bench.candidate)
            if evaluation.valid:
                self.bench.best = Judged(self.bench.candidate, evaluation)
        self.bench.turn_best = None
        if self.bench.best is not None:
            self.bench.candidate = self.bench.best.candidate
        self.start = self.bench.best

    def merge(self, branch: Workbench) -> None:
        """Take in what a parallel branch reached: its arrangements, and its bests where better."""
        bench = self.bench
        bench.snapshots.update(branch.snapshots)
        if branch.best is not None and (
            bench.best is None or branch.best.evaluation.is_better_than(bench.best.evaluation)
        ):
            bench.best = branch.best
        if branch.turn_best is not None and (
            bench.turn_best is None or branch.turn_best.evaluation.is_better_than(bench.turn_best.evaluation)
        ):
            bench.turn_best = branch.turn_best
        if bench.best is not None:
            bench.candidate = bench.best.candidate

    def lane(self, name: str, branch: Workbench, messages: list[Any], **extra: Any) -> dict[str, Any]:
        """Describe what one parallel agent reached this turn, for a view of its own.

        Its best arrangement of the turn with the engine's verdict, whether that beat its own
        best of earlier turns, and its report. ``name`` is the agent's, as its tool calls carry
        it; ``extra`` fields are added, such as the idea it was given.
        """
        candidate = branch.turn_best.candidate if branch.turn_best else branch.candidate
        verdict = None if candidate is None else evaluate(self.problem, candidate)
        own = self.lanes.get(name)
        improved = verdict is not None and verdict.valid and (own is None or verdict.is_better_than(own))
        if improved:
            self.lanes[name] = verdict
        return {
            "id": name,
            "candidate": None if candidate is None else candidate.to_dict(),
            "valid": None if verdict is None else verdict.valid,
            "primary": None if verdict is None else verdict.primary,
            "accepted": improved,
            "note": note_of(messages),
            "verdict": None if verdict is None else verdict.to_dict(),
            **extra,
        }

    def record(
        self, state: dict[str, Any], messages: list[Any], seconds: float,
        note: str | None = None, **extra: Any,
    ) -> dict[str, Any]:
        """Note down what the turn reached, whether it improved the run, and what it cost.

        The note is the turn's closing text unless ``note`` gives another, such as the reports
        of parallel agents; ``extra`` fields are added to the trace step, such as a plan.
        """
        cost = spent(messages, seconds)
        tools = [
            str(item["name"])
            for message in messages
            if isinstance(message, AIMessage)
            for item in message.tool_calls
        ]
        note = note_of(messages) if note is None else note
        notes = [*state["notes"], note] if note else list(state["notes"])

        # The turn's own best, not the arrangement it happened to end on; what the run keeps is
        # its best overall, which the tools update as they go.
        bench = self.bench
        candidate = bench.turn_best.candidate if bench.turn_best else bench.candidate
        verdict = None if candidate is None else evaluate(self.problem, candidate)

        step = {
            "round": state["round"],
            "outcome": "ended" if bench.gave_up is None else "gave_up",
            "reason": bench.gave_up or "",
            "candidate_id": None if candidate is None else candidate.candidate_id,
            "valid": None if verdict is None else verdict.valid,
            "primary": None if verdict is None else verdict.primary,
            "accepted": bench.best is not self.start,
            "note": note,
            "notes": notes,
            "tool_calls": cost.tool_calls,
            "llm_calls": cost.llm_calls,
            "tools": tools,
            "events": tool_events(messages, bench.snapshots, node_id="turn"),
            "model_messages": model_messages(messages),
            # The arrangement itself, so a run read back can be replayed: the trace is what a
            # viewer scrubs through, and an identifier alone draws nothing.
            "candidate": None if candidate is None else candidate.to_dict(),
            "verdict": None if verdict is None else verdict.to_dict(),
            **extra,
        }
        return {
            "round": state["round"] + 1,
            "notes": notes,
            "trace": [*state["trace"], step],
            "spend": state["spend"] + cost,
        }


__all__ = ["AgentSession", "NOTE_CHARS", "new_state", "note_of", "spent"]
