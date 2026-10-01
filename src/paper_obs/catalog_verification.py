#!/usr/bin/env python3
"""Put every published record of the catalogue back in front of the engine.

The catalogue (packing_equal_copies.json) records what each source page prints: a
number, its unit, and who published it. Nothing checks those numbers against the
engine, so a record can be stale, mis-transcribed or already beaten without the
interface saying so -- and every card's "last checked" date is the catalogue's own
build date, which is not a date anything was checked on.

This script closes that loop for every entry it can find coordinates for. It builds
the same problem the interface builds (equalCopiesCatalog.ts, copyProblem): the
family's own template at this count, the section's own objective (a covering derives
its target, a total-perimeter family maximises a sum), and the source's own unit read
back from the symbol the page printed. It hands the arrangement to the engine, keeps
the measurement that unit names, and compares the two.

What the answers mean
---------------------
reproduces    the engine reads the printed number back, within the precision the page
              printed it to. The arrangement is written out as a candidate of the
              catalogue problem, so a run can start from the record.
beaten        the engine reads something strictly better, by more than that precision,
              and the page printed enough decimals for that to mean something. A better
              arrangement is never promoted here: the interface keeps showing the
              published value.
below         the engine reads something worse, on a number precise enough to say so.
differs       the engine reads something else on a number too rounded to settle a
              record: the arrangement is kept as an approach and the gap is reported
              without a claim. Either the arrangement is not the record (a seed), or
              the transcription, the frame or the unit is wrong -- which is exactly what
              this script is for.
invalid       the engine rejects the arrangement; nothing is compared.
unmeasurable  the source's unit is not one the engine measures (an area, say).
no_value      the source printed a formula, not a number.
error         the engine refused the problem or the candidate.

The printed precision bounds every claim
----------------------------------------
10.304 cannot be told apart from anything within half of its last printed digit, so an
improvement smaller than that is not claimed as one. Worse, a number printed to three
decimals cannot settle a record at all: an entry is only confirmed when the page
printed at least REQUIRED_DECIMALS decimals and the engine reads that number back.
Anything coarser is reported as an approach, because a margin far smaller than the
rounding can decide whether a record was beaten.

Frames
------
A Packomania archive holds its centres inside the family's own normalised container --
a unit circle, a regular polygon of circumradius 1 -- while the catalogue normalises
the same container on the length its page prints (a polygon's side is 1). A published
arrangement is therefore re-expressed in the catalogue's frame before it is judged: a
derived container (a square, a circle) only needs its copies brought back to radius 1,
and a regular polygon is scaled by that polygon's circumradius. Both are exact changes
of frame, so what the engine reads is the number the page printed -- which is why a
mismatch is a finding, never something to paper over.

Usage
-----
    python -m paper_obs.catalog_verification [--check] [--asset PATH] [--output PATH]

--check compares what is on disk with what a run would write and fails instead of
writing, for the test suite and for a continuous check.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

from paper_obs.domain.arena import RegularNGon
from paper_obs.domain.candidate import Candidate
from paper_obs.domain.objectives import MaximizeCoveredSize
from paper_obs.domain.problem import Problem
from paper_obs.domain.reference import REFERENCE_METRICS, SAME_QUANTITY
from paper_obs.geometry.engine import evaluate
from paper_obs.storage.files import load_candidate, save_candidate

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "apps/web/public/catalog"
ASSET = CATALOG / "packing_equal_copies.json"
OUTPUT = CATALOG / "verification.json"

#: The interface shows a card for a count up to this one (catalog.ts,
#: MAX_VISIBLE_COUNT), and the identifier rule below counts the same cards.
MAX_VISIBLE_COUNT = 100

PERIMETER_SECTION = "Packing Copies to Maximize Total Perimeter"
COVERING_SECTION = "Covering"

#: The identifier namespace of each section, as equalCopiesCatalog.ts names it.
SECTION_NAMESPACES = {
    "Packing Equal Copies": "in-smallest",
    PERIMETER_SECTION: "total-perimeter-in",
    COVERING_SECTION: "covering",
}

#: The plural noun a card's identifier is built from, as the interface names it.
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

#: Decimals a published number must carry before it can settle a record.
REQUIRED_DECIMALS = 5

#: The engine's own descriptive tolerance (a relative one).
TOLERANCE = 1e-6

#: How close a held arrangement has to be to a record before it is called near it, and
#: before it is called an approach at all: a hundredth, then a tenth of a percent.
NEAR_GAP = 1e-4
APPROX_GAP = 1e-3

#: The Packomania archives whose container the collection also lists, catalogue slug to
#: archive code. Packomania publishes nineteen families; the collection has a page for
#: four of them. The others (a semicircle, a quadrant, a heptagon, an octagon, a
#: nonagon, a decagon, rectangles and a right isosceles triangle) name a container the
#: collection never lists for circles, so their coordinates have nothing to sit beside.
#: Their candidate files stay in place for a future family.
PUBLISHED_FAMILIES = {
    "cirinsqu": "csq",
    "cirincir": "cci",
    "cirinhex": "chx",
    "cirinpen": "cpt",
}

#: The candidate files a catalogue entry may be judged from, in the order they win: the
#: source's own coordinates first, then a construction, then a seed, then a
#: reconstruction. Each names one file of the candidates directory.
SOURCE_KINDS = ("published", "record", "seed", "approx")

#: The Packomania page a family's coordinates come from.
PACKOMANIA_PAGE = "https://www.packomania.com/{code}/{code}.html"


def is_perimeter(family: dict[str, Any]) -> bool:
    """Whether a family asks for the largest sum of the copies' sizes."""
    return str(family.get("section") or "") == PERIMETER_SECTION


