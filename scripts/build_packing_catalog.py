"""Build the catalogue of Erich Friedman's *Packing Center* from its own pages.

The collection publishes an index of sections and one page per subfamily
("circles in squares", "tans in hexagons"…); each page lists its instances with
the published value, whether it is an optimum or a construction, who found it and
when, and a figure. This script reads the index, then every page of the sections
it catalogues, and writes one record per instance.

Besides the "Packing Equal Copies" matrix, two sections publish exactly one
measured value per figure and are catalogued the same way: "Packing Copies to
Maximize Total Perimeter" (the value is the largest sum of radii, or of short
sides, the copies reach) and "Covering" (the value is the size — radius, side or
area — of the largest shape a fixed number of unit shapes covers). "Other Packing
Problems" joins them where its page reads like the others: the consecutive dominoes
and L's publish one side per figure. The consecutive rectangles publish three
quantities (aspect ratio, side, coverage) in one cell, and "Tiling Almost Squares"
publishes no measured value; both are left out and listed under "excluded" with the
reason. "Three Dimensional Packing" (solid geometry), "Packing Animations" (no
instances), "Heilbronn Problems" (external pages of points, not packed shapes) and
"Related Problems" (not packing problems) are out of scope for a planar lab and are
not parsed.

The templates
-------------
Every subfamily of "Packing Equal Copies" also carries a ready-made
``problem_template``: the arena of its container at the length the source
publishes, its unit shape, and the objective whose primary is the reciprocal of
that number. A square or circle container keeps ``minimize_container`` -- the
domain derives those two exactly -- and every other container is a fixed arena
read with ``maximize_scale``, the convention the Packomania importer already
uses. The ellipse is the one container whose arena needed a new primitive and a
fixed proportion of its own; the equal-copies family that packs into one publishes
the *area* of the smallest ellipse with a free aspect ratio, so its template is
launchable but carries a ``caveat`` saying the engine's size is not that area --
the one published number the launched problem cannot read back. Every "Covering"
subfamily carries a ``problem_template`` too: the arena is the region the copies
cover at its unit size, the shape is the family's unit copy, and the objective is
``cover_region``, whose promoted ``covered_size`` is the reciprocal of the common
scale -- the size of the largest target the copies cover, the published number.
The squares-covering-squares family publishes an *area* where every other covering
family publishes a length, so its template carries a ``caveat`` noting that the
area is ``covered_size ** 2``. Every "Packing Copies to Maximize Total Perimeter"
subfamily carries a template too: the arena is the family's container at the length
the source measures it by, the shape is its unit copy, and the objective is
``maximize_total_perimeter``, whose promoted ``total_scale`` is the sum of the
copies' local scales -- the page's own ``Σ r`` or ``Σ s``. The ellipse of
perimeter 2*pi and the rectangle of perimeter 4 publish a container of free aspect
ratio, so their templates fix the circular and square cases and carry a caveat. The
index's own title row names a subfamily, so the
uppercase L containers and the two "arbitrary" pages are catalogued too, and the
three subfamilies the collection links elsewhere are documented under "excluded".

Nothing is guessed. A value that does not parse, a label that disagrees with the
figure it is drawn from, a page that has moved: all of it is reported in
"warnings" and left out of the records rather than filled with a plausible
number. An ellipse area is the product of the two semi-axes the page prints; a
record whose axes the source truncates with a plus carries no number at all, so
``value`` is null and the card shows the printed formula instead. Re-running costs
no request; pages are cached under ignored ``scripts/out/``.

    .venv/bin/python scripts/build_packing_catalog.py [--refresh]

Writes scripts/out/packing_equal_copies.json and prints a summary.
"""

from __future__ import annotations

import json
import math
import re
import sys
import urllib.request
from datetime import date
from html import unescape
from pathlib import Path

from paper_obs.domain.arena import Arena
from paper_obs.domain.constraints import RotationMode, RotationPolicy
from paper_obs.domain.objectives import (
    CoverRegion,
    MaximizeScale,
    MaximizeTotalPerimeter,
    MinimizeContainer,
)
from paper_obs.domain.problem import Problem
from paper_obs.domain.shapes import (
    Circle,
    RegularPolygon,
    domino,
    l_tromino,
    right_isosceles_triangle,
)

INDEX = "https://erich-friedman.github.io/packing/index.html"
BASE = "https://erich-friedman.github.io/packing/"
CACHE = Path(__file__).resolve().parent / "out/packing-cache"
OUT = Path(__file__).resolve().parent / "out" / "packing_equal_copies.json"
#: The same document, where the interface can fetch it while it is being served.
WEB = Path(__file__).resolve().parents[1] / "apps" / "web" / "public" / "catalog" / "packing_equal_copies.json"

#: The nine shapes and nine containers of the matrix, by the collection's own abbreviations.
PARTS = {
    "cir": "circle",
    "tri": "triangle",
    "squ": "square",
    "pen": "pentagon",
    "hex": "hexagon",
    "oct": "octagon",
    "tan": "tan",
    "dom": "domino",
    "l": "l",
}

SLUG = re.compile(r"\b(%s)in(%s)\b" % ("|".join(PARTS), "|".join(PARTS)))

