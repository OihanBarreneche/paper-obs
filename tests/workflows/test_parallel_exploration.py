"""Offline contract tests for the parallel exploration workflow."""

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
from paper_obs.workflows.parallel_exploration.graph import build  # noqa: E402
from paper_obs.workflows.session import new_state  # noqa: E402

IDEAS = {"reflection": "", "ideas": [
    {"idea": "a grid at scale 2", "steps": [], "start": "best"},
    {"idea": "a grid at scale 1.5", "steps": [], "start": "empty"},
]}
#: The first message each explorer read, in the order they read it.
OPENINGS: list[str] = []


class Reactive(BaseChatModel):
    """Answers by what it is shown, so explorers running at once cannot take each other's turn."""

    @property
    def _llm_type(self) -> str:
        return "reactive"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "Reactive":
        return self

    def _generate(self, messages: list[Any], stop: Any = None, run_manager: Any = None,
                  **kwargs: Any) -> ChatResult:
        system, last = str(messages[0].content), messages[-1]
        if "The strategist" in system:
            reply = call("Ideas", IDEAS, "ideas")
        elif isinstance(last, ToolMessage):
            reply = answer("done")
        else:
            OPENINGS.append(str(last.content))
            scale = 2.0 if "a grid at scale 2" in str(last.content) else 1.5
            reply = call("place_shapes", {"placements": grid_spots(), "scale": scale}, f"place-{scale}")
        return ChatResult(generations=[ChatGeneration(message=reply)])


def test_explorers_run_apart_and_the_engine_keeps_the_best_of_them() -> None:
    problem = load_problem(EXAMPLES / "circle_25_in_square.json")
    budget = Budget(rounds=1, llm_calls=0, tool_calls=0)
    final = list(build(problem, model=Reactive(), budget=budget, settings={"explorers": 2}).stream(
        new_state(problem.problem_id, run_id="test", budget=budget), stream_mode="values"))[-1]

    step = final["trace"][0]
    # Both ideas were built; the engine kept the larger valid scale, whichever finished first.
    assert step["valid"] and step["accepted"] and step["primary"] == pytest.approx(2.0, abs=1e-9)
    assert {event["branch_id"] for event in step["events"]} == {"explorer 1", "explorer 2"}
    assert "Explorer 1 (best): a grid at scale 2" in step["plan"]
    # Each explorer keeps a view of its own: its arrangement, its record, its idea, its replies.
    lanes = {lane["id"]: lane for lane in step["lanes"]}
    assert set(lanes) == {"explorer 1", "explorer 2"}
    assert lanes["explorer 1"]["primary"] == pytest.approx(2.0, abs=1e-9)
    assert lanes["explorer 2"]["primary"] == pytest.approx(1.5, abs=1e-9)
    assert all(lane["valid"] and lane["accepted"] for lane in lanes.values())
    assert lanes["explorer 2"]["idea"].startswith("a grid at scale 1.5")
    assert {message["branch_id"] for message in step["model_messages"]} == {"explorer 1", "explorer 2"}
    assert step["note"].startswith("Explorer 1: done") and "Explorer 2: done" in step["note"]
    # The strategist's answer, then two replies per explorer.
    assert final["spend"].llm_calls == 5
    assert final["results"] == []


def test_the_strategist_chooses_whether_an_explorer_starts_on_the_best_or_an_empty_board() -> None:
    problem = load_problem(EXAMPLES / "circle_25_in_square.json")
    budget = Budget(rounds=2, llm_calls=0, tool_calls=0)
    OPENINGS.clear()
    final = list(build(problem, model=Reactive(), budget=budget, settings={"explorers": 2}).stream(
        new_state(problem.problem_id, run_id="test", budget=budget), stream_mode="values"))[-1]

    # On the second turn, only the explorer asked to refine the best is shown it.
    on_best = [text for text in OPENINGS if "The run's best scores 2" in text]
    assert len(on_best) == 1 and "a grid at scale 2" in on_best[0]
    empty = [text for text in OPENINGS[2:] if "a grid at scale 1.5" in text]
    assert len(empty) == 1 and "There is no arrangement yet" in empty[0]
    # The empty board rebuilt 1.5 on its own: no fall back to the best, which stays the run's.
    lanes = {lane["id"]: lane for lane in final["trace"][1]["lanes"]}
    assert lanes["explorer 2"]["primary"] == pytest.approx(1.5, abs=1e-9)
    assert final["trace"][1]["primary"] == pytest.approx(2.0, abs=1e-9)