def is_covering(family: dict[str, Any]) -> bool:
    """Whether a family covers a target instead of packing into a container."""
    return str(family.get("section") or "") == COVERING_SECTION


def copy_noun(shape: str) -> str:
    """Return the plural noun a card's identifier is built from."""
    return COPY_NOUNS.get(shape, shape)


def counts_of(instance: dict[str, Any]) -> list[int]:
    """Return the counts one published figure stands for."""
    return [int(count) for count in instance.get("counts", [])]


def figure_stem(figure: str) -> str:
    """Return a figure's file name without its extension."""
    return figure.rsplit(".", 1)[0] if "." in figure else figure


def copy_problem_id(family: dict[str, Any], count: int, figure: str = "") -> str:
    """Return the identifier the interface files this card under.

    A source may print one count beside two different figures; such a count is
    ambiguous, so the card also carries its figure's stem (equalCopiesCatalog.ts,
    copyProblemId). The identifier has to match, or a loaded candidate would be refused
    as belonging to another problem.
    """
    namespace = SECTION_NAMESPACES.get(str(family.get("section") or ""), "family")
    identity = (
        f"{copy_noun(str(family.get('shape') or ''))}-{count}-{namespace}-{family.get('container')}"
    )
    printed = [
        instance
        for instance in family.get("instances", [])
        if count in counts_of(instance) and count <= MAX_VISIBLE_COUNT
    ]
    stem = figure_stem(figure)
    return f"{identity}-figure-{stem}" if len(printed) > 1 and stem else identity


def cover_target(family: dict[str, Any]) -> str:
    """Return the target a covering family's own container names."""
    container = str(family.get("container") or "")
    if container not in {"circle", "square", "triangle"}:
        raise ValueError(f"the covering family {family.get('slug')} names no derived target")
    return container


def card_problem(family: dict[str, Any], instance: dict[str, Any], count: int) -> Problem:
    """Return the problem the interface builds for one card.

    A covering card is the one covering model the product exposes: the copies at their
    unit size, the target derived from their union, and the template's fixed arena
    dropped. Every other card keeps the template's objective at this count.
    """
    template = dict(family["problem_template"])
    figure = str(instance.get("figure") or "")
    template["problem_id"] = copy_problem_id(family, count, figure)
    template["seed"] = count
    problem = Problem.from_dict(template)
    if is_covering(family):
        objective = MaximizeCoveredSize(count=count, target=cover_target(family))
        return replace(problem, objective=objective, arena=None)
    objective = problem.objective
    if hasattr(objective, "count"):
        objective = replace(objective, count=count)
    return replace(problem, objective=objective)