#: The nine unit copies of the matrix, at the size the source publishes them.
#:
#: A circle is radius 1 - the collection measures 'n unit circles' by their radius,
#: so the size of the smallest container is 1 / primary - exactly the normalisation
#: the Packomania importer uses (build_packomania_candidates.py, CIRCLE). A regular
#: polygon is side 1; the tan is leg 1, the domino short side 1 and the L a unit
#: square, the natural sizes the domain's own helpers define. The published number
#: is always the container's own defining length, so maximising the common scale of
#: these units and taking its reciprocal reads it back.
UNIT_SHAPES = {
    "circle": Circle(radius=1.0),
    "triangle": RegularPolygon(sides=3, side=1.0),
    "square": RegularPolygon(sides=4, side=1.0),
    "pentagon": RegularPolygon(sides=5, side=1.0),
    "hexagon": RegularPolygon(sides=6, side=1.0),
    "octagon": RegularPolygon(sides=8, side=1.0),
    "tan": right_isosceles_triangle(),
    "domino": domino(),
    "l": l_tromino(),
}


def _regular_arena(sides: int) -> Arena:
    """Return the arena of a regular polygon whose physical side is 1."""
    return Arena.regular_polygon(sides, 1.0 / (2.0 * math.sin(math.pi / sides)))


def _polygon_arena(shape, scale: float = 1.0) -> Arena:
    """Return a centred custom outline as an arena, normalised by its defining length.

    The outline is the domain's own shape for that family — the tan's triangle, the
    L's three squares — scaled so that the length the source prints for the container
    is 1, and the arena declares that length, so the engine reports the published
    size (``equivalent_container_side``) as exactly 1 / primary. The arena keeps the
    family's natural orientation: the initialiser searches for a place to put its
    lattice now, so turning the region is no longer needed, and the unturned arena
    is the one the published numbers are about.
    """
    return Arena(shape=Arena.polygon([(float(x), float(y)) for x, y in shape.vertices(scale)]).shape,
                 reference_length=1.0)


#: The fixed ellipse arena of the collection's ellipse families: a 2 x 1 ellipse,
#: the proportion ``build_subfamily_previews.py`` draws the same container at, with
#: semi-axes 1 and 2. The proportion is a choice, not a measurement -- it is only
#: what makes an ellipse an arena the engine can read with ``maximize_scale`` --
#: and it is deliberately not the free-ratio ellipse the equal-copies family
#: publishes, whose area no single arena can reproduce.
ELLIPSE_ARENA = Arena.ellipse(2.0, 1.0)

#: The seven *rotatable* containers of the matrix, normalised so that the source's
#: printed number is the arena's own defining length and the published size is
#: exactly 1 / primary. A regular polygon is side 1; the domino is its short side
#: (a 2 x 1 rectangle); the tan is leg 1. Every non-regular arena declares that
#: length (``reference_length``), so the engine reports the published size for it
#: too. The L depends on the page: most measure it by its short side (l_tromino is
#: exactly that unit), the circle and square pages by its long side (outline scaled
#: by a half) -- see :func:`l_arena`. The square and the circle are deliberately
#: absent: the domain derives those two exactly (objectives.CONTAINERS), so their
#: families keep minimize_container, faithful to the curated square records.
ROTATABLE_ARENAS = {
    "triangle": _regular_arena(3),
    "pentagon": _regular_arena(5),
    "hexagon": _regular_arena(6),
    "octagon": _regular_arena(8),
    "tan": _polygon_arena(right_isosceles_triangle(), 1.0),
    "domino": Arena(shape=Arena.rectangle(2.0, 1.0).shape, reference_length=1.0),
    "l": _polygon_arena(l_tromino(), 1.0),
    "ellipse": ELLIPSE_ARENA,
}


def l_arena(page_intro: str) -> Arena:
    """Return the L arena whose declared length is the side the page prints.

    "Circles in L's" and "Squares in L's" print the long side; every other L page
    prints the short side, the side of one of the L's three squares.
    """
    return _polygon_arena(l_tromino(), 0.5 if "long side" in page_intro else 1.0)

#: The target regions the covering families cover, at the unit size the source
#: measures them by: a circle by its radius 1 -- the collection measures circles,
#: packed or covered, by radius, exactly as the equal-copies matrix does -- and a
#: regular polygon by side 1. The copies are the same UNIT_SHAPES as the matrix.
#: The template's promoted ``covered_size`` is the reciprocal of the common scale,
#: which is the source's published radius or side. The one family whose published
#: size is an area keeps its number and carries a caveat, see COVERING_AREA_CAVEAT.
COVERING_ARENAS = {
    "triangle": _regular_arena(3),
    "square": Arena.rectangle(1.0, 1.0),
    "circle": Arena.disk(1.0),
}

#: The target containers the total-perimeter families pack into, at the length the
#: source measures them by: a unit square (side 1), a unit circle (radius 1, the
#: collection measures circles by radius everywhere), a unit regular polygon (side
#: 1), and the two free-ratio containers fixed to the case the source's own first
#: instance is -- the ellipse of perimeter 2*pi becomes the circle of radius 1 and
#: the rectangle of perimeter 4 becomes the square of side 1. The copies are the
#: same UNIT_SHAPES as the matrix, and every one of them carries its own local
#: scale, which is what the objective scores.
PERIMETER_ARENAS = {
    "circle": Arena.disk(1.0),
    "triangle": _regular_arena(3),
    "square": Arena.rectangle(1.0, 1.0),
    "pentagon": _regular_arena(5),
    "ellipse": Arena.disk(1.0),
    "rectangle": Arena.rectangle(1.0, 1.0),
}

