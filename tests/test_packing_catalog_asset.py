"""The generated Packing Center asset must stay complete and readable.

The interface fetches this file as-is and shows one card per published record, so
an empty subfamily or a record without a value would render as a broken tile. For
the equal-copies matrix and the covering section the asset also carries a ready-made
`problem_template`: the test asks the domain to decode each one and the engine to
judge a construction built on it, so a family the interface offers really is a
problem the lab can run.
The test asserts the observable contract of the asset, never how the script builds
it.
"""

import copy
import json
import math
from pathlib import Path

import pytest

from paper_obs.domain import Problem
from paper_obs.geometry.engine import evaluate
from paper_obs.search.operators.initialization import (
    cover_initialize,
    grid_initialize,
    varied_initialize,
)

ROOT = Path(__file__).resolve().parents[1]
ASSET = ROOT / "apps/web/public/catalog/packing_equal_copies.json"

#: Every section the asset publishes, by the collection's own heading.
SECTIONS = {
    "Packing Equal Copies",
    "Packing Copies to Maximize Total Perimeter",
    "Other Packing Problems",
    "Covering",
}

#: The equal-copies subfamilies the collection links to a page it does not host.
EXTERNAL_PAGES = {"Squares in Squares", "Circles in Octagons", "Circles in Dominoes"}


def asset() -> dict:
    return json.loads(ASSET.read_text(encoding="utf-8"))


def equal_copies(document: dict) -> list[dict]:
    """The subfamilies of the matrix, the only ones the lab can launch today."""
    return [family for family in document["families"] if family["section"] == "Packing Equal Copies"]


def test_asset_publishes_every_section_and_no_empty_family():
    document = asset()
    assert document["families"], "the catalogue is empty"
    assert {family["section"] for family in document["families"]} == SECTIONS
    for family in document["families"]:
        assert family["instances"], f"{family['slug']} publishes no instance"
        assert family["page"].startswith(document["base"]), family["slug"]


def test_every_record_carries_a_readable_measure_and_an_attribution():
    """A record shows a number, or the formula that stands in for one.

    The ellipse page prints some of its areas as truncated decimals; those records
    carry no number at all (``value`` is null) and must keep the formula the source
    printed, so no card is ever asked to display a value nobody could read.
    """
    for family in asset()["families"]:
        for record in family["instances"]:
            assert record["counts"], family["slug"]
            if record["value"] is None:
                assert str(record["formula"]).strip(), family["slug"]
            else:
                assert isinstance(record["value"], (int, float)), family["slug"]
            assert record["attribution"].strip(), family["slug"]


def test_the_two_measured_sections_are_judged_while_the_other_problems_stay_references():
    """Covering and total-perimeter are judged now; "Other Packing Problems" is not."""
    for family in asset()["families"]:
        if family["section"] in ("Covering", "Packing Copies to Maximize Total Perimeter"):
            assert family["supported"] is True, family["slug"]
        elif family["section"] != "Packing Equal Copies":
            # The matrix keeps its own table of launchable and documented
            # subfamilies; only the reference section is decided here.
            assert family["supported"] is False, family["slug"]


def test_every_covering_family_is_launchable_and_the_engine_judges_it():
    """Each covering page becomes a cover_region problem the engine can run.

    The asset ships no covering arrangement, so the engine initializes a lattice to
    judge: that starting point does not cover the arena, which is why this asserts a
    positive score and a judged verdict, never validity. A covering applies neither
    containment nor non-overlap; the exact arrangements themselves are pinned in
    tests/geometry/test_covering.py and tests/domain/test_cover_region.py.
    """
    families = [family for family in asset()["families"] if family["section"] == "Covering"]
    assert len(families) == 9, [family["slug"] for family in families]
    for family in families:
        assert family["supported"] is True, family["slug"]
        template = family.get("problem_template")
        assert isinstance(template, dict), family["slug"]
        problem = Problem.from_dict(copy.deepcopy(template))
        assert problem.arena is not None, family["slug"]
        assert problem.objective.kind == "cover_region", family["slug"]
        assert problem.rotation.mode.value == "free", family["slug"]
        kinds = [constraint.kind for constraint in problem.effective_constraints]
        assert "arena_covered" in kinds, family["slug"]
        assert "arena_containment" not in kinds, family["slug"]
        assert "non_overlap" not in kinds, family["slug"]
        verdict = evaluate(problem, grid_initialize(problem), with_metrics=False)
        assert verdict.primary > 0.0, family["slug"]


