"""Prepare local Packing Center submissions and selected email batches.

Coordinates and engine checks stay in the private dossier. The recipient archive
contains only replacement images, page-level measurements and an email draft.
Nothing here sends mail or publishes a candidate.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZipFile, ZIP_DEFLATED

from paper_obs import research
from paper_obs.catalog_verification import card_problem, reference_of
from paper_obs.domain.candidate import Candidate
from paper_obs.domain.problem import Problem
from paper_obs.domain.reference import REFERENCE_METRICS, record_gap, record_measure
from paper_obs.geometry.engine import evaluate
from paper_obs.geometry.exact_check import exact_check
from paper_obs.research.picture import submission_picture
from paper_obs.storage.files import save_candidate, save_problem

ROOT = Path(__file__).resolve().parents[3] / ".private" / "submissions"


def _fingerprint(document: dict) -> str:
    return hashlib.sha256(json.dumps([document["problem"], document["champion"]],
                                    sort_keys=True).encode()).hexdigest()


def _current_problem(document: dict) -> tuple[Problem, str]:
    """Use the current catalog, keeping the session's historical reference intact."""
    problem = Problem.from_dict(document["problem"])
    reference = problem.metadata.get("reference") or {}
    catalog = json.loads(research.CATALOG.read_text(encoding="utf-8"))
    pages = {source.get("url") for source in reference.get("sources", [])}
    family = next((f for f in catalog["families"] if f["page"] in pages), None)
    if family is None:
        raise ValueError("submission preparation needs a current Packing Center catalog reference")
    if family.get("supported") is not True:
        raise ValueError("the source family is outside the engine's supported problem model")
    count = getattr(problem.objective, "count", None)
    if count is None:
        raise ValueError("submission preparation needs a fixed count of copies")
    instance = next((i for i in family["instances"] if count in i["counts"]), None)
    if instance is None:
        raise ValueError("this count has no current reference image to replace")
    if family.get("problem_template") is not None:
        canonical = card_problem(family, instance, count)
        if (problem.shape.to_dict() != canonical.shape.to_dict()
                or problem.objective.kind != canonical.objective.kind
                or (problem.arena.to_dict() if problem.arena else None)
                != (canonical.arena.to_dict() if canonical.arena else None)):
            raise ValueError("the session's shape, arena or objective does not match the source family")
    data = problem.to_dict()
    data["metadata"] = {**data.get("metadata", {}), "reference": {
        **reference_of(family, instance), "preview": family["page"] + instance["figure"],
        "verified_on": family.get("source_checked_on", catalog["generated"]),
        "source_upper_bound": instance.get("value_upper_bound", instance["value"]),
        "sources": [{"label": "Erich's Packing Center", "url": family["page"]}],
    }}
    return Problem.from_dict(data), family["slug"]


def prepare(session_id: str, *, original: Path, author: str, method: str,
            rotate: float = 0.0, root: Path = ROOT) -> dict:
    """Prepare the session's best against today's bundled source snapshot.

    The owner/agent supplies the downloaded original and the rotation established
    by visual comparison. The renderer copies its dimensions, palette and format;
    the source URL supplies the exact filename, including any letters. A raster
    match is not a geometric proof: the engine always judges the saved candidate.
    """
    from PIL import Image

    if not author.strip() or not method.strip():
        raise ValueError("provide the submitter's full name and a short method description")
    document = research.load(session_id)
    if document.get("champion") is None:
        raise ValueError("the session has no valid arrangement to prepare")
    problem, slug = _current_problem(document)
    candidate = Candidate.from_dict(document["champion"])
    verdict = evaluate(problem, candidate)
    reference = problem.metadata["reference"]
    gap = record_gap(reference, verdict.primary, verdict.metrics)
    if not verdict.valid or gap is None or gap <= 1e-9:
        raise ValueError("the arrangement does not improve the current published reference")
    measure = record_measure(reference, verdict.primary, verdict.metrics)
    if measure is None:
        raise ValueError("the engine cannot measure the source's quantity")
    if REFERENCE_METRICS[reference["unit"]][1] and measure < reference["source_upper_bound"]:
        raise ValueError("the improvement is inside the source's truncated last digit")
    filename = Path(urlsplit(reference["preview"]).path).name
    if Path(filename).suffix.lower() not in {".gif", ".png", ".jpg", ".jpeg"}:
        raise ValueError("the replacement image must have a supported raster format")
    with Image.open(original) as source:
        size, format = source.size, source.format
    expected = {".gif": "GIF", ".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG"}[Path(filename).suffix.lower()]
    if format != expected:
        raise ValueError("the supplied original's format differs from the source filename")
    # Exact arithmetic is an additional local check where supported, never a
    # recipient requirement. Unsupported cases remain explicitly engine-only.
    try:
        independent = exact_check(problem, candidate)
    except ValueError as error:
        independent = {"valid": None, "reason": str(error)}
    if independent["valid"] is False:
        raise ValueError("the independent exact check rejected the arrangement")
    folder = root / session_id
    # A failed re-render must not leave an older manifest marking partial files ready.
    (folder / "manifest.json").unlink(missing_ok=True)
    image = folder / "send" / slug / filename
    style = {"rainbow": True, "crisp": False} if problem.objective.kind == "maximize_total_perimeter" else None
    submission_picture(problem, candidate, image, like=original, rotate=rotate, style=style)
    # The SVG is a working file, not an attachment requested by the recipient.
    internal = folder / "internal"
    internal.mkdir(parents=True, exist_ok=True)
    image.with_suffix(".svg").replace(internal / "drawing.svg")
    with Image.open(image) as replacement:
        if replacement.size != size or replacement.format != format:
            raise ValueError("the replacement image dimensions or format changed")
    save_problem(problem, internal / "problem.json")
    save_candidate(candidate, internal / "candidate.json")
    (internal / "verification.json").write_text(json.dumps({"engine": verdict.to_dict(),
        "independent": independent}, indent=2) + "\n", encoding="utf-8")
    manifest = {"session_id": session_id, "fingerprint": _fingerprint(document),
        "family": slug, "count": problem.objective.count, "page": reference["sources"][0]["url"],
        "source_checked_on": reference["verified_on"], "prepared_at": research._now(),
        "filename": filename, "size": list(size), "previous": reference["value"],
        "value": measure, "unit": reference["unit"], "author": author.strip(), "method": method.strip(),
        "rotate": rotate, "original_sha256": hashlib.sha256(original.read_bytes()).hexdigest()}
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    research.add_note(session_id, f"Submission dossier prepared: {slug}/{filename}; source checked {reference['verified_on']}.", step="check")
    return manifest