#: Why an equal-copies subfamily the domain cannot express stays unsupported: it
#: packs a different container shape per figure, so no single arena exists.
ARBITRARY_REASON = (
    "the source packs each figure into a different container, so there is no single "
    "arena a common scale could be maximised against"
)
#: The caveat a launchable family carries when its published number cannot be read
#: back from the fixed arena its template uses. The free-ratio ellipse is the one:
#: the domain builds the arena now and the family is offered, but the template fixes
#: a proportion, so its size is not the area the source publishes.
ELLIPSE_CAVEAT = (
    "The source publishes the AREA of the smallest ellipse that holds the copies with "
    "a free aspect ratio; the launched problem fixes that ratio (2:1), so the engine's "
    "container size is not directly comparable to the published area."
)
#: The one covering family whose published size is itself an area: "n unit squares
#: covering the largest known square (of area A)". The template's promoted
#: covered_size is the side of the largest covered square at unit copies, so the
#: published area is that metric squared; the caveat says so rather than letting a
#: similar-looking number pass for the area.
COVERING_AREA_CAVEAT = (
    "The source publishes the AREA A of the largest square the copies cover; the "
    "template's promoted covered_size is the side of that square at unit copies, so "
    "A = covered_size ** 2."
)
#: The two total-perimeter containers whose published aspect ratio is free. The
#: template fixes the case the source's own first instance confirms -- the circle
#: of perimeter 2*pi and the square of perimeter 4 -- so the engine's promoted
#: total_scale is the published sum at n = 1 and a lower bound beyond it.
PERIMETER_FREE_RATIO_CAVEATS = {
    "ellipse": (
        "The source packs the copies into an ellipse with perimeter 2*pi and a free "
        "aspect ratio; the launched problem fixes the circular case (radius 1, also "
        "perimeter 2*pi), which is the source's own n = 1 answer, so the engine's "
        "total_scale is the published sum at n = 1 and a lower bound beyond it."
    ),
    "rectangle": (
        "The source packs the copies into a rectangle of perimeter 4 and a free "
        "aspect ratio; the launched problem fixes the square case (side 1, also "
        "perimeter 4), which is the source's own n = 1 answer, so the engine's "
        "total_scale is the published sum at n = 1 and a lower bound beyond it."
    ),
}

#: What every problem_template in the asset means, so a reader never has to infer it.
TEMPLATE_CONVENTION = (
    "unit shapes: circle radius 1, regular polygon side 1, tan leg 1, domino short "
    "side 1, L unit square. A square or circle container keeps minimize_container; "
    "every other container is a fixed arena normalised to the length the source "
    "publishes (regular polygon side 1, domino short side 1, tan leg 1, L long side "
    "1) and the objective is maximize_scale, free rotation, count 1. The published "
    "size of a maximize_scale template is 1 / primary. An ellipse container is a "
    "fixed 2 x 1 arena: the equal-copies ellipse family publishes the area of a "
    "free-ratio ellipse, so its template is launchable and the family carries a "
    "caveat saying the engine's size is not that area. A covering template uses "
    "cover_region instead: the arena is the covered shape at unit size (circle "
    "radius 1, regular polygon side 1), the shape is the same unit copy, rotation "
    "is free, count is 1, and the published size is the promoted covered_size, the "
    "reciprocal of the common scale. The one covering family whose published size "
    "is an area (squares covering squares) carries a caveat saying "
    "A = covered_size ** 2. A total-perimeter template uses "
    "maximize_total_perimeter: the arena is the family's container at the source's "
    "own length (unit square, unit circle of radius 1, unit regular polygon of side "
    "1), the shape is the source's unit copy, rotation is free, count is 1, the "
    "common scale is fixed at 1, and the published number is the promoted "
    "total_scale -- the sum of the copies' local scales, which for these unit copies "
    "is the page's own sum of radii or of sides. The free-ratio ellipse of perimeter "
    "2*pi and the free-ratio rectangle of perimeter 4 are fixed to their circular "
    "and square cases and carry a caveat saying so."
)

#: The index sections this script parses, in the order the collection lists them.
#: The headings are the index's own, so the document names a section exactly as
#: the source does.
SECTIONS = (
    "Packing Equal Copies",
    "Packing Copies to Maximize Total Perimeter",
    "Other Packing Problems",
    "Covering",
)

#: Subfamilies the index lists in a published section whose page does not publish
#: one measured value per figure. They are reported, never given a guessed record.
UNPUBLISHED = {
    "minrect": "three quantities per figure (aspect ratio r, container side s, coverage p)",
    "almost": "figures label the index n only; no measured value",
}

#: The shape nouns the index titles use, and the canonical name stored for each.
SHAPE_WORDS = {
    "circle": "circle",
    "circles": "circle",
    "triangle": "triangle",
    "triangles": "triangle",
    "square": "square",
    "squares": "square",
    "pentagon": "pentagon",
    "pentagons": "pentagon",
    "hexagon": "hexagon",
    "hexagons": "hexagon",
    "octagon": "octagon",
    "octagons": "octagon",
    "tan": "tan",
    "tans": "tan",
    "domino": "domino",
    "dominoes": "domino",
    "l": "l",
    "l's": "l",
    "rectangle": "rectangle",
    "rectangles": "rectangle",
    "ellipse": "ellipse",
    "ellipses": "ellipse",
    "elipse": "ellipse",
    "elipses": "ellipse",
}

#: Descriptors the index puts in front of a shape without changing what it is.
QUALIFIERS = {"consecutive", "arbitrary", "similar", "almost", "tiling", "unit"}

#: The index heading that opens a section: the collection's own table of contents.
HEADING = re.compile(
    r"<HR[^>]*>\s*<CENTER>\s*<font\s+size=\+4>\s*([^<]+?)\s*</font>", re.I
)

