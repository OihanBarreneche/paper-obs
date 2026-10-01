"""Teams of a builder and a critic, run in parallel, and the engine's choice between them.

Each turn, a planner proposes distinct ideas, one per team. LangGraph's ``Send`` starts one team
per idea, and a team is a small graph of its own. Its builder builds the idea with the engine's
tools and, when the sandbox is on, with Python programs run in an isolated sandbox. Its critic,
who may only read, looks for the arrangement's weakest point in the engine's numbers and names
one move; the builder answers the critique in the same conversation. The engine, not a model,
keeps the best valid arrangement any team reached, and tells whether each critique paid off.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel, Field

from paper_obs.agent_tools.engine import Judged, Workbench, basic_agent_tools, describe_state, engine_tools
from paper_obs.agent_tools.sandbox import deno, sandbox_tools
from paper_obs.domain.candidate import Candidate
from paper_obs.domain.problem import Problem
from paper_obs.workflows.briefing import opening, problem_section
from paper_obs.workflows.budget import Budget
from paper_obs.workflows.parallel_exploration.graph import Idea, Ideas, told
from paper_obs.workflows.session import AgentSession, note_of, spent
from paper_obs.workflows.turns import (
    REPLY_LIMIT, STALLED, TOOL_LIMIT, AnswerBrokenCalls, TurnNote, allowance, keep_going,
)

from .state import LabState, Reported, Team

PROMPTS = Path(__file__).with_name("prompts")

#: Teams each turn, when the manifest did not say.
TEAMS = 3
#: What a critic may spend: a few reads, then its critique. A tool-call ceiling would also
#: count the critique itself, which is a tool call, and refuse it.
CRITIC_REPLIES = 4
#: What a builder may spend answering the critique.
REVISION_REPLIES, REVISION_TOOLS = 4, 6
#: The tools a critic reads an arrangement with; none of them changes it.
READING = {"read_state", "read_voids", "inspect_neighborhood"}


class Critique(BaseModel):
    """What the critic found: one weakness, the numbers that show it, and one move to try."""

    flaw: str = Field(description="the arrangement's weakest point, in one sentence")
    evidence: str = Field(description="the engine's numbers that show it: shapes, gaps, overlaps, empty areas")
    move: str = Field(description="one concrete change for the builder to try, naming the shapes it moves")

    def text(self) -> str:
        """Return the critique as the builder reads it."""
        return f"Weakness: {self.flaw}\nEvidence: {self.evidence}\nMove to try: {self.move}"


def build(
    problem: Problem, *, model: BaseChatModel, budget: Budget,
    settings: dict[str, Any] | None = None, guard: Any = None, start: Candidate | None = None,
) -> Any:
    """Return the compiled graph: planner, teams in parallel, the engine's choice, the loop."""
    settings = settings or {}
    teams = max(1, int(settings.get("teams", TEAMS)))
    reply_limit = int(settings.get("reply_limit", REPLY_LIMIT))
    tool_limit = int(settings.get("tool_limit", TOOL_LIMIT))
    stall_limit = int(settings.get("stall_limit", STALLED))
    sandbox = bool(settings.get("sandbox", 1))
    if sandbox and model is not None and deno() is None:
        raise ValueError("the Python sandbox needs Deno: install it as docs/strategies-and-runs.md says, "
                         "or turn the sandbox off")
    bench = Workbench(problem=problem, candidate=start)
    session = AgentSession(problem, bench)
    prompt = lambda name: (PROMPTS / name).read_text(encoding="utf-8")  # noqa: E731
    guarded = [guard] if guard is not None else []
    planner = create_agent(
        model=model, system_prompt=prompt("planner.md"),
        response_format=ToolStrategy(Ideas), middleware=guarded,
    )

    def brief(template: str, state: dict[str, Any], replies: int, tools: int,
              on: Workbench = bench, **extra: str) -> str:
        return opening(
            prompt(template), problem, on, state, replies=replies, tools=tools,
            output_tokens=getattr(guard, "max_tokens", None),
            share_reference=bool(settings.get("share_reference", 0)), stalled=stall_limit, **extra,
        )

    def builder(own: Workbench, team: int, replies: int, tools: int, used: int = 0) -> Any:
        """Return a team's builder: the engine's tools, the sandbox when it is on, its limits."""
        return create_agent(
            model=model,
            # give_up is left out: one team's doubt must not end the others' run.
            tools=[item for item in basic_agent_tools(own) if item.name != "give_up"]
            + (sandbox_tools(own) if sandbox else []),
            system_prompt=prompt("builder.md") + (prompt("sandbox.md") if sandbox else ""),
            middleware=[
                # A builder taking up its conversation counts the tools it already used.
                TurnNote(prompt("report.md"), replies=replies, tools=tools and used + tools),
                AnswerBrokenCalls(),
                *guarded,
                *([ModelCallLimitMiddleware(run_limit=replies)] if replies else []),
                *([ToolCallLimitMiddleware(run_limit=tools, exit_behavior="continue")] if tools else []),
            ],
            name=f"builder {team}",
        )

    def planner_node(state: dict[str, Any]) -> dict[str, Any]:
        """Reflect on the last turn, critiques included, and propose one distinct idea per team."""
        session.open_turn()
        answer = planner.invoke({"messages": [("user", brief(
            "planning.md", state, reply_limit, tool_limit, teams=str(teams),
            reports=state["notes"][-1] if state["notes"] else "No turn has run yet.",
        ))]})
        found = answer.get("structured_response")
        ideas = found.ideas[:teams] if isinstance(found, Ideas) and found.ideas else [
            # A model that answered in prose instead of the tool still gives one team its words.
            Idea(idea=answer["messages"][-1].text, steps=[], start="best"),
        ]
        plan = "\n".join([*([f"Reflection: {found.reflection}"] if isinstance(found, Ideas) and found.reflection else []),
                          *(f"Team {number} ({item.start}): {item.idea}" for number, item in enumerate(ideas, 1))])
        return {"plan": plan, "ideas": ideas, "spend": state["spend"] + spent(answer["messages"])}

    def fan_out(state: dict[str, Any]) -> list[Send]:
        """Start one team per idea, each with the turn's allowance."""
        replies = allowance(reply_limit, budget.llm_calls, state["spend"].llm_calls)
        tools = allowance(tool_limit, budget.tool_calls, state["spend"].tool_calls)
        return [
            Send("team", {"team": number, "idea": told(idea), "empty": idea.start == "empty",
                          "replies": replies, "tools": tools, "state": state})
            for number, idea in enumerate(state["ideas"], 1)
        ]

    def build_node(team: Team) -> dict[str, Any]:
        """The builder builds its idea on the team's own board, then reports."""
        own = Workbench(problem=problem) if team["empty"] else Workbench(
            problem=problem, candidate=bench.candidate, best=bench.best)
        started = time.perf_counter()
        answer = builder(own, team["team"], team["replies"], team["tools"]).invoke({"messages": [("user", brief(
            "building.md", team["state"], team["replies"], team["tools"], on=own, idea=team["idea"],
        ))]})
        return {"bench": own, "built": answer["messages"], "started": started}

    def critique_node(team: Team) -> dict[str, Any]:
        """The critic reads the builder's best arrangement, and names its weakest point and one move."""
        own = team["bench"]
        reached = own.turn_best.candidate if own.turn_best else own.candidate
        view = Workbench(problem=problem, candidate=reached)
        critic = create_agent(
            model=model, tools=[item for item in engine_tools(view) if item.name in READING],
            system_prompt=prompt("critic.md"), response_format=ToolStrategy(Critique),
            middleware=[
                AnswerBrokenCalls(), *guarded, ModelCallLimitMiddleware(run_limit=CRITIC_REPLIES),
            ],
            name=f"critic {team['team']}",
        )
        answer = critic.invoke({"messages": [("user", prompt("critique.md").format(
            problem=problem_section(problem), idea=team["idea"], report=note_of(team["built"]) or "(no report)",
            arrangement="No arrangement was built." if reached is None else json.dumps(describe_state(view)),
        ))]})
        found = answer.get("structured_response")
        critique = found if isinstance(found, Critique) else Critique(
            flaw=answer["messages"][-1].text or "The critic gave no critique.", evidence="", move="")
        return {"critique": critique.model_dump(), "critic": answer["messages"]}

    def revise_node(team: Team) -> dict[str, Any]:
        """The builder answers the critique in its own conversation, from its best arrangement."""
        own, number, built = team["bench"], team["team"], team["built"]
        held: Judged | None = own.turn_best
        if held is not None:
            own.candidate = held.candidate
        used = sum(1 for item in built if isinstance(item, ToolMessage) and item.status != "error")
        request = prompt("revision.md").format(critique=Critique(**team["critique"]).text())
        answer = builder(own, number, REVISION_REPLIES, REVISION_TOOLS, used).invoke(
            {"messages": [*built, ("user", request)]})
        revised = answer["messages"][len(built):]
        # The critique paid off when the engine found the arrangement that answered it better.
        after = own.turn_best
        revision = {
            "before": _measure(held),
            "after": _measure(after),
            "paid": after is not None and after is not held,
            "answer": note_of(revised),
        }
        return {"results": [{
            "team": number, "bench": own, "critique": team["critique"], "revision": revision,
            "report": note_of(built), "messages": [*built, *team["critic"], *revised],
            "seconds": time.perf_counter() - team["started"],
        }]}

    def select_node(state: dict[str, Any]) -> dict[str, Any]:
        """Keep the best valid arrangement any team reached: the engine ranks, not a model."""
        results = sorted(state["results"], key=lambda item: item["team"])
        # Each team's own view of the turn: its arrangement, its critique and what came of it.
        lanes = [session.lane(
            f"team {item['team']}", item["bench"], item["messages"],
            note=item["revision"]["answer"] or item["report"], idea=told(state["ideas"][item["team"] - 1]),
            agents=[f"builder {item['team']}", f"critic {item['team']}"],
            critique=item["critique"], revision=item["revision"],
        ) for item in results]
        for result in results:
            session.merge(result["bench"])
        reports = "\n\n".join(_report(item) for item in results)
        recorded = session.record(
            state, [message for item in results for message in item["messages"]],
            max(item["seconds"] for item in results), note=reports, plan=state["plan"], lanes=lanes,
        )
        return {**recorded, "results": None}

    def route(state: dict[str, Any]) -> str:
        """Plan again while the run still improves, and end it when it does not."""
        return "again" if keep_going(state, budget=budget, guard=guard, stall_limit=stall_limit) else "done"

    team = StateGraph(Team, output_schema=Reported)
    team.add_node("build", build_node)
    team.add_node("critique", critique_node)
    team.add_node("revise", revise_node)
    team.add_edge(START, "build")
    team.add_edge("build", "critique")
    team.add_edge("critique", "revise")
    team.add_edge("revise", END)

    graph = StateGraph(LabState)
    graph.add_node("planner", planner_node)
    graph.add_node("team", team.compile())
    graph.add_node("select", select_node)
    graph.add_edge(START, "planner")
    graph.add_conditional_edges("planner", fan_out, ["team"])
    graph.add_edge("team", "select")
    graph.add_conditional_edges("select", route, {"again": "planner", "done": END})
    return graph.compile()


def _measure(judged: Judged | None) -> float | None:
    """Return the measurement the objective promotes, such as a container's side, or None.

    An objective whose primary score is already that measurement, a common scale, records no
    separate metric for it.
    """
    if judged is None:
        return None
    evaluation = judged.evaluation
    return evaluation.metrics.get(evaluation.promoted_metric, evaluation.score.primary)


def _report(item: dict[str, Any]) -> str:
    """Return what a team did, as the planner reads it: the build, the critique, its outcome."""
    critique, revision = item["critique"], item["revision"]
    outcome = "the critique paid off" if revision["paid"] else "the critique brought no gain"
    return "\n".join([
        f"Team {item['team']}: {item['report'] or '(no report)'}",
        f"Its critic: {critique['flaw']} Move: {critique['move'] or '—'}",
        f"After the critique ({outcome}, {revision['before']} → {revision['after']}): {revision['answer'] or '(no answer)'}",
    ])


__all__ = ["Critique", "TEAMS", "build"]
