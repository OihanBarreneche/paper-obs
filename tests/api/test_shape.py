"""POST /api/shape: a stack of primitives compiled into one polygon outline.

The composer sends the same parts the arena editor does, so these tests speak
that vocabulary. What comes back has to be the engine's own outline: the
browser draws the returned path and the engine later judges placements of the
returned shape, so a path written by the route instead of compiled by the shape
layer would let the picture and the verdict drift apart.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from paper_obs.api import create_app  # noqa: E402
from paper_obs.domain.shapes import CustomPolygon, PackableShape  # noqa: E402
from paper_obs.geometry.view import path_data  # noqa: E402

CLIENT = TestClient(create_app(static_directory=Path("/nonexistent-frontend")))


def _two_overlapping_squares() -> list[dict]:
    """Two 2 x 2 squares overlapping on a corner, whose union has area 7."""
    return [
        {"op": "base", "params": {"kind": "rect", "width": 2.0, "height": 2.0}},
        {
            "op": "union",
            "params": {"kind": "rect", "width": 2.0, "height": 2.0},
            "offset": [1.0, 1.0],
        },
    ]


def test_two_overlapping_squares_compose_into_one_polygon() -> None:
    body = CLIENT.post("/api/shape", json={"parts": _two_overlapping_squares()}).json()
    assert body["shape"]["type"] == "custom_polygon"
    # 4 + 4 minus the 1 x 1 corner the two squares share.
    assert body["area"] == pytest.approx(7.0)
    shape = PackableShape.from_dict(body["shape"])
    assert isinstance(shape, CustomPolygon)
    assert shape.area(1.0) == pytest.approx(7.0)
    # The path is the engine's own: rebuilding the ring through the shape layer
    # and its path formatter gives exactly the string the route answered with.
    assert body["path"] == path_data(shape.footprint(1.0))
    assert body["path"].startswith("M ")
    assert body["summary"]
    assert list(body["bounds"]) == pytest.approx(list(shape.bounding_box(1.0)))


def test_a_composed_shape_is_placed_in_a_problem_like_any_other() -> None:
    """The problem document carries the shape, so no other route has to know it.

    This is the whole contract of the library: a composed outline is a ShapeDoc
    like a circle or a square, and the engine judges a placement of it without a
    single change to the problem or evaluate routes.
    """
    shape = CLIENT.post("/api/shape", json={"parts": _two_overlapping_squares()}).json()["shape"]
    example = CLIENT.get("/api/examples/circle-25-in-square").json()["problem"]
    problem = {
        **example,
        "problem_id": "composed-shape-probe",
        "shape": shape,
        "objective": {"type": "maximize_scale", "count": 1},
    }
    candidate = {
        "candidate_id": "probe",
        "problem_id": "composed-shape-probe",
        "scale": 1.0,
        "placements": [{"shape_id": "s000", "x": 0.0, "y": 0.0}],
    }
    body = CLIENT.post("/api/evaluate", json={"problem": problem, "candidate": candidate}).json()
    assert body["evaluation"]["valid"] is True
    assert body["view"]["shapes"][0]["kind"] == "polygon"


def test_a_disjoint_stack_is_refused() -> None:
    response = CLIENT.post(
        "/api/shape",
        json={
            "parts": [
                {"op": "base", "params": {"kind": "rect", "width": 2.0, "height": 2.0}},
                {
                    "op": "union",
                    "params": {"kind": "rect", "width": 2.0, "height": 2.0},
                    "offset": [5.0, 0.0],
                },
            ]
        },
    )
    assert response.status_code == 400
    assert "single connected outline" in response.json()["detail"]


def test_an_empty_stack_is_refused_in_the_domain_words() -> None:
    """An empty list reaches the domain, so the refusal is the composer module's own."""
    response = CLIENT.post("/api/shape", json={"parts": []})
    assert response.status_code == 400
    assert "at least one part" in response.json()["detail"]


def test_a_stack_that_cancels_itself_is_refused_in_the_domain_words() -> None:
    response = CLIENT.post(
        "/api/shape",
        json={
            "parts": [
                {"op": "base", "params": {"kind": "rect", "width": 2.0, "height": 2.0}},
                {"op": "difference", "params": {"kind": "rect", "width": 4.0, "height": 4.0}},
            ]
        },
    )
    assert response.status_code == 400
    assert "empty region" in response.json()["detail"]


def test_a_hole_is_refused_because_an_outline_cannot_store_it() -> None:
    """A ring has no single simple outline, and filling it would change the area."""
    response = CLIENT.post(
        "/api/shape",
        json={
            "parts": [
                {"op": "base", "params": {"kind": "rect", "width": 4.0, "height": 4.0}},
                {"op": "difference", "params": {"kind": "disk", "radius": 1.0}},
            ]
        },
    )
    assert response.status_code == 400
    assert "hole" in response.json()["detail"]
