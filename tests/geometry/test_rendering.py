"""The picture: what a viewer can actually check in the produced SVG."""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from dataclasses import replace

import pytest

from paper_obs.domain import Arena, Circle, MaximizeCount, Placement, Problem
from paper_obs.geometry import RenderOptions, build_view, render_svg

SVG = "{http://www.w3.org/2000/svg}"


def _root(svg: str) -> ElementTree.Element:
    return ElementTree.fromstring(svg)


def test_a_candidate_is_drawn_with_one_element_per_shape(
    circle_problem, lattice, make_candidate
) -> None:
    svg = render_svg(circle_problem, make_candidate(circle_problem, lattice(2, 2, 5.0), scale=5.0))
    root = _root(svg)
    assert root.tag == f"{SVG}svg"
    assert root.get("viewBox") is not None
    assert len(root.findall(f".//{SVG}circle")) == 4


def test_polygons_are_drawn_as_polygons(square_problem, lattice, make_candidate) -> None:
    svg = render_svg(square_problem, make_candidate(square_problem, lattice(4, 4, 2.5), scale=2.5))
    assert len(_root(svg).findall(f".//{SVG}polygon")) == 16


def test_a_hole_is_drawn_as_a_second_subpath(circle_problem, make_candidate) -> None:
    holed = replace(
        circle_problem,
        arena=Arena.rectangle(10.0, 10.0).difference(Arena.disk(2.0)),
        objective=MaximizeCount(scale=1.0),
    )
    svg = render_svg(holed, make_candidate(holed, [Placement("s000", 4.0, 4.0)], scale=1.0))
    arena_path = _root(svg).find(f".//{SVG}path")
    assert arena_path is not None
    assert arena_path.get("fill-rule") == "evenodd"
    assert arena_path.get("d").count("M") == 2


def test_violating_shapes_are_highlighted(circle_problem, lattice, make_candidate) -> None:
    placements = list(lattice(2, 2, 5.0))
    placements[1] = placements[1].moved(2.4, 2.5)
    svg = render_svg(circle_problem, make_candidate(circle_problem, placements, scale=5.0))
    fills = [element.get("fill") for element in _root(svg).findall(f".//{SVG}circle")]
    assert fills.count(RenderOptions().violation_fill) == 2


def test_highlighting_can_be_turned_off(circle_problem, lattice, make_candidate) -> None:
    placements = list(lattice(2, 2, 5.0))
    placements[1] = placements[1].moved(2.4, 2.5)
    options = RenderOptions(show_violations=False)
    svg = render_svg(circle_problem, make_candidate(circle_problem, placements, scale=5.0), options)
    fills = [element.get("fill") for element in _root(svg).findall(f".//{SVG}circle")]
    assert fills.count(options.violation_fill) == 0


def test_the_view_carries_the_colour_of_every_shape(circle_problem, lattice, make_candidate) -> None:
    """The view is the single source of colour: one shape painted, the rest left to the theme."""
    placements = list(lattice(2, 2, 5.0))
    placements[1] = replace(placements[1], color="#ff8800")
    view = build_view(circle_problem, make_candidate(circle_problem, placements, scale=5.0))
    assert [shape.color for shape in view.shapes] == [None, "#ff8800", None, None]
    assert [shape["color"] for shape in view.to_dict()["shapes"]] == [None, "#ff8800", None, None]


def test_view_groups_visually_identical_square_orientations(square_problem, make_candidate) -> None:
    placements = [
        Placement("s000", -2, 0, rotation=0),
        Placement("s001", 0, 0, rotation=90),
        Placement("s002", 2, 0, rotation=45),
        Placement("s003", 4, 0, rotation=45.02),
        Placement("s004", 6, 0, rotation=-36.623786),
    ]
    view = build_view(square_problem, make_candidate(square_problem, placements, scale=1))
    assert [shape.orientation_group for shape in view.shapes] == [0, 0, 1, 1, 2]
    assert [shape.orientation_deg for shape in view.shapes] == pytest.approx([0, 0, 45, 45, -36.623786])


def test_a_coloured_shape_is_painted_in_its_own_colour(circle_problem, lattice, make_candidate) -> None:
    placements = list(lattice(2, 2, 5.0))
    placements[1] = replace(placements[1], color="#ff8800")
    svg = render_svg(circle_problem, make_candidate(circle_problem, placements, scale=5.0))
    circles = _root(svg).findall(f".//{SVG}circle")
    assert (circles[1].get("fill"), circles[1].get("stroke")) == ("#ff8800", "#ff8800")
    others = [element.get("fill") for index, element in enumerate(circles) if index != 1]
    assert others == [RenderOptions().shape_fill] * 3


