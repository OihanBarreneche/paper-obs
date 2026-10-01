"""The command line: end to end on the example files, exit codes included."""

from __future__ import annotations

import json
import socket
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest

from paper_obs import cli
from paper_obs.cli import main

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
CIRCLES = EXAMPLES / "circle_25_in_square.json"


def test_info_describes_a_problem(capsys) -> None:
    assert main(["info", "-p", str(CIRCLES)]) == 0
    output = capsys.readouterr().out
    assert "maximise the common scale of 25 shapes" in output
    assert "scale" in output


def test_init_then_validate_a_real_problem(tmp_path, capsys) -> None:
    candidate = tmp_path / "grid.json"
    picture = tmp_path / "grid.svg"
    assert (
        main(["init", "-p", str(CIRCLES), "-o", str(candidate), "--svg", str(picture)]) == 0
    )
    assert "valid" in capsys.readouterr().out

    assert main(["validate", "-p", str(CIRCLES), "-c", str(candidate)]) == 0
    assert "VALID" in capsys.readouterr().out
    assert ElementTree.parse(picture).getroot().tag.endswith("svg")


def test_evaluate_writes_the_verdict_and_its_metrics(tmp_path, capsys) -> None:
    candidate = tmp_path / "grid.json"
    report = tmp_path / "evaluation.json"
    main(["init", "-p", str(CIRCLES), "-o", str(candidate)])
    assert main(["evaluate", "-p", str(CIRCLES), "-c", str(candidate), "--json", str(report)]) == 0

    output = capsys.readouterr().out
    assert "density" in output
    evaluation = json.loads(report.read_text(encoding="utf-8"))
    assert evaluation["valid"] is True
    assert evaluation["score"]["primary"] == pytest.approx(2.0)
    assert evaluation["metrics"]["n_shapes"] == 25.0


def test_an_invalid_candidate_exits_with_one(tmp_path, capsys) -> None:
    candidate = tmp_path / "overlapping.json"
    candidate.write_text(
        json.dumps(
            {
                "candidate_id": "bad",
                "problem_id": "circle-25-in-square",
                "scale": 2.0,
                "placements": [
                    {"shape_id": "s000", "x": 0.0, "y": 0.0},
                    {"shape_id": "s001", "x": 0.0, "y": 0.0},
                ],
            }
        ),
        encoding="utf-8",
    )
    assert main(["validate", "-p", str(CIRCLES), "-c", str(candidate)]) == 1
    output = capsys.readouterr().out
    assert "INVALID" in output
    assert "overlap" in output


def test_a_free_port_is_kept() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free = int(probe.getsockname()[1])
    # The probe is closed again: the port is free, so it must come back unchanged.
    assert cli._available_port("127.0.0.1", free) == free


def test_a_busy_port_is_never_handed_to_the_server() -> None:
    """A launcher must not fail because something else already holds the port."""
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen(1)
        busy = int(taken.getsockname()[1])
        chosen = cli._available_port("127.0.0.1", busy)
        assert chosen != busy
        assert busy < chosen <= busy + 9


def test_a_url_never_carries_a_wildcard_host() -> None:
    assert cli._browsable_host("0.0.0.0") == "127.0.0.1"
    assert cli._browsable_host("::") == "127.0.0.1"
    assert cli._browsable_host("127.0.0.1") == "127.0.0.1"


def test_a_candidate_from_another_problem_is_a_usage_error(tmp_path, capsys) -> None:
    candidate = tmp_path / "circles.json"
    main(["init", "-p", str(CIRCLES), "-o", str(candidate)])
    other = EXAMPLES / "squares_16_in_square.json"
    assert main(["validate", "-p", str(other), "-c", str(candidate)]) == 2
    assert "belongs to problem" in capsys.readouterr().err


def test_a_missing_file_is_a_usage_error(capsys) -> None:
    assert main(["info", "-p", "does-not-exist.json"]) == 2
    assert "No such file" in capsys.readouterr().err


def test_render_and_analyze_on_a_disk_problem(tmp_path, capsys) -> None:
    problem = EXAMPLES / "circles_19_in_disk.json"
    candidate = tmp_path / "hex.json"
    picture = tmp_path / "hex.svg"
    assert main(["init", "-p", str(problem), "-s", "staggered", "-o", str(candidate)]) == 0
    assert main(["render", "-p", str(problem), "-c", str(candidate), "-o", str(picture), "--voids"]) == 0
    assert ElementTree.parse(picture).getroot().tag.endswith("svg")

    assert main(["analyze", "-p", str(problem), "-c", str(candidate)]) == 0
    assert "voids" in capsys.readouterr().out


def test_squares_and_triangles_examples_load_and_score(tmp_path, capsys) -> None:
    for name in ("squares_16_in_square.json", "triangles_in_holed_rect.json"):
        problem = EXAMPLES / name
        candidate = tmp_path / f"{name}.json"
        assert main(["init", "-p", str(problem), "-o", str(candidate)]) == 0
        assert main(["evaluate", "-p", str(problem), "-c", str(candidate)]) in (0, 1)
    assert capsys.readouterr().out


def test_generate_sends_its_document_to_the_file_or_the_directory_it_was_given(
    tmp_path, capsys
) -> None:
    """``--out`` names a file when it carries a suffix, a directory when it does not."""
    directory = tmp_path / "runs"
    assert main(["generate", "--seed", "7", "--arena", "rect", "--out", str(directory)]) == 0
    written = sorted(directory.glob("*.json"))
    assert len(written) == 1
    document = json.loads(written[0].read_text())
    assert document["problem_id"] == written[0].stem
    assert document["metadata"]["generator"]["seed"] == 7
    assert str(written[0]) in capsys.readouterr().out

    target = tmp_path / "one-instance.json"
    args = ["generate", "--seed", "3", "--arena", "composite", "--counts", "2", "5"]
    assert main([*args, "--out", str(target)]) == 0
    assert json.loads(target.read_text())["seed"] == 3


def test_search_keeps_one_artefact_per_strategy_in_a_directory(tmp_path) -> None:
    """One file per object: two runs never share a path, whatever the suffix."""
    directory = tmp_path / "curves"
    command = [
        "search", "-p", str(CIRCLES), "-b", "lattice", "-b", "basin_hopping", "--budget", "40",
        "--json", str(directory), "--svg", str(directory),
    ]
    assert main(command) == 0
    assert sorted(path.name for path in directory.iterdir()) == [
        "basin_hopping.json", "basin_hopping.svg", "lattice.json", "lattice.svg",
    ]


def test_search_writes_exactly_the_file_it_was_given_for_one_baseline(tmp_path) -> None:
    target = tmp_path / "curve.json"
    command = ["search", "-p", str(CIRCLES), "-b", "lattice", "--budget", "40", "--json", str(target)]
    assert main(command) == 0
    assert json.loads(target.read_text())["strategy"] == "lattice"
