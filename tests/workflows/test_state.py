"""The teaching workflow keeps its run record in the graph and its geometry in the tools."""

import pytest

pytest.importorskip("langchain")

from paper_obs.workflows.basic_agent_loop.state import SearchState
from paper_obs.workflows.budget import Budget, Cost
from paper_obs.workflows.session import new_state


def test_the_graph_state_is_the_run_record_and_not_a_conversation() -> None:
    """A turn starts a fresh conversation, so no message channel may cross turns."""
    channels = set(SearchState.__annotations__)
    assert channels == {"problem_id", "run_id", "budget", "spend", "round", "trace", "notes"}
    assert "messages" not in channels


def test_run_record_starts_empty() -> None:
    state = new_state("problem", run_id="run", budget=Budget())
    assert state["round"] == 0
    assert state["spend"] == Cost()
    assert state["trace"] == []
