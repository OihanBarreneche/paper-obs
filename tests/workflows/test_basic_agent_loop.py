"""Offline contract tests for the turn loop and its run recorder."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("langchain")

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from paper_obs.agent_tools.engine import Workbench, basic_agent_tools, engine_tools
from paper_obs.storage import load_problem
from paper_obs.workflows.basic_agent_loop.graph import build
from paper_obs.workflows.budget import Budget
from paper_obs.workflows.session import new_state

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


class Scripted(BaseChatModel):
    """A model that answers the script it was given, in order, repeating its last reply."""

    replies: list[AIMessage]
    index: int = 0
    seen: list[list[Any]] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "Scripted":
        return self

    def _generate(
        self, messages: list[Any], stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None, **kwargs: Any,
    ) -> ChatResult:
        self.seen.append(messages)
        reply = self.replies[min(self.index, len(self.replies) - 1)]
        self.index += 1
        return ChatResult(generations=[ChatGeneration(message=reply)])


def call(name: str, args: dict[str, Any], identifier: str) -> AIMessage:
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": args, "id": identifier, "type": "tool_call"}],
        usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
    )


def answer(content: str) -> AIMessage:
    return AIMessage(content=content,
                     usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110})


def conversation(model: Scripted) -> str:
    """Return everything the model was ever sent, as one searchable string."""
    return json.dumps([[str(message.content) for message in seen] for seen in model.seen])


def opening_of(model: Scripted, call_index: int) -> str:
    """Return the opening message a model call was made with."""
    return str(model.seen[call_index][1].content)


def grid_spots() -> list[dict[str, float]]:
    return [{"x": -4.0 + 2 * (i % 5), "y": -4.0 + 2 * (i // 5)} for i in range(25)]


def place(scale: float, identifier: str) -> AIMessage:
    return call("place_shapes", {"placements": grid_spots(), "scale": scale}, identifier)


def run(problem, model: Scripted, budget: Budget, **settings: Any):
    """Run the workflow to its end and return the last state it wrote."""
    return list(
        build(problem, model=model, budget=budget, settings=settings or None)
        .stream(new_state(problem.problem_id, run_id="test", budget=budget), stream_mode="values")
    )[-1]


@pytest.fixture(scope="module")
def problem():
    return load_problem(EXAMPLES / "circle_25_in_square.json")


def test_the_agent_is_offered_geometry_and_the_run_ending_but_no_note_tool(problem) -> None:
    names = {item.name for item in engine_tools(Workbench(problem=problem))}
    assert {"place_shapes", "edit_shapes", "give_up", "read_state", "polish"} <= names
    assert not {"remember", "submit_solution"} & names
    narrowed = {item.name for item in basic_agent_tools(Workbench(problem=problem))}
    assert narrowed <= names and "place_shapes" in narrowed


def test_each_turn_records_one_step_and_opens_a_fresh_conversation(problem) -> None:
    model = Scripted(replies=[
        place(2.0, "place"),
        answer("The 5x5 grid at scale 2 holds."),
        call("give_up", {"reason": "nothing better to try"}, "stop"),
        answer("Stopped."),
    ])
    budget = Budget(rounds=4, llm_calls=8, tool_calls=8)
    final = run(problem, model, budget)

    assert model.index == 4
    assert final["round"] == 2
    # One step per turn, carrying that turn's tool calls rather than one row per call.
    first, second = final["trace"]
    assert first["accepted"] and first["valid"]
    assert first["outcome"] == "ended"
    assert first["note"] == "The 5x5 grid at scale 2 holds."
    assert [event["tool"] for event in first["events"]] == ["place_shapes"]
    assert first["events"][0]["node_id"] == "turn"
    assert second["outcome"] == "gave_up"
    assert final["spend"].llm_calls == 4
    # The second turn opens a new conversation instead of carrying the first one.
    assert len(model.seen[2]) < len(model.seen[1])


def test_the_second_turn_is_told_where_the_run_stands(problem) -> None:
    model = Scripted(replies=[
        place(2.0, "place"),
        answer("The 5x5 grid at scale 2 holds."),
        call("give_up", {"reason": "nothing better to try"}, "stop"),
        answer("Stopped."),
    ])
    run(problem, model, Budget(rounds=4, llm_calls=8, tool_calls=8))

    first, second = opening_of(model, 0), opening_of(model, 2)
    assert "There is no arrangement yet" in first
    assert "You have no note yet" in first
    assert "this is turn 2 of at most 4" in second
    assert "larger number is better" in second
    assert "Your environment this turn" in second
    assert "the endpoint decides how long a reply" in second
    assert "The run's best scores 2" in second and "You start this turn on it" in second
    assert "Journal of the run" in second
    assert "turn 1: reached 2 (valid), a new best; place_shapes" in second
    assert "Your note from the last turn" in second and "The 5x5 grid at scale 2 holds." in second


def test_the_last_reply_of_a_turn_is_kept_for_the_note(problem) -> None:
    """The reply ceiling's last call is sent without tools, asking for the note."""
    model = Scripted(replies=[
        call("read_state", {}, "one"), call("read_state", {}, "two"), answer("Nothing placed yet."),
    ])
    final = run(problem, model, Budget(rounds=1, llm_calls=3, tool_calls=8), reply_limit=3)

    last_request = model.seen[2][-1]
    assert isinstance(last_request, HumanMessage)
    assert "last reply of the turn" in str(last_request.content)
    assert all("last reply of the turn" not in str(item.content) for item in model.seen[1])
    assert final["trace"][0]["note"] == "Nothing placed yet."
    assert final["notes"] == ["Nothing placed yet."]


