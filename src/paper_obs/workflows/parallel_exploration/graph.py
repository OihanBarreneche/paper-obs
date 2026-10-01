"""Several ideas explored in parallel each turn, and the engine keeps the best of them.

Each turn, a strategist reflects on the last turn's reports and proposes distinct ideas, one per
explorer. LangGraph's ``Send`` starts one explorer per idea, in parallel: each is a fresh agent
with the engine's tools, working on its own copy of the run's best arrangement or, when the
strategist asks for a new topology, on an empty board. When all have reported, the engine — not
a model — keeps the best valid arrangement any of them reached.
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
from langgraph.types import Send
from pydantic import BaseModel, Field

from paper_obs.agent_tools.engine import Workbench, basic_agent_tools
from paper_obs.domain.candidate import Candidate
from paper_obs.domain.problem import Problem
from paper_obs.workflows.briefing import opening
from paper_obs.workflows.budget import Budget
from paper_obs.workflows.session import AgentSession, note_of, spent
from paper_obs.workflows.turns import (
    REPLY_LIMIT, STALLED, TOOL_LIMIT, AnswerBrokenCalls, TurnNote, allowance, keep_going,
)

from .state import Branch, ExplorationState

PROMPTS = Path(__file__).with_name("prompts")

#: Explorers each turn, when the manifest did not say.
EXPLORERS = 3


class Idea(BaseModel):
    """One arrangement for one explorer to build."""

    idea: str = Field(description="the arrangement, in one sentence")
    steps: list[str] = Field(description="how to build and tune it, in a few short steps")
    start: Literal["best", "empty"] = Field(
        description="'best' to refine the run's best arrangement; 'empty' to build a new topology "
                    "from an empty board, without the best to fall back on")


class Ideas(BaseModel):
    """The strategist's answer for one turn."""

    reflection: str = Field(description="what the last turn's explorers showed, in two sentences; empty on the first turn")
    ideas: list[Idea] = Field(description="one arrangement per explorer, sharing nothing with each other")


def told(item: Idea) -> str:
    """Return an idea as its explorer reads it."""
    start = "Start: the run's best arrangement." if item.start == "best" else "Start: an empty board."
    return "\n".join([item.idea, start, *(f"- {step}" for step in item.steps)])


