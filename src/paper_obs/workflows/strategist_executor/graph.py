"""A strategist that chooses the idea, an executor that builds it, turn after turn.

Each turn, the strategist reads where the run stands — the best arrangement, the journal, the
executor's last report — reflects on what the last attempt showed, and answers a structured
``Plan``. A fresh executor then builds that plan with the engine's tools and reports back. The
plan is all that crosses from one agent to the other; the best arrangement, the journal and the
report are all that cross from one turn to the next.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Literal

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from paper_obs.agent_tools.engine import Workbench, basic_agent_tools
from paper_obs.domain.candidate import Candidate
from paper_obs.domain.problem import Problem
from paper_obs.workflows.briefing import opening
from paper_obs.workflows.budget import Budget
from paper_obs.workflows.session import AgentSession, spent
from paper_obs.workflows.turns import (
    REPLY_LIMIT, STALLED, TOOL_LIMIT, AnswerBrokenCalls, TurnNote, allowance, keep_going,
)

from .state import StrategyState

PROMPTS = Path(__file__).with_name("prompts")


class Plan(BaseModel):
    """The strategist's answer for one turn."""

    reflection: str = Field(description="what the last attempt showed, in one or two sentences; empty on the first turn")
    idea: str = Field(description="the arrangement to build this turn, in one sentence")
    steps: list[str] = Field(description="how the executor should build and tune it, in a few short steps")
    start: Literal["best", "last"] = Field(
        description="'best' to start on the run's best arrangement; 'last' to go on with the arrangement "
                    "the last turn reached, when its idea was still gaining without beating the best")

    def text(self) -> str:
        """Return the plan as the executor reads it."""
        lines = [f"Reflection: {self.reflection}"] if self.reflection else []
        lines.append(f"Idea: {self.idea}")
        lines.append("Start: the run's best arrangement." if self.start == "best"
                     else "Start: the arrangement the last turn reached.")
        lines += [f"{number}. {step}" for number, step in enumerate(self.steps, 1)]
        return "\n".join(lines)


def build(
    problem: Problem, *, model: BaseChatModel, budget: Budget,
    settings: dict[str, Any] | None = None, guard: Any = None, start: Candidate | None = None,
) -> Any:
    """Return the compiled graph: strategist, executor, and the routing that loops them."""
    settings = settings or {}
    reply_limit = int(settings.get("reply_limit", REPLY_LIMIT))
    tool_limit = int(settings.get("tool_limit", TOOL_LIMIT))
    stall_limit = int(settings.get("stall_limit", STALLED))
    bench = Workbench(problem=problem, candidate=start)
    session = AgentSession(problem, bench)
    prompt = lambda name: (PROMPTS / name).read_text(encoding="utf-8")  # noqa: E731
    guarded = [guard] if guard is not None else []
    strategist = create_agent(
        model=model, system_prompt=prompt("strategist.md"),
        response_format=ToolStrategy(Plan), middleware=guarded,
    )

    def brief(template: str, state: dict[str, Any], replies: int, tools: int, **extra: str) -> str:
        return opening(
            prompt(template), problem, bench, state, replies=replies, tools=tools,
            output_tokens=getattr(guard, "max_tokens", None),
            share_reference=bool(settings.get("share_reference", 0)), stalled=stall_limit, **extra,
        )

    def strategist_node(state: dict[str, Any]) -> dict[str, Any]:
        """Reflect on the last attempt, choose the idea this turn builds and where it starts."""
        # What the last turn reached, kept before the turn opens on the run's best.
        reached = bench.turn_best.candidate if bench.turn_best else bench.candidate
        session.open_turn()
        answer = strategist.invoke({"messages": [("user", brief(
            "strategy.md", state, reply_limit, tool_limit,
            report=state["notes"][-1] if state["notes"] else "No turn has run yet.",
            last_plan=state.get("plan") or "None yet: this is the first turn.",
        ))]})
        plan = answer.get("structured_response")
        # A model that answered in prose instead of the Plan tool still hands its words over.
        text = plan.text() if isinstance(plan, Plan) else answer["messages"][-1].text
        if isinstance(plan, Plan) and plan.start == "last" and reached is not None:
            bench.candidate = reached
        return {"plan": text, "spend": state["spend"] + spent(answer["messages"])}

    def executor_node(state: dict[str, Any]) -> dict[str, Any]:
        """Build the plan with the engine's tools, then report what came of it."""
        replies = allowance(reply_limit, budget.llm_calls, state["spend"].llm_calls)
        tools = allowance(tool_limit, budget.tool_calls, state["spend"].tool_calls)
        executor = create_agent(
            model=model,
            tools=basic_agent_tools(bench),
            system_prompt=prompt("executor.md"),
            middleware=[
                TurnNote(prompt("report.md"), replies=replies, tools=tools),
                AnswerBrokenCalls(),
                *guarded,
                *([ModelCallLimitMiddleware(run_limit=replies)] if replies else []),
                *([ToolCallLimitMiddleware(run_limit=tools, exit_behavior="continue")] if tools else []),
            ],
        )
        started = time.perf_counter()
        answer = executor.invoke({"messages": [("user", brief(
            "execution.md", state, replies, tools, plan=state["plan"],
        ))]})
        return session.record(state, answer["messages"], time.perf_counter() - started, plan=state["plan"])

    def route(state: dict[str, Any]) -> str:
        """Plan again while the run still improves, and end it when it does not."""
        return "again" if keep_going(state, budget=budget, guard=guard, stall_limit=stall_limit) else "done"

    graph = StateGraph(StrategyState)
    graph.add_node("strategist", strategist_node)
    graph.add_node("executor", executor_node)
    graph.add_edge(START, "strategist")
    graph.add_edge("strategist", "executor")
    graph.add_conditional_edges("executor", route, {"again": "strategist", "done": END})
    return graph.compile()


__all__ = ["Plan", "build"]
