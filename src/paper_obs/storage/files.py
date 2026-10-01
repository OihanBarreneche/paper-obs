"""Reading and writing the JSON artefacts of the lab.

One problem is one file, one candidate is one file, one run is one file. That is
the whole storage strategy of the MVP, and it is deliberate: a file is the
smallest unit that a human can inspect, diff, keep in a git repository and hand
to someone else, which is what "an experiment must be reproducible from a file"
ends up meaning in practice.

Everything else — a candidate store, the blackboard, the trace of an agentic run
— is built on top of these three formats rather than beside them.
"""

from __future__ import annotations

from pathlib import Path

from paper_obs.domain.candidate import Candidate
from paper_obs.domain.problem import Problem
from paper_obs.domain.serde import dump, load
from paper_obs.search.baselines import Convergence


def save_problem(problem: Problem, path: str | Path) -> Path:
    """Write a problem as JSON and return the path written."""
    return dump(problem.to_dict(), path)


def load_problem(path: str | Path) -> Problem:
    """Read a problem from a JSON file."""
    return Problem.from_dict(load(path))


def save_candidate(candidate: Candidate, path: str | Path) -> Path:
    """Write a candidate as JSON and return the path written."""
    return dump(candidate.to_dict(), path)


def load_candidate(path: str | Path) -> Candidate:
    """Read a candidate from a JSON file."""
    return Candidate.from_dict(load(path))


def save_run(convergence: Convergence, path: str | Path) -> Path:
    """Write a run as JSON and return the path written.

    A run is a document like the other two, and its ``kind`` field is what tells it
    apart from a candidate sitting in the same directory. Writing it and reading
    it back changes nothing about it, which is the property the observability of
    an agentic run will rest on.
    """
    return dump(convergence.to_dict(), path)


def load_run(path: str | Path) -> Convergence:
    """Read a run from a JSON file."""
    return Convergence.from_dict(load(path))


__all__ = [
    "load_candidate",
    "load_problem",
    "load_run",
    "save_candidate",
    "save_problem",
    "save_run",
]
