"""Free research sessions: the journal an outside agent writes and the engine judges."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from paper_obs import research
from paper_obs.cli import main
from paper_obs.domain.placement import Placement
from paper_obs.search.operators.initialization import grid_initialize


@pytest.fixture(autouse=True)
def runs(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_OBS_RUNS", str(tmp_path))
    return tmp_path


def test_a_catalog_problem_carries_its_published_record() -> None:
    problem = research.catalog_problem("taninL", 26)
    assert problem.problem_id == "tans-26-in-smallest-l"
    assert problem.objective.count == 26
    reference = problem.metadata["reference"]
    assert reference["unit"] == "container side" and reference["value"] > 2.0
    assert reference["preview"].endswith("26.gif")


def test_a_session_keeps_only_improvements_and_measures_them_in_the_record_unit(runs) -> None:
    problem = research.catalog_problem("squintri", 5)
    session = research.start(problem, name="five squares", agent="test")
    assert (runs / "research" / session["session_id"] / "work").is_dir()

    start = grid_initialize(problem)
    first = research.submit(session["session_id"], start, "grid start")
    assert first["valid"] and first["accepted"]
    assert first["metric"] == "container side"
    assert first["measure"] == pytest.approx(1.0 / start.scale, rel=1e-9)
    assert first["record_gap"] is not None and first["record_gap"] < 0  # a grid is no record

    stacked = replace(start, placements=tuple(Placement(item.shape_id, 0.0, 0.0, item.rotation)
                                              for item in start.placements))
    second = research.submit(session["session_id"], stacked)
    assert not second["valid"] and not second["accepted"] and second["candidate"] is None
    research.add_note(session["session_id"], "stacking every copy on one spot overlaps, as it should")

    document = research.load(session["session_id"])
    assert document["kind"] == "research-session"
    assert [item["kind"] for item in document["journal"]] == ["submission", "submission", "note"]
    assert document["champion"]["candidate_id"] == start.candidate_id
    line = research.listing(problem.problem_id)[0]
    assert line["submissions"] == 2 and len(line["track"]) == 1
    assert (line["shape"], line["container"]) == ("square", "triangle")


def test_the_command_line_answers_in_json(runs, tmp_path, capsys) -> None:
    problem_file = tmp_path / "problem.json"
    assert main(["research", "problem", "squintri", "5", "--out", str(problem_file)]) == 0
    capsys.readouterr()
    assert main(["research", "start", "-p", str(problem_file), "--name", "cli", "--agent", "test"]) == 0
    session_id = json.loads(capsys.readouterr().out)["session_id"]
    assert main(["research", "status", session_id, "--set", "paused"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["status"] == "paused" and status["record"]["unit"] == "container side"
    assert main(["research", "note", session_id, "corner seeds stall at 7.62", "--step", "dead-end"]) == 0
    assert json.loads(capsys.readouterr().out)["step"] == "dead-end"


def test_the_journal_tells_each_step_and_where_each_arrangement_comes_from(runs) -> None:
    problem = research.catalog_problem("squintri", 5)
    session_id = research.start(problem, name="steps", agent="test")["session_id"]
    (runs / "research" / session_id / "work" / "grid.py").write_text("print('grid')\n", encoding="utf-8")

    research.add_note(session_id, "a grid is a fair first start", step="idea")
    program = research.add_note(session_id, "places the squares on a grid", step="program", path="./grid.py")
    assert program["step"] == "program" and program["path"] == "grid.py"
    start = grid_initialize(problem)
    first = research.submit(session_id, start, method="reasoning", builds_on="a square grid", programs=["grid.py"])
    again = research.submit(session_id, start, method="refinement", builds_on=0)
    assert (first["method"], first["builds_on"], first["programs"]) == ("reasoning", "a square grid", ["grid.py"])
    assert (again["method"], again["builds_on"], again["programs"]) == ("refinement", 0, [])
    assert research.work_file(session_id, "grid.py") == {"path": "grid.py", "text": "print('grid')\n"}

    with pytest.raises(ValueError):
        research.add_note(session_id, "no file named", step="program")
    with pytest.raises(ValueError):
        research.add_note(session_id, "outside work/", step="program", path="../session.json")
    with pytest.raises(ValueError):
        research.submit(session_id, start, method="luck")
    with pytest.raises(ValueError):
        research.submit(session_id, start, builds_on=5)
    with pytest.raises(ValueError):
        research.work_file(session_id, "../session.json")


def test_a_deleted_session_leaves_the_listing_and_keeps_its_folder(runs) -> None:
    session_id = research.start(research.catalog_problem("squintri", 5), name="gone", agent="test")["session_id"]
    research.delete(session_id)
    assert research.listing() == []
    assert (runs / "research" / "deleted" / session_id / "session.json").is_file()
    with pytest.raises(ValueError):
        research.delete(session_id)