def prepared(session_id: str, *, root: Path = ROOT) -> dict | None:
    """Return a prepared dossier only while it matches the saved best candidate."""
    document = research.load(session_id)  # validate the id before using it as a path
    path = root / session_id / "manifest.json"
    if not path.is_file():
        return None
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("fingerprint") != _fingerprint(document):
        return None
    problem, slug = _current_problem(document)
    reference = problem.metadata["reference"]
    if manifest.get("previous") != reference["value"] or manifest.get("family") != slug:
        return None
    if manifest.get("filename") != Path(urlsplit(reference["preview"]).path).name:
        return None
    return manifest


def batch(session_ids: list[str], *, root: Path = ROOT) -> bytes:
    """ZIP selected dossiers, grouped by page, with no coordinates or internal checks.

    Duplicate replacement names on the same page are rejected instead of silently
    overwriting attachments. Identical basenames on different pages are preserved.
    Re-evaluation against the current catalog prevents batching a superseded record.
    """
    import io
    if not session_ids or len(session_ids) != len(set(session_ids)):
        raise ValueError("select distinct prepared sessions")
    stream = io.BytesIO()
    pages: dict[str, list[dict]] = {}
    names = set()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        for session_id in session_ids:
            manifest = prepared(session_id, root=root)
            if manifest is None:
                raise ValueError(f"{session_id}: prepare the current arrangement first")
            document = research.load(session_id)
            problem, _ = _current_problem(document)
            verdict = evaluate(problem, Candidate.from_dict(document["champion"]))
            gap = record_gap(problem.metadata["reference"], verdict.primary, verdict.metrics)
            if not verdict.valid or gap is None or gap <= 1e-9:
                raise ValueError(f"{session_id}: the current source record is no longer beaten")
            reference = problem.metadata["reference"]
            measure = record_measure(reference, verdict.primary, verdict.metrics)
            if REFERENCE_METRICS[reference["unit"]][1] and measure < reference["source_upper_bound"]:
                raise ValueError(f"{session_id}: the improvement is inside the source's truncated last digit")
            name = f"{manifest['family']}/{manifest['filename']}"
            if name in names:
                raise ValueError(f"two dossiers replace the same image: {name}")
            names.add(name)
            archive.write(root / session_id / "send" / name, name)
            pages.setdefault(manifest["family"], []).append(manifest)
        email = ["Subject: Improved packings for Erich's Packing Center", "", "Hello Erich,", "", "Please find the following improved packings attached.", ""]
        for slug, records in pages.items():
            lines = [records[0]["page"]]
            for record in records:
                lines += [f"n = {record['count']}; {record['filename']}; {record['unit']} = {record['value']:.5f}",
                          f"Previous published value: {record['previous']}; author: {record['author']}",
                          f"Method: {record['method']}"]
            archive.writestr(f"{slug}/values.txt", "\n".join(lines) + "\n")
            email.extend(lines + [""])
        email += ["Credits: Erich's Packing Center — https://erich-friedman.github.io/packing/index.html", ""]
        archive.writestr("email.txt", "\n".join(email))
    return stream.getvalue()


__all__ = ["batch", "prepare", "prepared"]
