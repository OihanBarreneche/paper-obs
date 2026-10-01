"""The baselines: the curve they promise, and what they must never do.

Every test reads a curve and the candidate the engine judged — never a private
helper, never a constant of the module. The one number that is asserted is the
density of a perfect packing, because that number *is* the contract: a lattice
baseline that cannot reach density 1 on a tileable instance has no place in a
comparison. The rest is behaviour a caller can see: a run replays from its seed,
never bills more than its budget — a budget of one included — never lets the
engine's ranking slip, and never ends a basin hop below the lattice it started from.

The budgets stay small on purpose: a baseline is billed per engine judgement, and
what is checked here is the shape of a run, not the quality of a search.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

import pytest

from paper_obs.domain import MaximizeCoveredSize, RegularPolygon, RotationMode, RotationPolicy
from paper_obs.domain.problem import Problem
from paper_obs.geometry.engine import evaluate
from paper_obs.search import BASELINES, Convergence, convergence_svg
from paper_obs.storage import load_problem, load_run, save_run

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"

#: Room for the lattices and one basin hop, which is what the contract needs.
BUDGET = 48
SEED = 39182


@pytest.fixture(scope="module")
def reference() -> Problem:
    """The 16 squares, whose perfect packing exists at scale 2.5."""
    return load_problem(EXAMPLES / "squares_16_in_square.json")


@pytest.fixture(scope="module")
def circles() -> Problem:
    """The 25 discs, whose optimal arrangement is the 5 x 5 grid."""
    return load_problem(EXAMPLES / "circle_25_in_square.json")


@pytest.fixture(scope="module")
def container() -> Problem:
    """The 17 squares, whose objective measures the container around them."""
    return load_problem(EXAMPLES / "squares_17_in_smallest_square.json")


@pytest.fixture(
    scope="module", params=tuple(sorted(path.stem for path in EXAMPLES.glob("*.json")))
)
def shipped(request: pytest.FixtureRequest) -> Problem:
    """Every instance the examples ship, one test per instance."""
    return load_problem(EXAMPLES / f"{request.param}.json")


@pytest.fixture(scope="module")
def runs(circles: Problem) -> dict[str, Convergence]:
    """One run of every baseline on the discs, shared by the tests that read a curve.

    A run is deterministic from its seed, so sharing one between tests asserts the
    same thing as running it again would, for a fraction of the engine calls.
    """
    return {
        name: BASELINES[name].run(circles, budget=BUDGET, seed=SEED) for name in sorted(BASELINES)
    }


@pytest.fixture(params=sorted(BASELINES))
def strategy(request: pytest.FixtureRequest) -> str:
    """Every registered baseline, one test per baseline."""
    return str(request.param)


def test_a_run_replays_from_its_seed(strategy: str, circles: Problem) -> None:
    baseline = BASELINES[strategy]
    first = baseline.run(circles, budget=BUDGET, seed=SEED)
    second = baseline.run(circles, budget=BUDGET, seed=SEED)
    assert first.to_dict() == second.to_dict()


def test_the_seed_of_a_run_defaults_to_the_problem(strategy: str, circles: Problem) -> None:
    baseline = BASELINES[strategy]
    default = baseline.run(circles, budget=BUDGET)
    explicit = baseline.run(circles, budget=BUDGET, seed=circles.seed)
    assert default.to_dict() == explicit.to_dict()


def test_a_run_stays_within_a_one_judgement_budget(strategy: str, circles: Problem) -> None:
    """The smallest budget is the one that catches a judgement nobody guarded.

    Every other case here runs at a budget large enough to hide a call site that
    judges without asking what is left, which is how a strategy that lays down two
    lattices came to spend two judgements out of a budget of one. One judgement is
    a run that is all budget and no slack: whatever the strategy proposes, it may
    not propose more of it than it was given.
    """
    convergence = BASELINES[strategy].run(circles, budget=1, seed=SEED)
    assert convergence.evaluations <= 1


#: Budgets tight around the price of a hop. A strategy that declares less than it
#: spends slips past exactly here: just under and over the price of one hop.
TIGHT_BUDGETS = (1, 2, 3, 21, 22)


@pytest.mark.parametrize("budget", TIGHT_BUDGETS)
def test_no_strategy_bills_past_the_budget_it_was_given(
    strategy: str, budget: int, container: Problem
) -> None:
    """A compound move has to declare what it can spend, or a run walks past its budget.

    The budget is what makes two strategies comparable, so the accounting is part
    of the contract rather than an implementation detail: a hop judges candidates
    inside its polish, and the price it declares must be paid before it starts. A budget of one catches a missing
    guard; these catch a wrong price, which is quieter — the curve still looks like
    a curve, and only the numbers at equal budget are wrong.
    """
    convergence = BASELINES[strategy].run(container, budget=budget, seed=SEED)
    assert convergence.evaluations <= budget


def test_a_run_spends_its_budget_and_no_more(strategy: str, runs: dict[str, Convergence]) -> None:
    convergence = runs[strategy]
    assert 0 < convergence.evaluations <= BUDGET
    assert len(convergence.steps) <= convergence.evaluations
    assert convergence.steps[-1].evaluations == convergence.evaluations


def test_the_curve_never_walks_backwards(strategy: str, runs: dict[str, Convergence]) -> None:
    convergence = runs[strategy]
    evaluations = [step.evaluations for step in convergence.steps]
    assert evaluations == sorted(evaluations)
    # The score itself is allowed to step down once: a feasible candidate is worth
    # more than an infeasible one of a larger scale, which is the engine's ranking.
    # What the curve does record exactly is where the incumbent changed.
    assert sum(step.accepted for step in convergence.steps) == len(convergence.incumbents)


def test_a_valid_candidate_is_never_outranked_by_an_invalid_one(
    strategy: str, circles: Problem, runs: dict[str, Convergence]
) -> None:
    convergence = runs[strategy]
    validity = [step.best_valid for step in convergence.steps]
    assert validity == sorted(validity)
    evaluation = evaluate(circles, convergence.best)
    assert evaluation.valid == convergence.steps[-1].best_valid
    assert evaluation.primary == convergence.steps[-1].best_primary


def test_the_best_candidate_is_the_last_incumbent(
    strategy: str, runs: dict[str, Convergence]
) -> None:
    convergence = runs[strategy]
    assert convergence.incumbents
    assert convergence.best is convergence.incumbents[-1]


def test_a_lattice_reaches_density_one_on_a_tileable_instance(reference: Problem) -> None:
    convergence = BASELINES["lattice"].run(reference, budget=BUDGET)
    evaluation = evaluate(reference, convergence.best)
    assert evaluation.valid
    assert evaluation.metrics["density"] == pytest.approx(1.0, abs=1e-9)


def test_the_chart_is_a_standalone_svg_with_one_curve(reference: Problem) -> None:
    convergence = BASELINES["lattice"].run(reference, budget=BUDGET)
    svg = convergence_svg(convergence)
    assert svg.startswith("<svg")
    root = ElementTree.fromstring(svg)
    polylines = root.findall("{http://www.w3.org/2000/svg}polyline")
    assert len(polylines) == 1
    assert len(polylines[0].get("points", "").split()) >= 2


def test_basin_hopping_is_never_below_the_lattice(shipped: Problem) -> None:
    """A hop starts from the better lattice and keeps only what the engine ranks higher.

    Nothing is asserted about which of the two is *better*: on an instance whose
    lattice is already optimal they meet, and saying so is the point of the pair.
    """
    hopped = evaluate(shipped, BASELINES["basin_hopping"].run(shipped, budget=50, seed=SEED).best)
    construction = evaluate(shipped, BASELINES["lattice"].run(shipped, budget=50, seed=SEED).best)
    assert hopped.rank_key() >= construction.rank_key()


def test_a_hop_can_leave_the_lattice_basin() -> None:
    """On 19 discs in a disk the hexagonal lattice is far from the best packing, and a hop finds better."""
    problem = load_problem(EXAMPLES / "circles_19_in_disk.json")
    lattice = BASELINES["lattice"].run(problem, budget=BUDGET, seed=SEED)
    hopped = BASELINES["basin_hopping"].run(problem, budget=BUDGET, seed=SEED)
    assert hopped.steps[-1].best_valid
    assert hopped.steps[-1].best_primary > lattice.steps[-1].best_primary


def test_a_step_names_the_candidate_it_judged(runs: dict[str, Convergence]) -> None:
    """Every point of the curve says which candidate the engine judged.

    The identifier is what an agentic run's trace joins on, so a step without one
    is a point of the curve nothing can be attached to.
    """
    for strategy, convergence in runs.items():
        assert all(step.candidate_id is not None for step in convergence.steps), strategy
        judged = {step.candidate_id for step in convergence.steps}
        assert convergence.best.candidate_id in judged
        assert convergence.incumbents[0].candidate_id in judged


def test_a_run_round_trips_through_its_json(runs: dict[str, Convergence]) -> None:
    """Reading a run back gives the run: the document is the contract."""
    for strategy, convergence in runs.items():
        document = convergence.to_dict()
        assert document["kind"] == "run"
        assert document["engine_version"]
        assert Convergence.from_dict(document).to_dict() == document, strategy


def test_a_candidate_document_carries_its_kind(runs: dict[str, Convergence]) -> None:
    """A candidate says what it is, so one directory can hold runs and candidates."""
    assert runs["lattice"].best.to_dict()["kind"] == "candidate"


def test_a_run_document_written_before_the_added_fields_still_reads(
    runs: dict[str, Convergence],
) -> None:
    """The added keys are optional on the way in: an old file is still a run."""
    current = runs["basin_hopping"].to_dict()
    legacy = {
        key: value
        for key, value in current.items()
        if key not in {"kind", "format", "engine_version"}
    }
    legacy["steps"] = [
        {key: value for key, value in step.items() if key != "candidate_id"}
        for step in legacy["steps"]
    ]
    restored = Convergence.from_dict(legacy)
    assert restored.steps[0].candidate_id is None
    assert restored.strategy == current["strategy"]
    assert restored.evaluations == current["evaluations"]


def test_a_run_is_written_and_read_back_as_one_file(
    runs: dict[str, Convergence], tmp_path: Path
) -> None:
    """One file per run, exactly as for a problem and for a candidate."""
    path = save_run(runs["lattice"], tmp_path / "lattice.json")
    assert path.is_file()
    assert load_run(path).to_dict() == runs["lattice"].to_dict()


def _derived_covering(target: str = "circle", count: int = 4) -> Problem:
    """A derived-covering problem, as the editor builds one: unit squares, fixed count."""
    return Problem(
        problem_id=f"derived-{target}",
        arena=None,
        shape=RegularPolygon(sides=4, side=1.0),
        objective=MaximizeCoveredSize(count=count, target=target),
        rotation=RotationPolicy(mode=RotationMode.FREE),
    )


def test_the_derived_covering_keeps_its_count_and_scale_through_a_run() -> None:
    """A run never trades the two constraints the objective fixes for a bigger target."""
    problem = _derived_covering()
    convergence = BASELINES["basin_hopping"].run(problem, budget=BUDGET, seed=SEED)

    assert convergence.best.n_shapes == 4
    assert convergence.best.scale == 1.0
    assert convergence.steps[-1].best_valid


def test_a_smallest_container_curve_follows_the_side_not_its_inverse() -> None:
    """The primary score ranks, but a person compares container sides."""
    problem = load_problem(EXAMPLES / "squares_5_in_smallest_square.json")
    convergence = BASELINES["lattice"].run(problem, budget=BUDGET, seed=SEED)
    final = convergence.steps[-1]
    side = evaluate(problem, convergence.best).metrics["container_side"]
    assert final.best_measure == pytest.approx(side)
    assert final.best_measure == pytest.approx(1 / final.best_primary)