def test_a_call_whose_arguments_do_not_parse_is_answered_before_the_next_reply(problem) -> None:
    """A provider refuses a conversation holding a tool call nobody answered."""
    broken = AIMessage(
        content="", tool_calls=call("read_state", {}, "fine").tool_calls,
        invalid_tool_calls=[{"name": "place_shapes", "args": '{"placements": [', "id": "cut",
                             "error": "unterminated JSON", "type": "invalid_tool_call"}],
        usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
    )
    model = Scripted(replies=[broken, answer("done")])
    run(problem, model, Budget(rounds=1, llm_calls=0, tool_calls=0))

    answered = {item.tool_call_id: item for item in model.seen[1] if isinstance(item, ToolMessage)}
    assert set(answered) == {"fine", "cut"}
    assert answered["cut"].status == "error"


def test_a_tool_ceiling_leaves_the_turn_its_note_and_the_budget_ends_the_run(problem) -> None:
    model = Scripted(replies=[
        call("read_state", {}, "one"), call("read_state", {}, "two"), answer("Read twice."),
    ])
    final = run(problem, model, Budget(rounds=4, llm_calls=8, tool_calls=2))

    assert final["spend"].tool_calls == 2
    assert "last reply of the turn" in str(model.seen[2][-1].content)
    assert final["trace"][0]["note"] == "Read twice."
    assert final["round"] == 1


def test_a_reply_the_model_did_not_produce_is_not_counted(problem) -> None:
    """A limit that ends the turn with a message of its own is not a model call."""
    model = Scripted(replies=[call("read_state", {}, f"read-{n}") for n in range(4)])
    final = run(problem, model, Budget(rounds=1, llm_calls=2, tool_calls=8), reply_limit=2)

    assert model.index == 2
    assert final["spend"].llm_calls == 2
    assert final["trace"][0]["note"] == ""


def test_the_next_turn_starts_on_the_best_arrangement_not_the_last_one(problem) -> None:
    model = Scripted(replies=[
        place(2.0, "good"),
        call("place_shapes", {"placements": [{"x": 0.0, "y": 0.0}] * 25, "scale": 2.0}, "pile"),
        answer("The pile overlaps."),
        call("read_state", {}, "look"),
        call("give_up", {"reason": "done"}, "stop"),
        answer("Stopped."),
    ])
    final = run(problem, model, Budget(rounds=3, llm_calls=12, tool_calls=12))

    looked = next(item for item in model.seen[4] if isinstance(item, ToolMessage))
    state = json.loads(looked.content)
    assert state["valid"] is True and state["score"] == pytest.approx(2.0)
    assert state["candidate_id"] == final["trace"][0]["candidate_id"]
    assert '"valid":true' in opening_of(model, 3)


def test_a_run_that_improves_nothing_for_four_turns_ends(problem) -> None:
    """An unbounded turn loop still has a net: drifting is not searching."""
    model = Scripted(replies=[
        place(2.0, "first"), answer("Placed."),
        *[item for scale in (1.9, 1.8, 1.7, 1.6)
          for item in (place(scale, f"t{scale}"), answer("Smaller."))],
    ])
    final = run(problem, model, Budget(rounds=20, llm_calls=16, tool_calls=16))

    assert len(final["trace"]) == 5
    assert final["trace"][0]["accepted"]
    assert not any(step["accepted"] for step in final["trace"][1:])


def test_a_turn_keeps_the_best_it_reached_even_when_it_ends_lower(problem) -> None:
    """What the run keeps from a turn is the best that turn reached, not what it ended on."""
    model = Scripted(replies=[place(2.0, "good"), place(1.5, "worse"), answer("Went lower.")])
    final = run(problem, model, Budget(rounds=1, llm_calls=8, tool_calls=8))

    assert final["trace"][0]["accepted"] and final["trace"][0]["valid"]
    assert final["trace"][0]["primary"] == pytest.approx(2.0, abs=1e-9)


def test_the_published_record_is_told_only_when_the_run_asks_for_it(problem) -> None:
    """The catalogue's record is a comparison point, and the run decides whether to share it."""
    with_record = replace(problem, metadata={"reference": {
        "value": 2.0, "unit": "packing scale", "status": "proved",
        "author": "G. Wengerodt", "date": "1987",
    }})

    def script() -> list[AIMessage]:
        return [
            place(2.0, "place"), answer("Grid."),
            call("give_up", {"reason": "nothing better to try"}, "stop"), answer("Stopped."),
        ]

    budget = Budget(rounds=4, llm_calls=8, tool_calls=8)
    asked = Scripted(replies=script())
    run(with_record, asked, budget, share_reference=1)
    opening = opening_of(asked, 2)
    assert "A published record for this family" in opening
    assert "2 packing scale (proved optimum)" in opening
    assert "the run's best measures 2 packing scale: level with the record." in opening

    quiet = Scripted(replies=script())
    run(with_record, quiet, budget)
    assert "A published record for this family" not in opening_of(quiet, 2)


def test_an_unlimited_allowance_installs_no_ceiling(problem) -> None:
    """A dash in the counts leaves the turn to the agent: it ends when the model ends it."""
    model = Scripted(replies=[
        *[call("read_state", {}, f"read-{n}") for n in range(6)],
        call("give_up", {"reason": "nothing left to try"}, "stop"),
        answer("Stopped."),
    ])
    budget = Budget(rounds=0, llm_calls=0, tool_calls=0)
    final = run(problem, model, budget, reply_limit=0, tool_limit=0)

    # Six reads and the give-up are more tool calls than the shipped allowances allow in one
    # turn, and no turn ceiling exists to cut them: the run stops on the agent's own word.
    assert final["trace"][0]["tool_calls"] == 7
    assert final["trace"][-1]["outcome"] == "gave_up"
    assert final["spend"].llm_calls == 8
    assert "last reply of the turn" not in conversation(model)
