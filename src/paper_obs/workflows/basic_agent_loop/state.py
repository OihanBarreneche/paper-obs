"""What the outer graph carries between turns.

The graph does not carry the conversation: each turn builds a fresh agent and opens it with a
short message, so the messages of a finished turn never reach the next one. What it carries is
the run record that the shared session writes and the run file keeps — how many turns have
passed, what the run has spent, its trace and the agent's notes.

The geometry is deliberately absent. The arrangement under work and the best valid one found
so far live on the bench the tools share (:class:`paper_obs.agent_tools.engine.Workbench`); a
channel here would be a second copy to keep in step, and the run file already stores each
turn's arrangement.
"""

from __future__ import annotations

from typing import Any, TypedDict

from ..budget import Budget, Cost


class SearchState(TypedDict, total=False):
    """The run record, exactly as :func:`paper_obs.workflows.session.new_state` starts it."""

    problem_id: str
    run_id: str
    budget: Budget
    spend: Cost
    round: int
    trace: list[dict[str, Any]]
    notes: list[str]


__all__ = ["SearchState"]