#: "s = 2+5√2/4 = 3.76776+" or "r = 0.5 = 0.5": the symbol, the exact form, the value.
VALUE = re.compile(r"\b([sra])\s*=\s*(?:([^=]*?)\s*=\s*)?([0-9]*\.?[0-9]+)\s*\+?", re.I)
VALUE_START = re.compile(r"\b([sra])(?:\s*=\s*|\s+(?=[0-9]))", re.I)
FIGURE = re.compile(r"<img[^>]+src=[\"']?([^\"'>\s]+)", re.I)

#: The ellipse page prints its area beside the two semi-axes:
#: "A = π(16√6/9) a = 8/√6   b = 4/3". The generic VALUE pattern would read the
#: first numeral after the second "=" — a numerator, not the area — so an ellipse
#: cell is read from its two lengths instead, and their product is the number.
ELLIPSE_AREA = re.compile(r"A\s*=\s*(π\s*\([^)]*\))")
#: The two semi-axes, exactly as the page writes them: "3/√2", "1+√3", "√(3/2)".
ELLIPSE_AXES = re.compile(r"\ba\s*=\s*(\S+)\s+b\s*=\s*(\S+)")
#: A number in a printed length; the rest of the grammar is operators and "√".
LENGTH_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def fetch(url: str, *, refresh: bool = False) -> str:
    """Return the page at a URL, cached on disk: a re-run costs no request."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / (re.sub(r"[^a-zA-Z0-9]+", "_", url).strip("_") + ".html")
    if path.is_file() and not refresh:
        return path.read_text(encoding="utf-8", errors="replace")
    request = urllib.request.Request(url, headers={"User-Agent": "paper-obs catalog"})
    with urllib.request.urlopen(request, timeout=60) as answer:
        text = answer.read().decode("utf-8", errors="replace")
    path.write_text(text, encoding="utf-8")
    return text


def visible(cell: str) -> str:
    """Return the readable text of one HTML fragment, its line breaks kept."""
    text = re.sub(r"<br\s*/?>", " ", cell, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def cells(row: str) -> list[str]:
    """Split one table row into its cells."""
    return re.split(r"<t[dh]\b[^>]*>", row, flags=re.I)[1:]


def tables(html: str) -> list[list[str]]:
    """Return every table of a page as its list of rows.

    Rows are cut at their opening tag and not paired with a closing one: the older
    pages close every row, the newer ones leave the last one open, and reading the
    opening tag alone is what reads both.
    """
    found = re.findall(r"<table\b[\s\S]*?</table>", html, flags=re.I)
    return [
        [
            re.split(r"</tr>", part, flags=re.I)[0]
            for part in re.split(r"<tr\b[^>]*>", table, flags=re.I)[1:]
        ]
        for table in found
    ]


def counts_of(label: str) -> list[int]:
    """Return the instance numbers one figure stands for: "1.-2." is two of them."""
    match = re.search(r"([0-9]+)\s*\.?\s*(?:[-–]\s*([0-9]+))?", visible(label))
    if match is None:
        return []
    first, last = int(match.group(1)), match.group(2)
    return list(range(first, int(last) + 1)) if last else [first]


def status_of(attribution: str) -> str:
    """Return how the published value is known: proved, best known, or nothing said."""
    text = attribution.strip().lower()
    if text.startswith("proved"):
        return "proved"
    if text.startswith("found"):
        return "best_known"
    if text.startswith("trivial"):
        return "proved"
    return "none"


def figures_of(row: str) -> list[str]:
    """Return the cells of one row that carry a figure."""
    return [cell for cell in cells(row) if FIGURE.search(cell)]


def values_of(row: str) -> list[str]:
    """Return the cells of one row that carry a published value."""
    return [cell for cell in cells(row) if VALUE_START.search(visible(cell))]


def _printed_length(text: str) -> float | None:
    """Return the length the source prints, or None when it is not exact.

    An ellipse page writes a semi-axis as an exact form -- "3/√2", "1+√3",
    "√(3/2)" -- or as a decimal it truncates with a plus, "3.822+". The first is
    reproduced exactly; the second is a lower bound and is refused, because a
    number a reader cannot trust is worse than no number at all.
    """
    if text.endswith("+"):
        return None
    try:
        value, end = _length_sum(text, 0)
    except ValueError:
        return None
    return value if end == len(text) else None


def _length_sum(text: str, at: int) -> tuple[float, int]:
    """Read a sum or difference of terms, left to right."""
    value, at = _length_product(text, at)
    while True:
        at = _skip_spaces(text, at)
        if at < len(text) and text[at] in "+-":
            operator, at = text[at], at + 1
            right, at = _length_product(text, at)
            value = value + right if operator == "+" else value - right
        else:
            return value, at


def _length_product(text: str, at: int) -> tuple[float, int]:
    """Read a product or quotient, including the implicit "2√3" multiplication."""
    value, at = _length_factor(text, at)
    while True:
        at = _skip_spaces(text, at)
        if at < len(text) and text[at] in "*/":
            operator, at = text[at], at + 1
            right, at = _length_factor(text, at)
            value = value * right if operator == "*" else value / right
        elif at < len(text) and (text[at] == "√" or text[at] == "(" or text[at].isdigit()):
            right, at = _length_factor(text, at)
            value = value * right
        else:
            return value, at


def _length_factor(text: str, at: int) -> tuple[float, int]:
    """Read a number, a square root or a parenthesised expression."""
    at = _skip_spaces(text, at)
    if at >= len(text):
        raise ValueError(f"unfinished length {text!r}")
    if text[at] == "√":
        inside, at = _length_factor(text, at + 1)
        return math.sqrt(inside), at
    if text[at] == "(":
        value, at = _length_sum(text, at + 1)
        at = _skip_spaces(text, at)
        if at >= len(text) or text[at] != ")":
            raise ValueError(f"unclosed parenthesis in {text!r}")
        return value, at + 1
    match = LENGTH_NUMBER.match(text, at)
    if match is None:
        raise ValueError(f"no number at {text[at:]!r}")
    return float(match.group(0)), match.end()


def _skip_spaces(text: str, at: int) -> int:
    """Step over the spaces a page may put between tokens."""
    while at < len(text) and text[at].isspace():
        at += 1
    return at


def ellipse_reading(written: str) -> tuple[float | None, str, str, str]:
    """Read one ellipse cell: its area, its printed formula, and the rest.

    The area is ``π * a * b`` when both semi-axes are exact, and nothing when
    either is not: the record then keeps only the formula the source printed, so
    the card shows no number that was not read from the page.
    """
    area = ELLIPSE_AREA.search(written)
    axes = ELLIPSE_AXES.search(written)
    formula = area.group(0).strip() if area is not None else ""
    if axes is None:
        # The area is there but the two lengths are not: keep the formula and the
        # words after it, and leave the number unread rather than guess one.
        return None, formula, "a", written[area.end():] if area is not None else ""
    a, b = _printed_length(axes.group(1)), _printed_length(axes.group(2))
    value = math.pi * a * b if a is not None and b is not None else None
    return value, formula, "a", written[axes.end():]


def reading(written: str) -> tuple[float | None, str, str, str]:
    """Return one cell's published measure: value, formula, symbol, and the rest.

    An ellipse cell is read from its two semi-axes; every other page reads as one
    "symbol = exact form = value" cell. A record whose number could not be read
    still comes back with its formula, so it is kept and the card shows that
    formula rather than a guessed number.
    """
    # Only an ellipse page prints its area as pi times two lengths. The arbitrary
    # triangle pages print "A = 31.212+ a = ... b = ... c = ..." with no pi, and
    # their records keep the reading every other section gets.
    if ELLIPSE_AREA.search(written) is not None:
        return ellipse_reading(written)
    start = VALUE_START.search(written)
    if start is not None:
        body = written[start.end():]
        expression = re.split(r"\s+(?=Found\b|Proved\b|Trivial\b)", body, maxsplit=1, flags=re.I)
        exact = _printed_length(expression[0].strip())
        if exact is not None and not re.fullmatch(r"[0-9]*\.?[0-9]+", expression[0].strip()):
            return exact, expression[0].strip(), start.group(1).lower(), expression[1] if len(expression) > 1 else ""
        # A missing '=' still carries a decimal in its own cell (taninoct n=36).
        if "=" not in start.group(0):
            written = written[:start.end()] + "= " + body
    match = VALUE.search(written)
    if match is None:
        return None, "", "", written
    return (
        float(match.group(3)),
        (match.group(2) or "").strip(),
        match.group(1).lower(),
        written[match.end():],
    )


def instances(html: str, page: str, warnings: list[str]) -> list[dict]:
    """Return one record per published instance, and note what did not line up.

    The pages put three figures in a row and their values in the row below, with
    spacer cells between them; a few put one instance per row instead. Reading the
    figures of a table in order and its values in order covers both, where pairing
    cells by position does not.
    """
    found: list[dict] = []
    for rows in tables(html):
        heads = [cell for row in rows for cell in figures_of(row)]
        values = [cell for row in rows for cell in values_of(row)]
        ambiguous = len(heads) != len(values)
        if ambiguous:
            warnings.append(f"{page}: {len(heads)} figures for {len(values)} values")
        # Never zip unequal lists: one missing value shifts every later record.
        readings = [reading(visible(value)) for value in values]
        for position, head in enumerate(heads):
            value = values[position] if not ambiguous else ""
            written = visible(value)
            label = visible(head.split("<br")[0])
            numbers = counts_of(label)
            figure = FIGURE.search(head)
            drawn = re.search(r"([0-9]+)", figure.group(1)) if figure else None
            if not numbers and drawn is not None:
                numbers = [int(drawn.group(1))]
                warnings.append(f"{page}: no label, figure {figure.group(1)!r} read as one instance")
            numeric, formula, symbol, tail = reading(written)
            if ambiguous:
                numeric, symbol = None, next((item[2] for item in readings if item[2]), "")
                printed = [VALUE.search(visible(cell)) for cell in values]
                formula = f"Σ{symbol}: " + " / ".join(
                    match.group(3) + ("+" if match.group(0).rstrip().endswith("+") else "")
                    for match in printed if match
                ) + " (?)"
                tails = {item[3].strip(" .") for item in readings}
                tail = next(iter(tails)) if len(tails) == 1 else ""
            # A record with no count, or with neither a number nor a formula to
            # show, is reported rather than forced into a card.
            if not numbers or (numeric is None and not formula):
                warnings.append(f"{page}: skipped {label or 'a figure'}: {written[:60]!r}")
                continue
            # The figure is drawn for the largest n of its group; the label says which.
            if drawn is not None and int(drawn.group(1)) != numbers[-1]:
                warnings.append(f"{page}: label {label!r} is drawn from figure {figure.group(1)!r}")
            record = {
                    "counts": numbers,
                    "value": numeric,
                    "formula": formula,
                    "symbol": symbol,
                    "status": status_of(tail),
                    "attribution": tail.strip(" ."),
                    "figure": figure.group(1) if figure else "",
                }
            if ambiguous:
                record.update(source_ambiguous=True, source_values=[item[0] for item in readings if item[0] is not None])
            else:
                match = VALUE.search(written)
                if match is not None and numeric is not None:
                    printed = match.group(3)
                    record["value_upper_bound"] = numeric + 10 ** (-len(printed.partition(".")[2])) if match.group(0).rstrip().endswith("+") else numeric
            found.append(record)
    return found


def intro(html: str) -> str:
    """Return the sentence the page opens with, which says what is packed in what."""
    text = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html))).strip()
    match = re.search(r"The following (?:pictures|figures)[^.]*\.", text)
    return match.group(0) if match else ""


def equal_copies_index() -> tuple[list[tuple[str, str]], list[dict]]:
    """Return the matrix subfamilies: the pages the collection hosts, and the rest.

    The index lays a row of figures above the row of their titles, so the nth figure
    of a row is named by the nth title of the next row. Reading the titles rather
    than the slugs is what lets the uppercase L containers and the two "arbitrary"
    families in at all; the slug is the figure's own relative URL. A figure the
    index links outside the collection has no page here to read, so it comes back
    separately to be reported rather than fetched.
    """
    html = fetch(INDEX)
    heads = list(HEADING.finditer(html))
    position = next(
        (index for index, head in enumerate(heads) if head.group(1).strip() == "Packing Equal Copies"),
        None,
    )
    if position is None:
        return [], []
    end = heads[position + 1].start() if position + 1 < len(heads) else len(html)
    body = html[heads[position].end():end]
    rows: list[tuple[list[str], list[str]]] = []
    for row in re.split(r"<TR\b[^>]*>", body, flags=re.I)[1:]:
        row = re.split(r"</tr>", row, flags=re.I)[0]
        figures = [
            match.group(1)
            for cell in re.findall(r"(?is)<TD[^>]*>(.*?)</TD>", row)
            if (match := re.search(r"(?i)HREF\s*=\s*[\"']?([^\"'>\s]+)", cell))
        ]
        titles = [
            re.sub(r"\s+", " ", visible(cell)).strip()
            for cell in re.findall(r"<font\s+size=\+1>\s*<b>(.*?)</b></font>", row, re.I | re.S)
        ]
        rows.append((figures, titles))
    hosted: list[tuple[str, str]] = []
    elsewhere: list[dict] = []
    for index, (figures, _) in enumerate(rows):
        if not figures:
            continue
        titles = next((titles for _, titles in rows[index + 1:] if titles), [])
        for column, href in enumerate(figures):
            title = titles[column] if column < len(titles) else ""
            if href.startswith("http"):
                elsewhere.append(
                    {
                        "title": title or href,
                        "page": href,
                        "section": "Packing Equal Copies",
                        "reason": "the collection links this subfamily to an external page, which it does not host",
                    }
                )
                continue
            hosted.append((href.rstrip("/"), title))
    return hosted, elsewhere


def problem_template(
    shape: str, container: str, *, arbitrary: bool = False, page_intro: str = ""
) -> tuple[dict | None, str]:
    """Return the ready-made problem of one equal-copies subfamily, or why none exists.

    The second value is why no template could be built, and is empty exactly when one
    was: a family that can be launched but whose published number cannot be read back
    from its template carries a caveat instead, see :func:`template_caveat`.

    The arena is the family's container at the length the source publishes, the shape
    is the family's unit copy, the objective is the one whose primary is the reciprocal
    of that published size, and the rotation is free because the published packings turn
    their shapes. A square or circle container keeps minimize_container: the domain
    derives those two exactly and the curated square records were measured through it.
    Every other container is a fixed arena and the objective is maximize_scale, the
    reading the Packomania importer already uses. The template carries the trivial count
    of one; a caller that knows its own n overwrites the objective count (and the seed),
    exactly as the Packomania importer's report documents. ``page_intro`` is the page's
    opening sentence, which says which side of an L the published number measures.
    """
    if arbitrary and container != "ellipse":
        return None, ARBITRARY_REASON
    unit = UNIT_SHAPES.get(shape)
    if unit is None:
        return None, f"the domain has no {shape!r} shape primitive"
    if container in ("square", "circle"):
        problem = Problem(
            problem_id=f"{shape}-1-in-smallest-{container}",
            arena=None,
            shape=unit,
            objective=MinimizeContainer(count=1, container=container),
            rotation=RotationPolicy(mode=RotationMode.FREE),
        )
    else:
        arena = l_arena(page_intro) if container == "l" else ROTATABLE_ARENAS.get(container)
        if arena is None:
            return None, f"the domain has no {container!r} arena primitive"
        problem = Problem(
            problem_id=f"{shape}-1-in-smallest-{container}",
            arena=arena,
            shape=unit,
            objective=MaximizeScale(count=1),
            rotation=RotationPolicy(mode=RotationMode.FREE),
        )
    return problem.to_dict(), ""


def covering_template(shape: str, container: str) -> tuple[dict | None, str]:
    """Return the ready-made problem of one covering subfamily, or why none exists.

    The source asks for the largest region n unit copies can cover; read in this
    lab's frame, the *arena* is that region at its unit size (a unit circle of
    radius 1, a unit regular polygon of side 1), the *shape* is the family's unit
    copy, and the objective is :class:`CoverRegion`, whose primary is the reciprocal
    of the common scale. That reciprocal is the size of the largest target the
    copies cover -- exactly the number the page publishes. Rotation is free because
    the published coverings turn their copies; the template carries the trivial
    count of one, and a caller that knows its own n overwrites it.
    """
    unit = UNIT_SHAPES.get(shape)
    if unit is None:
        return None, f"the domain has no {shape!r} shape primitive"
    arena = COVERING_ARENAS.get(container)
    if arena is None:
        return None, f"the domain has no {container!r} arena primitive"
    problem = Problem(
        problem_id=f"{shape}-1-covering-{container}",
        arena=arena,
        shape=unit,
        objective=CoverRegion(count=1),
        rotation=RotationPolicy(mode=RotationMode.FREE),
    )
    return problem.to_dict(), ""


def perimeter_template(shape: str, container: str) -> tuple[dict | None, str]:
    """Return the ready-made problem of one total-perimeter subfamily, or why none exists.

    The source packs ``count`` copies of *independent* sizes into a container at its
    own length and asks for the largest sum of their radii or sides. Read in this
    lab's frame, the *arena* is that container at that length, the *shape* is the
    family's unit copy, and the objective is :class:`MaximizeTotalPerimeter`: the
    common scale is fixed at 1, every placement carries its own local scale, and
    the promoted ``total_scale`` is the sum the page prints. Rotation is free
    because the published packings turn their copies; the template carries the
    trivial count of one, and a caller that knows its own n overwrites it.
    """
    unit = UNIT_SHAPES.get(shape)
    if unit is None:
        return None, f"the domain has no {shape!r} shape primitive"
    arena = PERIMETER_ARENAS.get(container)
    if arena is None:
        return None, f"the domain has no {container!r} arena primitive"
    problem = Problem(
        problem_id=f"{shape}-1-total-perimeter-in-{container}",
        arena=arena,
        shape=unit,
        objective=MaximizeTotalPerimeter(count=1),
        rotation=RotationPolicy(mode=RotationMode.FREE),
    )
    return problem.to_dict(), ""


def template_caveat(
    container: str, *, arbitrary: bool, section: str = "", shape: str = ""
) -> str:
    """Return why a launchable family's published number cannot be read back, or "".

    Three cases today. The equal-copies free-ratio ellipse fixes a 2:1 proportion,
    so the area the source publishes is not the length the engine's score inverts
    to. A square covering a square publishes an area while the template's
    covered_size is the side of the covered square. And the two total-perimeter
    containers whose aspect ratio is free are fixed to their circular and square
    cases. The caveat travels in the asset so a launcher can show it, never hiding
    the mismatch behind a number that looks comparable.
    """
    if section == "Covering":
        return COVERING_AREA_CAVEAT if shape == "square" and container == "square" else ""
    if section == "Packing Copies to Maximize Total Perimeter":
        return PERIMETER_FREE_RATIO_CAVEATS.get(container, "")
    return ELLIPSE_CAVEAT if container == "ellipse" and arbitrary else ""


def family(
    slug: str,
    *,
    refresh: bool,
    section: str,
    shape: str,
    container: str,
    supported: bool,
    title: str = "",
    problem_template_doc: dict | None = None,
    unsupported_reason: str = "",
    caveat: str = "",
) -> dict:
    """Return one subfamily: what it packs, in what, and every instance it publishes.

    The slug names the page, never the shape: the perimeter and covering pages read
    their shape and container from the index title, and only the equal-copies matrix
    encodes them in the slug. A non-empty `title` is the index's own wording, which
    the collection sometimes prints differently on the page itself. `caveat` is what
    a launchable family says about its published number, and is empty for one whose
    template reads that number back exactly.
    """
    warnings: list[str] = []
    try:
        html = fetch(BASE + slug + "/", refresh=refresh)
    except Exception as error:  # a page that moved is reported, not guessed
        return {
            "slug": slug,
            "title": title,
            "shape": shape,
            "container": container,
            "error": f"{type(error).__name__}: {error}",
            "instances": [],
            "warnings": [f"{slug}: {type(error).__name__}: {error}"],
            "section": section,
            "supported": False,
            "problem_template": problem_template_doc,
            "unsupported_reason": unsupported_reason,
            "caveat": caveat,
        }
    heading = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
    return {
        "slug": slug,
        "page": BASE + slug + "/",
        "title": title or (unescape(heading.group(1)).strip() if heading else slug),
        "shape": shape,
        "container": container,
        "supported": supported,
        "problem_template": problem_template_doc,
        "unsupported_reason": unsupported_reason,
        "caveat": caveat,
        "intro": intro(html),
        "instances": instances(html, slug, warnings),
        "warnings": warnings,
        "section": section,
    }


def index_sections(html: str) -> list[tuple[str, list[str], list[str]]]:
    """Return the index's sections: their own heading, their page slugs, and the
    title each slug is printed under.

    The index pairs a row of linked figures with the row of titles below it, so the
    nth slug of a section and the nth title describe the same subfamily. Only links
    to a page of this collection are kept (a relative href ending in "/"), never an
    external page.
    """
    heads = list(HEADING.finditer(html))
    found: list[tuple[str, list[str], list[str]]] = []
    for position, head in enumerate(heads):
        end = heads[position + 1].start() if position + 1 < len(heads) else len(html)
        body = html[head.end():end]
        title = re.sub(r"\s+", " ", head.group(1)).strip()
        page_slugs = re.findall(r'<A\s+HREF="([A-Za-z0-9]+)/"\s*>', body, re.I)
        page_titles = [
            re.sub(r"\s+", " ", visible(cell)).strip()
            for cell in re.findall(r"<font\s+size=\+1>\s*<b>(.*?)</b></font>", body, re.I | re.S)
        ]
        found.append((title, page_slugs, page_titles))
    return found


def shape_container(title: str) -> tuple[str, str]:
    """Return the shape and the container one index title names, canonicalised.

    "Circles in Squares" and "Squares Covering Circles" both read as one shape and
    one container; the qualifiers the collection uses ("Consecutive Dominoes…") are
    dropped. An empty pair means the title did not say, and the caller reports it
    rather than guessing.
    """

    def canonical(part: str) -> str:
        name = ""
        for word in re.findall(r"[A-Za-z']+", part.lower()):
            if word in QUALIFIERS:
                continue
            name = SHAPE_WORDS.get(word, name)
        return name

    parts = re.split(r"\s+(?:in|covering)\s+", visible(title), maxsplit=1, flags=re.I)
    if len(parts) != 2:
        return "", ""
    return canonical(parts[0]), canonical(parts[1])


def equal_copies(*, refresh: bool) -> tuple[list[dict], list[dict]]:
    """Return the matrix subfamilies, each with the template the lab can build.

    Every page the collection hosts is read; the subfamilies it links elsewhere, and
    the ones the domain cannot express, are documented instead of guessed. A family
    is judgeable exactly when a template could be built for it; one whose published
    number the template cannot read back is still launched, and carries a caveat that
    says so, because the owner asked for every equal-copies family to be launchable.
    """
    hosted, elsewhere = equal_copies_index()
    families: list[dict] = []
    for slug, title in hosted:
        arbitrary = "arbitrary" in title.lower()
        shape, container = shape_container(title)
        if not shape or not container:
            fallback = SLUG.fullmatch(slug.lower())
            if fallback is not None:
                shape, container = PARTS[fallback.group(1)], PARTS[fallback.group(2)]
        # An L page says in its opening sentence which side it prints; the page is
        # cached, so reading it here costs family() below no second request.
        page_intro = ""
        if container == "l":
            try:
                page_intro = intro(fetch(BASE + slug + "/", refresh=refresh))
            except Exception:  # family() below reports the page that failed
                pass
        template, reason = problem_template(shape, container, arbitrary=arbitrary, page_intro=page_intro)
        if not shape or not container:
            reason = "the index title does not name a shape in a container"
        # A template makes the family launchable whatever it measures; when the
        # published number cannot be read back from it, a caveat says so instead of
        # the family being withheld. Both travel in the asset and reach the card.
        supported = template is not None
        caveat = template_caveat(container, arbitrary=arbitrary) if supported else ""
        families.append(
            family(
                slug,
                refresh=refresh,
                section="Packing Equal Copies",
                shape=shape,
                container=container,
                supported=supported,
                title=title,
                problem_template_doc=template,
                unsupported_reason=reason,
                caveat=caveat,
            )
        )
        if not supported:
            # The reason travels on the family and in the document-wide list, so a
            # reader of either sees why a subfamily is not launchable.
            elsewhere.append(
                {"slug": slug, "section": "Packing Equal Copies", "title": title, "reason": reason}
            )
    return families, elsewhere


def published(*, refresh: bool, warnings: list[str]) -> tuple[list[dict], list[dict]]:
    """Return the subfamilies of the other published sections, and the ones left out.

    The index is read section by section. A section this script does not publish is
    skipped whole; inside a published one, a subfamily whose page does not publish
    one measured value per figure is listed under "excluded" with its reason instead
    of being forced into a record.
    """
    sections = {
        title: (page_slugs, page_titles)
        for title, page_slugs, page_titles in index_sections(fetch(INDEX))
    }
    families: list[dict] = []
    excluded: list[dict] = []
    for section in SECTIONS:
        if section == "Packing Equal Copies" or section not in sections:
            continue
        page_slugs, page_titles = sections[section]
        if len(page_slugs) != len(page_titles):
            warnings.append(f"{section}: {len(page_slugs)} links for {len(page_titles)} titles")
        for position, slug in enumerate(page_slugs):
            title = page_titles[position] if position < len(page_titles) else slug
            if slug in UNPUBLISHED:
                excluded.append({"slug": slug, "section": section, "title": title, "reason": UNPUBLISHED[slug]})
                continue
            shape, container = shape_container(title)
            if not shape or not container:
                excluded.append(
                    {
                        "slug": slug,
                        "section": section,
                        "title": title,
                        "reason": "the index title does not name a shape in a container",
                    }
                )
                continue
            # Covering and the total-perimeter section are judged by the engine
            # now; the other problems stay references until their objective is
            # written.
            if section == "Covering":
                template, reason = covering_template(shape, container)
            elif section == "Packing Copies to Maximize Total Perimeter":
                template, reason = perimeter_template(shape, container)
            else:
                template, reason = None, "the engine has no objective for this section yet"
            supported = template is not None
            caveat = (
                template_caveat(container, arbitrary=False, section=section, shape=shape)
                if supported
                else ""
            )
            families.append(
                family(
                    slug,
                    refresh=refresh,
                    section=section,
                    shape=shape,
                    container=container,
                    supported=supported,
                    title=title,
                    problem_template_doc=template,
                    unsupported_reason=reason,
                    caveat=caveat,
                )
            )
    return families, excluded


def main(argv: list[str]) -> int:
    """Keep the old refresh invocation as an alias for the safe update command."""
    from update_catalog import main as update

    return update([argument for argument in argv if argument not in {"--refresh", "--report"}])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