def test_a_caveat_marks_a_launchable_family_whose_value_is_not_comparable():
    """A caveat says the template cannot read the published number back.

    It may only mark a family that is launchable and carries a template, and it must
    be absent from every family whose template reads its published size back exactly;
    a launcher therefore never hides a mismatch behind a comparable-looking score.
    """
    document = asset()
    caveated = {
        family["slug"] for family in document["families"] if str(family.get("caveat", "")).strip()
    }
    # The free-ratio ellipse publishes an area, and so does squares-covering-squares;
    # the two free-ratio total-perimeter containers fix their circular and square
    # cases; every other launchable family's promoted metric is the published number.
    assert caveated == {"cirinel", "squcosqu", "cirRell", "cirRrec"}, caveated
    for family in document["families"]:
        if family["slug"] in caveated:
            assert family["supported"] is True, family["slug"]
            assert isinstance(family.get("problem_template"), dict), family["slug"]
            assert str(family.get("unsupported_reason", "")) == "", family["slug"]
        else:
            assert str(family.get("caveat", "")) == "", family["slug"]


def test_the_ellipse_records_show_the_source_area_or_no_number():
    """The ellipse page prints A = pi(k) beside a and b, and our value is pi*a*b.

    A record whose axes the source truncates with a plus gets no number at all: the
    card falls back on the formula the source itself printed.
    """
    families = [family for family in asset()["families"] if family["slug"] == "cirinel"]
    assert families, "the catalogue no longer names the ellipse family"
    records = families[0]["instances"]
    assert all(record["symbol"] == "a" for record in records)
    assert all(str(record["formula"]).startswith("A = π(") for record in records)
    numbers = [record["value"] for record in records]
    assert any(value is not None for value in numbers), "no exact ellipse area was read"
    assert any(value is None for value in numbers), "no truncated ellipse area was refused"
    assert all(value is None or value > 0.0 for value in numbers)


def test_every_equal_copies_family_is_launchable_or_documented():
    """No subfamily of the matrix is silently left out.

    A family the lab can express carries a `problem_template` and is supported; one
    it cannot carries the reason in the asset itself, so the interface's "coming
    soon" always has a documented cause. The pages the collection links elsewhere
    are documented the same way, in `excluded`.
    """
    document = asset()
    for family in equal_copies(document):
        if family["supported"]:
            assert isinstance(family.get("problem_template"), dict), family["slug"]
        else:
            assert family.get("unsupported_reason", "").strip(), family["slug"]
    external = {
        entry["title"]
        for entry in document["excluded"]
        if entry.get("section") == "Packing Equal Copies"
    }
    assert EXTERNAL_PAGES <= external, external


def test_every_template_is_accepted_and_judged_by_the_engine():
    """Each template decodes in the domain and the engine judges a construction.

    The template carries the trivial count of one; the engine initializes a grid on
    it and every constraint must pass. This is the same trip the interface makes
    when a card is added, without the HTTP layer and without a network.
    """
    families = equal_copies(asset())
    supported = [family for family in families if family["supported"]]
    templates = 0
    for family in supported:
        problem = Problem.from_dict(copy.deepcopy(family["problem_template"]))
        candidate = grid_initialize(problem)
        verdict = evaluate(problem, candidate, with_metrics=False)
        assert verdict.primary > 0.0, family["slug"]
        assert verdict.valid, f"{family['slug']}: {verdict.validation.summary()}"
        templates += 1
    assert templates == len(supported) >= 70, f"only {templates} templates were emitted"


def test_the_ellipse_family_is_launchable_with_a_caveat_and_a_template():
    """The ellipse arena is real, and the family is offered with its caveat.

    The equal-copies ellipse family publishes an area for a free-ratio ellipse; the
    launched template fixes that ratio, so the asset says so in ``caveat`` instead of
    withholding the family. The engine still judges a construction built on it.
    """
    families = [
        family
        for family in asset()["families"]
        if family["section"] == "Packing Equal Copies" and family["container"] == "ellipse"
    ]
    assert families, "the catalogue no longer names an ellipse family"
    for family in families:
        assert family["supported"] is True, family["slug"]
        assert str(family.get("caveat", "")).strip(), family["slug"]
        template = family.get("problem_template")
        assert isinstance(template, dict), family["slug"]
        problem = Problem.from_dict(copy.deepcopy(template))
        assert problem.arena is not None and problem.arena.shape.kind == "ellipse"
        verdict = evaluate(problem, grid_initialize(problem), with_metrics=False)
        assert verdict.valid, f"{family['slug']}: {verdict.validation.summary()}"


def test_the_template_convention_is_stated():
    """The asset says what a template means, so a reader never has to infer it."""
    convention = asset().get("template_convention", "")
    assert "maximize_scale" in convention
    assert "minimize_container" in convention
    assert "cover_region" in convention
    assert "covered_size" in convention
    assert "maximize_total_perimeter" in convention
    assert "total_scale" in convention