def measure_unit(family: dict[str, Any], symbol: str) -> str:
    """Return the unit a source's symbol names, as the interface reads it.

    A total-perimeter page prints a sum rather than a length of the container, whatever
    letter the parser read beside the number; a covering page prints the size of what
    the copies cover. The rest print the size of the container.
    """
    if is_perimeter(family):
        return "sum of radii" if family.get("shape") == "circle" else "sum of sides"
    target = "covered" if is_covering(family) else "container"
    size = {"r": "radius", "a": "area"}.get(symbol, "side")
    return f"{target} {size}"


def reference_of(family: dict[str, Any], instance: dict[str, Any]) -> dict[str, Any]:
    """Return the reference record the interface attaches to a card."""
    return {
        "status": instance.get("status"),
        "value": instance.get("value"),
        "unit": measure_unit(family, str(instance.get("symbol") or "")),
        "note": instance.get("attribution", ""),
    }


def printed_decimals(value: float) -> int:
    """Return how many decimals a published number was printed with."""
    text = repr(float(value))
    if "e" in text or "E" in text:
        return 0
    return len(text.partition(".")[2])


def printed_precision(value: float) -> float:
    """Return one unit of a published number's last printed digit.

    A page that rounds and a page that truncates both stay inside it, and a page that
    prints few decimals is treated as the coarse reading it is rather than trusted.
    Never more than a thousandth of the value: a printed 1 is not a licence for 0.9.
    """
    return min(10.0 ** -printed_decimals(value), abs(float(value)) * 1e-3)


def classify(value: float, measured: float, larger_is_better: bool) -> tuple[str, float, bool]:
    """Return a measurement's status against a published number, its gap, and whether
    that number is precise enough for the comparison to settle a record.

    The gap is a signed fraction of the record, positive when the measurement beats it,
    whichever way the record's unit improves. A number printed to fewer than
    REQUIRED_DECIMALS decimals cannot settle one at all: the status stays "differs",
    whatever the sign, because a margin far smaller than the rounding can decide it.
    """
    limit = max(TOLERANCE * abs(value), printed_precision(value))
    delta = measured - float(value)
    gap = delta / abs(value) * (1.0 if larger_is_better else -1.0)
    precise = printed_decimals(value) >= REQUIRED_DECIMALS
    if abs(delta) <= limit:
        return "reproduces", gap, precise
    if not precise:
        return "differs", gap, False
    better = delta > 0.0 if larger_is_better else delta < 0.0
    return ("beaten" if better else "below"), gap, True


def frame_factor(problem: Problem, candidate: Candidate) -> float | None:
    """Return the factor that puts a published arrangement in a problem's own frame.

    None when the frame the archive used is not one this script knows how to map: the
    caller reports that instead of guessing.
    """
    if problem.objective.derives_region:
        # The archive's frame normalises the derived container itself; copies of radius
        # one are the catalogue's own reading.
        return 1.0 / candidate.scale
    shape = problem.arena.shape if problem.arena is not None else None
    if isinstance(shape, RegularNGon):
        # Packomania normalises a regular polygon on its circumradius, the catalogue on
        # its side: the factor is that polygon's own circumradius.
        return float(shape.circumradius)
    return None


def frame_angle(problem: Problem) -> float:
    """Return the turn, in degrees, that puts a published frame on the catalogue's.

    Packomania prints an even-sided polygon edge-up, while the domain's own
    RegularNGon puts a vertex on +y: the importer of the archives turns that polygon
    by half a step, so an arrangement coming back has to be turned the same way. An
    odd-sided polygon needs no turn, both readings putting a vertex upwards.
    """
    shape = problem.arena.shape if problem.arena is not None else None
    if isinstance(shape, RegularNGon) and shape.sides % 2 == 0:
        return 180.0 / shape.sides
    return 0.0


