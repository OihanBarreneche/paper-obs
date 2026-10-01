"""Objectives: what they score, and what they require."""

from __future__ import annotations

import pytest

from paper_obs.domain import (
    Arena,
    Candidate,
    Circle,
    CommonScale,
    MaximizeCount,
    MaximizeScale,
    MinimizeContainer,
    NonOverlap,
    Objective,
    Placement,
    Problem,
    RegularPolygon,
    RequiredShapeCount,
    RotationMode,
    RotationPolicy,
)


def _problem(objective, **kwargs) -> Problem:
    return Problem(
        problem_id="p",
        arena=Arena.rectangle(10.0, 10.0),
        shape=Circle(),
        objective=objective,
        **kwargs,
    )


def _candidate(scale: float, count: int, problem_id: str = "p") -> Candidate:
    return Candidate(
        candidate_id="c",
        problem_id=problem_id,
        scale=scale,
        placements=tuple(
            Placement(shape_id=f"s{index:03d}", x=float(index), y=0.0) for index in range(count)
        ),
    )


def test_maximize_scale_scores_the_common_scale() -> None:
    problem = _problem(MaximizeScale(count=4))
    score = problem.objective.evaluate(problem, _candidate(2.5, 4))
    assert score.primary == pytest.approx(2.5)
    assert score.label == "common_scale"
    assert score.secondary["shape_area"] == pytest.approx(problem.shape.area(2.5))
    assert score.secondary["n_shapes"] == 4.0


def test_maximize_scale_requires_its_count() -> None:
    problem = _problem(MaximizeScale(count=4))
    constraint = problem.objective.constraints(problem)[0]
    assert isinstance(constraint, RequiredShapeCount)
    assert constraint.count == 4


def test_maximize_count_scores_the_number_of_shapes() -> None:
    problem = _problem(MaximizeCount(scale=2.0))
    score = problem.objective.evaluate(problem, _candidate(2.0, 11))
    assert score.primary == 11.0
    assert score.label == "shape_count"
    assert score.secondary["scale"] == 2.0


def test_maximize_count_fixes_the_scale() -> None:
    problem = _problem(MaximizeCount(scale=2.0))
    constraint = problem.objective.constraints(problem)[0]
    assert isinstance(constraint, CommonScale)
    assert constraint.scale == 2.0


def test_effective_constraints_are_structural_extras_policy_and_objective() -> None:
    problem = _problem(
        MaximizeScale(count=4),
        rotation=RotationPolicy(mode=RotationMode.FREE),
        constraints=(CommonScale(2.0),),
    )
    kinds = [constraint.kind for constraint in problem.effective_constraints]
    assert kinds == [
        "arena_containment",
        "non_overlap",
        "common_scale",
        "rotation_policy",
        "required_shape_count",
    ]


def test_scores_compare_on_the_primary_value_only() -> None:
    from paper_obs.domain import ObjectiveScore

    better = ObjectiveScore(primary=2.0, label="scale", secondary={"density": 0.1})
    worse = ObjectiveScore(primary=1.9, label="scale", secondary={"density": 0.9})
    assert better.is_better_than(worse)
    assert not worse.is_better_than(better)


def test_degenerate_objectives_are_rejected() -> None:
    with pytest.raises(ValueError, match="at least one shape"):
        MaximizeScale(count=0)
    with pytest.raises(ValueError, match="positive scale"):
        MaximizeCount(scale=0.0)


def test_the_container_objective_scores_the_reciprocal_of_the_size_it_is_given() -> None:
    """It reads the engine's measurement, so it refuses to be scored without one.

    The score has to be a number that grows with quality — that is the whole reason
    the lab has one ranking — and the reciprocal of a container's size is one, and
    the same number a unit-arena reading of the same instance calls its common
    scale. Scored from anything else it would be a guess, which is why a missing
    measurement is an error and not a fallback.
    """
    objective = MinimizeContainer(count=17)
    problem = Problem(problem_id="p", arena=None, shape=RegularPolygon(sides=4, side=1.0), objective=objective)
    candidate = Candidate(candidate_id="c", problem_id="p", scale=1.0)

    score = objective.evaluate(problem, candidate, {"container_side": 2.5})

    assert score.primary == 0.4
    assert score.label == "container_scale"
    assert score.secondary["container_size"] == 2.5
    with pytest.raises(ValueError, match="scored from the engine's measurement"):
        objective.evaluate(problem, candidate)


def test_the_container_objective_replaces_containment_with_the_count_it_fixes() -> None:
    """Two structural rules: no arena to be inside of, and nothing to choose but positions."""
    objective = MinimizeContainer(count=17)
    problem = Problem(problem_id="p", arena=None, shape=RegularPolygon(sides=4, side=1.0), objective=objective)

    structural = objective.structural_constraints(problem)
    assert [type(constraint).__name__ for constraint in structural] == ["NonOverlap"]
    assert isinstance(problem.rotation, RotationPolicy)
    implied = objective.constraints(problem)
    assert isinstance(implied[0], RequiredShapeCount)
    assert isinstance(implied[1], CommonScale)
    assert objective.preset_count() == 17
    assert objective.preset_scale() == 1.0
    assert objective.enclosing_container == "square"
    assert Objective.from_dict(objective.to_dict()) == objective


def test_a_circle_container_scores_the_radius_it_is_given() -> None:
    """The container a family asks for decides the measurement, and the number in front."""
    objective = MinimizeContainer(count=3, container="circle")
    problem = Problem(
        problem_id="p",
        arena=None,
        shape=RegularPolygon(sides=4, side=1.0),
        objective=objective,
    )
    candidate = Candidate(candidate_id="c", problem_id="p", scale=1.0)

    score = objective.evaluate(problem, candidate, {"container_radius": 1.25})

    assert objective.size_measurement == "container_radius"
    assert objective.promoted_metric == "container_radius"
    assert score.primary == pytest.approx(0.8)
    assert score.secondary["container_size"] == 1.25
    # The square keeps the measurement and the leading number it always had.
    assert MinimizeContainer(count=3).promoted_metric == "container_side"
