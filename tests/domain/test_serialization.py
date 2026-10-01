"""The JSON contract: a document must round trip, and a broken one must say why."""

from __future__ import annotations

import pytest

from paper_obs.domain import (
    Arena,
    Candidate,
    Circle,
    MaximizeCount,
    MaximizeScale,
    MinimizeContainer,
    Placement,
    Problem,
    RequiredShapeCount,
    RotationMode,
    RotationPolicy,
    square,
)
from paper_obs.domain.serde import dumps, jsonable


def _rich_problem() -> Problem:
    return Problem(
        problem_id="rich",
        arena=Arena.rectangle(10.0, 10.0).difference(Arena.disk(2.0)),
        shape=square(side=1.5),
        objective=MaximizeCount(scale=2.0),
        rotation=RotationPolicy(mode=RotationMode.DISCRETE, angles=(0.0, 45.0)),
        constraints=(RequiredShapeCount(12),),
        seed=7,
        name="a rich problem",
        description="exercises every serialised field",
        metadata={"author": "test", "tags": ["polygon", "hole"]},
    )


def test_problem_round_trip_is_lossless() -> None:
    problem = _rich_problem()
    assert Problem.from_dict(problem.to_dict()).to_dict() == problem.to_dict()


def test_candidate_round_trip_keeps_genealogy_and_placements() -> None:
    candidate = Candidate(
        candidate_id="c-1",
        problem_id="rich",
        scale=2.0,
        placements=(Placement("s000", 1.0, 2.0, 45.0, 1.25), Placement("s001", -3.0, 0.5)),
        parents=("c-0",),
        origin="boundary",
        generation=3,
        metadata={"score": 2.0},
    )
    restored = Candidate.from_dict(candidate.to_dict())
    assert restored == candidate
    assert restored.placements[0].scale == 1.25


def test_deriving_a_candidate_links_it_to_its_parent() -> None:
    parent = Candidate(
        candidate_id="c-1",
        problem_id="rich",
        scale=2.0,
        placements=(Placement("s000", 0.0, 0.0),),
        origin="lattice",
        generation=4,
    )
    child = parent.derive(placements=(Placement("s000", 1.0, 0.0),), origin="jitter")
    assert child.parents == ("c-1",)
    assert child.generation == 5
    assert child.origin == "jitter"
    assert child.problem_id == parent.problem_id
    assert child.scale == parent.scale
    assert child.candidate_id != parent.candidate_id


def test_defaults_are_left_out_of_the_document() -> None:
    data = Placement("s000", 1.0, 2.0).to_dict()
    assert data == {"shape_id": "s000", "x": 1.0, "y": 2.0}


def test_a_coloured_placement_round_trips_through_json() -> None:
    placement = Placement("s000", 1.0, 2.0, color="#ff8800")
    assert placement.to_dict()["color"] == "#ff8800"
    assert Placement.from_dict(placement.to_dict()) == placement


def test_a_document_written_before_colours_loads_and_rewrites_unchanged() -> None:
    """The compatibility promise: old bytes in, the very same bytes out.

    ``color`` is written only when it is set, exactly like ``rotation`` and
    ``scale``, so a placement saved before the field existed comes back without a
    key, and ``to_dict`` invents nothing.
    """
    legacy = {"shape_id": "s007", "x": 1.5, "y": -2.0, "rotation": 45.0, "scale": 1.25}
    placement = Placement.from_dict(legacy)
    assert placement.color is None
    assert placement.to_dict() == legacy


@pytest.mark.parametrize("bad", ["#ff880", "#FF8800", "ff8800", "red", "#ff880g", "#ff8800 "])
def test_a_malformed_colour_names_the_form_it_expected(bad: str) -> None:
    with pytest.raises(ValueError, match="lower-case #rrggbb"):
        Placement("s000", 0.0, 0.0, color=bad)


def test_a_colour_that_is_not_a_string_is_refused_like_any_other() -> None:
    """A malformed document raises the error the API knows how to turn into a 400."""
    with pytest.raises(ValueError, match="lower-case #rrggbb"):
        Placement.from_dict({"shape_id": "s000", "x": 0.0, "y": 0.0, "color": 16746496})


def test_a_missing_field_names_itself() -> None:
    with pytest.raises(ValueError, match="missing required field 'shape'"):
        Problem.from_dict({"problem_id": "p"})


def test_the_arena_is_absent_exactly_when_the_objective_measures_it() -> None:
    """A minimised container is derived from the arrangement, so there is nothing to declare.

    The two refusals matter as much as the round trip: a problem that packs into
    an arena must have one, and a problem whose objective measures its own region
    must not, or a reader of the file would believe an arena that nothing reads.
    """
    problem = Problem(
        problem_id="box", arena=None, shape=Circle(), objective=MinimizeContainer(count=3)
    )
    assert "arena" not in problem.to_dict()
    assert Problem.from_dict(problem.to_dict()) == problem

    with pytest.raises(ValueError, match="packs into an arena"):
        Problem(
            problem_id="p", arena=None, shape=Circle(), objective=MaximizeScale(count=3)
        )
    with pytest.raises(ValueError, match="would be ignored"):
        Problem(
            problem_id="p",
            arena=Arena.rectangle(1.0, 1.0),
            shape=Circle(),
            objective=MinimizeContainer(count=3),
        )


def test_an_unknown_type_lists_the_known_ones() -> None:
    with pytest.raises(ValueError, match="unknown type 'blob'.*known: circle, custom_polygon"):
        Problem.from_dict(
            {
                "problem_id": "p",
                "arena": {"shape": {"type": "rect", "width": 1.0, "height": 1.0}},
                "shape": {"type": "blob"},
                "objective": {"type": "maximize_count", "scale": 1.0},
            }
        )


def test_a_wrong_field_type_is_refused() -> None:
    with pytest.raises(ValueError, match="expected a number"):
        Circle.from_dict({"type": "circle", "radius": "wide"})


def test_unserialisable_objects_fail_loudly() -> None:
    with pytest.raises(TypeError, match="cannot serialise"):
        jsonable(object())


def test_non_finite_numbers_are_refused() -> None:
    with pytest.raises(ValueError):
        dumps({"density": float("nan")})
