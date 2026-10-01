"""What a turn's opening message says: the problem, the limits, and where the run stands.

Shared by every workflow whose agents work in turns. Each function below returns one section
of text, and a workflow's own template (its ``prompts/bench.md``) arranges them, so the words
an agent reads stay in the prompt files and the numbers stay the engine's.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping
from typing import Any

from paper_obs.agent_tools.engine import Workbench, describe_state, problem_facts
from paper_obs.domain.problem import Problem

#: How a published record's unit maps to a measurement the engine takes of a candidate, and
#: whether a larger one is better. A unit that is not here is quoted as the source states it
#: and never compared: a silent conversion would invent a comparison the source never made.
REFERENCE_METRICS: dict[str, tuple[str, bool]] = {
    "container side": ("container_side", False),
    "container radius": ("container_radius", False),
    # A scale objective has no separate measurement for its size: the engine's score is it.
    "packing scale": ("primary", True),
    "sum of radii": ("total_scale", True),
    "sum of sides": ("total_scale", True),
    "covered side": ("covered_size", True),
    "covered radius": ("covered_size", True),
}

#: What an objective needs the agent to know and no tool reply says.
OBJECTIVE_NOTES: dict[str, str] = {
    "maximize_scale": "Every copy shares one size, and raising it is the whole question. Choose "
                      "where the copies go; fit_scale then takes the largest size they hold, and "
                      "polish moves them to hold more.",
    "maximize_count": "The copies have a fixed size: the question is how many fit. read_voids "
                      "shows the room left, fill_void adds a copy there, and polish tries more.",
    "minimize_container": "There is no arena to fit inside: the container is measured from your "
                          "arrangement, so packing tightly is what shrinks it, and a larger score "
                          "means a smaller container. Choose which shape touches which and how "
                          "each one is turned; polish then squeezes that arrangement and repair "
                          "separates what overlaps.",
    "cover_region": "The copies may overlap and stick out. What is scored is the size of the "
                    "target they cover, the reciprocal of their common scale. Arrange the copies; "
                    "fit_scale then takes the smallest scale that still covers, and read_voids "
                    "shows what is left uncovered.",
    "maximize_covered_size": "The copies may overlap and stick out. What is scored is the size "
                             "of the largest target inside their union, not how many of them fit.",
    "maximize_total_perimeter": "Each shape carries its own size — `size` in place_shapes and "
                                "edit_shapes, the common scale staying at 1 — and the engine "
                                "scores their sum. Growing one leaves less room for the others, "
                                "so unequal sizes can beat equal ones. seed('varied') starts "
                                "from one large shape and the rest smaller, grow_sizes enlarges "
                                "one shape or all of them, and polish trades size between shapes.",
}

#: Turns the journal lists one by one; earlier ones are only counted.
JOURNAL_TURNS = 20


def opening(
    template: str,
    problem: Problem,
    bench: Workbench,
    state: dict[str, Any],
    *,
    replies: int,
    tools: int,
    output_tokens: int | None,
    share_reference: bool,
    stalled: int,
    **extra: str,
) -> str:
    """Fill a turn template with every section, and drop the ones that have nothing to say.

    ``extra`` fills a workflow's own placeholders, such as the plan an executor builds.
    """
    text = template.format(
        problem=problem_section(problem),
        reference=reference_section(problem, bench) if share_reference else "",
        environment=environment_section(
            state, replies=replies, tools=tools, output_tokens=output_tokens, stalled=stalled,
        ),
        standing=standing_section(bench),
        journal=journal_section(state["trace"]),
        note=note_section(state["notes"]),
        **extra,
    )
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def problem_section(problem: Problem) -> str:
    """Return what is asked: the problem, the shape, the score's orientation, the objective's note."""
    lines = [
        problem.describe(),
        "",
        shape_facts(problem),
        "",
        "The engine's score is always oriented so that a larger number is better.",
        OBJECTIVE_NOTES.get(problem.objective.kind, ""),
    ]
    interval = problem_facts(problem)["scale_interval"]
    # The interval is only worth stating where one common scale is the free variable.
    if problem.objective.preset_scale() is None and "low" in interval:
        lines.append(
            f"The common scale may be searched between {interval['low']:.3f} "
            f"and {interval['high']:.3f}."
        )
    return "\n".join(lines)


def shape_facts(problem: Problem) -> str:
    """Return what a model needs to place one shape, read from the domain's own shape.

    Without it a model guesses the size of its shape — a unit pentagon taken for one of
    circumradius 1 is 18 % too wide — and turns it by multiples of its own symmetry, which
    only ever places the same outline again.
    """
    shape = problem.shape
    min_x, min_y, max_x, max_y = shape.bounding_box(1.0, 0.0)
    if shape.is_circle:
        lines = [f"Each shape is a disc of radius {shape.circumradius(1.0):.6g} at scale 1."]
    else:
        corners = shape.vertices(1.0, 0.0)
        on_top = sum(1 for _, y in corners if abs(y - max_y) < 1e-9)
        lines = [
            f"Each shape is a {shape.name}. At scale 1 its circumradius is "
            f"{shape.circumradius(1.0):.6g} and its inradius {shape.inradius(1.0):.6g}; at rotation 0 "
            f"it is {max_x - min_x:.6g} wide and {max_y - min_y:.6g} tall, with "
            f"{'a vertex' if on_top == 1 else 'an edge'} on top."
        ]
    lines.append(
        "A position is the shape's centre, and every length grows with "
        + ("that shape's own size (the common scale stays 1)."
           if problem.objective.kind == "maximize_total_perimeter" else "the common scale.")
    )
    period = shape.symmetry_period
    if 0.0 < period < 360.0:
        lines.append(
            f"Rotations are degrees, counter-clockwise about the centre. Turning by {period:g}° "
            f"gives the same outline, so angles from 0 to {period:g} cover every orientation."
        )
    elif period >= 360.0:
        lines.append("Rotations are degrees, counter-clockwise about the centre.")
    return " ".join(lines)


def record_measure(reference: Any, primary: float | None, metrics: Mapping[str, Any]) -> float | None:
    """Return the engine's measure of an arrangement in a published record's unit.

    ``primary`` and ``metrics`` are an evaluation's. None where the record's unit is not one the
    engine measures, or the evaluation lacks that measure.
    """
    if not isinstance(reference, Mapping):
        return None
    compared = REFERENCE_METRICS.get(str(reference.get("unit") or ""))
    if compared is None:
        return None
    measured = primary if compared[0] == "primary" else metrics.get(compared[0])
    return float(measured) if isinstance(measured, (int, float)) and not isinstance(measured, bool) else None


def record_gap(reference: Any, primary: float | None, metrics: Mapping[str, Any]) -> float | None:
    """Return how far an arrangement is from a published record, as a signed fraction of it.

    Positive when the arrangement beats the record, negative when it falls short, whichever way
    the record's unit improves. None when there is no comparable record or measure.
    """
    measured = record_measure(reference, primary, metrics)
    value = reference.get("value") if isinstance(reference, Mapping) else None
    if measured is None or not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        return None
    larger_is_better = REFERENCE_METRICS[str(reference["unit"])][1]
    return (measured - value) / value * (1 if larger_is_better else -1)


def reference_section(problem: Problem, bench: Workbench) -> str:
    """Return the published record of a problem, and how the run's best compares with it.

    Information only: the agent learns whether it is level, ahead or far behind, which tells
    whether its idea of the arrangement is the record's, and nothing asks it to work otherwise.
    The comparison is computed here, in the record's unit, and only where the engine measures
    that same quantity.
    """
    reference = problem.metadata.get("reference")
    if not isinstance(reference, Mapping):
        return ""
    value = reference.get("value")
    unit = str(reference.get("unit") or "")
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        return ""
    stated = "proved optimum" if reference.get("status") == "proved" else "best known"
    author = str(reference.get("author") or "")
    date = str(reference.get("date") or "")
    lines = [
        "A published record for this family",
        "==================================",
        f"- the source states {value:g} {unit} ({stated})"
        + (f", by {author}" + (f", {date}" if date else "") if author else "") + ".",
    ]
    if bench.best is not None:
        best = bench.best.evaluation
        measured = record_measure(reference, best.primary, best.metrics)
        gain = record_gap(reference, best.primary, best.metrics)
        if measured is not None and gain is not None:
            standing = ("level with the record" if abs(gain) < 1e-6
                        else f"{abs(gain):.2%} {'better' if gain > 0 else 'worse'} than the record")
            lines.append(f"- the run's best measures {measured:.6g} {unit}: {standing}.")
    lines.append(
        "- this is information, not an instruction: work exactly as you would without it. A gap "
        "of several percent usually means an arrangement unlike the record's; a fraction of a "
        "percent, finer tuning."
    )
    return "\n".join(lines)


def environment_section(
    state: dict[str, Any], *, replies: int, tools: int,
    output_tokens: int | None, stalled: int,
) -> str:
    """Return what this turn and this run allow, restated every turn because runs differ."""
    budget, spent = state["budget"], state["spend"]
    allowance = ", ".join(
        f"at most {value} {noun}" if value > 0 else f"no ceiling on {noun}"
        for value, noun in ((tools, "tool calls"), (replies, "replies"))
    )
    lines = [
        f"- this is turn {state['round'] + 1}"
        + (f" of at most {budget.rounds}" if budget.rounds > 0 else " (no turn ceiling)")
        + f", with {allowance}.",
    ]
    if replies > 1 or tools > 0:
        lines.append(
            "- when the allowance runs out, your last reply comes without tools: it is the note "
            "the next turn starts from. Answering without a tool call ends the turn early, and "
            "that answer is the note."
        )
    else:
        lines.append(
            "- this turn has no ceiling of its own: it ends when you answer without calling a "
            "tool, and that answer is the note the next turn starts from."
        )

    def spent_of(used: int, ceiling: int, noun: str) -> str:
        return f"{used} of {ceiling} {noun}" if ceiling > 0 else f"{used} {noun} (no limit)"

    time = f"{spent.seconds:.0f} s" + (
        f" of {budget.seconds:.0f} s" if budget.seconds > 0 else " (no time limit)"
    )
    money = "" if budget.max_cost is None else (
        f", unknown price of ${budget.max_cost:.4g}" if spent.cost is None
        else f", ${spent.cost:.4f} of ${budget.max_cost:.4g}"
    )
    cut = (f"each reply is cut off after {output_tokens} output tokens" if output_tokens
           else "the endpoint decides how long a reply may be and can cut one off")
    lines += [
        f"- the run has spent {spent_of(spent.llm_calls, budget.llm_calls, 'replies')}, "
        f"{spent_of(spent.tool_calls, budget.tool_calls, 'tool calls')} and {time}{money}.",
        f"- {cut}, and a reply cut before a tool call ends the turn having done nothing.",
        "- the run ends when you call give_up, "
        + (f"when {stalled} turns in a row improve nothing, " if stalled > 0 else "")
        + "or when a ceiling above is reached.",
    ]
    return "\n".join(lines)


def standing_section(bench: Workbench) -> str:
    """Return the arrangement the turn starts on, as ``read_state`` would describe it."""
    if bench.candidate is None:
        return "There is no arrangement yet. Place or seed one."
    if bench.best is not None and bench.candidate is bench.best.candidate:
        best = bench.best.evaluation
        measure = best.metrics.get(best.promoted_metric)
        head = (f"The run's best scores {best.primary:.6g} ({best.score.label}"
                + (f"; {best.promoted_metric} {measure:.6g}" if measure is not None else "")
                + "). You start this turn on it:")
    elif bench.best is not None:
        head = (f"The run's best scores {bench.best.evaluation.primary:.6g}, and restore_best returns to it. "
                "You start this turn on the arrangement the last turn reached:")
    else:
        head = "Nothing valid yet. You start this turn on the last arrangement tried:"
    return head + "\n" + json.dumps(describe_state(bench), ensure_ascii=False, separators=(",", ":"))


def journal_section(trace: list[dict[str, Any]]) -> str:
    """Return one line per finished turn, written from the trace rather than by the agent."""
    if not trace:
        return ""
    lines = ["Journal of the run", "=================="]
    if len(trace) > JOURNAL_TURNS:
        lines.append(f"- ({len(trace) - JOURNAL_TURNS} earlier turns)")
    # How much each new best gained on the one before: shrinking gains say an idea is spent.
    gains: dict[int, str] = {}
    best = None
    for step in trace:
        if step["accepted"] and step["primary"] is not None:
            if best is not None and best > 0:
                gains[step["round"]] = f" (+{(step['primary'] / best - 1):.3%})"
            best = step["primary"]
    for step in trace[-JOURNAL_TURNS:]:
        reached = (
            "nothing judged" if step["primary"] is None
            else f"{step['primary']:.6g} ({'valid' if step['valid'] else 'invalid'})"
        )
        used = ", ".join(
            f"{name}×{count}" if count > 1 else name
            for name, count in Counter(step["tools"]).most_common()
        ) or "no tools"
        lines.append(
            f"- turn {step['round'] + 1}: reached {reached}, "
            f"{'a new best' + gains.get(step['round'], '') if step['accepted'] else 'no improvement'}; {used}."
        )
    return "\n".join(lines)


def note_section(notes: list[str]) -> str:
    """Return the note the last turn ended on, the one thing the agent itself carries over."""
    if not notes:
        return (
            "You have no note yet. The last reply of each turn is kept as the note the next turn "
            "starts from; the conversation itself is not."
        )
    return "Your note from the last turn\n============================\n" + notes[-1]


__all__ = ["JOURNAL_TURNS", "OBJECTIVE_NOTES", "REFERENCE_METRICS", "opening", "shape_facts"]
