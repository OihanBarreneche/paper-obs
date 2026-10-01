"""Offline contract tests for the research lab: teams of a builder and a critic."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("langchain")

from langchain_core.language_models import BaseChatModel  # noqa: E402
from langchain_core.messages import ToolMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: E402
from test_basic_agent_loop import EXAMPLES, answer, call, grid_spots  # noqa: E402

from paper_obs.storage import load_problem  # noqa: E402
from paper_obs.workflows.budget import Budget  # noqa: E402
from paper_obs.workflows.research_lab.graph import build  # noqa: E402
from paper_obs.workflows.session import new_state  # noqa: E402

IDEAS = {"reflection": "", "ideas": [
    {"idea": "idea one: follow the critic", "steps": [], "start": "empty"},
    {"idea": "idea two: shrink instead", "steps": [], "start": "empty"},
]}
CRITIQUE = {"flaw": "the grid leaves room on every side", "evidence": "the largest void is 0.5 wide",
            "move": "grow the grid to scale 2"}


class Reactive(BaseChatModel):
    """Answers by who asks and what it is shown, so teams running at once keep to their own."""

    @property
    def _llm_type(self) -> str:
        return "reactive"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "Reactive":
        return self

    def _generate(self, messages: list[Any], stop: Any = None, run_manager: Any = None,
                  **kwargs: Any) -> ChatResult:
        system, last = str(messages[0].content), messages[-1]
        seen = " ".join(str(message.content) for message in messages)
        team = "one" if "idea one" in seen else "two"
        if system.startswith("# The planner"):
            reply = call("Ideas", IDEAS, "ideas")
        elif system.startswith("# The critic"):
            # One read of the arrangement, then the critique.
            reply = call("Critique", CRITIQUE, f"critique-{team}") if isinstance(last, ToolMessage) \
                else call("read_voids", {}, f"read-{team}")
        elif isinstance(last, ToolMessage):
            reply = answer(f"team {team} done")
        elif "A critic read" in str(last.content):
            # Team one takes the move and gains; team two answers with a worse arrangement.
            scale = 2.0 if team == "one" else 1.0
            reply = call("place_shapes", {"placements": grid_spots(), "scale": scale}, f"revise-{team}")
        else:
            reply = call("place_shapes", {"placements": grid_spots(), "scale": 1.5}, f"build-{team}")
        return ChatResult(generations=[ChatGeneration(message=reply)])


def test_each_team_builds_is_criticised_answers_and_the_engine_keeps_the_best() -> None:
    problem = load_problem(EXAMPLES / "circle_25_in_square.json")
    budget = Budget(rounds=1, llm_calls=0, tool_calls=0)
    final = list(build(problem, model=Reactive(), budget=budget, settings={"teams": 2, "sandbox": 0}).stream(
        new_state(problem.problem_id, run_id="test", budget=budget), stream_mode="values"))[-1]

    step = final["trace"][0]
    # The engine kept team one's answer to its critique, the largest valid scale.
    assert step["valid"] and step["accepted"] and step["primary"] == pytest.approx(2.0, abs=1e-9)
    assert "Team 1 (empty): idea one" in step["plan"]
    lanes = {lane["id"]: lane for lane in step["lanes"]}
    assert set(lanes) == {"team 1", "team 2"}
    # A team's view gathers its builder and its critic, and keeps the critic's point of view.
    assert lanes["team 1"]["agents"] == ["builder 1", "critic 1"]
    assert all(lane["critique"] == CRITIQUE for lane in lanes.values())
    one, two = lanes["team 1"]["revision"], lanes["team 2"]["revision"]
    assert one["paid"] and one["before"] == pytest.approx(1.5) and one["after"] == pytest.approx(2.0)
    assert not two["paid"] and two["after"] == pytest.approx(1.5)
    assert lanes["team 1"]["primary"] == pytest.approx(2.0) and lanes["team 2"]["primary"] == pytest.approx(1.5)
    # Every reply and tool call is told apart by the agent that made it.
    agents = {"builder 1", "critic 1", "builder 2", "critic 2"}
    assert {event["branch_id"] for event in step["events"]} == agents
    assert {message["branch_id"] for message in step["model_messages"]} == agents
    reads = [event for event in step["events"] if event["tool"] == "read_voids"]
    assert {event["branch_id"] for event in reads} == {"critic 1", "critic 2"}
    # The planner reads each team's report, critique and outcome on the next turn.
    assert "Its critic: the grid leaves room on every side" in step["note"]
    assert "the critique paid off" in step["note"] and "the critique brought no gain" in step["note"]
    # The planner's answer, then per team: build and report, read and critique, answer and report.
    assert final["spend"].llm_calls == 1 + 2 * 6
    assert final["results"] == []


def test_the_sandbox_needs_deno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("paper_obs.workflows.research_lab.graph.deno", lambda: None)
    problem = load_problem(EXAMPLES / "circle_25_in_square.json")
    with pytest.raises(ValueError, match="Deno"):
        build(problem, model=Reactive(), budget=Budget(), settings={"sandbox": 1})
    build(problem, model=Reactive(), budget=Budget(), settings={"sandbox": 0})
