"""The run's ceilings, checked around every model call rather than only between turns."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from threading import Event, Lock
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, ToolMessage

from .budget import Budget, Prices, usage

logger = logging.getLogger(__name__)


def answered(messages: list[Any]) -> list[Any]:
    """Return the conversation with an error reply for every tool call nobody answered.

    An OpenAI-compatible provider refuses a conversation holding one, and LangChain can leave
    one behind: a strategist's structured answer that fails validation is sent back with a reply
    to that call alone, whatever else the same reply called.
    """
    fixed: list[Any] = []
    for index, message in enumerate(messages):
        fixed.append(message)
        if not isinstance(message, AIMessage):
            continue
        replies: set[str] = set()
        for item in messages[index + 1:]:
            if not isinstance(item, ToolMessage):
                break
            replies.add(item.tool_call_id)
        missing = [call for call in [*message.tool_calls, *message.invalid_tool_calls]
                   if call.get("id") and call["id"] not in replies]
        if missing:
            logger.warning("answered tool call(s) left without a reply: %s",
                           ", ".join(str(call.get("name")) for call in missing))
        fixed += [ToolMessage("Not run: this call was left without a reply.", tool_call_id=call["id"],
                              name=call.get("name") or "", status="error") for call in missing]
    return fixed


class RunGuard(AgentMiddleware):
    """Refuse a model call past a ceiling, cap its reply to the money left, and report usage.

    One instance serves every turn of a run, so its counters are the run's. A refused call
    answers a stop message of its own instead of reaching the provider.
    """

    def __init__(
        self,
        budget: Budget,
        *,
        max_tokens: int | None,
        prices: Prices | None,
        stop_requested: Event | None,
        on_progress: Callable[[RunGuard], None],
    ) -> None:
        self.budget = budget
        self.max_tokens = max_tokens
        self.prices = prices
        self.stop_requested = stop_requested
        self.on_progress = on_progress
        self.started = time.perf_counter()
        self.calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.tokens_cached = 0
        #: Seconds during which at least one model call was waiting on the provider, the rest of
        #: the run being the lab's own work. Parallel calls overlap, so they are counted once.
        self.model_seconds = 0.0
        self.waiting, self.waiting_since = 0, 0.0
        self.stop_reason: str | None = None
        #: Parallel agents share this guard: their counts and the progress they write take turns.
        self.lock = Lock()

    def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        """Check the ceilings, send the call with its output cap, then count what it used."""
        calls_spent = self.budget.llm_calls > 0 and self.calls >= self.budget.llm_calls
        self.stop_reason = self._interrupted() or ("llm_calls" if calls_spent else None) or self.stop_reason
        # A ceiling the caller asked for is applied; without one the provider decides, and
        # only a cost ceiling of the caller's own may lower it further.
        allowed = self.max_tokens
        if self.stop_reason is None and self.prices is not None and self.budget.max_cost is not None:
            allowed = self._affordable(request)
        if self.stop_reason is not None:
            return AIMessage(content=f"Run stopped: {self.stop_reason}.",
                             response_metadata={"run_guard_stop": True})

        settings = dict(request.model_settings)
        if allowed is not None:
            settings["max_tokens"] = allowed
        with self.lock:
            if self.waiting == 0:
                self.waiting_since = time.perf_counter()
            self.waiting += 1
        try:
            response = handler(request.override(model_settings=settings, messages=answered(request.messages)))
        finally:
            with self.lock:
                # Each end adds the time since the last event while some call was waiting.
                now = time.perf_counter()
                self.model_seconds += now - self.waiting_since
                self.waiting, self.waiting_since = self.waiting - 1, now
        with self.lock:
            self.calls += 1
            for message in response.result:
                tokens_in, tokens_out, tokens_cached = usage(message)
                self.tokens_in += tokens_in
                self.tokens_out += tokens_out
                self.tokens_cached += tokens_cached
            self.on_progress(self)
        cost_spent = self.budget.max_cost is not None and self.cost >= self.budget.max_cost
        self.stop_reason = self._interrupted() or ("max_cost" if cost_spent else None) or self.stop_reason
        return response

    def _interrupted(self) -> str | None:
        """Return "user" when someone asked the run to stop, "seconds" past its deadline."""
        if self.stop_requested is not None and self.stop_requested.is_set():
            return "user"
        if self.budget.seconds > 0 and time.perf_counter() - self.started >= self.budget.seconds:
            return "seconds"
        return None

    def _affordable(self, request: Any) -> int | None:
        """Return the reply length the money left still pays for, or stop the run on too little.

        The prompt is billed first, so its estimated price comes off what is left; a reply
        shorter than 128 tokens would be cut before it says anything useful.
        """
        remaining = self.budget.max_cost - self.cost - _prompt_tokens(request) * self.prices.input / 1e6
        allowed = self.max_tokens
        if self.prices.output > 0:
            affordable = int(remaining * 1e6 / self.prices.output)
            allowed = affordable if allowed is None else min(allowed, affordable)
        if remaining <= 0 or (allowed is not None and allowed < 128):
            self.stop_reason = "max_cost"
        return allowed

    @property
    def cost(self) -> float:
        """Return what the run has spent so far at the caller's prices, zero without them."""
        if self.prices is None:
            return 0.0
        return self.prices.cost(self.tokens_in, self.tokens_out, self.tokens_cached)


def _prompt_tokens(request: Any) -> int:
    """Estimate the tokens a request's prompt is billed, erring high.

    Three characters to a token, which tokenizers splitting more finely than English still
    stay under, and 1024 more for the tool schemas. The provider's reported usage replaces the
    estimate once the reply is back.
    """
    texts = [str(request.system_message.content)] if request.system_message else []
    texts.extend(str(message.content) for message in request.messages)
    return sum(map(len, texts)) // 3 + 1024
