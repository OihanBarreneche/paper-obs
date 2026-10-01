"""What the graph carries: the run record, the turn's ideas, and what the explorers reached.

As in the other workflows, conversations do not cross turns: each explorer's messages live in
``results`` only until the engine has chosen, then the channel is emptied for the next turn.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from ..budget import Budget, Cost


def gather(current: list[dict[str, Any]] | None, update: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Add the explorers' results as they arrive; ``None`` empties the list for a new turn."""
    return [] if update is None else [*(current or []), *update]


class ExplorationState(TypedDict, total=False):
    """The run record :func:`paper_obs.workflows.session.new_state` starts, and the turn's work."""

    problem_id: str
    run_id: str
    budget: Budget
    spend: Cost
    round: int
    trace: list[dict[str, Any]]
    #: The explorers' reports of each turn, oldest first: the strategist reads the last one.
    notes: list[str]
    #: The strategist's reflection and ideas, kept with the turn.
    plan: str
    #: One idea per explorer, with where it starts.
    ideas: list[Any]
    #: What each explorer reached this turn, in the order they finished.
    results: Annotated[list[dict[str, Any]], gather]


class Branch(TypedDict):
    """What ``Send`` hands one explorer: its idea, where it starts, its allowance, and the state."""

    branch: int
    idea: str
    #: Start on an empty board rather than on a copy of the run's best.
    empty: bool
    replies: int
    tools: int
    state: dict[str, Any]


__all__ = ["Branch", "ExplorationState", "gather"]
