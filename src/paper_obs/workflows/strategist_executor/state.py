"""What the graph carries: the run record, and the plan handed from strategist to executor.

As in the basic loop, the conversation and the geometry stay out of it: each agent opens on a
short message, and the arrangements live on the bench the executor's tools share.
"""

from __future__ import annotations

from typing import Any, TypedDict

from ..budget import Budget, Cost


class StrategyState(TypedDict, total=False):
    """The run record :func:`paper_obs.workflows.session.new_state` starts, and the plan."""

    problem_id: str
    run_id: str
    budget: Budget
    spend: Cost
    round: int
    trace: list[dict[str, Any]]
    #: The executor's reports, oldest first: the last one is what the strategist reads next.
    notes: list[str]
    #: The strategist's plan for the turn under way, as the executor reads it.
    plan: str


__all__ = ["StrategyState"]
