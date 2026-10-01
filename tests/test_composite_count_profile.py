"""The incremental composite demonstration asks for a count, not a common size."""

from pathlib import Path

from paper_obs.domain import Candidate, Placement
from paper_obs.geometry import evaluate
from paper_obs.storage.files import load_problem


def test_unit_disc_demo_rewards_another_valid_disc() -> None:
    path = Path(__file__).resolve().parents[1] / "examples" / "unit_discs_in_irregular_region.json"
    problem = load_problem(path)
    assert problem.objective.kind == "maximize_count"
    first = Candidate("first", problem.problem_id, 1.0, (Placement("s000", 0, 0),))
    second = first.derive(placements=(*first.placements, Placement("s001", 2, 0)))
    one, two = evaluate(problem, first), evaluate(problem, second)
    assert one.valid and two.valid
    assert two.primary == one.primary + 1