def test_monochrome_export_ignores_saved_shape_colours(circle_problem, lattice, make_candidate) -> None:
    placements = list(lattice(2, 2, 5.0))
    placements[1] = replace(placements[1], color="#ff8800")
    options = RenderOptions(shape_fill="#b6b6b6", shape_stroke="#4d4d4d",
                            honor_shape_colors=False, show_violations=False)
    svg = render_svg(circle_problem, make_candidate(circle_problem, placements, scale=5.0), options)
    circles = _root(svg).findall(f".//{SVG}circle")
    assert {circle.get("fill") for circle in circles} == {"#b6b6b6"}
    assert "#ff8800" not in svg


def test_a_violation_outranks_the_colour_of_a_shape(circle_problem, lattice, make_candidate) -> None:
    """A shape the analysis reports as overlapping keeps the violation colours."""
    placements = list(lattice(2, 2, 5.0))
    placements[0] = replace(placements[0], color="#ff8800")
    placements[1] = replace(placements[1].moved(2.4, 2.5), color="#ff8800")
    svg = render_svg(circle_problem, make_candidate(circle_problem, placements, scale=5.0))
    options = RenderOptions()
    marked = _root(svg).findall(f".//{SVG}circle")[:2]
    assert [element.get("fill") for element in marked] == [options.violation_fill] * 2
    assert [element.get("stroke") for element in marked] == [options.violation_stroke] * 2


def test_labels_are_upright_and_ordered_top_to_bottom(
    circle_problem, lattice, make_candidate
) -> None:
    candidate = make_candidate(circle_problem, lattice(2, 2, 5.0), scale=5.0)
    labels = _root(render_svg(circle_problem, candidate, RenderOptions(show_ids=True))).findall(
        f".//{SVG}text"
    )
    assert [label.text for label in labels] == ["s000", "s001", "s002", "s003"]
    # s000 is the top-left circle, s002 the bottom-left one: on screen the
    # former must have the smaller y, which is only true if the flip is right.
    assert float(labels[0].get("y")) < float(labels[2].get("y"))


def test_voids_can_be_outlined(circle_problem, lattice, make_candidate) -> None:
    candidate = make_candidate(circle_problem, lattice(2, 2, 5.0), scale=5.0)
    options = RenderOptions(show_voids=True)
    svg = render_svg(circle_problem, candidate, options)
    strokes = [element.get("stroke") for element in _root(svg).findall(f".//{SVG}path")]
    assert options.void_fill in strokes


def test_strokes_keep_their_pixel_width_at_any_scale(circle_problem, make_candidate) -> None:
    """A width set in pixels stays so once the scene is scaled, even for a rasteriser
    that ignores ``vector-effect`` (a tiny problem is scaled by hundreds)."""
    tiny = replace(circle_problem, arena=Arena.rectangle(2.0, 2.0), objective=MaximizeCount(scale=0.5))
    options = RenderOptions(width=800, padding=0.0)
    root = _root(render_svg(tiny, make_candidate(tiny, [Placement("s000", 0.0, 0.0)], scale=0.5), options))
    circle = root.find(f".//{SVG}circle")
    arena = root.find(f".//{SVG}path")
    assert circle is not None and arena is not None
    pixels_per_unit = 800 / 2.0
    assert float(circle.get("stroke-width")) * pixels_per_unit == pytest.approx(options.shape_stroke_width, rel=1e-3)
    assert float(arena.get("stroke-width")) * pixels_per_unit == pytest.approx(options.arena_stroke_width, rel=1e-3)


def test_an_empty_candidate_still_renders(circle_problem, make_candidate) -> None:
    svg = render_svg(circle_problem, make_candidate(circle_problem, [], scale=1.0))
    assert _root(svg).tag == f"{SVG}svg"


def test_a_non_square_arena_keeps_its_aspect_ratio(circle_problem, make_candidate) -> None:
    wide = Problem(
        problem_id="wide",
        arena=Arena.rectangle(20.0, 10.0),
        shape=Circle(),
        objective=MaximizeCount(scale=1.0),
    )
    svg = render_svg(wide, make_candidate(wide, [], scale=1.0), RenderOptions(width=800, padding=0.0))
    root = _root(svg)
    assert int(root.get("width")) == 800
    assert int(root.get("height")) == 400
