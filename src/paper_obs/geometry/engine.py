"""The public façade of the deterministic engine.

Every other layer — search operators, baselines, agents, the CLI, the UI —
talks to the geometry through the three functions below and nothing else:

``validate(problem, candidate)``
    Is this candidate allowed? Which shapes break which rule, and how badly?
``evaluate(problem, candidate)``
    What is its score, its validity and its descriptive metrics?
``analyze(problem, candidate)``
    Where is it empty, how do its shapes touch?

The three share one :class:`~paper_obs.geometry.facts.Facts` when they are
called together, so a caller that needs several views pays for the geometry
once. The engine never mutates a candidate, never generates one, and never
decides anything beyond the constraints it was given.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from paper_obs.domain.candidate import Candidate
from paper_obs.domain.objectives import ObjectiveScore
from paper_obs.domain.problem import Problem
from paper_obs.domain.serde import JSON, as_float, require

from .analysis import CandidateAnalysis, analyze_facts, shape_neighborhood
from .facts import Facts, build_facts
from .metrics import compute_metrics
from .validation import Validation, evaluate_constraints


@dataclass(frozen=True)
class Evaluation:
    """The complete verdict on a candidate: score, validity, metrics."""

    problem_id: str
    candidate_id: str
    score: ObjectiveScore
    validation: Validation
    metrics: Mapping[str, float] = field(default_factory=dict)
    promoted_metric: str = "density"
    """Metric the interface puts in front of the others.

    It comes from the objective rather than from the panel: a family whose score
    is a size has a different number worth reading first, and a component that
    decides for itself would eventually highlight the wrong one.
    """

    @property
    def valid(self) -> bool:
        """Whether every constraint of the problem passed."""
        return self.validation.valid

    @property
    def primary(self) -> float:
        """The objective value, higher meaning better."""
        return self.score.primary

    def rank_key(self) -> tuple[float, float, float]:
        """Return the sort key used to compare two evaluations.

        Validity comes first: a beautiful scale obtained with overlapping shapes
        is worth nothing. The objective comes next, and the last component is a
        tie-break on the total violation severity, so that two invalid
        candidates of equal nominal score can still be ordered by how close they
        are to being valid.
        """
        return (1.0 if self.valid else 0.0, self.score.primary, -self.validation.severity)

    def is_better_than(self, other: Evaluation) -> bool:
        """Whether this evaluation outranks ``other``."""
        return self.rank_key() > other.rank_key()

    def summary(self) -> str:
        """One-line verdict for logs and the CLI."""
        parts = ["valid" if self.valid else "invalid", str(self.score)]
        if self.promoted_metric in self.metrics:
            value = self.metrics[self.promoted_metric]
            parts.append(f"{self.promoted_metric}={value:.4g}")
        if not self.valid:
            parts.append(self.validation.summary())
        return "  ".join(parts)

    def to_dict(self) -> JSON:
        """Return the JSON representation."""
        return {
            "problem_id": self.problem_id,
            "candidate_id": self.candidate_id,
            "valid": self.valid,
            "score": self.score.to_dict(),
            "metrics": dict(self.metrics),
            "promoted_metric": self.promoted_metric,
            "validation": self.validation.to_dict(),
        }

    @staticmethod
    def from_dict(data: JSON) -> Evaluation:
        """Decode an evaluation from its JSON representation."""
        return Evaluation(
            problem_id=str(require(data, "problem_id", "evaluation")),
            candidate_id=str(require(data, "candidate_id", "evaluation")),
            score=ObjectiveScore.from_dict(require(data, "score", "evaluation")),
            validation=Validation.from_dict(require(data, "validation", "evaluation")),
            metrics={str(key): as_float(value, "evaluation.metrics") for key, value in data.get("metrics", {}).items()},
            promoted_metric=str(data.get("promoted_metric", "density")),
        )


def facts_for(problem: Problem, candidate: Candidate) -> Facts:
    """Return the geometric facts of a candidate, for callers that need several views."""
    return build_facts(problem, candidate)


def validate(problem: Problem, candidate: Candidate) -> Validation:
    """Judge a candidate against every effective constraint of the problem."""
    return evaluate_constraints(build_facts(problem, candidate))


def evaluate(problem: Problem, candidate: Candidate, *, with_metrics: bool = True) -> Evaluation:
    """Score a candidate.

    Metrics describe a packing for a human and cost a pass over the shapes; a
    search loop that only needs the score and the verdict can turn them off.
    """
    facts = build_facts(problem, candidate)
    validation = evaluate_constraints(facts)
    return Evaluation(
        problem_id=problem.problem_id,
        candidate_id=candidate.candidate_id,
        score=problem.objective.evaluate(problem, candidate, facts.container),
        validation=validation,
        metrics=compute_metrics(facts) if with_metrics else {},
        promoted_metric=problem.objective.promoted_metric,
    )


def analyze(problem: Problem, candidate: Candidate, *, void_limit: int = 5) -> CandidateAnalysis:
    """Read the structure of a candidate: empty regions and neighbour counts."""
    return analyze_facts(build_facts(problem, candidate), void_limit=void_limit)


def inspect_shape(problem: Problem, candidate: Candidate, shape_id: str, *, distance: float = 5.0, limit: int = 8) -> dict:
    """Return local spatial facts for one named shape, in world units."""
    if distance < 0 or limit < 0:
        raise ValueError("distance and limit must be nonnegative")
    return shape_neighborhood(build_facts(problem, candidate), shape_id, distance=distance, limit=limit)


__all__ = ["Evaluation", "analyze", "evaluate", "facts_for", "inspect_shape", "validate"]
