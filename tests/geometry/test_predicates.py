"""The exact kernels: what the broad phase keeps, and how deep an overlap is."""

from __future__ import annotations

import numpy as np
import pytest

from paper_obs.geometry.predicates import (
    bounding_circle_pairs,
    circle_gaps,
    circle_polygon_gap,
    convex_penetration_depth,
    convex_separation_axis,
    edge_normals,
    unit_direction,
)


def _square(half_side: float = 0.5, offset: tuple[float, float] = (0.0, 0.0)) -> np.ndarray:
    size = half_side
    corners = np.array(
        [(-size, -size), (size, -size), (size, size), (-size, size)], dtype=float
    )
    return corners + np.array(offset)


def test_broad_phase_keeps_close_pairs_and_drops_the_others() -> None:
    centers = np.array([[0.0, 0.0], [1.0, 0.0], [50.0, 0.0]])
    radii = np.ones(3)
    first, second, distances = bounding_circle_pairs(centers, radii)
    assert list(zip(first.tolist(), second.tolist())) == [(0, 1)]
    assert distances == pytest.approx([1.0])


def test_broad_phase_can_be_loosened() -> None:
    centers = np.array([[0.0, 0.0], [5.0, 0.0]])
    radii = np.ones(2)
    assert len(bounding_circle_pairs(centers, radii)[0]) == 0
    assert len(bounding_circle_pairs(centers, radii, slack=3.5)[0]) == 1


def test_broad_phase_is_empty_below_two_shapes() -> None:
    first, second, distances = bounding_circle_pairs(np.array([[0.0, 0.0]]), np.array([1.0]))
    assert len(first) == len(second) == len(distances) == 0


def test_circle_gaps_are_negative_when_the_circles_overlap() -> None:
    distances = np.array([3.0, 1.5, 2.0])
    radii = np.ones(3)
    assert circle_gaps(distances, radii, radii) == pytest.approx([1.0, -0.5, 0.0])


def test_a_disc_and_a_polygon_are_separated_by_their_true_distance() -> None:
    from shapely.geometry import Point, box

    square = box(-1.0, -1.0, 1.0, 1.0)
    assert circle_polygon_gap(Point(3.0, 0.0), square, 0.5) == pytest.approx(1.5)
    assert circle_polygon_gap(Point(1.2, 0.0), square, 0.5) == pytest.approx(-0.3)


def test_a_disc_swallowed_by_a_polygon_exits_through_the_nearest_edge() -> None:
    from shapely.geometry import Point, box

    square = box(-1.0, -1.0, 1.0, 1.0)
    assert circle_polygon_gap(Point(0.0, 0.0), square, 0.25) == pytest.approx(-1.25)


def test_penetration_depth_is_the_shallowest_way_out() -> None:
    depth = convex_penetration_depth(_square(), _square(offset=(0.75, 0.0)))
    assert depth == pytest.approx(0.25, abs=1e-12)


def test_touching_and_separated_polygons_do_not_overlap() -> None:
    assert convex_penetration_depth(_square(), _square(offset=(1.0, 0.0))) == 0.0
    assert convex_penetration_depth(_square(), _square(offset=(2.0, 0.0))) == 0.0


def test_corner_overlap_is_detected() -> None:
    depth = convex_penetration_depth(_square(), _square(offset=(0.9, 0.9)))
    assert depth == pytest.approx(0.1, abs=1e-12)


def test_edge_normals_are_unit_vectors() -> None:
    normals = edge_normals(_square())
    assert normals.shape == (4, 2)
    assert np.allclose(np.hypot(normals[:, 0], normals[:, 1]), 1.0)


def test_the_separation_axis_pushes_the_second_polygon_out() -> None:
    depth, axis = convex_separation_axis(_square(), _square(offset=(0.75, 0.0)))
    assert depth == pytest.approx(0.25, abs=1e-12)
    assert axis == pytest.approx((1.0, 0.0))
    # The axis is oriented: moving the second square *backwards* would bury it.
    assert convex_separation_axis(_square(), _square(offset=(-0.75, 0.0)))[1] == pytest.approx(
        (-1.0, 0.0)
    )


def test_a_corner_overlap_reports_an_axis_that_actually_separates() -> None:
    depth, axis = convex_separation_axis(_square(), _square(offset=(0.9, 0.9)))
    moved = _square(offset=(0.9 + depth * axis[0], 0.9 + depth * axis[1]))
    assert convex_penetration_depth(_square(), moved) == 0.0


def test_polygons_that_do_not_overlap_still_report_a_direction() -> None:
    """A relaxation needs somewhere to push even where there is nothing to separate."""
    depth, axis = convex_separation_axis(_square(), _square(offset=(3.0, 0.0)))
    assert depth == 0.0
    assert axis == pytest.approx((1.0, 0.0))


def test_the_direction_between_two_coincident_points_is_stated_not_computed() -> None:
    assert unit_direction((1.0, 2.0), (1.0, 2.0)) == (1.0, 0.0)
    assert unit_direction((0.0, 0.0), (0.0, 3.0)) == pytest.approx((0.0, 1.0))
