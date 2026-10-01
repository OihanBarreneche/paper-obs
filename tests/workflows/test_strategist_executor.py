"""Offline contract tests for the strategist and executor workflow."""

from __future__ import annotations

import pytest

pytest.importorskip("langchain")

from test_basic_agent_loop import EXAMPLES, Scripted, answer, call, place  # noqa: E402

from paper_obs.storage import load_problem  # noqa: E402
from paper_obs.workflows.budget import Budget  # noqa: E402
from paper_obs.workflows.session import new_state  # noqa: E402
from paper_obs.workflows.strategist_executor.graph import build  # noqa: E402

PLAN = {"reflection": "", "idea": "a 5 × 5 grid of discs", "steps": ["place the grid", "polish it"], "start": "best"}


def test_the_strategist_plans_and_the_executor_builds_and_reports() -> None:
    problem = load_problem(EXAMPLES / "circle_25_in_square.json")
    model = Scripted(replies=[
        call("Plan", PLAN, "plan-1"),
        place(2.0, "place"),
        answer("Built the grid: score 2, valid."),
    ])
    model.seen.clear()
    budget = Budget(rounds=1, llm_calls=0, tool_calls=0)
    final = list(build(problem, model=model, budget=budget).stream(
        new_state(problem.problem_id, run_id="test", budget=budget), stream_mode="values"))[-1]

    step = final["trace"][0]
    # The plan crosses from the strategist to the executor, and is kept with the turn.
    assert "Idea: a 5 × 5 grid of discs" in step["plan"]
    assert "Idea: a 5 × 5 grid of discs" in str(model.seen[1][1].content)
    assert step["accepted"] and step["valid"]
    assert step["note"] == "Built the grid: score 2, valid."
    assert final["notes"] == ["Built the grid: score 2, valid."]
    # Every reply is paid for: the strategist's plan and the executor's two replies.
    assert final["spend"].llm_calls == 3


def test_the_strategist_can_go_on_with_what_the_last_turn_reached() -> None:
    problem = load_problem(EXAMPLES / "circle_25_in_square.json")
    model = Scripted(replies=[
        call("Plan", PLAN, "plan-1"), place(2.0, "place-1"), answer("A grid at 2."),
        call("Plan", PLAN, "plan-2"), place(1.5, "place-2"), answer("A grid at 1.5, still gaining."),
        call("Plan", {**PLAN, "start": "last"}, "plan-3"), answer("Went on with it."),
    ])
    model.seen.clear()
    budget = Budget(rounds=3, llm_calls=0, tool_calls=0)
    final = list(build(problem, model=model, budget=budget).stream(
        new_state(problem.problem_id, run_id="test", budget=budget), stream_mode="values"))[-1]

    # Turn 2 opens on the run's best; turn 3 on the smaller grid turn 2 reached, which it says.
    assert "You start this turn on it" in str(model.seen[4][1].content)
    third = str(model.seen[7][1].content)
    assert "Start: the arrangement the last turn reached." in third
    assert "You start this turn on the arrangement the last turn reached" in third and '"scale":1.5' in third
    # The run's best is kept whatever a turn starts on.
    assert final["trace"][-1]["accepted"] is False and final["trace"][0]["primary"] == pytest.approx(2.0)
