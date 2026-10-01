"""The HTTP surface: translating, judging, and refusing a bad document clearly.

The API is a translator, so the tests check what a client would observe: a
complete verdict with its picture, the engine's own words when a document is
refused, and a view that carries every number a browser would otherwise be
tempted to compute itself.
"""

from __future__ import annotations

import json
import time

from pathlib import Path
from threading import Event

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from paper_obs.api import create_app, library  # noqa: E402

CLIENT = TestClient(create_app(static_directory=Path("/nonexistent-frontend"), processes=False))


def test_an_active_run_can_be_asked_to_stop() -> None:
    signal = Event()
    CLIENT.app.state.active_runs["run-stop-test"] = signal
    try:
        answer = CLIENT.post("/api/agent-runs/run-stop-test/stop")
        assert answer.status_code == 200
        assert answer.json()["status"] == "stop_requested"
        assert signal.is_set()
    finally:
        CLIENT.app.state.active_runs.pop("run-stop-test", None)


def test_a_run_read_while_its_stop_is_pending_says_so(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Until the run writes its end, a reload still learns that a stop was asked for."""
    monkeypatch.setenv("PAPER_OBS_RUNS", str(tmp_path))
    (tmp_path / "run-pending.json").write_text(json.dumps(
        {"kind": "agent-run", "run_id": "run-pending", "status": "running"}), encoding="utf-8")
    assert "stop_requested" not in CLIENT.get("/api/agent-runs/run-pending").json()
    signal = Event()
    CLIENT.app.state.active_runs["run-pending"] = signal
    try:
        assert "stop_requested" not in CLIENT.get("/api/agent-runs/run-pending").json()
        signal.set()
        assert CLIENT.get("/api/agent-runs/run-pending").json()["stop_requested"] is True
    finally:
        CLIENT.app.state.active_runs.pop("run-pending", None)


def test_research_sessions_are_listed_by_problem_and_read_back(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The interface reads the sessions an outside agent writes; an unknown one is a 404."""
    from paper_obs import research

    monkeypatch.setenv("PAPER_OBS_RUNS", str(tmp_path))
    problem = research.catalog_problem("squintri", 5)
    session = research.start(problem, name="api", agent="test")
    lines = CLIENT.get("/api/research-sessions", params={"problem_id": problem.problem_id}).json()["sessions"]
    assert [line["session_id"] for line in lines] == [session["session_id"]]
    assert CLIENT.get("/api/research-sessions", params={"problem_id": "other"}).json()["sessions"] == []
    assert CLIENT.get(f"/api/research-sessions/{session['session_id']}").json()["name"] == "api"
    assert CLIENT.get("/api/research-sessions/res-missing").status_code == 404
    folder = tmp_path / "research" / session["session_id"]
    (folder / "work" / "seed.py").write_text("print(1)\n", encoding="utf-8")
    base = f"/api/research-sessions/{session['session_id']}/work"
    assert CLIENT.get(f"{base}/seed.py").json() == {"path": "seed.py", "text": "print(1)\n"}
    assert CLIENT.get(f"{base}/..%2Fsession.json").status_code == 404


def _example(problem_id: str = "circle-25-in-square") -> dict:
    """Return one shipped problem document, as a client would fetch it."""
    return CLIENT.get(f"/api/examples/{problem_id}").json()["problem"]


def _empty_candidate(problem: dict) -> dict:
    """Return a candidate holding no shape, enough to see how a problem is judged."""
    return {
        "candidate_id": "empty",
        "problem_id": problem["problem_id"],
        "scale": 1.0,
        "placements": [],
    }


def test_health_reports_the_version_and_where_examples_come_from() -> None:
    body = CLIENT.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["frontend"] is False
    assert body["example_directories"]


def test_the_picker_offers_the_ladder_and_only_the_ladder() -> None:
    """The instances are meant to be tried in order, so the order is part of the answer."""
    examples = CLIENT.get("/api/examples").json()["examples"]
    assert [example["rung"] for example in examples] == [1, 2, 3, 4, 5]
    assert [example["problem_id"] for example in examples] == [
        name for name, _, _ in library.LADDER
    ]
    assert all(example["why"] for example in examples)
    assert all(example["objective"] for example in examples)
    # A file the ladder does not name is still read by the command line, and is not
    # offered as a question the interface asks.
    assert "squares-16-in-square" not in [example["problem_id"] for example in examples]


def test_reading_an_example_returns_it_with_its_search_interval() -> None:
    body = CLIENT.get("/api/examples/circle-25-in-square").json()
    assert body["problem"]["objective"] == {"type": "maximize_scale", "count": 25}
    assert body["scale_bounds"]["high"] == pytest.approx(2.25676, rel=1e-4)
    assert "maximise" in body["text"]


def test_group_rotation_uses_the_selection_centre_and_returns_a_verdict() -> None:
    example = CLIENT.get("/api/examples/squares-5-in-smallest-square").json()
    original = example["candidate"]
    response = CLIENT.post("/api/rotate-selection", json={
        "problem": example["problem"],
        "candidate": original,
        "shape_ids": ["s000", "s003"],
        "degrees": 90,
    })
    assert response.status_code == 200
    verdict = response.json()
    placements = {item["shape_id"]: item for item in verdict["candidate"]["placements"]}
    assert placements["s000"]["x"] == pytest.approx(1.3535533905932737)
    assert placements["s003"]["x"] == pytest.approx(1.3535533905932737)
    assert placements["s000"]["y"] == pytest.approx(1.3535533905932737)
    assert placements["s003"]["y"] == pytest.approx(-0.3535533905932737)
    assert placements["s004"] == original["placements"][4]
    assert verdict["candidate"]["parents"] == [original["candidate_id"]]
    assert verdict["evaluation"]["valid"] is False


def test_every_shipped_solution_is_a_packing_the_engine_accepts() -> None:
    """An example's default arrangement has to be valid, because it is what the lab opens on.

    The verdict beside it is the engine's, computed from the shipped coordinates:
    the file carries no score, so a solution that overlapped its own neighbours
    would greet the user with a red verdict and a number nobody could compare.
    """
    refused = []
    # Every example on disk, not only the ladder: an off-ladder file is still a problem
    # the command line reads, and its shipped solution has to hold for it too.
    for problem_id in library.examples():
        document = CLIENT.get(f"/api/examples/{problem_id}").json()
        if document["candidate"] is None:
            continue
        verdict = CLIENT.post(
            "/api/evaluate",
            json={"problem": document["problem"], "candidate": document["candidate"]},
        ).json()
        if not verdict["evaluation"]["valid"]:
            refused.append(problem_id)
    assert refused == []


def test_a_measured_region_is_not_offered_as_an_editable_arena() -> None:
    """The browser may edit only an arena the problem owns.

    A container problem declares no arena — the domain refuses that pair outright —
    so the view must keep drawing the region the engine measured while reporting
    nothing to edit. Announcing an editable stack of parts invites the client to
    write it back into the problem, which the engine then answers with a 400, and
    from there every later request of the session is refused.
    """
    document = CLIENT.get("/api/examples/squares-17-in-smallest-square").json()
    view = CLIENT.post(
        "/api/evaluate",
        json={"problem": document["problem"], "candidate": document["candidate"]},
    ).json()["view"]
    assert view["arena"]["editable"] is False
    assert view["arena"]["parts"] == []
    assert view["arena"]["path"]


def test_a_part_that_carries_an_angle_comes_back_with_it() -> None:
    """A part the client can turn has to be handed back the way it was received.

    The editor sends the parts it holds to `/api/arena` and writes the compiled
    answer into the problem, so a part whose angle the view left out would lose
    its turn at the first edit of its stack — and the canvas, which draws the
    engine's own outline, would have nothing to put a rotation control on.
    """
    parts = [
        {"op": "base", "params": {"kind": "rect", "width": 4.0, "height": 2.0}},
        {"op": "difference", "params": {"kind": "disk", "radius": 0.5}, "offset": [1.0, 0.0], "angle": 90.0},
    ]
    arena = CLIENT.post("/api/arena", json={"parts": parts}).json()["arena"]
    # The verdict is not what this asserts: the candidate is the example's own and
    # most of it falls outside the small arena composed here. What matters is that
    # the view the browser is handed names the turn, so the part can be given back.
    example = CLIENT.get("/api/examples/squares-16-in-square").json()
    view = CLIENT.post(
        "/api/evaluate",
        json={"problem": {**example["problem"], "arena": arena}, "candidate": example["candidate"]},
    ).json()["view"]
    assert view["arena"]["parts"][1]["angle"] == 90.0
    assert view["arena"]["parts"][0]["angle"] == 0.0


def test_a_rebuilt_page_is_not_served_from_the_browser_cache(tmp_path: Path) -> None:
    """A rebuilt page has to be revalidated, or the previous bundle keeps running.

    The document names its bundle by a hash and carries no version of its own, so
    with no explicit freshness the browser applies a heuristic lifetime and reuses
    it without ever asking the server: `dist` is rebuilt, the old document and the
    old bundle are both still in the cache, and the whole previous page runs on. The
    hashed assets are the opposite case — their name changes with their content, so
    keeping them for ever costs nothing.
    """
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text('<script src="/assets/app.js"></script>')
    (tmp_path / "assets" / "app.js").write_text("export {};")
    client = TestClient(create_app(static_directory=tmp_path))
    assert client.get("/").headers["cache-control"] == "no-cache"
    assert client.get("/assets/app.js").headers["cache-control"] == (
        "public, max-age=31536000, immutable"
    )


def test_the_published_instances_measure_their_published_size() -> None:
    """Three numbers that come from outside this repository, recovered from coordinates.

    Five unit squares in Goebel's rigid packing measure ``2 + sqrt(2)/2`` exactly;
    seventeen in Bidwell's measure the root the source page publishes,
    4.67553009360455; and Packomania's seventeen circles in a square measure the
    reciprocal of its printed radius, 8.53266034749436. Each of these is an
    outside value, which is the whole point: a round trip through our own code
    would agree with any rule at all.
    """
    published = {
        "squares-5-in-smallest-square": 2.0 + 2**0.5 / 2.0,
        "squares-17-in-smallest-square": 4.67553009360455,
        "circles-17-in-smallest-square": 1.0 / 0.117196742783,
    }
    for problem_id, side in published.items():
        document = CLIENT.get(f"/api/examples/{problem_id}").json()
        verdict = CLIENT.post(
            "/api/evaluate",
            json={"problem": document["problem"], "candidate": document["candidate"]},
        ).json()
        assert verdict["evaluation"]["metrics"]["container_side"] == pytest.approx(side, abs=1e-9), problem_id


def test_the_two_readings_of_one_instance_score_the_same_number() -> None:
    """``1/side`` on the direct reading *is* the common scale on the unit-arena one.

    That identity is what the family claims: the same instance asked from either
    end. Both examples ship a solution, and the two solutions must land on the
    same primary — if they ever drift, one of the two readings has stopped
    meaning what the objective says it means.
    """
    primaries = []
    for problem_id in ("squares-17-in-smallest-square", "squares-17-in-unit-square"):
        document = CLIENT.get(f"/api/examples/{problem_id}").json()
        verdict = CLIENT.post(
            "/api/evaluate",
            json={"problem": document["problem"], "candidate": document["candidate"]},
        ).json()
        primaries.append(verdict["evaluation"]["score"]["primary"])
    assert primaries[0] == pytest.approx(primaries[1], rel=1e-12)


def test_init_returns_a_valid_candidate_its_verdict_and_its_picture() -> None:
    body = CLIENT.post(
        "/api/init", json={"problem": _example(), "strategy": "grid"}
    ).json()
    assert body["evaluation"]["valid"] is True
    assert body["evaluation"]["score"]["primary"] == pytest.approx(2.0)
    assert body["evaluation"]["metrics"]["density"] == pytest.approx(0.7854, abs=1e-4)
    assert len(body["view"]["shapes"]) == 25
    assert body["view"]["arena"]["path"].startswith("M ")
    assert body["summary"]["verdict"] == "valid"


def test_the_view_carries_every_number_a_browser_would_otherwise_compute() -> None:
    squares = _example("squares-16-in-square")
    body = CLIENT.post("/api/init", json={"problem": squares, "strategy": "grid"}).json()
    primitive = body["view"]["shapes"][0]
    assert primitive["kind"] == "polygon"
    assert len(primitive["points"]) == 4
    assert primitive["center"] == [-3.75, -3.75]
    assert body["view"]["frame"] == [-5.0, -5.0, 5.0, 5.0]


def test_an_overlap_comes_back_with_the_depth_that_separates_it() -> None:
    problem = _example()
    problem["objective"] = {"type": "maximize_count", "scale": 2.0}
    candidate = {
        "candidate_id": "bad",
        "problem_id": "circle-25-in-square",
        "scale": 2.0,
        "placements": [
            {"shape_id": "s000", "x": 0.0, "y": 0.0},
            {"shape_id": "s001", "x": 1.5, "y": 0.0},
        ],
    }
    body = CLIENT.post(
        "/api/evaluate", json={"problem": problem, "candidate": candidate}
    ).json()
    assert body["evaluation"]["valid"] is False
    violations = body["evaluation"]["validation"]["results"]
    overlap = next(result for result in violations if result["constraint"] == "non_overlap")
    assert overlap["violations"][0]["magnitude"] == pytest.approx(0.5)
    assert [shape["invalid"] for shape in body["view"]["shapes"]] == [True, True]


def test_the_empty_regions_are_only_computed_when_asked_for() -> None:
    problem = _example()
    candidate = CLIENT.post("/api/init", json={"problem": problem, "strategy": "grid"}).json()[
        "candidate"
    ]
    without = CLIENT.post("/api/evaluate", json={"problem": problem, "candidate": candidate}).json()
    asked = CLIENT.post(
        "/api/evaluate", json={"problem": problem, "candidate": candidate, "with_voids": True}
    ).json()
    assert "voids" not in without["view"]
    assert asked["view"]["voids"]
    assert asked["view"]["voids"][0]["area"] > 0.0


def test_an_arena_can_be_composed_from_a_stack_of_parts() -> None:
    body = CLIENT.post(
        "/api/arena",
        json={
            "parts": [
                {"op": "base", "params": {"kind": "rect", "width": 10.0, "height": 10.0}},
                {
                    "op": "difference",
                    "params": {"kind": "disk", "radius": 2.0},
                    "offset": [2.0, 0.0],
                },
            ]
        },
    ).json()
    assert body["area"] == pytest.approx(100.0 - 4.0 * 3.14159265, rel=1e-3)
    # The disc sits clear of the walls, so its ring is a hole and not a notch.
    assert body["path"].count("M") == 2
    assert [item["op"] for item in body["parts"]] == ["base", "difference"]
    assert body["parts"][1]["params"]["kind"] == "disk"
    assert body["parts"][1]["offset"] == [2.0, 0.0]
    assert body["arena"]["shape"]["type"] == "difference"


def test_a_rotated_part_is_read_from_the_request() -> None:
    """A part sent back with an angle is compiled turned, in degrees, about its own origin."""
    body = CLIENT.post(
        "/api/arena",
        json={
            "parts": [
                {
                    "op": "base",
                    "params": {"kind": "rect", "width": 4.0, "height": 2.0},
                    "offset": [0.0, 0.0],
                    "angle": 90.0,
                },
            ]
        },
    ).json()
    assert body["area"] == pytest.approx(8.0)
    assert body["bounds"] == pytest.approx([-1.0, -2.0, 1.0, 2.0])
    assert body["parts"][0]["bounds"] == pytest.approx([-1.0, -2.0, 1.0, 2.0])


def test_a_part_sent_without_an_angle_is_not_turned() -> None:
    """A client that never received an angle sends none, and the arena is the one it always was."""
    body = CLIENT.post(
        "/api/arena",
        json={
            "parts": [
                {"op": "base", "params": {"kind": "rect", "width": 4.0, "height": 2.0}, "offset": [0.0, 0.0]}
            ]
        },
    ).json()
    assert body["bounds"] == pytest.approx([-2.0, -1.0, 2.0, 1.0])
    assert body["parts"][0]["bounds"] == pytest.approx([-2.0, -1.0, 2.0, 1.0])


def test_a_malformed_angle_is_refused_like_any_other_malformed_part() -> None:
    response = CLIENT.post(
        "/api/arena",
        json={
            "parts": [
                {
                    "op": "base",
                    "params": {"kind": "rect", "width": 4.0, "height": 2.0},
                    "angle": "a quarter turn",
                }
            ]
        },
    )
    assert response.status_code == 400
    assert "invalid arena part" in response.json()["detail"]


def test_an_impossible_stack_is_refused_in_the_domain_words() -> None:
    response = CLIENT.post(
        "/api/arena",
        json={
            "parts": [
                {"op": "base", "params": {"kind": "rect", "width": 2.0, "height": 2.0}},
                {"op": "difference", "params": {"kind": "rect", "width": 4.0, "height": 4.0}},
            ]
        },
    )
    assert response.status_code == 400
    assert "empty region" in response.json()["detail"]


def test_an_unknown_part_kind_is_refused() -> None:
    response = CLIENT.post(
        "/api/arena",
        json={"parts": [{"op": "base", "params": {"kind": "blob", "size": 1.0}}]},
    )
    assert response.status_code == 400
    assert "invalid arena part" in response.json()["detail"]


def test_an_empty_stack_is_refused() -> None:
    response = CLIENT.post("/api/arena", json={"parts": []})
    assert response.status_code == 400
    assert "non-empty" in response.json()["detail"]


def test_a_composite_arena_shows_its_parts_to_the_interface() -> None:
    problem = _example("triangles-in-holed-rect")
    problem["objective"] = {"type": "maximize_count", "scale": 1.0}
    body = CLIENT.post("/api/evaluate", json={"problem": problem, "candidate": _empty_candidate(problem)}).json()
    arena = body["view"]["arena"]
    assert arena["editable"] is True
    assert [item["params"]["kind"] for item in arena["parts"]] == ["rect", "disk"]


def test_render_returns_an_svg_document() -> None:
    problem = _example()
    verdict = CLIENT.post("/api/init", json={"problem": problem, "strategy": "grid"}).json()
    response = CLIENT.post(
        "/api/render",
        json={"problem": problem, "candidate": verdict["candidate"], "options": {"show_ids": True}},
    )
    assert response.status_code == 200
    assert response.text.startswith("<svg")
    assert response.text.count("<circle") == 25
    assert response.text.count("<text") == 25


def test_an_unknown_problem_is_a_404_naming_the_known_ones() -> None:
    response = CLIENT.get("/api/examples/does-not-exist")
    assert response.status_code == 404
    assert "circle-25-in-square" in response.json()["detail"]


def test_a_malformed_problem_is_refused_in_the_domain_layer_wording() -> None:
    response = CLIENT.post("/api/init", json={"problem": {"problem_id": "p"}, "strategy": "grid"})
    assert response.status_code == 400
    assert "missing required field 'shape'" in response.json()["detail"]


def test_a_candidate_from_another_problem_is_refused() -> None:
    response = CLIENT.post(
        "/api/evaluate",
        json={
            "problem": _example("squares-16-in-square"),
            "candidate": {
                "candidate_id": "c",
                "problem_id": "circle-25-in-square",
                "scale": 2.0,
                "placements": [],
            },
        },
    )
    assert response.status_code == 400
    assert "belongs to problem" in response.json()["detail"]


def test_an_unknown_strategy_is_refused_with_the_known_ones() -> None:
    response = CLIENT.post("/api/init", json={"problem": _example(), "strategy": "magic"})
    assert response.status_code == 400
    assert "grid" in response.json()["detail"]


def test_the_staggered_lattice_refuses_a_non_disc_problem() -> None:
    response = CLIENT.post(
        "/api/init", json={"problem": _example("squares-16-in-square"), "strategy": "staggered"}
    )
    assert response.status_code == 400
    assert "only defined for discs" in response.json()["detail"]


def test_capabilities_say_which_initialisers_and_baselines_apply() -> None:
    """A client hides what cannot work, so the answer must name what can."""
    disc = CLIENT.post("/api/capabilities", json={"problem": _example()}).json()
    assert disc["initialize"] == ["grid", "staggered", "random", "varied"]
    assert disc["search"] == CLIENT.get("/api/baselines").json()["baselines"]
    assert disc["reason"] == ""

    square = CLIENT.post(
        "/api/capabilities", json={"problem": _example("squares-16-in-square")}
    ).json()
    # The staggered lattice is defined for discs only, and the engine refuses it
    # for a square: the client is not offered what the engine will not run.
    assert square["initialize"] == ["grid", "random", "varied"]


def test_capabilities_offer_only_the_varied_start_for_a_total_perimeter_problem() -> None:
    """Every other initialiser sizes the copies alike, which that objective refuses.

    The varied start is the one that speaks the family's language, so the engine
    offers it alone; opening the problem on it produces a valid candidate whose
    promoted total_scale is the sum the source pages print.
    """
    document = {
        "problem_id": "cirRsqu-3",
        "name": "3 circles",
        "description": "",
        "seed": None,
        "arena": {"name": "arena", "shape": {"type": "rect", "width": 1.0, "height": 1.0}},
        "shape": {"type": "circle", "radius": 1.0},
        "objective": {"type": "maximize_total_perimeter", "count": 3},
        "rotation": {"type": "rotation_policy", "mode": "free", "angles": [0]},
        "constraints": [],
        "metadata": {},
    }

    body = CLIENT.post("/api/capabilities", json={"problem": document}).json()
    assert body["initialize"] == ["varied"]
    # No baseline varies a copy's own size: a run there is a search that can never
    # improve on its own first judgement, so the panel is not offered one.
    assert body["search"] == []
    assert body["reason"] == ""

    response = CLIENT.post("/api/init", json={"problem": document, "strategy": "varied"})
    assert response.status_code == 200
    verdict = response.json()
    assert verdict["evaluation"]["valid"] is True
    assert verdict["evaluation"]["promoted_metric"] == "total_scale"
    assert verdict["evaluation"]["metrics"]["total_scale"] > 0.0
    # The common scale is fixed at 1, and the answer says so rather than offering an
    # interval a client could mistake for a searchable scale.
    assert verdict["scale_bounds"]["fixed"] == 1.0


def test_capabilities_offer_only_the_covering_start_for_a_covering_problem() -> None:
    """A covering reads the scale upwards, and no offered baseline can cover.

    The covering start lays copies over the arena, while the lattice initialisers
    fill it and the baselines pack shapes inside it: neither speaks the covering
    question, so the engine offers the covering start alone and no run. Opening the
    problem on that start produces a valid candidate whose promoted metric is the
    covered size.
    """
    document = {
        "problem_id": "sqcovcir-2",
        "name": "2 squares covering a circle",
        "description": "",
        "seed": None,
        "arena": {"name": "target", "shape": {"type": "disk", "radius": 1.0}},
        "shape": {"type": "regular_polygon", "sides": 4, "side": 1.0},
        "objective": {"type": "cover_region", "count": 2},
        "rotation": {"type": "rotation_policy", "mode": "free", "angles": [0]},
        "constraints": [],
        "metadata": {},
    }

    body = CLIENT.post("/api/capabilities", json={"problem": document}).json()
    assert body["initialize"] == ["cover"]
    assert body["search"] == []
    assert body["reason"] == ""

    response = CLIENT.post("/api/init", json={"problem": document, "strategy": "cover"})
    assert response.status_code == 200
    verdict = response.json()
    assert verdict["evaluation"]["valid"] is True
    assert verdict["evaluation"]["promoted_metric"] == "covered_size"


def test_capabilities_answer_nothing_for_a_document_the_domain_refuses() -> None:
    """The question has a true answer even for a document that cannot be built."""
    response = CLIENT.post("/api/capabilities", json={"problem": {"problem_id": "p"}})
    assert response.status_code == 200
    body = response.json()
    assert body["initialize"] == []
    assert body["search"] == []
    assert "invalid problem" in body["reason"]


def test_an_unknown_render_option_is_refused_with_the_known_ones() -> None:
    problem = _example()
    verdict = CLIENT.post("/api/init", json={"problem": problem, "strategy": "grid"}).json()
    response = CLIENT.post(
        "/api/render",
        json={"problem": problem, "candidate": verdict["candidate"], "options": {"glitter": True}},
    )
    assert response.status_code == 400
    assert "show_ids" in response.json()["detail"]


def test_a_request_without_a_problem_is_refused() -> None:
    response = CLIENT.post("/api/evaluate", json={"candidate": {}})
    assert response.status_code == 400
    assert "problem" in response.json()["detail"]


def test_every_shape_of_the_palette_can_be_placed_in_a_problem() -> None:
    """The palette is only useful if what it offers can actually be packed."""
    entries = CLIENT.get("/api/shapes").json()["shapes"]
    assert entries, "an empty palette would leave the interface with nothing to add"
    for entry in entries:
        problem = _example()
        problem["shape"] = entry["shape"]
        # One shape asked for, one shape placed: the palette's shape is what is
        # being judged here, not the example's own count.
        problem["objective"] = {"type": "maximize_scale", "count": 1}
        candidate = _empty_candidate(problem)
        candidate["placements"] = [{"shape_id": "s000", "x": 0.0, "y": 0.0}]
        body = CLIENT.post("/api/evaluate", json={"problem": problem, "candidate": candidate}).json()
        assert body["evaluation"]["valid"] is True, f"{entry['id']}: {body['evaluation']['validation']}"


def test_the_baselines_are_listed_for_a_client_to_choose_from() -> None:
    names = CLIENT.get("/api/baselines").json()["baselines"]
    assert set(names) == {"lattice", "basin_hopping"}


def test_a_baseline_run_returns_its_curve_and_the_candidate_it_found() -> None:
    """A comparison needs the curve as much as the winner, and the picture too."""
    problem = _example()
    body = CLIENT.post(
        "/api/search", json={"problem": problem, "baseline": "lattice", "budget": 80}
    ).json()
    convergence = body["convergence"]
    assert convergence["strategy"] == "lattice"
    assert convergence["problem_id"] == problem["problem_id"]
    assert len(convergence["steps"]) == convergence["evaluations"] <= 80
    assert [step["evaluations"] for step in convergence["steps"]] == sorted(
        step["evaluations"] for step in convergence["steps"]
    )
    # The winner is judged and drawn like any other candidate: the client puts it
    # on its canvas without a second round trip.
    verdict = body["verdict"]
    assert verdict["candidate"]["candidate_id"] == convergence["best"]["candidate_id"]
    assert verdict["evaluation"]["valid"] is True
    assert len(verdict["view"]["shapes"]) == problem["objective"]["count"]


def test_a_run_is_reproducible_from_the_seed_the_client_passes() -> None:
    problem = _example()
    request = {"problem": problem, "baseline": "basin_hopping", "budget": 50, "seed": 5}
    first = CLIENT.post("/api/search", json=request).json()["convergence"]
    second = CLIENT.post("/api/search", json=request).json()["convergence"]
    assert first == second


def test_an_unknown_baseline_lists_the_known_ones() -> None:
    response = CLIENT.post(
        "/api/search", json={"problem": _example(), "baseline": "annealing", "budget": 10}
    )
    assert response.status_code == 400
    assert "known baselines: lattice, basin_hopping" in response.json()["detail"]


def test_a_budget_outside_what_one_request_may_spend_is_refused() -> None:
    problem = _example()
    too_big = CLIENT.post(
        "/api/search", json={"problem": problem, "baseline": "lattice", "budget": 10**9}
    )
    assert too_big.status_code == 400
    assert "must not exceed" in too_big.json()["detail"]
    empty = CLIENT.post("/api/search", json={"problem": problem, "baseline": "lattice", "budget": 0})
    assert empty.status_code == 400
    assert "at least 1" in empty.json()["detail"]


def test_providers_lists_endpoints_and_never_a_key() -> None:
    """The provider table is data, and the only thing said about a key is whether it exists."""
    body = CLIENT.get("/api/providers").json()
    names = [item["name"] for item in body["providers"]]
    assert "deepseek" in names
    assert names == sorted(names)
    # A client needs the endpoint and the name of a variable, never a value.
    for item in body["providers"]:
        assert set(item) == {
            "name", "base_url", "api_key_env", "models", "note", "needs_key", "accepts_temperature",
            "subscription",
        }
    # The dialog greys the temperature out where the endpoint refuses one.
    accepts = {item["name"]: item["accepts_temperature"] for item in body["providers"]}
    assert accepts["deepseek"] is True and accepts["openai"] is False
    assert body["key_present"]["environment_key"] == "PAPER_OBS_API_KEY"
    assert set(body["key_present"]["providers"]) == set(names)


def test_workflows_lists_the_manifest_with_its_topology() -> None:
    """The interface draws a workflow from this, so the shape is part of the answer."""
    body = CLIENT.get("/api/workflows").json()
    assert [item["id"] for item in body["workflows"]] == [
        "basic_agent_loop", "strategist_executor", "parallel_exploration", "research_lab",
    ]
    manifest = body["workflows"][0]
    assert [node["id"] for node in manifest["nodes"]] == ["turn", "route"]
    assert len(manifest["edges"]) == 3
    # A turn-based loop: how many turns, and what one of them may spend.
    assert {parameter["name"] for parameter in manifest["parameters"]} == {
        "rounds",
        "reply_limit",
        "tool_limit",
        "share_reference",
        "stall_limit",
        "seconds",
    }


def test_exported_problem_can_be_validated_for_import() -> None:
    problem = _example()
    response = CLIENT.post("/api/problems/validate", json={"problem": problem})
    assert response.status_code == 200
    assert response.json() == problem

    bad = CLIENT.post("/api/problems/validate", json={"problem": {"problem_id": "broken"}})
    assert bad.status_code == 400


def test_a_workflow_lists_its_tools_as_a_model_reads_them() -> None:
    """The tool viewer draws this: what a model is sent of each tool, and where it is offered."""
    pytest.importorskip("langchain")
    body = CLIENT.get("/api/workflows/basic_agent_loop/tools").json()
    assert "maximize_total_perimeter" in body["objectives"]
    tools = {item["name"]: item for item in body["tools"]}
    place = tools["place_shapes"]
    assert len(place["description"]) >= 2
    assert all("\n" not in paragraph and "  " not in paragraph for paragraph in place["description"])
    assert place["parameters"]["required"] == ["placements"]
    assert "x" in place["parameters"]["properties"]["placements"]["items"]["properties"]
    assert set(place["objectives"]) == set(body["objectives"])
    assert tools["grow_sizes"]["objectives"] == ["maximize_total_perimeter"]
    assert CLIENT.get("/api/workflows/nope/tools").status_code == 404


def test_a_run_of_an_unknown_workflow_is_refused() -> None:
    answer = CLIENT.post("/api/agent-runs", json={"problem": _example(), "workflow": "nope"})
    assert answer.status_code == 400
    assert "unknown workflow" in answer.json()["detail"]


def test_an_unknown_run_is_a_404() -> None:
    assert CLIENT.get("/api/agent-runs/run-nope").status_code == 404


def test_a_saved_run_can_be_deleted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PAPER_OBS_RUNS", str(tmp_path))
    (tmp_path / "run-gone.json").write_text(
        json.dumps({"kind": "agent-run", "run_id": "run-gone", "workflow": "basic_agent_loop"}),
        encoding="utf-8",
    )
    assert [line["run_id"] for line in CLIENT.get("/api/agent-runs").json()["runs"]] == ["run-gone"]

    answer = CLIENT.delete("/api/agent-runs/run-gone")
    assert answer.status_code == 200
    assert answer.json()["status"] == "deleted"
    assert CLIENT.get("/api/agent-runs/run-gone").status_code == 404
    # A deleted run is still listed, marked so, for what it spent; and it can come back.
    assert [(line["run_id"], line["deleted"]) for line in CLIENT.get("/api/agent-runs").json()["runs"]] == [("run-gone", True)]
    assert CLIENT.post("/api/agent-runs/run-gone/restore").status_code == 200
    assert CLIENT.get("/api/agent-runs/run-gone").status_code == 200
    assert [line["deleted"] for line in CLIENT.get("/api/agent-runs").json()["runs"]] == [False]
    assert CLIENT.post("/api/agent-runs/run-gone/restore").status_code == 404


def test_deleting_an_unknown_run_is_a_404(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PAPER_OBS_RUNS", str(tmp_path))
    assert CLIENT.delete("/api/agent-runs/run-nope").status_code == 404


def test_an_active_run_is_refused_rather_than_deleted() -> None:
    """The process that owns a running run would write its file again on its next turn."""
    signal = Event()
    CLIENT.app.state.active_runs["run-busy"] = signal
    try:
        assert CLIENT.delete("/api/agent-runs/run-busy").status_code == 409
    finally:
        CLIENT.app.state.active_runs.pop("run-busy", None)


def test_cost_ceiling_requires_prices_before_a_run_starts() -> None:
    answer = CLIENT.post("/api/agent-runs", json={
        "problem": _example(), "workflow": "basic_agent_loop",
        "provider": "deepseek", "model": "deepseek-flash",
        "budget": {"max_cost": 0.1},
    })
    assert answer.status_code == 400
    assert "token prices" in answer.json()["detail"]


@pytest.mark.parametrize("name", ["", "   ", "a" * 101, "line\nbreak", 42])
def test_invalid_run_names_are_rejected_before_start(name: object) -> None:
    answer = CLIENT.post("/api/agent-runs", json={
        "problem": _example(), "workflow": "basic_agent_loop", "name": name,
    })
    assert answer.status_code == 400


def test_starting_a_run_answers_with_its_identifier(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A run answers at once and happens afterwards; without a key it says so and stops."""
    monkeypatch.setenv("PAPER_OBS_RUNS", str(tmp_path))
    for name in ("PAPER_OBS_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    answer = CLIENT.post(
        "/api/agent-runs",
        json={
            "problem": _example(),
            "workflow": "basic_agent_loop",
            "name": "  Essai avec nom  ",
            "provider": "deepseek",
            "model": "deepseek-flash",
            "cost_per_million_in": 0.30,
            "cost_per_million_out": 1.20,
            "budget": {"rounds": 1},
        },
    )
    assert answer.status_code == 200
    body = answer.json()
    assert body["status"] == "running"
    assert body["run_id"].startswith("run-")
    # The test client runs background tasks with the response, so the document exists.
    written = json.loads((tmp_path / f"{body['run_id']}.json").read_text(encoding="utf-8"))
    assert written["status"] == "failed"
    assert written["name"] == "Essai avec nom"
    assert "no key" in written["error"]
    # The price travels with the run and is recorded beside the model, never inside it.
    assert written["model"]["cost_per_million_in"] == pytest.approx(0.30)
    # The listing is what a watcher polls: it carries the round, the score and the spend.
    line = CLIENT.get("/api/agent-runs").json()["runs"][0]
    assert line["run_id"] == body["run_id"]
    assert line["name"] == "Essai avec nom"
    assert {"round", "spend", "seconds", "champion", "status"} <= set(line)


def test_a_run_in_its_own_process_is_going_at_once_and_ends_there(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The document says running before the process starts, and the process writes the end."""
    monkeypatch.setenv("PAPER_OBS_RUNS", str(tmp_path))
    for name in ("PAPER_OBS_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    client = TestClient(create_app(static_directory=Path("/nonexistent-frontend")))
    run_id = client.post("/api/agent-runs", json={
        "problem": _example(), "workflow": "basic_agent_loop",
        "provider": "deepseek", "model": "deepseek-flash", "budget": {"rounds": 1},
    }).json()["run_id"]
    assert client.get(f"/api/agent-runs/{run_id}").json()["status"] == "running"
    deadline = time.monotonic() + 120
    while client.get(f"/api/agent-runs/{run_id}").json()["status"] == "running":
        assert time.monotonic() < deadline, "the run's process never wrote its end"
        time.sleep(0.2)
    written = client.get(f"/api/agent-runs/{run_id}").json()
    assert written["status"] == "failed" and "no key" in written["error"]


def _covering_document() -> dict:
    """One unit square covering a unit disc, the source's first covering instance."""
    return {
        "problem_id": "sqcovcir-1",
        "name": "1 square covering a circle",
        "description": "",
        "seed": None,
        "arena": {"name": "target", "shape": {"type": "disk", "radius": 1.0}},
        "shape": {"type": "regular_polygon", "sides": 4, "side": 1.0},
        "objective": {"type": "cover_region", "count": 1},
        "rotation": {"type": "rotation_policy", "mode": "free", "angles": [0]},
        "constraints": [],
        "metadata": {},
    }


def test_the_union_path_is_drawn_only_when_the_client_asks() -> None:
    """The covering overlay is optional, and the metric beside it is not.

    The metric is part of every verdict — it describes the arrangement — while the
    union is a drawn region the client has to request. Asking for it must not
    change the verdict, and not asking must not carry a path.
    """
    problem = _covering_document()
    candidate = {
        "candidate_id": "c",
        "problem_id": problem["problem_id"],
        "scale": 2.0,
        "placements": [{"shape_id": "s000", "x": 0.0, "y": 0.0}],
    }

    without = CLIENT.post(
        "/api/evaluate", json={"problem": problem, "candidate": candidate}
    ).json()
    asked = CLIENT.post(
        "/api/evaluate",
        json={"problem": problem, "candidate": candidate, "with_union": True},
    ).json()

    assert "union" not in without["view"]
    assert asked["view"]["union"]["path"].startswith("M ")
    assert without["evaluation"]["metrics"]["covered_circle_radius"] == pytest.approx(0.5, abs=1e-6)
    assert asked["evaluation"]["metrics"]["covered_circle_radius"] == pytest.approx(0.5, abs=1e-6)
    assert asked["candidate"] == without["candidate"]


def test_a_covering_arena_is_read_only_and_the_objective_says_why() -> None:
    """The engine, not the client, decides which arenas may be edited."""
    problem = _covering_document()
    candidate = {
        "candidate_id": "c",
        "problem_id": problem["problem_id"],
        "scale": 2.0,
        "placements": [{"shape_id": "s000", "x": 0.0, "y": 0.0}],
    }

    view = CLIENT.post(
        "/api/evaluate", json={"problem": problem, "candidate": candidate}
    ).json()["view"]

    assert view["arena"]["editable"] is False
    assert view["arena"]["objective_fixed"] is True
    # The capability answer says the same before any candidate exists.
    assert CLIENT.post("/api/capabilities", json={"problem": problem}).json()["arena_fixed"] is True


def test_a_maximizing_arena_stays_editable_and_the_capability_says_so() -> None:
    """The existing behaviour is kept where the arena is only the sandbox chosen."""
    problem = _example("squares-16-in-square")
    assert problem["objective"]["type"] == "maximize_scale"

    view = CLIENT.post(
        "/api/evaluate", json={"problem": problem, "candidate": _empty_candidate(problem)}
    ).json()["view"]

    assert view["arena"]["editable"] is True
    assert view["arena"]["objective_fixed"] is False
    assert CLIENT.post("/api/capabilities", json={"problem": problem}).json()["arena_fixed"] is False
def _derived_covering(target: str = "circle", count: int = 4) -> dict:
    """Return a derived-covering problem document, as the editor would build one."""
    return {
        "problem_id": f"derived-{target}",
        "name": "",
        "description": "",
        "seed": None,
        "shape": {"type": "regular_polygon", "sides": 4, "side": 1.0},
        "objective": {"type": "maximize_covered_size", "count": count, "target": target},
        "rotation": {"type": "rotation_policy", "mode": "free", "angles": [0.0]},
        "constraints": [],
        "metadata": {},
    }


def _block_candidate(problem: dict) -> dict:
    return {
        "candidate_id": "block",
        "problem_id": problem["problem_id"],
        "scale": 1.0,
        "placements": [
            {"shape_id": f"s{index:03d}", "x": x, "y": y}
            for index, (x, y) in enumerate(
                ((-0.5, -0.5), (0.5, -0.5), (-0.5, 0.5), (0.5, 0.5))
            )
        ],
    }


def test_covering_frame_includes_copies_outside_the_measured_target() -> None:
    problem = _derived_covering("circle", count=2)
    candidate = {
        "candidate_id": "separated",
        "problem_id": problem["problem_id"],
        "scale": 1.0,
        "placements": [
            {"shape_id": "s000", "x": 0.0, "y": 0.0},
            {"shape_id": "s001", "x": 3.0, "y": 0.0},
        ],
    }
    view = CLIENT.post("/api/evaluate", json={"problem": problem, "candidate": candidate}).json()["view"]

    assert view["frame"][0] <= min(shape["bounds"][0] for shape in view["shapes"])
    assert view["frame"][2] >= max(shape["bounds"][2] for shape in view["shapes"])
    assert view["frame"][2] > view["arena"]["bounds"][2]


def test_the_derived_covering_measures_the_target_and_draws_it() -> None:
    """The panel shows the derived size and the canvas is handed the derived region."""
    problem = _derived_covering("circle")

    verdict = CLIENT.post(
        "/api/evaluate", json={"problem": problem, "candidate": _block_candidate(problem)}
    ).json()

    assert verdict["evaluation"]["valid"] is True
    assert verdict["evaluation"]["promoted_metric"] == "covered_size"
    assert verdict["evaluation"]["metrics"]["covered_size"] == pytest.approx(1.0, abs=1e-4)
    # The region the canvas draws is the measured target, not an arena the user
    # could edit: the objective owns it.
    assert verdict["view"]["arena"]["path"].startswith("M ")
    assert verdict["view"]["arena"]["editable"] is False
    assert verdict["view"]["arena"]["parts"] == []


def test_the_derived_covering_offers_fills_and_every_baseline() -> None:
    """The score is the measured covered size, which the generic runs can grow.

    The derived covering fixes its count and its scale, so the fill initialisers
    build its start; the search strategies read the same number the objective does
    and are all offered -- a basin hop's polish grows the union with translations,
    and the lattice is an honest reference for the same measure.
    """
    problem = _derived_covering()
    capabilities = CLIENT.post("/api/capabilities", json={"problem": problem}).json()

    assert "cover" not in capabilities["initialize"]
    assert "varied" not in capabilities["initialize"]
    assert "grid" in capabilities["initialize"]
    assert capabilities["search"] == CLIENT.get("/api/baselines").json()["baselines"]
    assert capabilities["arena_fixed"] is False

    # The fill the engine offers builds, at the fixed unit scale, a candidate the
    # engine judges valid: the derived covering has a start it can open on.
    started = CLIENT.post("/api/init", json={"problem": problem, "strategy": "grid"}).json()
    assert started["evaluation"]["valid"] is True
    assert len(started["candidate"]["placements"]) == 4


def test_a_search_run_on_the_derived_covering_improves_the_measured_size() -> None:
    """The run route works on the derived covering, and its verdict beats the fill."""
    problem = _derived_covering("circle", count=4)
    started = CLIENT.post("/api/init", json={"problem": problem, "strategy": "grid"}).json()
    body = CLIENT.post(
        "/api/search", json={"problem": problem, "baseline": "basin_hopping", "budget": 80}
    ).json()

    assert body["verdict"]["evaluation"]["valid"] is True
    assert body["verdict"]["evaluation"]["promoted_metric"] == "covered_size"
    assert (
        body["verdict"]["evaluation"]["score"]["primary"]
        > started["evaluation"]["score"]["primary"]
    )


def test_the_triangle_target_is_measured_like_the_other_two() -> None:
    """The largest apex-up equilateral triangle inside the union is now a real score."""
    problem = _derived_covering("triangle", count=4)

    body = CLIENT.post(
        "/api/evaluate", json={"problem": problem, "candidate": _block_candidate(problem)}
    ).json()

    assert body["evaluation"]["valid"] is True
    assert body["evaluation"]["promoted_metric"] == "covered_size"
    # The 2 x 2 block of unit squares holds the analytic side 2.
    assert body["evaluation"]["metrics"]["covered_size"] == pytest.approx(2.0, abs=1e-6)
    # The drawn region is the measured triangle, so the panel and the canvas agree.
    assert body["view"]["arena"]["path"].startswith("M ")