def aligned(
    problem: Problem, candidate: Candidate, factor: float, angle: float, note: str
) -> Candidate:
    """Return a published arrangement re-expressed as a candidate of a problem."""
    radians = math.radians(angle)
    cosine, sine = math.cos(radians), math.sin(radians)
    placements = []
    for placement in candidate.placements:
        x, y = placement.x * factor, placement.y * factor
        placements.append(replace(placement, x=x * cosine - y * sine, y=x * sine + y * cosine))
    return replace(
        candidate,
        candidate_id=f"{problem.problem_id}-published",
        problem_id=problem.problem_id,
        scale=candidate.scale * factor,
        placements=tuple(placements),
        parents=(),
        generation=0,
        metadata={
            "published_problem_id": candidate.problem_id,
            "published_by": note,
        },
    )


def candidate_files(slug: str, count: int) -> list[tuple[str, str]]:
    """Return the (kind, file name) pairs a catalogue entry may be judged from."""
    names: list[tuple[str, str]] = []
    code = PUBLISHED_FAMILIES.get(slug)
    if code:
        names.append(("published", f"packomania-{code}-{count}.json"))
    names.extend((kind, f"{kind}-{slug}-{count}.json") for kind in ("record", "seed", "approx"))
    return names


def measure_of(reference: dict[str, Any], verdict: Any) -> float | None:
    """Return the engine's reading of a verdict in the reference's own unit."""
    compared = REFERENCE_METRICS.get(str(reference.get("unit") or ""))
    if compared is None:
        return None
    name = compared[0]
    raw = verdict.primary if name == "primary" else verdict.metrics.get(name)
    if raw is None:
        raw = verdict.metrics.get(SAME_QUANTITY.get(name, ""))
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    return None


def judge(problem: Problem, candidate: Candidate, reference: dict[str, Any]) -> dict[str, Any]:
    """Return one candidate's verdict against a card's published record."""
    entry: dict[str, Any] = {"valid": None, "measured": None, "gap": None, "status": "error"}
    try:
        verdict = evaluate(problem, candidate)
    except Exception as error:  # the engine is the judge; a refusal is a finding
        entry["status"] = "error"
        entry["note"] = str(error)
        return entry
    entry["valid"] = verdict.valid
    if not verdict.valid:
        entry["status"] = "invalid"
        entry["note"] = verdict.validation.summary()
        return entry
    measured = measure_of(reference, verdict)
    if measured is None:
        entry["status"] = "unmeasurable"
        return entry
    entry["measured"] = measured
    value = reference.get("value")
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        entry["status"] = "no_value"
        return entry
    larger_is_better = REFERENCE_METRICS[str(reference["unit"])][1]
    status, gap, precise = classify(float(value), measured, larger_is_better)
    entry["status"] = status
    entry["gap"] = gap
    entry["precise"] = precise
    return entry


def level_of(status: str, gap: float | None, value: Any) -> str:
    """Return how close the arrangement a card holds is to its published record.

    Only a number the page printed to at least REQUIRED_DECIMALS decimals can make a
    configuration exact: with fewer, a margin far smaller than the rounding can decide
    whether a record was reached, so the card is an approach however good it looks. The
    entry also reports whether what it holds is the source's own arrangement, which is a
    different question and is what a run should start from.
    """
    if status == "beaten":
        return "beaten"
    precise = isinstance(value, (int, float)) and printed_decimals(value) >= REQUIRED_DECIMALS
    if status == "reproduces" and precise:
        return "exact"
    if gap is None:
        return "none"
    distance = abs(gap)
    if distance <= NEAR_GAP:
        return "near"
    if distance <= APPROX_GAP:
        return "approx"
    return "far"


def checked_cards(family: dict[str, Any]) -> list[tuple[int, dict[str, Any]]]:
    """Return every count of a family, with the instance that printed it."""
    cards: list[tuple[int, dict[str, Any]]] = []
    for instance in family.get("instances", []):
        cards.extend((count, instance) for count in counts_of(instance))
    return cards


