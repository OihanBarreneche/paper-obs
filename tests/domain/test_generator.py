"""The procedural generator: reproducibility, and what it refuses.

A generated instance is only useful if it can be rebuilt from its number and if
the engine can judge it. The tests below check both, over a sweep of seeds rather
than one, because "it works on seed 7" says nothing about a family of instances.
"""

from __future__ import annotations

import pytest

from paper_obs.domain import (
    Arena,
    Candidate,
    MaximizeCount,
    MaximizeScale,
    Placement,
    Problem,
    arena_parts,
)
from paper_obs.domain.generator import (
    ARENA_FAMILIES,
    PRIMITIVE_FAMILIES,
    GeneratorSpec,
    generate,
)
from paper_obs.geometry import evaluate

#: Seeds the sweep walks. Enough to cover every arena family several times
#: without making the suite slow: one instance costs a few milliseconds to
#: generate and one evaluation to judge.
SWEEP = tuple(range(1, 41))


def _one_shape_candidate(problem: Problem) -> Candidate:
    """A candidate holding a single shape at the origin, whatever the problem asks."""
    return Candidate(
        candidate_id="c-probe",
        problem_id=problem.problem_id,
        scale=1.0,
        placements=(Placement("s000", 0.0, 0.0),),
    )


def test_the_same_seed_and_spec_give_the_same_instance() -> None:
    spec = GeneratorSpec(seed=19)
    assert generate(spec).to_dict() == generate(spec).to_dict()


def test_two_seeds_give_two_instances() -> None:
    documents = {seed: generate(GeneratorSpec(seed=seed)).to_dict() for seed in range(6)}
    assert len({str(document) for document in documents.values()}) == len(documents)


def test_a_generated_instance_is_a_normal_problem_document() -> None:
    problem = generate(GeneratorSpec(seed=3))
    assert Problem.from_dict(problem.to_dict()).to_dict() == problem.to_dict()
    assert problem.seed == 3
    # The recipe travels with the instance: without it, nobody could rebuild it.
    assert problem.metadata["generator"]["seed"] == 3


@pytest.mark.parametrize("family", ARENA_FAMILIES)
def test_every_arena_family_produces_an_arena_the_engine_can_judge(family: str) -> None:
    for seed in SWEEP[:12]:
        problem = generate(GeneratorSpec(seed=seed, arenas=(family,)))
        assert problem.arena.area > 0.0, f"{family} seed {seed} described nothing"
        verdict = evaluate(problem, _one_shape_candidate(problem))
        assert verdict.metrics["arena_area"] > 0.0


def test_a_composite_arena_stays_editable_as_a_stack_of_parts() -> None:
    """A generated arena must open in the arena editor like any other."""
    for seed in SWEEP:
        problem = generate(GeneratorSpec(seed=seed, arenas=("composite",)))
        assert arena_parts(problem.arena.shape) is not None


def test_a_sweep_of_seeds_never_produces_something_the_engine_refuses_to_judge() -> None:
    """The generator may well produce an instance nobody can solve — never an impossible document."""
    for seed in SWEEP:
        problem = generate(GeneratorSpec(seed=seed))
        verdict = evaluate(problem, _one_shape_candidate(problem))
        assert verdict.score.primary > 0.0
        assert isinstance(problem.objective, (MaximizeScale, MaximizeCount))


def test_a_generated_instance_can_be_unsolvable_and_says_so() -> None:
    """The shape count is a demand, not a promise: the engine reports the gap."""
    problem = generate(GeneratorSpec(seed=5, arenas=("disk",), counts=(51, 51)))
    assert problem.objective == MaximizeScale(count=51)
    verdict = evaluate(problem, _one_shape_candidate(problem))
    assert not verdict.valid
    assert {violation.kind for result in verdict.validation.results for violation in result.violations} == {
        "wrong_shape_count"
    }


def test_counting_shapes_asks_for_no_scale() -> None:
    """``maximize_count`` at scale 1 is the opposite problem: how many fit.

    The objective changes what the engine reports, and nothing else: a single
    shape stays a valid packing either way. What differs is the score — a scale
    one moment, a number of shapes the next — and the fact that no count is
    demanded any more.
    """
    problem = generate(GeneratorSpec(seed=11, objective="maximize_count"))
    assert problem.objective == MaximizeCount(scale=1.0)
    verdict = evaluate(problem, _one_shape_candidate(problem))
    assert verdict.valid
    assert verdict.score.label == "shape_count"
    assert "wrong_shape_count" not in {
        violation.kind for result in verdict.validation.results for violation in result.violations
    }


def test_the_rotation_policy_is_drawn_from_the_spec() -> None:
    problem = generate(GeneratorSpec(seed=8, rotations=("discrete",)))
    assert problem.rotation.mode.value == "discrete"
    assert len(problem.rotation.angles) >= 2
    assert list(problem.rotation.angles) == sorted(problem.rotation.angles)


def test_every_primitive_family_is_reachable_as_folds() -> None:
    """A composite arena folds primitives; each of the three must appear somewhere."""
    seen = set()
    for seed in range(60):
        arena: Arena = generate(GeneratorSpec(seed=seed, arenas=("composite",))).arena
        for part in arena_parts(arena.shape) or ():
            seen.add(part.shape.kind)
    assert set(PRIMITIVE_FAMILIES) <= seen | {"rect"}, f"only drew {sorted(seen)}"


def test_an_unknown_family_is_refused_with_the_known_ones() -> None:
    with pytest.raises(ValueError, match="unknown arena family"):
        GeneratorSpec(seed=1, arenas=("donut",))
    with pytest.raises(ValueError, match="unknown shape family"):
        GeneratorSpec(seed=1, shapes=("star",))
    with pytest.raises(ValueError, match="unknown rotation mode"):
        GeneratorSpec(seed=1, rotations=("sideways",))
    with pytest.raises(ValueError, match="unknown objective"):
        GeneratorSpec(seed=1, objective="maximize_beauty")
    with pytest.raises(ValueError, match="counts must be"):
        GeneratorSpec(seed=1, counts=(0, 5))


def test_a_spec_survives_a_round_trip_through_json() -> None:
    spec = GeneratorSpec(seed=13, arenas=("rect", "composite"), counts=(2, 6))
    assert GeneratorSpec.from_dict(spec.to_dict()) == spec