def test_every_total_perimeter_family_is_launchable_and_the_engine_judges_it():
    """Each perimeter page becomes a total-perimeter problem the engine can run.

    The asset ships no arrangement, so the varied start -- the family's own kind of
    candidate, one large copy and the rest smaller -- is judged: it must be valid,
    because the copies stay inside the arena and never share area, and its promoted
    total_scale is the sum the source pages print. The published records themselves
    are pinned in tests/geometry/test_total_perimeter.py.
    """
    families = [
        family
        for family in asset()["families"]
        if family["section"] == "Packing Copies to Maximize Total Perimeter"
    ]
    assert len(families) == 16, [family["slug"] for family in families]
    for family in families:
        assert family["supported"] is True, family["slug"]
        template = family.get("problem_template")
        assert isinstance(template, dict), family["slug"]
        problem = Problem.from_dict(copy.deepcopy(template))
        assert problem.arena is not None, family["slug"]
        assert problem.objective.kind == "maximize_total_perimeter", family["slug"]
        assert problem.rotation.mode.value == "free", family["slug"]
        kinds = [constraint.kind for constraint in problem.effective_constraints]
        assert "arena_containment" in kinds, family["slug"]
        assert "non_overlap" in kinds, family["slug"]
        assert "required_shape_count" in kinds, family["slug"]
        assert "common_scale" in kinds, family["slug"]
        verdict = evaluate(problem, varied_initialize(problem))
        assert verdict.valid, f"{family['slug']}: {verdict.validation.summary()}"
        assert verdict.primary > 0.0, family["slug"]
        assert verdict.promoted_metric == "total_scale", family["slug"]


def test_the_free_ratio_perimeter_containers_carry_a_caveat():
    """The ellipse of perimeter 2*pi and the rectangle of perimeter 4 are fixed.

    Both publish a container of free aspect ratio; the launched template fixes the
    case the source's own n = 1 instance is -- the circle of radius 1 and the square
    of side 1 -- so both carry the caveat that says the engine's total is the
    published sum at n = 1 and a lower bound beyond it.
    """
    families = {
        family["slug"]: family
        for family in asset()["families"]
        if family["section"] == "Packing Copies to Maximize Total Perimeter"
    }
    for slug in ("cirRell", "cirRrec"):
        family = families.get(slug)
        assert family is not None, slug
        assert family["supported"] is True, slug
        assert str(family.get("caveat", "")).strip(), slug
        template = Problem.from_dict(copy.deepcopy(family["problem_template"]))
        assert template.objective.kind == "maximize_total_perimeter", slug
    assert families["cirRell"]["container"] == "ellipse"
    assert families["cirRrec"]["container"] == "rectangle"

#: The identifier namespace the frontend gives each section (copyProblemId).
SECTION_NAMESPACES = {
    "Packing Equal Copies": "in-smallest",
    "Packing Copies to Maximize Total Perimeter": "total-perimeter-in",
    "Covering": "covering",
}

#: The plural noun the frontend builds a shape's identifier from (copyNoun).
COPY_NOUNS = {
    "circle": "circles",
    "triangle": "triangles",
    "square": "squares",
    "pentagon": "pentagons",
    "hexagon": "hexagons",
    "octagon": "octagons",
    "tan": "tans",
    "domino": "dominoes",
    "l": "L's",
}

#: The largest count the navigator lists (catalog.ts MAX_VISIBLE_COUNT).
MAX_VISIBLE_COUNT = 100


def copy_problem_id(family: dict, count: int, figure: str) -> str:
    """Mirror apps/web/src/equalCopiesCatalog.ts for one card.

    The frontend builds a card's identifier from the shape's plural, its count,
    the section's namespace and the container, and qualifies an *ambiguous* count
    -- one the family prints beside more than one figure -- with the figure's stem,
    so two cards that share a printed number cannot overwrite one another.
    """
    namespace = SECTION_NAMESPACES.get(family["section"], "family")
    noun = COPY_NOUNS.get(family["shape"], family["shape"])
    identity = f"{noun}-{count}-{namespace}-{family['container']}"
    cards = [
        record["counts"]
        for record in family["instances"]
        if record["counts"]
    ]
    printed = [value for counts in cards for value in counts if value <= MAX_VISIBLE_COUNT]
    ambiguous = printed.count(count) > 1
    stem = figure.rsplit(".", 1)[0] if "." in figure else figure
    return f"{identity}-figure-{stem}" if ambiguous and stem else identity


