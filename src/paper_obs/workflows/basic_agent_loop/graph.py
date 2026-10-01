"""Turns of one agent, until the run stops improving.

A *turn* hands a fresh agent the run's best arrangement, the engine judges everything it
proposes, and the agent's last reply — sent without tools — is its note to the next turn. What
crosses from one turn to the next is the best arrangement, a journal the engine writes, and
that note; never the transcript. Inside a turn, the model loop, the tool calls and the limits
are LangChain's; what is written here is only what surrounds them.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph

from paper_obs.agent_tools.engine import Workbench, basic_agent_tools
from paper_obs.domain.candidate import Candidate
from paper_obs.domain.problem import Problem
from paper_obs.workflows.briefing import opening
from paper_obs.workflows.budget import Budget
from paper_obs.workflows.session import AgentSession
from paper_obs.workflows.turns import (
    REPLY_LIMIT, STALLED, TOOL_LIMIT, AnswerBrokenCalls, TurnNote, allowance, keep_going,
)

from .state import SearchState

PROMPTS = Path(__file__).with_name("prompts")


def build(
    problem: Problem, *, model: BaseChatModel, budget: Budget,
    settings: dict[str, Any] | None = None, guard: Any = None, start: Candidate | None = None,
) -> Any:
    """Return the compiled graph of the workflow: one turn node, one routing, one loop.

    ``start`` is the arrangement a resumed run had kept; a new run starts from nothing.
    """
    settings = settings or {}
    reply_limit = int(settings.get("reply_limit", REPLY_LIMIT))
    tool_limit = int(settings.get("tool_limit", TOOL_LIMIT))
    stall_limit = int(settings.get("stall_limit", STALLED))
    bench = Workbench(problem=problem, candidate=start)
    session = AgentSession(problem, bench)
    system_prompt = (PROMPTS / "placer.md").read_text(encoding="utf-8")
    template = (PROMPTS / "turn.md").read_text(encoding="utf-8")
    note_request = (PROMPTS / "note.md").read_text(encoding="utf-8")

    def turn_node(state: dict[str, Any]) -> dict[str, Any]:
        """Run one turn: a fresh agent improves the best arrangement, then writes its note."""
        session.open_turn()
        replies = allowance(reply_limit, budget.llm_calls, state["spend"].llm_calls)
        tools = allowance(tool_limit, budget.tool_calls, state["spend"].tool_calls)
        agent = create_agent(
            model=model,
            tools=basic_agent_tools(bench),
            system_prompt=system_prompt,
            middleware=[
                TurnNote(note_request, replies=replies, tools=tools),
                AnswerBrokenCalls(),
                *([guard] if guard is not None else []),
                # A zero allowance is no allowance: a ceiling of zero is not installed at all.
                *([ModelCallLimitMiddleware(run_limit=replies)] if replies else []),
                # Calls past the ceiling are refused and the loop goes on, so the next reply is
                # the note rather than an abrupt end.
                *([ToolCallLimitMiddleware(run_limit=tools, exit_behavior="continue")] if tools else []),
            ],
        )
        started = time.perf_counter()
        # No config on purpose: create_agent sizes its own recursion limit for the middleware
        # nodes it adds, and a limit derived from the call budget would cut a turn short.
        answer = agent.invoke({"messages": [("user", opening(
            template, problem, bench, state, replies=replies, tools=tools,
            output_tokens=getattr(guard, "max_tokens", None),
            share_reference=bool(settings.get("share_reference", 0)), stalled=stall_limit,
        ))]})
        return session.record(state, answer["messages"], time.perf_counter() - started)

    def route(state: dict[str, Any]) -> str:
        """Send the run round again while it still improves, and end it when it does not."""
        return "again" if keep_going(state, budget=budget, guard=guard, stall_limit=stall_limit) else "done"

    graph = StateGraph(SearchState)
    graph.add_node("turn", turn_node)
    graph.add_edge(START, "turn")
    graph.add_conditional_edges("turn", route, {"again": "turn", "done": END})
    return graph.compile()


__all__ = ["build"]