def build(
    problem: Problem, *, model: BaseChatModel, budget: Budget,
    settings: dict[str, Any] | None = None, guard: Any = None, start: Candidate | None = None,
) -> Any:
    """Return the compiled graph: strategist, parallel explorers, the engine's choice, the loop."""
    settings = settings or {}
    explorers = max(1, int(settings.get("explorers", EXPLORERS)))
    reply_limit = int(settings.get("reply_limit", REPLY_LIMIT))
    tool_limit = int(settings.get("tool_limit", TOOL_LIMIT))
    stall_limit = int(settings.get("stall_limit", STALLED))
    bench = Workbench(problem=problem, candidate=start)
    session = AgentSession(problem, bench)
    prompt = lambda name: (PROMPTS / name).read_text(encoding="utf-8")  # noqa: E731
    guarded = [guard] if guard is not None else []
    strategist = create_agent(
        model=model, system_prompt=prompt("strategist.md"),
        response_format=ToolStrategy(Ideas), middleware=guarded,
    )

    def brief(template: str, state: dict[str, Any], replies: int, tools: int,
              on: Workbench = bench, **extra: str) -> str:
        return opening(
            prompt(template), problem, on, state, replies=replies, tools=tools,
            output_tokens=getattr(guard, "max_tokens", None),
            share_reference=bool(settings.get("share_reference", 0)), stalled=stall_limit, **extra,
        )

    def strategist_node(state: dict[str, Any]) -> dict[str, Any]:
        """Reflect on the last turn and propose one distinct idea per explorer."""
        session.open_turn()
        answer = strategist.invoke({"messages": [("user", brief(
            "strategy.md", state, reply_limit, tool_limit, explorers=str(explorers),
            reports=state["notes"][-1] if state["notes"] else "No turn has run yet.",
        ))]})
        found = answer.get("structured_response")
        ideas = found.ideas[:explorers] if isinstance(found, Ideas) and found.ideas else [
            # A model that answered in prose instead of the tool still gives one explorer its words.
            Idea(idea=answer["messages"][-1].text, steps=[], start="best"),
        ]
        plan = "\n".join([*([f"Reflection: {found.reflection}"] if isinstance(found, Ideas) and found.reflection else []),
                          *(f"Explorer {number} ({item.start}): {item.idea}" for number, item in enumerate(ideas, 1))])
        return {
            "plan": plan,
            "ideas": ideas,
            "spend": state["spend"] + spent(answer["messages"]),
        }

    def fan_out(state: dict[str, Any]) -> list[Send]:
        """Start one explorer per idea, each with the turn's allowance."""
        replies = allowance(reply_limit, budget.llm_calls, state["spend"].llm_calls)
        tools = allowance(tool_limit, budget.tool_calls, state["spend"].tool_calls)
        return [
            Send("explorer", {"branch": number, "idea": told(idea), "empty": idea.start == "empty",
                              "replies": replies, "tools": tools, "state": state})
            for number, idea in enumerate(state["ideas"], 1)
        ]

    def explorer_node(branch: Branch) -> dict[str, Any]:
        """Build one idea on a copy of the run's best arrangement or on an empty board, then report."""
        own = Workbench(problem=problem) if branch["empty"] else Workbench(
            problem=problem, candidate=bench.candidate, best=bench.best)
        replies, tools = branch["replies"], branch["tools"]
        explorer = create_agent(
            model=model,
            # give_up is left out: one explorer's doubt must not end the others' run.
            tools=[item for item in basic_agent_tools(own) if item.name != "give_up"],
            system_prompt=prompt("explorer.md"),
            middleware=[
                TurnNote(prompt("report.md"), replies=replies, tools=tools),
                AnswerBrokenCalls(),
                *guarded,
                *([ModelCallLimitMiddleware(run_limit=replies)] if replies else []),
                *([ToolCallLimitMiddleware(run_limit=tools, exit_behavior="continue")] if tools else []),
            ],
            name=f"explorer {branch['branch']}",
        )
        started = time.perf_counter()
        answer = explorer.invoke({"messages": [("user", brief(
            "exploration.md", branch["state"], replies, tools, on=own, idea=branch["idea"],
        ))]})
        return {"results": [{
            "branch": branch["branch"], "bench": own, "messages": answer["messages"],
            "seconds": time.perf_counter() - started,
        }]}

    def select_node(state: dict[str, Any]) -> dict[str, Any]:
        """Keep the best valid arrangement any explorer reached: the engine ranks, not a model."""
        results = sorted(state["results"], key=lambda item: item["branch"])
        # Each explorer's own view of the turn, before the engine picks among them.
        lanes = [session.lane(f"explorer {item['branch']}", item["bench"], item["messages"],
                              idea=told(state["ideas"][item["branch"] - 1])) for item in results]
        for result in results:
            session.merge(result["bench"])
        reports = "\n\n".join(f"Explorer {item['branch']}: {note_of(item['messages']) or '(no report)'}"
                              for item in results)
        recorded = session.record(
            state, [message for item in results for message in item["messages"]],
            max(item["seconds"] for item in results), note=reports, plan=state["plan"], lanes=lanes,
        )
        return {**recorded, "results": None}

    def route(state: dict[str, Any]) -> str:
        """Explore again while the run still improves, and end it when it does not."""
        return "again" if keep_going(state, budget=budget, guard=guard, stall_limit=stall_limit) else "done"

    graph = StateGraph(ExplorationState)
    graph.add_node("strategist", strategist_node)
    graph.add_node("explorer", explorer_node, input_schema=Branch)
    graph.add_node("select", select_node)
    graph.add_edge(START, "strategist")
    graph.add_conditional_edges("strategist", fan_out, ["explorer"])
    graph.add_edge("explorer", "select")
    graph.add_conditional_edges("select", route, {"again": "strategist", "done": END})
    return graph.compile()


__all__ = ["EXPLORERS", "Idea", "Ideas", "build", "told"]
