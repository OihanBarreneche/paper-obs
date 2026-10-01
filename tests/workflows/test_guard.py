"""A run can stop between model calls without waiting for its whole turn."""

from __future__ import annotations

from threading import Event
from typing import Any

import pytest

pytest.importorskip("langchain")

from langchain.agents.middleware.types import ModelRequest, ModelResponse  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402

from paper_obs.workflows.budget import Budget, Prices  # noqa: E402
from paper_obs.workflows.guard import RunGuard  # noqa: E402


def test_usage_is_reported_after_each_reply_and_stop_prevents_the_next() -> None:
    signal = Event()
    progress: list[tuple[int, int, int]] = []
    guard = RunGuard(Budget(), max_tokens=4096, prices=None, stop_requested=signal,
                     on_progress=lambda guard: progress.append(
                         (guard.calls, guard.tokens_in, guard.tokens_out, guard.tokens_cached)))
    request = ModelRequest(model=None, messages=[HumanMessage(content="Place shapes")])  # type: ignore[arg-type]
    sent: list[int] = []

    def answer(value: Any) -> ModelResponse[Any]:
        sent.append(value.model_settings["max_tokens"])
        return ModelResponse(result=[AIMessage(content="Done", usage_metadata={
            "input_tokens": 120, "output_tokens": 75, "total_tokens": 195,
        })])

    guard.wrap_model_call(request, answer)
    assert sent == [4096]
    assert progress == [(1, 120, 75, 0)]
    signal.set()
    guard.wrap_model_call(request, answer)
    assert sent == [4096]
    assert guard.stop_reason == "user"


def test_no_output_ceiling_leaves_the_provider_its_own() -> None:
    """An absent ceiling is an absent field, not a null the provider has to interpret."""
    guard = RunGuard(Budget(), max_tokens=None, prices=None, stop_requested=None,
                     on_progress=lambda *_: None)
    request = ModelRequest(model=None, messages=[HumanMessage(content="Place shapes")])  # type: ignore[arg-type]
    seen: list[dict[str, Any]] = []

    def answer(value: Any) -> ModelResponse[Any]:
        seen.append(dict(value.model_settings))
        return ModelResponse(result=[AIMessage(content="Done")])

    guard.wrap_model_call(request, answer)
    assert "max_tokens" not in seen[0]


def test_cost_remaining_reduces_the_next_output_limit() -> None:
    guard = RunGuard(Budget(max_cost=0.01), max_tokens=4096, prices=Prices(0, 5),
                     stop_requested=None, on_progress=lambda *_: None)
    request = ModelRequest(model=None, messages=[HumanMessage(content="Place shapes")])  # type: ignore[arg-type]
    limits: list[int] = []

    def answer(value: Any) -> ModelResponse[Any]:
        limits.append(value.model_settings["max_tokens"])
        return ModelResponse(result=[AIMessage(content="Done", usage_metadata={
            "input_tokens": 100, "output_tokens": 1000, "total_tokens": 1100,
        })])

    guard.wrap_model_call(request, answer)
    guard.wrap_model_call(request, answer)
    assert limits == [2000, 1000]
    assert guard.stop_reason == "max_cost"


def test_a_call_left_without_a_reply_is_answered_before_the_request_leaves() -> None:
    """A structured answer refused by validation is sent back with a reply to that call alone."""
    guard = RunGuard(Budget(), max_tokens=None, prices=None, stop_requested=None,
                     on_progress=lambda *_: None)
    reply = AIMessage(content="", tool_calls=[
        {"name": "Ideas", "args": {}, "id": "ideas", "type": "tool_call"},
        {"name": "read_state", "args": {}, "id": "other", "type": "tool_call"},
    ])
    request = ModelRequest(model=None, messages=[  # type: ignore[arg-type]
        HumanMessage(content="Plan"), reply, ToolMessage("Invalid Ideas", tool_call_id="ideas"),
    ])
    seen: list[list[Any]] = []

    def answer(value: Any) -> ModelResponse[Any]:
        seen.append(list(value.messages))
        return ModelResponse(result=[AIMessage(content="Done")])

    guard.wrap_model_call(request, answer)
    after = seen[0][seen[0].index(reply) + 1:]
    assert {item.tool_call_id for item in after if isinstance(item, ToolMessage)} == {"ideas", "other"}
    assert all(isinstance(item, ToolMessage) for item in after)