def verify_family(
    family: dict[str, Any], directory: Path, today: str
) -> tuple[dict[str, Any], dict[Path, Candidate], Counter]:
    """Return one family's verification, the candidates it settles, and its tallies."""
    slug = str(family.get("slug") or "")
    tallies: Counter = Counter()
    entries: dict[str, Any] = {}
    settled: dict[Path, Candidate] = {}
    for count, instance in checked_cards(family):
        found = [
            (kind, name, directory / name)
            for kind, name in candidate_files(slug, count)
            if (directory / name).exists()
        ]
        if not found:
            tallies["without_coordinates"] += 1
            continue
        problem: Problem | None = None
        reference: dict[str, Any] = {}
        best: dict[str, Any] | None = None
        files: list[str] = []
        for kind, name, path in found:
            files.append(name)
            try:
                problem = problem or card_problem(family, instance, count)
                reference = reference or reference_of(family, instance)
                candidate = load_candidate(path)
            except Exception as error:
                entries[str(count)] = {
                    "status": "error",
                    "note": str(error),
                    "files": files,
                    "checked_on": today,
                }
                break
            note = ""
            if kind == "published":
                code = PUBLISHED_FAMILIES[slug]
                note = f"Packomania ({code})"
                factor = frame_factor(problem, candidate)
                if factor is None:
                    entries[str(count)] = {
                        "status": "unmappable",
                        "note": "the archive's frame is not one the catalogue names",
                        "files": files,
                        "checked_on": today,
                    }
                    best = None
                    break
                candidate = aligned(problem, candidate, factor, frame_angle(problem), note)
            verdict = judge(problem, candidate, reference)
            verdict["kind"] = kind
            verdict["file"] = name
            verdict["candidate"] = candidate
            if verdict.get("status") == "invalid":
                verdict["note"] = verdict.get("note", "")
            improved = best is None or (verdict["valid"], verdict["measured"] or 0.0) > (
                best["valid"],
                best["measured"] or 0.0,
            )
            if improved:
                best = verdict
        if best is None:
            if str(count) not in entries:
                entries[str(count)] = {
                    "status": "error",
                    "note": "no candidate could be judged",
                    "files": files,
                    "checked_on": today,
                }
            tallies[entries[str(count)]["status"]] += 1
            continue
        value = reference.get("value")
        status = str(best["status"])
        level = level_of(status, best.get("gap"), reference.get("value"))
        repos = status == "reproduces"
        published = repos and best["kind"] == "published"
        target = None
        target = None
        if published:
            target = directory / f"published-{slug}-{count}.json"
            settled[target] = best["candidate"]
        entry: dict[str, Any] = {
            "status": status,
            "level": level,
            "precise": bool(best.get("precise")),
            "published": published,
            "promoted": level == "exact",
            "value": value,
            "unit": reference.get("unit"),
            "measured": best.get("measured"),
            "gap": best.get("gap"),
            "source_kind": best["kind"],
            "files": files,
            "candidate": None,
            "checked_on": today,
        }
        if best.get("note"):
            entry["note"] = best["note"]
        if target is not None:
            entry["candidate"] = f"/catalog/candidates/{target.name}"
        elif best["kind"] in {"seed", "approx"} and level in {"exact", "near", "approx"}:
            # A seed or a reconstruction is already a candidate of this very problem, so it
            # can be opened as it stands. An archive file is not -- it is only ever offered
            # through the reading this script settles -- and neither is a construction the
            # lab holds: until the owner promotes one, the interface must not present it as
            # the family's record.
            entry["candidate"] = f"/catalog/candidates/{best['file']}"
        entries[str(count)] = entry
        tallies[status] += 1
        tallies[f"level:{level}"] += 1
    if not entries:
        return {}, {}, tallies
    source: dict[str, Any] = {"kind": "figure"}
    code = PUBLISHED_FAMILIES.get(slug)
    if code:
        source = {
            "kind": "published",
            "label": f"Packomania ({code})",
            "url": PACKOMANIA_PAGE.format(code=code),
        }
    elif any(entry.get("source_kind") == "record" for entry in entries.values()):
        source = {"kind": "record", "label": "a construction held by the lab", "url": ""}
    elif any(entry.get("source_kind") == "seed" for entry in entries.values()):
        source = {"kind": "seed", "label": "the lab's own seed", "url": ""}
    family_entry = {
        "title": family.get("title", ""),
        "section": family.get("section", ""),
        "shape": family.get("shape", ""),
        "container": family.get("container", ""),
        "checked_on": today,
        "source": source,
        "entries": entries,
    }
    return family_entry, settled, tallies


