"""What the graphs carry: the run record and the turn's ideas, and one team's work in a turn.

The run's graph carries the record, as in the other workflows. Each team is a small graph of its
own: ``Team`` is what it carries from its builder to its critic and back, and ``Reported`` is the
one thing it hands the run when it is done.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from ..budget import Budget, Cost
from ..parallel_exploration.state import gather


class LabState(TypedDict, total=False):
    """The run record :func:`paper_obs.workflows.session.new_state` starts, and the turn's work."""

    problem_id: str
    run_id: str
    budget: Budget
    spend: Cost
    round: int
    trace: list[dict[str, Any]]
    #: The teams' reports of each turn, oldest first: the planner reads the last one.
    notes: list[str]
    #: The planner's reflection and ideas, kept with the turn.
    plan: str
    #: One idea per team, with where it starts.
    ideas: list[Any]
    #: What each team reached this turn, in the order they finished.
    results: Annotated[list[dict[str, Any]], gather]


class Team(TypedDict, total=False):
    """One team's turn: what ``Send`` hands it, then what its builder and critic produce."""

    team: int
    idea: str
    #: Start on an empty board rather than on a copy of the run's best.
    empty: bool
    replies: int
    tools: int
    state: dict[str, Any]
    started: float
    #: The team's own board, which its builder's tools change.
    bench: Any
    #: The builder's conversation, which it takes up again to answer the critique.
    built: list[Any]
    #: The critic's conversation, and what it found.
    critic: list[Any]
    critique: dict[str, str]
    results: Annotated[list[dict[str, Any]], gather]


class Reported(TypedDict):
    """What a team hands back to the run: its entry in the turn's results."""

    results: Annotated[list[dict[str, Any]], gather]


__all__ = ["LabState", "Reported", "Team"]
