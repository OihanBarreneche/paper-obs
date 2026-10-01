"""The example problems that ship with the lab.

A problem is a JSON file, and the lab ships one per instance under
``examples/``. They are read from whichever location the caller is working in,
in this order: the directory named by ``PAPER_OBS_EXAMPLES``, then
``examples/`` in the current directory, then the copy packaged inside the
distribution. The first definition of a given ``problem_id`` wins, so someone can
shadow a shipped example with their own without editing anything.

An example may also ship the arrangement it is known for, as a candidate, in a
``candidates/`` directory beside the problems and under the same identifier. When
one exists the interface opens on it instead of on a construction, so the lab
starts on the known solution of the instance rather than on a lattice — and the
verdict beside it is still the engine's, computed from the coordinates, never
copied from a table.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from paper_obs.domain.candidate import Candidate
from paper_obs.domain.problem import Problem
from paper_obs.storage.files import load_candidate, load_problem

#: Environment variable naming a directory of problem files to read first.
EXAMPLE_DIRECTORY_ENV = "PAPER_OBS_EXAMPLES"

#: Directory, relative to a source checkout, holding the shipped problems.
REPOSITORY_EXAMPLES = Path("examples")

#: The instances the lab runs, in the order it wants them tried, each with the reason
#: it is on that rung. A rung says what the instance proves, not how hard it feels.
#: The picker offers these and nothing else: an example the ladder does not name is a
#: measurement input — a file the tests and the command line still read by path — not a
#: question the interface asks.
LADDER: tuple[tuple[str, int, str], ...] = (
    (
        "circle-25-in-square",
        1,
        "the construction is optimal — the lattice reaches scale 2 in 26 judgements — so "
        "a run that misses it has broken something, and it is the one to try first",
    ),
    (
        "squares-5-in-smallest-square",
        2,
        "the optimum is proved, 2 + sqrt(2)/2, but the packing is rigid: one square has "
        "to be turned 45 degrees, which no axis-aligned construction will do",
    ),
    (
        "squares-17-in-smallest-square",
        3,
        "the smallest known container has side 4.67553, with squares at several "
        "angles; this packing is published but no proof of optimality is known",
    ),
    (
        "discs-in-irregular-region",
        4,
        "exactly 30 discs with one variable diameter: the best measured scale is 0.886; "
        "this tests moving shapes and growing their common size, not adding more discs",
    ),
    (
        "unit-discs-in-irregular-region",
        5,
        "fixed diameter 1 in the same composite arena: add as many valid discs as possible; "
        "this is the incremental fill problem",
    ),
)

#: Subdirectory of an example directory holding the shipped solutions.
CANDIDATE_DIRECTORY = "candidates"


@lru_cache(maxsize=1)
def example_directories() -> tuple[Path, ...]:
    """Return the directories scanned for example problems, most specific first."""
    candidates = []
    override = os.environ.get(EXAMPLE_DIRECTORY_ENV)
    if override:
        candidates.append(Path(override))
    candidates.append(Path.cwd() / REPOSITORY_EXAMPLES)
    packaged = _packaged_examples()
    if packaged is not None:
        candidates.append(packaged)
    return tuple(dict.fromkeys(path for path in candidates if path.is_dir()))


def _packaged_examples() -> Path | None:
    """Return the example directory shipped inside the distribution, if any."""
    try:
        from importlib.resources import files
    except ImportError:  # pragma: no cover - Python 3.11 always has it
        return None
    candidate = Path(str(files("paper_obs"))) / "examples"
    return candidate if candidate.is_dir() else None


@lru_cache(maxsize=1)
def examples() -> dict[str, Problem]:
    """Return every example problem, keyed by identifier, sorted by identifier."""
    found: dict[str, Problem] = {}
    for directory in example_directories():
        for path in sorted(directory.glob("*.json")):
            problem = load_problem(path)
            found.setdefault(problem.problem_id, problem)
    return dict(sorted(found.items()))


def example(problem_id: str) -> Problem:
    """Return one example problem, or raise ``KeyError`` naming the known ones."""
    known = examples()
    try:
        return known[problem_id]
    except KeyError as error:
        raise KeyError(
            f"unknown problem {problem_id!r}; known problems: {', '.join(known) or 'none'}"
        ) from error


def default_candidate(problem_id: str) -> Candidate | None:
    """Return the arrangement an example ships, or ``None`` when it ships none.

    Read from a ``candidates/`` directory beside the problems, under the same
    identifier, and only from a directory that already holds problems: a solution
    without its problem names nothing. A broken file raises rather than being
    skipped — an example whose published optimum silently failed to load would
    open on a lattice and look like every other run.
    """
    for directory in example_directories():
        path = directory / CANDIDATE_DIRECTORY / f"{problem_id}.json"
        if path.is_file():
            return load_candidate(path)
    return None


def summaries() -> list[dict[str, Any]]:
    """Return the short description of every rung, in the order the ladder tries them.

    A rung whose file is absent is left out rather than invented: the ladder names
    instances, and the files are what the lab has.
    """
    known = examples()
    listed: list[dict[str, Any]] = []
    for name, number, why in LADDER:
        problem = known.get(name)
        if problem is None:
            continue
        listed.append(
            {
                "problem_id": problem.problem_id,
                "name": problem.title,
                "description": problem.description,
                "arena": problem.describe_region(),
                "shape": problem.shape.describe(),
                "objective": problem.objective.describe(),
                "objective_kind": problem.objective.kind,
                "rung": number,
                "why": why,
            }
        )
    return listed


__all__ = [
    "CANDIDATE_DIRECTORY",
    "LADDER",
    "EXAMPLE_DIRECTORY_ENV",
    "default_candidate",
    "REPOSITORY_EXAMPLES",
    "example",
    "example_directories",
    "examples",
    "summaries",
]
