"""The run document: written after every turn, readable while it is still going."""

from __future__ import annotations

import json
import os

from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import Any, Iterator

import pytest

from paper_obs.domain.problem import Problem
from paper_obs.llm.models import ModelConfig
from paper_obs.storage import load_problem
from paper_obs.workflows import runner
from paper_obs.workflows.budget import Budget, Cost

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


class _FakeGraph:
    """A workflow that answers with the states a run of two turns leaves behind."""

    def __init__(self, states: list[dict[str, Any]]) -> None:
        self.states = states

    def stream(self, state: dict[str, Any], stream_mode: str,
               config: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        assert stream_mode == "values"
        yield from self.states


@pytest.fixture(scope="module")
def problem() -> Problem:
    return load_problem(EXAMPLES / "circle_25_in_square.json")


@pytest.fixture(autouse=True)
def no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep these tests offline: with no key, a run stops before it reaches a provider."""
    for name in ("PAPER_OBS_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_a_run_that_cannot_reach_a_model_leaves_a_document_saying_so(
    problem: Problem, tmp_path: Path
) -> None:
    document = runner.run(
        problem,
        workflow="basic_agent_loop",
        config=ModelConfig(provider="deepseek", model="deepseek-chat"),
        budget=Budget(rounds=1),
        directory=tmp_path,
        run_id="run-a",
        name="Essai composite A",
    )
    assert document["kind"] == "agent-run"
    assert document["name"] == "Essai composite A"
    assert document["status"] == "failed"
    assert "no key" in document["error"]
    assert document["problem_id"] == problem.problem_id
    assert document["problem"] == problem.to_dict()
    assert (tmp_path / "run-a.json").is_file()
    # The document names the provider it was asked for, and can never hold a secret.
    assert document["model"]["provider"] == "deepseek"
    assert "api_key" not in document["model"]


def test_a_folder_of_runs_lists_them_and_ignores_what_is_not_one(
    problem: Problem, tmp_path: Path
) -> None:
    runner.run(
        problem,
        workflow="basic_agent_loop",
        config=ModelConfig(provider="deepseek", model="deepseek-chat"),
        budget=Budget(rounds=1),
        directory=tmp_path,
        run_id="run-a",
    )
    (tmp_path / "candidate.json").write_text('{"kind": "candidate"}', encoding="utf-8")
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    lines = runner.listing(tmp_path)
    assert [line["run_id"] for line in lines] == ["run-a"]
    assert lines[0]["status"] == "failed"
    assert lines[0]["champion"] is None


def test_a_listing_is_newest_first_and_dates_what_predates_the_field(tmp_path: Path) -> None:
    """A run dates itself; a document written before the field is dated by its own file."""

    def write(name: str, run_id: str, created: str | None) -> Path:
        document: dict[str, Any] = {"kind": runner.FILE_KIND, "run_id": run_id, "name": run_id}
        if created is not None:
            document["created_at"] = created
        path = tmp_path / name
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    write("run-old.json", "run-old", "2026-01-02T03:04:05+00:00")
    write("run-new.json", "run-new", "2026-06-07T08:09:10+00:00")
    undated = write("run-undated.json", "run-undated", None)
    stale = datetime(2025, 12, 31, 23, 59, tzinfo=timezone.utc).timestamp()
    os.utime(undated, (stale, stale))

    lines = runner.listing(tmp_path)
    assert [line["run_id"] for line in lines] == ["run-new", "run-old", "run-undated"]
    # The undated one carries its file's date, and reading it back fills the same field.
    assert lines[-1]["created"].startswith("2025-12-31")
    assert runner.load("run-undated", tmp_path)["created_at"] == lines[-1]["created"]
    # A run never resumed started when it was created.
    assert lines[0]["started"] == "2026-06-07T08:09:10+00:00"


def test_a_listing_says_how_far_each_run_is_from_its_record(tmp_path: Path) -> None:
    """The gap is signed by what is better, whichever way the record's unit improves."""

    def write(run_id: str, unit: str, value: float, metrics: dict[str, float]) -> None:
        verdict = {"metrics": metrics, "promoted_metric": next(iter(metrics), "")}
        step = {"accepted": True, "valid": True, "primary": 1.0, "verdict": verdict}
        document = {"kind": runner.FILE_KIND, "run_id": run_id, "created_at": f"2026-01-0{len(run_id)}",
                    "model": {"provider": "deepseek", "model": "deepseek-flash"}, "steps": [step],
                    "problem": {"metadata": {"reference": {"unit": unit, "value": value}}}}
        (tmp_path / f"{run_id}.json").write_text(json.dumps(document), encoding="utf-8")

    write("run-a", "covered radius", 1.25, {"covered_size": 1.2})
    write("run-bb", "container side", 2.0, {"container_side": 2.1})
    write("run-ccc", "a unit the engine does not measure", 3.0, {})
    lines = {line["run_id"]: line for line in runner.listing(tmp_path)}
    assert lines["run-a"]["record_gap"] == pytest.approx(-0.04)
    assert lines["run-bb"]["record_gap"] == pytest.approx(-0.05)
    assert lines["run-ccc"]["record_gap"] is None
    # The run's best is quoted in the measurement its objective promotes: the side, not one over it.
    assert lines["run-bb"]["champion"]["measure"] == pytest.approx(2.1)
    assert lines["run-ccc"]["champion"]["measure"] == pytest.approx(1.0)
    assert lines["run-a"]["provider"] == "deepseek" and lines["run-a"]["model"] == "deepseek-flash"
    assert lines["run-a"]["track"] == [[0, 1.0, pytest.approx(-0.04)]]


def test_a_run_name_is_listed_and_legacy_documents_keep_a_readable_fallback(
    problem: Problem, tmp_path: Path
) -> None:
    runner.run(
        problem, workflow="basic_agent_loop",
        config=ModelConfig(provider="deepseek", model="deepseek-chat"),
        budget=Budget(rounds=1), directory=tmp_path, run_id="run-named", name="  Variante rapide  ",
    )
    assert runner.load("run-named", tmp_path)["name"] == "Variante rapide"
    assert runner.listing(tmp_path)[0]["name"] == "Variante rapide"
    path = tmp_path / "run-named.json"
    legacy = json.loads(path.read_text(encoding="utf-8"))
    del legacy["name"]
    path.write_text(json.dumps(legacy), encoding="utf-8")
    assert runner.load("run-named", tmp_path)["name"] == legacy["workflow_name"]
    assert runner.listing(tmp_path)[0]["name"] == legacy["workflow_name"]


def test_the_folder_of_runs_follows_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(runner.RUNS_ENVIRONMENT, str(tmp_path))
    assert runner.runs_directory() == tmp_path
    monkeypatch.delenv(runner.RUNS_ENVIRONMENT)
    assert runner.runs_directory().name == "runs"

def test_a_run_writes_down_what_each_turn_reached(
    problem: Problem, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The document is the run: it is rewritten after every turn, and ends where it ended."""
    steps: list[dict[str, Any]] = [
        {"round": 0, "accepted": False, "candidate": None, "valid": False, "primary": None, "notes": [], "tools": []},
        {"round": 1, "accepted": True, "valid": True, "candidate": {"candidate_id": "c-1"}, "primary": 2.0, "notes": [], "tools": []},
    ]
    snapshots: list[dict[str, Any]] = [
        {"round": 1, "spend": Cost(llm_calls=1, tool_calls=2, seconds=0.5), "trace": steps[:1]},
        {
            "round": 2,
            "spend": Cost(llm_calls=3, tool_calls=5, seconds=1.5, tokens_in=1000, tokens_out=200),
            "trace": steps,
            "notes": ["the corner resists"],
        },
    ]
    # The graph is the seam: what is being checked is that the runner turns a state into
    # a document, not what a model would answer.
    monkeypatch.setattr(runner.registry, "build", lambda *args, **kwargs: _FakeGraph(snapshots))
    document = runner.run(
        problem,
        workflow="basic_agent_loop",
        config=ModelConfig(
            provider="deepseek",
            model="deepseek-flash",
            cost_per_million_in=0.30,
            cost_per_million_out=1.20,
        ),
        budget=Budget(rounds=2),
        api_key="not-a-real-key",
        directory=tmp_path,
        run_id="run-b",
    )
    assert document["status"] == "done"
    assert document["error"] is None
    assert document["round"] == 2
    assert document["steps"] == steps
    assert document["champion"] == {"candidate_id": "c-1"}
    # What the agent wrote down is kept: it is the only reasoning a run leaves behind.
    assert document["notes"] == ["the corner resists"]
    assert document["spend"]["llm_calls"] == 3
    assert document["spend"]["tool_calls"] == 5
    # Money is the caller's price applied to the tokens the graph counted: 1000 tokens in at
    # 0.30 a million, 200 out at 1.20, and nothing invented when no price is given.
    assert document["spend"]["cost"] == pytest.approx(0.00054)
    # What is on disk is what was returned: a reader never needs the process that wrote it.
    written = runner.load("run-b", tmp_path)
    assert written == document


def test_cost_ceiling_stops_after_the_first_measured_turn(
    problem: Problem, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshots = [
        {"round": 1, "spend": Cost(tokens_in=800_000), "trace": []},
        {"round": 2, "spend": Cost(tokens_in=1_600_000), "trace": []},
    ]
    monkeypatch.setattr(runner.registry, "build", lambda *args, **kwargs: _FakeGraph(snapshots))
    document = runner.run(
        problem, workflow="basic_agent_loop",
        config=ModelConfig(provider="deepseek", model="deepseek-flash",
                           cost_per_million_in=1.0, cost_per_million_out=0.0),
        budget=Budget(rounds=10, max_cost=0.5), api_key="not-a-real-key",
        directory=tmp_path, run_id="run-cost",
    )
    assert document["status"] == "done"
    assert document["round"] == 1
    assert document["stopped_by"] == "max_cost"
    assert document["spend"]["cost"] == pytest.approx(0.8)


def test_an_invalid_retained_draft_is_not_a_champion(
    problem: Problem, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshots = [{"round": 1, "trace": [{"round": 0, "accepted": True,
                                           "valid": False, "primary": 0.8,
                                           "candidate": {"candidate_id": "invalid"}}]}]
    monkeypatch.setattr(runner.registry, "build", lambda *args, **kwargs: _FakeGraph(snapshots))
    document = runner.run(
        problem, workflow="basic_agent_loop",
        config=ModelConfig(provider="deepseek", model="deepseek-flash"),
        budget=Budget(rounds=1), api_key="not-a-real-key",
        directory=tmp_path, run_id="run-invalid",
    )
    assert document["champion"] is None
    assert runner.listing(tmp_path)[0]["champion"] is None


def test_user_stop_keeps_the_completed_turn(problem: Problem, tmp_path: Path,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    signal = Event()

    class StoppingGraph:
        def stream(self, state: dict[str, Any], stream_mode: str,
               config: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
            signal.set()
            yield {"round": 1, "spend": Cost(llm_calls=1),
                   "trace": [{"round": 0, "accepted": True, "valid": True, "primary": 2.0,
                              "candidate": {"candidate_id": "c"}}]}
            yield {"round": 2, "spend": Cost(llm_calls=2), "trace": []}

    monkeypatch.setattr(runner.registry, "build", lambda *args, **kwargs: StoppingGraph())
    document = runner.run(
        problem, workflow="basic_agent_loop",
        config=ModelConfig(provider="deepseek", model="deepseek-flash"),
        budget=Budget(rounds=10), api_key="not-a-real-key", directory=tmp_path,
        run_id="run-stop", stop_requested=signal,
    )
    assert document["status"] == "stopped"
    assert document["stopped_by"] == "user"
    assert document["round"] == 1
    assert document["champion"] == {"candidate_id": "c"}
    line = runner.listing(tmp_path)[0]
    assert line["champion"] == {"valid": True, "primary": 2.0, "measure": 2.0}


def test_a_run_left_going_by_a_stopped_lab_is_closed(tmp_path: Path) -> None:
    """Nothing else can finish a run, so a stale document is closed when the lab starts."""
    live = {"kind": runner.FILE_KIND, "run_id": "run-live", "status": "running"}
    (tmp_path / "run-live.json").write_text(json.dumps(live), encoding="utf-8")
    (tmp_path / "candidate.json").write_text('{"kind": "candidate"}', encoding="utf-8")

    assert runner.close_orphans(tmp_path) == ["run-live"]
    closed = runner.load("run-live", tmp_path)
    assert closed["status"] == "failed"
    assert closed["error"] == runner.ORPHAN_ERROR
    # A run that ended is left alone, and a document that is not a run is not touched.
    assert runner.close_orphans(tmp_path) == []
    assert json.loads((tmp_path / "candidate.json").read_text(encoding="utf-8")) == {
        "kind": "candidate"
    }


def test_legacy_run_loads_without_new_optional_fields(tmp_path: Path) -> None:
    legacy = {"kind": runner.FILE_KIND, "steps": [{"round": 0}], "status": "done"}
    (tmp_path / "run-old.json").write_text(json.dumps(legacy), encoding="utf-8")

    loaded = runner.load("run-old", tmp_path)

    assert loaded["notes"] == []
    assert loaded["settings"] == {}
    assert loaded["steps"][0]["notes"] == []
    assert loaded["steps"][0]["tools"] == []
    assert json.loads((tmp_path / "run-old.json").read_text(encoding="utf-8")) == legacy


def test_a_resumed_run_goes_on_in_its_own_document_from_what_it_kept(
    problem: Problem, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The graph starts from the kept best, the journal and the notes; spending adds up."""
    from paper_obs.search.operators import grid_initialize

    best = grid_initialize(problem).to_dict()
    first = [{"round": 0, "accepted": True, "valid": True, "candidate": best, "notes": [], "tools": []}]
    monkeypatch.setattr(runner.registry, "build", lambda *args, **kwargs: _FakeGraph([
        {"round": 1, "spend": Cost(llm_calls=2, tokens_in=1000), "trace": first, "notes": ["grid"]},
    ]))
    config = ModelConfig(provider="deepseek", model="deepseek-flash",
                         cost_per_million_in=1.0, cost_per_million_out=1.0)
    runner.run(problem, workflow="basic_agent_loop", config=config, budget=Budget(rounds=1),
               api_key="not-a-real-key", directory=tmp_path, run_id="run-r")

    seen: dict[str, Any] = {}

    class Resumed(_FakeGraph):
        def stream(self, state: dict[str, Any], stream_mode: str,
                   config: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
            seen["state"] = state
            yield from super().stream(state, stream_mode, config)

    def build(*args: Any, **kwargs: Any) -> _FakeGraph:
        seen["start"], seen["budget"] = kwargs["start"], args[3]
        second = [*first, {**first[0], "round": 1, "accepted": False}]
        return Resumed([{"round": 2, "spend": Cost(llm_calls=3, tokens_in=500), "trace": second,
                         "notes": ["grid"]}])

    monkeypatch.setattr(runner.registry, "build", build)
    document = runner.resume("run-r", config=config, budget=Budget(rounds=1, max_cost=0.01),
                             api_key="not-a-real-key", directory=tmp_path)

    assert seen["start"].to_dict() == best
    assert seen["state"]["round"] == 1 and seen["state"]["notes"] == ["grid"]
    assert len(seen["state"]["trace"]) == 1
    # The graph counts turns from the start of the run, the rest from the resumption.
    assert seen["budget"].rounds == 2 and seen["budget"].max_cost == pytest.approx(0.01)
    assert document["run_id"] == "run-r" and document["status"] == "done"
    assert document["round"] == 2 and len(document["steps"]) == 2
    assert document["spend"]["llm_calls"] == 5
    assert document["spend"]["cost"] == pytest.approx(0.0015)
    assert document["budget"]["max_cost"] == pytest.approx(0.011)
    assert [item["round"] for item in document["resumed"]] == [1]
    # The listing times a resumed run from its resumption.
    assert runner.listing(tmp_path)[0]["started"] == document["resumed"][-1]["at"]
