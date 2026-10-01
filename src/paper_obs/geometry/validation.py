"""Validation: running every constraint of a problem and aggregating the verdict.

A ``Validation`` keeps the per-constraint results instead of collapsing them
into a single boolean. The reason is the same one that makes constraints report
violations: a search operator, a repair loop or an agent needs to know *which*
shapes broke *which* rule, and how badly, long after the answer stopped being
``False``.
"""

from __future__ import annotations

from dataclasses import dataclass

from paper_obs.domain.constraints import ConstraintResult, Violation
from paper_obs.domain.serde import JSON, require

from .facts import Facts


@dataclass(frozen=True)
class Validation:
    """Every constraint result for one candidate, plus the aggregate verdict."""

    valid: bool
    results: tuple[ConstraintResult, ...] = ()

    @property
    def violations(self) -> tuple[Violation, ...]:
        """Every violation reported by every constraint."""
        return tuple(violation for result in self.results for violation in result.violations)

    @property
    def severity(self) -> float:
        """Sum of the constraint severities.

        Magnitudes are not comparable across constraints — an overlap is a
        length, an arena overflow is an area — so this total is a rough global
        indicator, useful as a tie-break, not as a metric to display alone.
        """
        return float(sum(result.severity for result in self.results))

    @property
    def collisions(self) -> tuple[Violation, ...]:
        """Violations reported by the ``NonOverlap`` constraint."""
        return self._violations_of("non_overlap")

    def result(self, constraint: str) -> ConstraintResult | None:
        """Return the result of one constraint, or ``None`` when it is not part of the problem."""
        for result in self.results:
            if result.constraint == constraint:
                return result
        return None

    def summary(self) -> str:
        """One-line verdict for logs and the CLI."""
        if self.valid:
            return "valid"
        return "; ".join(result.message for result in self.results if not result.valid)

    def _violations_of(self, constraint: str) -> tuple[Violation, ...]:
        result = self.result(constraint)
        return () if result is None else result.violations

    def to_dict(self) -> JSON:
        """Return the JSON representation."""
        return {
            "valid": self.valid,
            "severity": self.severity,
            "results": [result.to_dict() for result in self.results],
        }

    @staticmethod
    def from_dict(data: JSON) -> Validation:
        """Decode a validation from its JSON representation."""
        return Validation(
            valid=bool(require(data, "valid", "validation")),
            results=tuple(ConstraintResult.from_dict(result) for result in data.get("results", [])),
        )

    def __str__(self) -> str:
        return self.summary()


def evaluate_constraints(facts: Facts) -> Validation:
    """Run every effective constraint of the problem against precomputed facts."""
    results = tuple(
        constraint.evaluate(facts) for constraint in facts.problem.effective_constraints
    )
    return Validation(valid=all(result.valid for result in results), results=results)


__all__ = ["Validation", "evaluate_constraints"]