def test_the_covering_start_covers_every_family_at_counts_one_to_three() -> None:
    """The covering start is judged a covering, for every family and small count.

    The arena is the source's unit target, the copies are the family's unit shape,
    and the count is the card's: the start lays copies over the arena's bounding box
    and the engine's own coverage constraint decides. This asserts the verdict, the
    promoted metric and the placed count -- never the operator's arithmetic.
    """
    families = [family for family in asset()["families"] if family["section"] == "Covering"]
    assert len(families) == 9, [family["slug"] for family in families]
    for family in families:
        for count in (1, 2, 3):
            problem = Problem.from_dict(
                {
                    **copy.deepcopy(family["problem_template"]),
                    "objective": {"type": "cover_region", "count": count},
                }
            )
            candidate = cover_initialize(problem)
            verdict = evaluate(problem, candidate)
            assert verdict.valid, f"{family['slug']} n={count}: {verdict.validation.summary()}"
            assert candidate.n_shapes == count, family["slug"]
            assert verdict.promoted_metric == "covered_size", family["slug"]


def test_the_covering_start_reaches_the_pinned_square_on_disc_optima() -> None:
    """Squares Covering Circles pins its n = 1 and n = 2 optima exactly.

    One unit square covers a unit disc when its side is 2, so the score is 1/2; two
    squares turned 45 degrees and slid together reach the proved 2 - sqrt(2). The
    arrangements themselves are pinned in tests/geometry/test_covering.py; what this
    asserts is that the covering start finds them, the engine scoring the result.
    The coverage tolerance is 1e-6 of the arena area and admits a hair of over-claim
    on the frontier, hence a relative tolerance well above it.
    """
    family = next(family for family in asset()["families"] if family["slug"] == "sqcovcir")
    pinned = {1: 0.5, 2: 2.0 - math.sqrt(2.0)}
    for count, expected in pinned.items():
        problem = Problem.from_dict(
            {
                **copy.deepcopy(family["problem_template"]),
                "objective": {"type": "cover_region", "count": count},
            }
        )
        verdict = evaluate(problem, cover_initialize(problem))
        assert verdict.valid, verdict.validation.summary()
        assert verdict.primary == pytest.approx(expected, rel=1e-3)


def test_every_launchable_family_composes_a_distinct_problem_id() -> None:
    """Two families can never share the identifier a card is filed under.

    A covering card and an equal-copies card put the same shape into the same
    container from two sections, so before the namespace existed they composed the
    same identifier and overwrote each other in a category. This mirrors the
    frontend's rule -- see apps/web/src/equalCopiesCatalog.ts -- and asserts that no
    two launchable families collide, and that a shape and container really is shared
    across sections, so the test is not vacuous.
    """
    owners: dict[str, str] = {}
    shared: dict[tuple[str, str], set[str]] = {}
    for family in asset()["families"]:
        if not family["supported"]:
            continue
        shared.setdefault((family["shape"], family["container"]), set()).add(family["section"])
        for record in family["instances"]:
            for count in record["counts"]:
                identity = copy_problem_id(family, count, record["figure"])
                # The same family may qualify a doubly-printed count by its figure;
                # what must never happen is two *families* composing one identifier
                # and overwriting each other.
                owner = owners.setdefault(identity, family["slug"])
                assert owner == family["slug"], (
                    f"{family['slug']} and {owner} both compose {identity!r}"
                )
    assert any(len(sections) > 1 for sections in shared.values())


def test_a_within_family_duplicate_count_is_qualified_by_its_figure() -> None:
    """A source typo may print one count twice; the two cards now stay distinct.

    The dominoes-in-squares page prints "3." beside figure 5.png as well as beside
    its real n = 3 record (figure 4.png), and the asset records exactly that in the
    family's own warnings. Reproducing what the site prints means both cards keep
    that count, so the frontend qualifies an ambiguous count with the card's figure
    stem: the two cards compose different identifiers and can coexist in a category
    instead of the second overwriting the first. The React key still adds the card's
    position in the family's expanded list (see
    apps/web/src/components/ProfileNavigator.tsx), so a duplicated count can never
    make two siblings share a key either.
    """
    family = next(entry for entry in asset()["families"] if entry["slug"] == "dominsqu")
    assert any("label '3.'" in warning and "5.png" in warning for warning in family["warnings"])

    cards = [(record, count) for record in family["instances"] for count in record["counts"]]
    keys = [f"{index}:{record['figure']}:{count}" for index, (record, count) in enumerate(cards)]
    assert len(keys) == len(set(keys))

    three = [(record["figure"], count) for record, count in cards if count == 3]
    assert len(three) == 2
    assert {copy_problem_id(family, count, figure) for figure, count in three} == {
        "dominoes-3-in-smallest-square-figure-4",
        "dominoes-3-in-smallest-square-figure-5",
    }
    # A count printed beside a single figure keeps the historical identifier.
    four = next(record for record in family["instances"] if 4 in record["counts"])
    assert copy_problem_id(family, 4, four["figure"]) == "dominoes-4-in-smallest-square"
