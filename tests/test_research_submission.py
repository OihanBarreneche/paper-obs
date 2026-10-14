"""Recipient archives retain source filenames and exclude local research evidence."""
import io
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from paper_obs import research
from paper_obs.domain import Problem
from paper_obs.domain.objectives import MinimizeContainer
from paper_obs.domain.shapes import RegularPolygon
from paper_obs.research import submission
from paper_obs.search.operators.initialization import grid_initialize


@pytest.fixture
def dossiers(tmp_path, monkeypatch):
    image = pytest.importorskip("PIL.Image")
    pytest.importorskip("resvg_py")
    monkeypatch.setenv("PAPER_OBS_RUNS", str(tmp_path / "runs"))
    catalog = tmp_path / "catalog.json"
    families = [{"slug": slug, "supported": True, "page": f"https://erich-friedman.github.io/packing/{slug}/",
        "section": "Packing Equal Copies", "shape": "square", "container": "square", "source_checked_on": "2026-10-14",
        "instances": [{"counts": [2], "value": 2.1, "symbol": "s", "status": "best_known",
                       "attribution": "test", "figure": "ab2.gif"}]} for slug in ("test-a", "test-b")]
    catalog.write_text(json.dumps({"generated": "2026-10-14", "families": families}), encoding="utf-8")
    monkeypatch.setattr(research, "CATALOG", catalog)
    original = tmp_path / "downloaded.gif"
    picture = image.new("RGB", (120, 90), "white")
    picture.paste((240, 224, 240), (10, 10, 60, 60))
    picture.paste((0, 0, 0), (0, 70, 100, 72))
    picture.save(original)
    return tmp_path / "dossiers", original, families, catalog


def session(family):
    problem = Problem(problem_id="submission-test", shape=RegularPolygon(sides=4, side=1),
                      arena=None, objective=MinimizeContainer(count=2, container="square"),
                      metadata={"reference": {"value": 3.0, "unit": "container side",
                          "sources": [{"url": family["page"], "label": "test"}]}})
    document = research.start(problem, name="test", agent="test")
    research.submit(document["session_id"], grid_initialize(problem), "two squares")
    return document["session_id"]


def prepare(session_id, root, original):
    return submission.prepare(session_id, root=root, original=original, author="Test Author", method="Two adjacent squares")


def test_preparation_matches_source_filename_size_palette_and_keeps_evidence_local(dossiers):
    root, original, families, _ = dossiers
    session_id = session(families[0])
    manifest = prepare(session_id, root, original)
    assert manifest["filename"] == "ab2.gif"  # letters come from the source, not the count
    assert manifest["previous"] == 2.1  # current catalog, rather than the session's older 3.0
    from PIL import Image
    with Image.open(root / session_id / "send/test-a/ab2.gif") as image:
        assert image.size == (120, 90) and image.format == "GIF"
        assert {colour[:3] for _, colour in image.convert("RGBA").getcolors()} <= {
            (255, 255, 255), (240, 224, 240), (0, 0, 0)}
        # A derived square is drawn even though the two copies occupy a 2:1 row.
        from PIL import ImageChops
        dark = ImageChops.invert(image.convert("RGB")).convert("L").point(lambda value: 255 if value > 200 else 0)
        left, top, right, bottom = dark.getbbox()
        assert abs((right - left) - (bottom - top)) <= 1
    assert (root / session_id / "internal/candidate.json").is_file()
    assert (root / session_id / "internal/verification.json").is_file()
    with ZipFile(io.BytesIO(submission.batch([session_id], root=root))) as archive:
        assert set(archive.namelist()) == {"test-a/ab2.gif", "test-a/values.txt", "email.txt"}
        assert "2.00000" in archive.read("test-a/values.txt").decode()
        assert "Test Author" in archive.read("email.txt").decode()


def test_batch_preserves_same_names_on_different_pages_but_rejects_duplicates(dossiers):
    root, original, families, _ = dossiers
    first, second = [session(family) for family in families]
    for session_id in (first, second):
        prepare(session_id, root, original)
    with ZipFile(io.BytesIO(submission.batch([first, second], root=root))) as archive:
        assert {"test-a/ab2.gif", "test-b/ab2.gif"} <= set(archive.namelist())
    duplicate = session(families[0])
    prepare(duplicate, root, original)
    with pytest.raises(ValueError, match="same image"):
        submission.batch([first, duplicate], root=root)


def test_a_superseded_record_cannot_be_prepared_or_batched(dossiers):
    root, original, families, catalog = dossiers
    session_id = session(families[0])
    prepare(session_id, root, original)
    document = json.loads(catalog.read_text())
    document["families"][0]["instances"][0]["value"] = 1.9
    catalog.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="current published"):
        prepare(session_id, root, original)
    with pytest.raises(ValueError, match="prepare the current"):
        submission.batch([session_id], root=root)


def test_changing_the_best_invalidates_the_prepared_dossier(dossiers):
    root, original, families, _ = dossiers
    session_id = session(families[0])
    prepare(session_id, root, original)
    document = research.load(session_id)
    document["champion"]["candidate_id"] = "new-arrangement"
    research._write(document)
    assert submission.prepared(session_id, root=root) is None


