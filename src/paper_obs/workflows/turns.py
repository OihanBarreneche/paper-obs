"""What every workflow that works in turns shares: a turn's allowance, its closing reply, and
the rule that ends the run."""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import HumanMessage, ToolMessage

from .budget import Budget

#: Tool calls and model replies one turn may make, when the manifest did not say.
TOOL_LIMIT = 12
REPLY_LIMIT = 9

#: Turns in a row that may improve nothing before the run ends, when the manifest did not say:
#: a run that keeps producing arrangements and preferring none of them is drifting.
STALLED = 4


class TurnNote(AgentMiddleware):
    """Keep a turn's last model call for the text the next step starts from.

    The call the reply ceiling allows last, or the first one after the tool ceiling is reached,
    is sent without tools and with the closing request appended: its answer is text, the agent
    loop ends on it, and the session keeps it as the note.
    """

    def __init__(self, request: str, *, replies: int, tools: int) -> None:
        super().__init__()
        # Not ``self.tools``: a middleware's ``tools`` are tools it adds to the agent.
        self.request, self.reply_limit, self.tool_limit, self.calls = request, replies, tools, 0

    def wrap_model_call(self, request: Any, handler: Any) -> Any:
        self.calls += 1
        used = sum(1 for item in request.messages
                   if isinstance(item, ToolMessage) and item.status != "error")
        if (self.reply_limit > 1 and self.calls >= self.reply_limit) or (
            self.tool_limit > 0 and used >= self.tool_limit
        ):
            request = request.override(
                tools=[], messages=[*request.messages, HumanMessage(self.request)]
            )
        return handler(request)


class AnswerBrokenCalls(AgentMiddleware):
    """Answer the tool calls a reply wrote with arguments that do not parse.

    LangChain keeps such calls apart (``invalid_tool_calls``) and runs only the others, but an
    OpenAI-compatible provider is sent every call back and refuses one left without an answer.
    Each gets an error reply instead, and a reply that had nothing else to run goes back to the
    model, which can send the call again.
    """

    @hook_config(can_jump_to=["model"])
    def after_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        last = state["messages"][-1]
        broken = getattr(last, "invalid_tool_calls", None) or []
        if not broken:
            return None
        answers = [ToolMessage(
            f"Not run: its arguments are not valid JSON ({call.get('error') or 'cut off'}). "
            "Send the call again with complete arguments.",
            tool_call_id=call["id"], name=call.get("name") or "", status="error",
        ) for call in broken]
        return {"messages": answers, **({} if last.tool_calls else {"jump_to": "model"})}


def allowance(per_turn: int, total: int, spent: int) -> int:
    """Return what one turn may spend, or zero when nothing bounds it.

    A zero per-turn allowance means the turn has none of its own and a zero total means the
    run has none; either way the turn is never given more than the run has left.
    """
    left = 0 if total <= 0 else max(1, total - spent)
    if per_turn <= 0:
        return left
    return per_turn if left <= 0 else min(per_turn, left)


def keep_going(state: dict[str, Any], *, budget: Budget, guard: Any, stall_limit: int) -> bool:
    """Whether the run takes another turn: no ceiling reached, no give-up, and recent progress."""
    if (guard is not None and guard.stop_reason is not None) or budget.stopped_by(
        state["spend"], round=state["round"]
    ):
        return False
    trace = state["trace"]
    if not trace or trace[-1]["outcome"] == "gave_up":
        return False
    recent = trace[-stall_limit:]
    return not (stall_limit > 0 and len(recent) >= stall_limit
                and not any(step["accepted"] for step in recent))


__all__ = ["REPLY_LIMIT", "STALLED", "TOOL_LIMIT", "AnswerBrokenCalls", "TurnNote", "allowance", "keep_going"]
