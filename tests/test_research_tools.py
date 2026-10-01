"""Research mode's tools: exact refinement, dissection leads and submission pictures."""

from __future__ import annotations

import math

import pytest
from shapely.geometry import box

from paper_obs import research
from paper_obs.domain.placement import Placement
from paper_obs.geometry.engine import evaluate
from paper_obs.research.bounds import leads
from paper_obs.search.operators.initialization import grid_initialize


def _loose_tiling(problem, start):
    """The copies on the unit cells that tile the arena, shrunk, shifted and turned a little."""
    region = problem.arena.geometry
    ring = list(region.exterior.coords)
    side = min(math.dist(a, b) for a, b in zip(ring, ring[1:]))
    left, bottom, right, top = region.bounds
    cells = [(left + (i + 0.5) * side, bottom + (j + 0.5) * side)
             for i in range(round((right - left) / side)) for j in range(round((top - bottom) / side))
             if region.buffer(1e-9).contains(box(left + i * side, bottom + j * side, left + (i + 1) * side, bottom + (j + 1) * side))]
    assert len(cells) == len(start.placements)
    return side, start.derive(scale=0.8 * side, placements=[
        Placement(item.shape_id, x + 0.01 * k * side, y - 0.007 * k * side, 3.0 * k)
        for k, (item, (x, y)) in enumerate(zip(start.placements, cells))])


@pytest.mark.parametrize(("slug", "count"), [("squindom", 2), ("squinl", 3)])
def test_refinement_closes_the_contacts_of_a_loose_tiling(slug: str, count: int) -> None:
    pytest.importorskip("scipy")
    from paper_obs.search.refine import exact_refine

    problem = research.catalog_problem(slug, count)
    side, loose = _loose_tiling(problem, grid_initialize(problem))
    refined = exact_refine(problem, loose)
    assert evaluate(problem, refined).valid
    # The squares tile the domino and the L exactly: the L's notch corner must stay outside them.
    assert refined.scale == pytest.approx(side, rel=1e-6)


def test_a_rep_tile_construction_is_a_lead_against_a_weaker_entry() -> None:
    def instance(count: int, value: float) -> dict:
        return {"counts": [count], "value": value, "attribution": "test", "formula": ""}

    catalog = {"families": [{
        "slug": "squinsqu", "shape": "square", "container": "square", "section": "Packing Equal Copies",
        "supported": True, "problem_template": {"stub": True},
        "instances": [instance(1, 1.0), instance(2, 2.0), instance(4, 2.1)],
    }]}
    found = leads(catalog)
    assert [(lead["slug"], lead["count"]) for lead in found] == [("squinsqu", 4)]
    assert found[0]["bound"] == pytest.approx(2.0) and found[0]["published"] == 2.1


def test_the_shipped_catalog_can_be_scanned() -> None:
    import json

    for lead in leads(json.loads(research.CATALOG.read_text(encoding="utf-8"))):
        assert lead["bound"] < lead["published"] and lead["construction"]


def test_a_submission_picture_copies_the_size_palette_and_transparency_of_the_one_it_replaces(tmp_path) -> None:
    pytest.importorskip("resvg_py")
    image_module = pytest.importorskip("PIL.Image")
    original = image_module.new("RGBA", (120, 90), (0, 0, 0, 0))  # a transparent outside
    original.paste((255, 255, 255, 255), (0, 0, 100, 90))
    original.paste((240, 224, 240, 255), (10, 10, 60, 60))
    original.paste((0, 0, 0, 255), (0, 70, 100, 72))
    original.save(tmp_path / "26.gif")
    from paper_obs.research.picture import submission_picture

    problem = research.catalog_problem("taninL", 6)
    path = submission_picture(problem, grid_initialize(problem), tmp_path / "new" / "26.gif", like=tmp_path / "26.gif")
    assert path.with_suffix(".svg").read_text(encoding="utf-8").startswith("<svg")
    with image_module.open(path) as drawn:
        assert drawn.size == (120, 90) and "transparency" in drawn.info
        colours = {colour[:3] for _, colour in drawn.convert("RGBA").getcolors() if colour[3] == 255}
    assert colours <= {(255, 255, 255), (240, 224, 240), (0, 0, 0)} and len(colours) == 3