def build(asset: Path, today: str) -> tuple[dict[str, Any], dict[Path, Candidate]]:
    """Return the verification summary and the candidates it settles."""
    catalog = json.loads(asset.read_text(encoding="utf-8"))
    directory = asset.parent / "candidates"
    totals: Counter = Counter()
    families: dict[str, Any] = {}
    settled: dict[Path, Candidate] = {}
    for family in catalog.get("families", []):
        catalog_entries = sum(len(counts_of(instance)) for instance in family.get("instances", []))
        totals["entries_catalog"] += catalog_entries
        if not family.get("supported") or not family.get("problem_template"):
            totals["families_unsupported"] += 1
            totals["entries_unsupported"] += catalog_entries
            continue
        family_entry, family_settled, tallies = verify_family(family, directory, today)
        totals.update(tallies)
        settled.update(family_settled)
        if family_entry:
            families[str(family.get("slug") or "")] = family_entry
    totals["families_catalog"] = len(catalog.get("families", []))
    totals["families_checked"] = len(families)
    totals["entries_checked"] = sum(len(entry["entries"]) for entry in families.values())
    summary = {
        "generated": today,
        "asset": asset.name,
        "catalog_generated": catalog.get("generated"),
        "tolerance": TOLERANCE,
        "required_decimals": REQUIRED_DECIMALS,
        "near_gap": NEAR_GAP,
        "approx_gap": APPROX_GAP,
        "published_families": {
            slug: {"code": code, "url": PACKOMANIA_PAGE.format(code=code)}
            for slug, code in PUBLISHED_FAMILIES.items()
        },
        "totals": dict(sorted(totals.items())),
        "families": families,
    }
    return summary, settled


def emit(path: Path, data: dict[str, Any]) -> str:
    """Return the JSON text a file is written with."""
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--asset", type=Path, default=ASSET, help="the catalogue asset to read")
    parser.add_argument("--output", type=Path, default=OUTPUT, help="where the summary is written")
    parser.add_argument("--check", action="store_true", help="fail instead of writing when a file differs")
    args = parser.parse_args(argv)
    today = date.today().isoformat()
    summary, settled = build(args.asset, today)
    text = emit(args.output, summary)
    directory = args.output.parent / "candidates"
    stale = sorted(path for path in directory.glob("published-*.json") if path not in settled)
    if args.check:
        differences: list[str] = list(stale)
        if not args.output.exists() or args.output.read_text(encoding="utf-8") != text:
            differences.append(str(args.output))
        for path, candidate in sorted(settled.items()):
            if not path.exists() or load_candidate(path).to_dict() != candidate.to_dict():
                differences.append(str(path))
        if differences:
            print("the catalogue verification is out of date:")
            for name in differences:
                print(f"  {name}")
            return 1
        print(f"the catalogue verification is up to date ({len(settled)} settled candidates)")
        return 0
    args.output.write_text(text, encoding="utf-8")
    for path in stale:
        path.unlink()
    for path, candidate in sorted(settled.items()):
        save_candidate(candidate, path)
    totals = summary["totals"]
    print(f"checked {totals.get('entries_checked', 0)} entries of the catalogue")
    for status in (
        "reproduces",
        "beaten",
        "below",
        "differs",
        "invalid",
        "unmeasurable",
        "no_value",
        "unmappable",
        "error",
    ):
        if totals.get(status):
            print(f"  {status:<13} {totals[status]}")
    for level in ("exact", "near", "approx", "far"):
        if totals.get(f"level:{level}"):
            print(f"  {level:<13} {totals['level:' + level]}")
    print(f"  without coordinates {totals.get('without_coordinates', 0)}")
    print(f"wrote {args.output.relative_to(ROOT)} and {len(settled)} published candidates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
