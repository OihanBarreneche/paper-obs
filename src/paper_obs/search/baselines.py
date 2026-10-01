"""Baselines: the plain strategies a search is compared against, and their curves.

A baseline is the reference of a comparison, so what it owes is fairness rather
than cleverness. Every strategy is billed in the same currency — one engine
judgement, one candidate handed to :func:`~paper_obs.geometry.engine.evaluate`
— and reports the whole curve of what it had reached after each of them.
``budget`` is that currency, so two strategies are always run at equal cost, and
``seed`` comes from the problem's JSON, so a run is reproducible from an artefact
alone.

The two strategies answer two questions an agent's result raises:

``lattice``
    lays the shapes on a structured lattice, then grows the common scale while the
    engine still calls the result valid. It draws nothing: on a tileable instance
    it must reach density 1, and two runs of it are the same document. It is the
    floor: what a plain construction reaches in a handful of judgements.
``basin_hopping``
    starts from the better lattice, then hops: it shakes every shape of the best
    arrangement so far and lets the agents' own ``polish`` settle what the shake
    broke, keeping the result when the engine ranks it higher. It is monotonic
    basin hopping, the classical search for packings, and it is the reference an
    agent's choices must beat: the same tools, applied without reasoning.

A pure random draw and a local walk of the lattice used to sit here. Neither
measured anything: random anchors almost never make a valid packing at a scale
worth reading, and a walk that only nudges a lattice never leaves its contact
topology, so it ended exactly where the lattice did.

Nothing here measures a packing, ranks a candidate or decides a validity: the
ranking is :meth:`Evaluation.rank_key`, the verdict is the engine's, and a
baseline that recomputed either would drift from the tool that reports it.

The candidates a run keeps are renamed after the run (``basin_hopping-7-31``),
because the operators mint process-unique identifiers: two runs of one strategy, on
one problem, at one budget and seed, then produce the same curve *and* the same JSON.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from typing import ClassVar

import numpy as np

from paper_obs import __version__
from paper_obs.domain.candidate import Candidate
from paper_obs.domain.constraints import RotationMode
from paper_obs.domain.problem import Problem
from paper_obs.domain.serde import JSON, as_float, as_int, require

from paper_obs.geometry.bounds import scale_bounds
from paper_obs.geometry.engine import Evaluation, evaluate

from .operators import grid_initialize, jitter, polish, staggered_initialize

#: Halvings of the lattice scale search. Every probe is one engine judgement, and
#: twenty-four of them leave the retained scale within a millionth of the largest
#: one the engine accepts.
SCALE_ATTEMPTS = 24

#: Steps of the polish one hop runs: the agents' ``polish`` tool at half its default
#: length, which settles a shaken arrangement in about a second on discs.
HOP_POLISH = 20

#: What one hop is billed: one judgement per step of the polish, each of which
#: proposes and judges one arrangement, and the judgement of the result. The repair a
#: step makes is part of its proposal, as a lattice's own filtering is part of the
#: lattice, so it is not billed apart.
HOP_COST = HOP_POLISH + 1

#: How far a hop shakes every shape, as a share of the shape's size: enough to leave
#: the contact topology the best arrangement holds, not so much that the polish has a
#: pile to untangle. Where rotation is free, each shape also turns up to ``HOP_TURN``
#: degrees.
HOP_SHAKE = 0.3
HOP_TURN = 30.0

#: Hops in a row that may find nothing better before the run stops: the budget is a
#: ceiling, not a target, and a search that has stopped paying says so.
HOP_STALL = 5

#: Discriminator and schema version of a run document. ``kind`` lets a run file sit
#: in the same directory as a candidate file without either being mistaken for the
#: other; ``format`` is bumped only when a reader would have to branch on it.
RUN_KIND = "run"
RUN_FORMAT = 1


@dataclass(frozen=True)
class Step:
    """One point of the curve: what the run had reached after that evaluation."""

    evaluations: int
    """Engine judgements billed to the run so far, 1-based."""
    best_primary: float
    """Primary score of the incumbent: the best candidate the engine has seen.

    The incumbent is ranked by :meth:`Evaluation.rank_key`, where validity comes
    first, so this number is *not* monotone: a valid candidate at a smaller scale
    legitimately replaces an invalid one at a larger scale, and the curve steps
    down exactly once, when the run turns feasible.
    """
    best_measure: float
    """The incumbent's measurement the objective promotes, such as a container's side.

    The primary score ranks, and for a smallest container it is one over the side; a
    person reads the side. It is the primary score itself where the objective promotes
    no other measurement, a common scale.
    """
    best_valid: bool
    """Whether the incumbent is valid. Once true, it stays true: a valid candidate
    outranks every invalid one, whatever their scores."""
    severity: float
    """Total violation severity of the incumbent, zero when it is valid."""
    accepted: bool
    """Whether this evaluation replaced the incumbent."""
    candidate_id: str | None = None
    """Identifier of the candidate judged here, when the run knows it.

    Supplied so that a point of the curve joins the call that produced it: the
    trace of an agentic run is keyed on this identifier. It is
    `None` in a document written before the field existed, so a reader treats its
    absence as "no join available", never as an error.
    """

    def to_dict(self) -> JSON:
        """Return the JSON representation."""
        return {
            "evaluations": self.evaluations,
            "best_primary": self.best_primary,
            "best_measure": self.best_measure,
            "best_valid": self.best_valid,
            "severity": self.severity,
            "accepted": self.accepted,
            "candidate_id": self.candidate_id,
        }

    @classmethod
    def from_dict(cls, data: JSON) -> Step:
        """Decode one point of a curve."""
        where = "run.step"
        candidate_id = data.get("candidate_id")
        return cls(
            evaluations=as_int(require(data, "evaluations", where), f"{where}.evaluations"),
            best_primary=as_float(require(data, "best_primary", where), f"{where}.best_primary"),
            best_measure=as_float(require(data, "best_measure", where), f"{where}.best_measure"),
            best_valid=bool(require(data, "best_valid", where)),
            severity=as_float(require(data, "severity", where), f"{where}.severity"),
            accepted=bool(require(data, "accepted", where)),
            candidate_id=None if candidate_id is None else str(candidate_id),
        )


@dataclass(frozen=True)
class Convergence:
    """What one run of one strategy produced, in full.

    ``steps`` is the curve: one point per judgement the strategy made, carrying the
    billed total at that moment, which is why the numbers can jump when a move was
    delegated to an operator that judged several candidates of its own.
    ``incumbents`` is the other half of the story — only the candidates the engine
    ranked higher, in order — so a run of a few thousand judgements stays a few
    thousand steps and a handful of candidates.
    """

    strategy: str
    problem_id: str
    seed: int
    budget: int
    steps: tuple[Step, ...]
    best: Candidate
    incumbents: tuple[Candidate, ...]
    evaluations: int

    def to_dict(self) -> JSON:
        """Return the JSON representation, candidates included.

        The three leading keys are the document's own identity: `kind`
        discriminates a run from a candidate, `format` versions this schema, and
        `engine_version` says which engine wrote it. A reader that wants only the
        curve ignores them; :meth:`from_dict` accepts their absence.
        """
        return {
            "kind": RUN_KIND,
            "format": RUN_FORMAT,
            "engine_version": __version__,
            "strategy": self.strategy,
            "problem_id": self.problem_id,
            "seed": self.seed,
            "budget": self.budget,
            "evaluations": self.evaluations,
            "steps": [step.to_dict() for step in self.steps],
            "best": self.best.to_dict(),
            "incumbents": [candidate.to_dict() for candidate in self.incumbents],
        }

    @classmethod
    def from_dict(cls, data: JSON) -> Convergence:
        """Decode a run from its JSON representation.

        Deliberately tolerant: a document written before `kind`, `format` and
        `engine_version` existed carries none of them and is still a run, and a step
        without a `candidate_id` still describes its point of the curve.
        """
        where = "run"
        kind = data.get("kind")
        if kind is not None and kind != RUN_KIND:
            raise ValueError(f"{where}: expected kind {RUN_KIND!r}, got {kind!r}")
        return cls(
            strategy=str(require(data, "strategy", where)),
            problem_id=str(require(data, "problem_id", where)),
            seed=as_int(require(data, "seed", where), f"{where}.seed"),
            budget=as_int(require(data, "budget", where), f"{where}.budget"),
            steps=tuple(Step.from_dict(step) for step in data.get("steps", [])),
            best=Candidate.from_dict(require(data, "best", where)),
            incumbents=tuple(
                Candidate.from_dict(item) for item in data.get("incumbents", [])
            ),
            evaluations=as_int(require(data, "evaluations", where), f"{where}.evaluations"),
        )

    def describe(self) -> str:
        """One line: strategy, budget, evaluations spent, best score, validity."""
        if not self.steps:
            return f"{self.strategy}  budget {self.budget}  nothing evaluated"
        final = self.steps[-1]
        verdict = "valid" if final.best_valid else "invalid"
        return (
            f"{self.strategy}  budget {self.budget}  spent {self.evaluations}  "
            f"best {final.best_measure:.6g}  {verdict}"
        )


class Baseline(ABC):
    """A strategy that improves a candidate by spending evaluations."""

    #: Name the registry and the command line use.
    name: ClassVar[str]

    @abstractmethod
    def run(self, problem: Problem, *, budget: int, seed: int | None = None) -> Convergence:
        """Search, and report the curve it produced.

        ``budget`` is a number of *engine evaluations*, not iterations: it is the
        currency every strategy is billed in, so two strategies can be compared
        at equal cost. ``seed`` defaults to the problem's own seed, so a run is
        reproducible from its JSON alone.
        """


@dataclass
class Run:
    """The bookkeeping one search shares: the budget, the curve, the incumbents.

    A caller that brings its own strategy — the lab ships two, and a workflow or a
    user file may bring another — receives one of these and goes through it:
    :meth:`judge` bills a judgement, names the candidate and keeps it when the engine
    ranks it higher; :meth:`charge` bills the judgements an operator made inside its
    own loop; :meth:`convergence` returns the curve the run produced.
    """

    problem: Problem
    strategy: str
    seed: int
    budget: int
    steps: list[Step] = field(default_factory=list)
    incumbents: list[Candidate] = field(default_factory=list)
    best: Candidate | None = None
    best_evaluation: Evaluation | None = None
    best_measure: float = 0.0
    named: int = 0
    spent: int = 0

    @property
    def remaining(self) -> int:
        """How many engine judgements the run may still spend."""
        return self.budget - self.spent

    def charge(self, cost: int) -> None:
        """Bill ``cost`` judgements that an operator made inside its own loop."""
        self.spent += cost

    def name(self, candidate: Candidate) -> Candidate:
        """Return ``candidate`` under the name this run gives its next candidate.

        Every candidate the run derives another one from is named first, so a
        convergence never refers to an identifier that only existed inside the
        process that produced it — and two runs of one strategy on one problem
        write the same document, down to the genealogy.
        """
        self.named += 1
        return replace(candidate, candidate_id=f"{self.strategy}-{self.seed}-{self.named}")

    def judge(self, candidate: Candidate, *, cost: int = 1) -> Evaluation:
        """Bill, judge, and hold the candidate when the engine ranks it higher.

        The candidate is named by :meth:`name` before it is judged, which is what
        makes two runs of one strategy produce the same document. ``cost`` is the
        whole price of the proposal the caller is asking about, the judgements an
        operator spent on it included.
        """
        self.spent += cost
        named = self.name(candidate)
        evaluation = evaluate(self.problem, named, with_metrics=False)
        incumbent = self.best_evaluation
        accepted = incumbent is None or evaluation.is_better_than(incumbent)
        if accepted:
            self.best = named
            self.best_evaluation = evaluation
            # Measurements cost a judgement of their own, so only a new incumbent pays it.
            measured = evaluate(self.problem, named)
            self.best_measure = measured.metrics.get(measured.promoted_metric, measured.primary)
            self.incumbents.append(named)
            incumbent = evaluation
        assert incumbent is not None  # the first judgement of a run is always accepted
        self.steps.append(
            Step(
                evaluations=self.spent,
                best_primary=incumbent.primary,
                best_measure=self.best_measure,
                best_valid=incumbent.valid,
                severity=incumbent.validation.severity,
                accepted=accepted,
                candidate_id=named.candidate_id,
            )
        )
        return evaluation

    def convergence(self) -> Convergence:
        """Return the record of the run."""
        assert self.best is not None  # a run judges its starting candidate before it stops
        return Convergence(
            strategy=self.strategy,
            problem_id=self.problem.problem_id,
            seed=self.seed,
            budget=self.budget,
            steps=tuple(self.steps),
            best=self.best,
            incumbents=tuple(self.incumbents),
            evaluations=self.spent,
        )


class LatticeBaseline(Baseline):
    """Structured lattices, the better of them grown in scale while the engine agrees."""

    name: ClassVar[str] = "lattice"

    def run(self, problem: Problem, *, budget: int, seed: int | None = None) -> Convergence:
        """Judge the lattices, then bisect the scale of the better one, one judgement per probe."""
        run = _new_run(problem, self.name, budget=budget, seed=seed)
        for candidate in _lattices(problem, origin=self.name):
            if run.remaining < 1:
                break  # the smallest budgets must not buy a judgement they were not given
            run.judge(candidate)
        start, incumbent = run.best, run.best_evaluation
        assert start is not None and incumbent is not None  # a lattice is always judged above
        if not incumbent.valid or problem.objective.preset_scale() is not None:
            # An invalid lattice has no floor to bisect from — no scale is then
            # known to be good — and a scale the objective fixes leaves nothing to
            # grow. The lattice itself is the answer in both cases.
            return run.convergence()
        low, high = start.scale, scale_bounds(problem).high
        for _ in range(SCALE_ATTEMPTS):
            if run.remaining < 1:
                break
            middle = (low + high) / 2.0
            if not low < middle < high:
                break  # the bracket has closed on the float grid
            if run.judge(start.derive(scale=middle, origin=self.name)).valid:
                low = middle
            else:
                high = middle
        return run.convergence()


class BasinHoppingBaseline(Baseline):
    """Shake the best arrangement, polish it as an agent would, and keep what ranks higher."""

    name: ClassVar[str] = "basin_hopping"

    def run(self, problem: Problem, *, budget: int, seed: int | None = None) -> Convergence:
        """Judge the lattices, then hop while the budget affords a hop and hops still pay."""
        run = _new_run(problem, self.name, budget=budget, seed=seed)
        rng = np.random.default_rng(run.seed)
        for candidate in _lattices(problem, origin=self.name):
            if run.remaining < 1:
                break  # the smallest budgets must not buy a judgement they were not given
            run.judge(candidate)
        turn = HOP_TURN if problem.rotation.mode is RotationMode.FREE else 0.0
        stalled = 0
        while run.remaining >= HOP_COST and stalled < HOP_STALL:
            best = run.best
            assert best is not None  # a lattice is always judged above
            if best.n_shapes < 1:
                break  # nothing is placed, so a shake would have nothing to move
            size = problem.shape.natural_size * best.scale
            shaken = run.name(jitter(problem, best, amplitude=HOP_SHAKE * size, generator=rng,
                                     turn=turn, origin=self.name))
            held = len(run.incumbents)
            run.judge(polish(problem, shaken, iterations=HOP_POLISH, generator=rng, origin=self.name),
                      cost=HOP_COST)
            stalled = 0 if len(run.incumbents) > held else stalled + 1
        return run.convergence()


def _new_run(problem: Problem, strategy: str, *, budget: int, seed: int | None) -> Run:
    """Return the bookkeeping of a run, with the budget and seed it resolves to."""
    if budget < 1:
        raise ValueError(f"a run must afford at least one engine evaluation, got {budget!r}")
    return Run(
        problem=problem,
        strategy=strategy,
        seed=_seed_of(problem, seed),
        budget=int(budget),
    )


def _seed_of(problem: Problem, seed: int | None) -> int:
    """Return the seed of a run: the caller's, else the problem's, else ``0``.

    A problem without a seed still gets a reproducible run: the fallback is a
    number, never the generator's own entropy.
    """
    if seed is not None:
        return int(seed)
    return 0 if problem.seed is None else int(problem.seed)


def _lattices(problem: Problem, *, origin: str) -> tuple[Candidate, ...]:
    """Return the lattices worth judging: a grid, and a staggered one for discs.

    A hexagonal lattice is the denser arrangement *of discs*, but it needs half a
    spacing of margin against a straight wall, so on a square arena the grid can
    win. Both are proposed and the engine ranks them: deciding here which one is
    denser would be a measurement, and this layer measures nothing.

    Both strategies start from them: for :class:`LatticeBaseline` they *are* the
    strategy, and :class:`BasinHoppingBaseline` hops from the better one.
    """
    candidates = [grid_initialize(problem, origin=origin)]
    if problem.shape.is_circle:
        candidates.append(staggered_initialize(problem, origin=origin))
    return tuple(candidates)


#: The strategies the command line and the tests can name, by :attr:`Baseline.name`.
BASELINES: dict[str, Baseline] = {
    LatticeBaseline.name: LatticeBaseline(),
    BasinHoppingBaseline.name: BasinHoppingBaseline(),
}

#: Chart geometry, in pixels. A chart of two numbers per point, not a packing view.
CHART_WIDTH = 640
CHART_HEIGHT = 260
CHART_LEFT = 68
CHART_TOP = 32
CHART_RIGHT = 18
CHART_BOTTOM = 46


def convergence_svg(convergence: Convergence) -> str:
    """Return a standalone SVG chart of ``convergence``: best measurement, in evaluations.

    One polyline, one axis per direction, every label as text. Nothing is imported
    from the geometry layer and nothing here is reusable for a packing: this is a
    chart of two numbers per point, and the picture of a packing is
    :func:`paper_obs.geometry.rendering.render_svg`.
    """
    curve = [(float(step.evaluations), step.best_measure) for step in convergence.steps]
    if len(curve) == 1:
        # One point is still a line: repeated, so the polyline has two of them.
        curve.append(curve[0])
    left, top = float(CHART_LEFT), float(CHART_TOP)
    right, bottom = float(CHART_WIDTH - CHART_RIGHT), float(CHART_HEIGHT - CHART_BOTTOM)
    x_low = 1.0
    # A run that stopped after one judgement still needs a domain with a width.
    x_high = max(x_low + 1.0, float(convergence.evaluations))
    y_low = min((primary for _, primary in curve), default=0.0)
    y_high = max((primary for _, primary in curve), default=1.0)
    if y_high <= y_low:
        pad = abs(y_high) * 0.05 or 1.0  # a flat curve still needs a readable axis
        y_low, y_high = y_low - pad, y_high + pad

    def across(value: float) -> float:
        return left + (value - x_low) / (x_high - x_low) * (right - left)

    def up(value: float) -> float:
        return bottom - (value - y_low) / (y_high - y_low) * (bottom - top)

    def stroke(x1: float, y1: float, x2: float, y2: float) -> str:
        return f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="#333333"/>'

    def label(x: float, y: float, size: int, anchor: str, content: str) -> str:
        return (
            f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size}" text-anchor="{anchor}" '
            f'fill="#333333">{content}</text>'
        )

    elements = [
        f'<rect x="0" y="0" width="{CHART_WIDTH}" height="{CHART_HEIGHT}" fill="#ffffff"/>',
        stroke(left, bottom, right, bottom),
        stroke(left, top, left, bottom),
    ]
    for fraction in (0.0, 0.5, 1.0):
        tick = x_low + fraction * (x_high - x_low)
        elements.append(stroke(across(tick), bottom, across(tick), bottom + 4))
        elements.append(label(across(tick), bottom + 20, 11, "middle", f"{tick:.4g}"))
        level = y_low + fraction * (y_high - y_low)
        elements.append(stroke(left - 4, up(level), left, up(level)))
        elements.append(label(left - 8, up(level) + 4, 11, "end", f"{level:.4g}"))
    if curve:
        points = " ".join(f"{across(x):.2f},{up(primary):.2f}" for x, primary in curve)
        elements.append(
            f'<polyline fill="none" stroke="#0b6fb8" stroke-width="2" points="{points}"/>'
        )
    elements.append(
        f'<text x="{left:.2f}" y="{CHART_HEIGHT - 8:.2f}" font-size="11" '
        f'text-anchor="middle" fill="#333333">evaluations</text>'
    )
    elements.append(
        f'<text transform="translate(16 {((top + bottom) / 2):.2f}) rotate(-90)" '
        f'font-size="11" text-anchor="middle" fill="#333333">best</text>'
    )
    elements.append(
        f'<text x="{left:.2f}" y="{top - 12:.2f}" font-size="12" fill="#111111">'
        f"{_escaped(_title(convergence))}</text>"
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{CHART_WIDTH}" '
        f'height="{CHART_HEIGHT}" viewBox="0 0 {CHART_WIDTH} {CHART_HEIGHT}" '
        f'font-family="ui-monospace, monospace">\n  ' + "\n  ".join(elements) + "\n</svg>\n"
    )


def _title(convergence: Convergence) -> str:
    """Return the one-line caption of a chart."""
    verdict = "valid" if convergence.steps and convergence.steps[-1].best_valid else "invalid"
    return (
        f"{convergence.strategy} on {convergence.problem_id}: {verdict}, "
        f"{convergence.evaluations}/{convergence.budget} evaluations"
    )


def _escaped(text: str) -> str:
    """Return ``text`` with the characters that would end a text node escaped."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


__all__ = [
    "BASELINES",
    "Baseline",
    "BasinHoppingBaseline",
    "Convergence",
    "LatticeBaseline",
    "Step",
    "convergence_svg",
]