def test_batch_api_refuses_unprepared_or_invalid_selection(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from paper_obs.api import create_app
    monkeypatch.setenv("PAPER_OBS_RUNS", str(tmp_path))
    client = TestClient(create_app(static_directory=Path("/nonexistent"), processes=False))
    assert client.post("/api/research-submission-batch", json={"sessions": []}).status_code == 422
    assert client.post("/api/research-submission-batch", json={"sessions": [123]}).status_code == 422


def test_batch_api_downloads_only_selected_prepared_sessions(dossiers, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from paper_obs.api import create_app
    root, original, families, _ = dossiers
    first, second = [session(family) for family in families]
    for session_id in (first, second):
        prepare(session_id, root, original)
    monkeypatch.setattr(submission, "ROOT", root)
    client = TestClient(create_app(static_directory=Path("/nonexistent"), processes=False))
    assert all(row["submission_prepared"] for row in client.get("/api/research-sessions").json()["sessions"])
    response = client.post("/api/research-submission-batch", json={"sessions": [first]})
    assert response.status_code == 200 and response.headers["content-type"] == "application/zip"
    with ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == {"test-a/ab2.gif", "test-a/values.txt", "email.txt"}


def test_maximized_truncated_values_need_a_demonstrable_improvement(dossiers):
    from paper_obs.domain.arena import Arena
    from paper_obs.domain.candidate import Candidate
    from paper_obs.domain.objectives import MaximizeTotalPerimeter
    from paper_obs.domain.placement import Placement
    from paper_obs.domain.shapes import Circle
    root, original, families, catalog = dossiers
    data = json.loads(catalog.read_text())
    family = data["families"][0]
    family["section"] = "Packing Copies to Maximize Total Perimeter"
    family.update(shape="circle", container="circle")
    family["instances"][0].update(value=0.899, value_upper_bound=0.900, symbol="r")
    catalog.write_text(json.dumps(data), encoding="utf-8")
    problem = Problem(problem_id="two-discs", arena=Arena.disk(1), shape=Circle(radius=1),
        objective=MaximizeTotalPerimeter(count=2), metadata={"reference": {
            "value": 0.8, "unit": "sum of radii", "sources": [{"url": families[0]["page"]}]}})
    from PIL import Image
    transparent = Image.new("RGBA", (120, 90), (0, 0, 0, 0))
    transparent.paste((255, 255, 255, 255), (0, 0, 100, 90))
    transparent.paste((240, 224, 240, 255), (10, 10, 60, 60))
    transparent.paste((0, 0, 0, 255), (0, 70, 100, 72))
    transparent.save(original)
    session_id = research.start(problem, name="test", agent="test")["session_id"]
    candidate = Candidate(candidate_id="discs", problem_id=problem.problem_id, scale=1, placements=(
        Placement("a", -0.5, 0, scale=0.4), Placement("b", 0.49, 0, scale=0.4995)))
    assert research.submit(session_id, candidate)["valid"]
    with pytest.raises(ValueError, match="truncated last digit"):
        prepare(session_id, root, original)
    improved = candidate.derive(placements=(candidate.placements[0], Placement("b", 0.49, 0, scale=0.501)))
    assert research.submit(session_id, improved)["valid"]
    assert prepare(session_id, root, original)["value"] == pytest.approx(0.901)
    with Image.open(root / session_id / "send/test-a/ab2.gif") as image:
        assert "transparency" in image.info


def test_almost_equal_sizes_have_almost_equal_rainbow_colours():
    import xml.etree.ElementTree as xml
    from paper_obs.domain.arena import Arena
    from paper_obs.domain.candidate import Candidate
    from paper_obs.domain.objectives import MaximizeTotalPerimeter
    from paper_obs.domain.placement import Placement
    from paper_obs.geometry.submission import submission_svg
    from paper_obs.research.picture import DEFAULT
    problem = Problem(problem_id="colours", arena=Arena.rectangle(3, 3), shape=RegularPolygon(sides=4, side=1),
                      objective=MaximizeTotalPerimeter(count=2))
    candidate = Candidate(candidate_id="colours", problem_id=problem.problem_id, scale=1, placements=(
        Placement("a", -0.6, 0, scale=1), Placement("b", 0.6, 0, scale=0.999)))
    drawing = xml.fromstring(submission_svg(problem, candidate, {**DEFAULT, "rainbow": True}))
    fills = [path.attrib["fill"] for path in drawing.findall("{http://www.w3.org/2000/svg}path")][-2:]
    colours = [tuple(int(fill[i:i + 2], 16) for i in (1, 3, 5)) for fill in fills]
    assert max(abs(a - b) for a, b in zip(*colours)) <= 2


def test_preparation_refuses_a_different_shape_attached_to_a_source_reference(dossiers):
    from dataclasses import replace
    from paper_obs.domain.shapes import Circle
    root, original, families, catalog = dossiers
    session_id = session(families[0])
    document = research.load(session_id)
    expected = Problem.from_dict(document["problem"])
    data = json.loads(catalog.read_text())
    data["families"][0]["problem_template"] = expected.to_dict()
    catalog.write_text(json.dumps(data), encoding="utf-8")
    document["problem"] = replace(expected, shape=Circle(radius=1)).to_dict()
    research._write(document)
    with pytest.raises(ValueError, match="does not match the source family"):
        prepare(session_id, root, original)
