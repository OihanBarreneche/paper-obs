"""A key is spent on one run and reaches nothing else.

The owner wants a guarantee he can publish, so these tests hold the lab to it from the
outside: start a run carrying a sentinel key, then look for that sentinel everywhere a run
can leave something — every file of the runs folder, the document the API serves back, the
provider catalogue, the log records written while it runs, and, as a last line of defence,
the whole checkout.

No provider is ever reached: the chat factory is replaced by a fake, and the graph by a
stub, so what is under test is the path between a key arriving in a request and a run
document leaving, not a network call.
"""

from __future__ import annotations

import json
import logging
import os

from pathlib import Path
from typing import Any, Iterator

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from paper_obs.api import create_app  # noqa: E402
from paper_obs.llm import chat  # noqa: E402
from paper_obs.workflows import runner  # noqa: E402
from paper_obs.workflows.budget import Cost  # noqa: E402

#: A key with a recognisable prefix, so the shape rule and the exact rule can both be seen.
SENTINEL = "sk-SENTINEL-DO-NOT-PERSIST-0001"

FRONTEND = Path("/nonexistent-frontend")

#: Parts of the checkout that hold no source and would make the sentinel scan crawl.
SKIPPED_PARTS = {".git", ".venv", ".venv-win", ".uv-cache", "node_modules", "dist", "__pycache__"}


class _FakeGraph:
    """A workflow that answers with the states a run of one turn leaves behind."""

    def __init__(self, snapshots: list[dict[str, Any]]) -> None:
        self.snapshots = snapshots

    def stream(self, state: dict[str, Any], stream_mode: str,
               config: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        assert stream_mode == "values"
        yield from self.snapshots


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(static_directory=FRONTEND, processes=False))


@pytest.fixture
def runs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the runner at a folder of this test's own, emptied between runs."""
    monkeypatch.setenv(runner.RUNS_ENVIRONMENT, str(tmp_path))
    return tmp_path


def _problem(client: TestClient) -> dict:
    return client.get("/api/examples/circle-25-in-square").json()["problem"]


def _request(problem: dict, **overrides: Any) -> dict:
    body: dict[str, Any] = {
        "problem": problem,
        "workflow": "basic_agent_loop",
        "provider": "deepseek",
        "model": "deepseek-flash",
        "api_key": SENTINEL,
        "budget": {"rounds": 1},
    }
    body.update(overrides)
    return body


def _assert_sentinel_absent_from_folder(folder: Path) -> None:
    """Every file the run wrote, read as text, must be free of the sentinel."""
    assert list(folder.glob("*.json")), "the run wrote no document, so this test proves nothing"
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        assert SENTINEL not in path.read_text(encoding="utf-8", errors="replace"), path


def test_a_run_carrying_a_key_persists_it_nowhere(
    client: TestClient, runs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A whole successful run: the key is used, and no artefact repeats it."""
    quoted = f"the agent quoted Bearer {SENTINEL} back at us"
    steps = [
        {
            "round": 1,
            "accepted": True,
            "valid": True,
            "primary": 2.0,
            "candidate": {"candidate_id": "c-1"},
            "notes": [quoted],
            "tools": [{"name": "evaluate", "reply": quoted}],
        }
    ]
    snapshots = [{"round": 1, "spend": Cost(llm_calls=1, tool_calls=1), "trace": steps, "notes": [quoted]}]

    def fake_chat_model(config: Any, *, api_key: str | None = None) -> Any:
        assert api_key == SENTINEL, "the request's key is what the client is handed"
        return object()

    monkeypatch.setattr(chat, "chat_model", fake_chat_model)
    monkeypatch.setattr(runner.registry, "build", lambda *args, **kwargs: _FakeGraph(snapshots))

    answer = client.post("/api/agent-runs", json=_request(_problem(client), name="Privacy A"))
    assert answer.status_code == 200
    run_id = answer.json()["run_id"]

    # Every file under the runs folder, the document the API serves back, and the catalogue.
    _assert_sentinel_absent_from_folder(runs)
    served = client.get(f"/api/agent-runs/{run_id}")
    assert served.status_code == 200
    assert SENTINEL not in served.text
    assert SENTINEL not in client.get("/api/providers").text

    # The note and the tool reply survive, redacted rather than dropped: what the agent
    # wrote down is still readable, and the key is not in it.
    stored = runner.load(run_id, runs)
    assert stored["status"] == "done"
    assert stored["notes"] == [quoted.replace(SENTINEL, "[redacted]")]
    assert SENTINEL not in json.dumps(stored)


def test_an_exception_that_quotes_the_key_is_stored_redacted(
    client: TestClient, runs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure path: a provider error that echoes the header must not be filed as is."""

    def exploding_chat_model(config: Any, *, api_key: str | None = None) -> Any:
        raise RuntimeError(f"provider refused the request: Bearer {api_key}")

    monkeypatch.setattr(chat, "chat_model", exploding_chat_model)

    answer = client.post("/api/agent-runs", json=_request(_problem(client), name="Privacy B"))
    assert answer.status_code == 200
    run_id = answer.json()["run_id"]

    stored = json.loads((runs / f"{run_id}.json").read_text(encoding="utf-8"))
    assert stored["status"] == "failed"
    assert SENTINEL not in json.dumps(stored)
    assert "[redacted]" in stored["error"]

    _assert_sentinel_absent_from_folder(runs)
    served = client.get(f"/api/agent-runs/{run_id}")
    assert SENTINEL not in served.text
    assert SENTINEL not in client.get("/api/providers").text


def test_a_key_logged_during_a_run_cannot_reach_a_handler(
    client: TestClient, runs: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A library logging a header, inline or through a placeholder, is scrubbed at the record."""

    def logging_chat_model(config: Any, *, api_key: str | None = None) -> Any:
        logging.getLogger("paper_obs.test").warning("Bearer %s", api_key)
        logging.getLogger("paper_obs.test").warning("the run used " + str(api_key))
        return object()

    monkeypatch.setattr(chat, "chat_model", logging_chat_model)
    monkeypatch.setattr(runner.registry, "build", lambda *args, **kwargs: _FakeGraph([]))

    with caplog.at_level(logging.DEBUG):
        answer = client.post("/api/agent-runs", json=_request(_problem(client), name="Privacy C"))

    assert answer.status_code == 200
    assert SENTINEL not in caplog.text
    assert "[redacted]" in caplog.text, "the scrubber must rewrite the record, not drop it"


def test_a_key_cannot_be_smuggled_through_the_workflow_settings(
    client: TestClient, runs: Path
) -> None:
    """A field the manifest does not declare is refused before any run document exists."""
    answer = client.post(
        "/api/agent-runs",
        json=_request(_problem(client), budget={"rounds": 1, "api_key": SENTINEL}),
    )
    assert answer.status_code == 400
    assert "unknown workflow parameter" in answer.json()["detail"]
    assert SENTINEL not in answer.text
    assert list(runs.glob("*.json")) == []


def test_the_discovery_route_returns_ids_and_never_the_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Discovery is the one route that forwards a key to a third party; it answers with ids."""
    import paper_obs.api.app as app_module

    seen: list[tuple[str, str]] = []

    def fake_models_for(config: Any, *, api_key: str) -> list[str]:
        seen.append((config.provider, api_key))
        return ["m-1", "m-2"]

    monkeypatch.setattr(app_module, "models_for", fake_models_for)
    answer = client.post(
        "/api/providers/models", json={"provider": "openai", "api_key": SENTINEL}
    )
    assert answer.status_code == 200
    assert answer.json() == {"provider": "openai", "models": ["m-1", "m-2"]}
    assert SENTINEL not in answer.text
    assert seen == [("openai", SENTINEL)]


def test_a_failing_discovery_does_not_echo_the_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even the endpoint's own error message is redacted before it is returned."""
    import paper_obs.api.app as app_module

    def exploding_models_for(config: Any, *, api_key: str) -> list[str]:
        raise OSError(f"the endpoint answered 401 to Bearer {api_key}")

    monkeypatch.setattr(app_module, "models_for", exploding_models_for)
    answer = client.post(
        "/api/providers/models", json={"provider": "openai", "api_key": SENTINEL}
    )
    assert answer.status_code == 502
    assert SENTINEL not in answer.text
    assert "[redacted]" in answer.json()["detail"]


def test_discovery_without_a_key_asks_the_endpoint_and_explains_a_refusal(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Some catalogues answer without a key; one that refuses is told apart from an outage."""
    import urllib.error

    import paper_obs.api.app as app_module

    for name in ("PAPER_OBS_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    seen: list[str] = []

    def public_catalogue(config: Any, *, api_key: str) -> list[str]:
        seen.append(api_key)
        if config.provider == "openai":
            raise urllib.error.HTTPError("https://example.invalid/models", 401, "Unauthorized", {}, None)
        return ["owner/model"]

    monkeypatch.setattr(app_module, "models_for", public_catalogue)
    answer = client.post("/api/providers/models", json={"provider": "openrouter"})
    assert answer.status_code == 200 and answer.json()["models"] == ["owner/model"]
    refused = client.post("/api/providers/models", json={"provider": "openai"})
    assert refused.status_code == 502
    assert "only with a key" in refused.json()["detail"]
    assert seen == ["", ""]


def test_the_sentinel_appears_nowhere_in_the_checkout() -> None:
    """The last line of defence: if a leak was committed to a file, this finds it.

    The test file itself is the one place the sentinel is allowed to exist; it is the
    string the other tests inject, so excluding it is what makes the scan meaningful.
    """
    root = Path(__file__).resolve().parents[2]
    here = Path(__file__).resolve()
    offenders: list[str] = []
    # os.walk with a pruned directory list, not rglob: the walk must never descend into
    # .venv or node_modules, both of which sit inside the checkout and are enormous.
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if name not in SKIPPED_PARTS)
        for name in sorted(filenames):
            path = Path(directory) / name
            if path.resolve() == here:
                continue
            try:
                if path.stat().st_size > 5_000_000:
                    continue
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if SENTINEL in text:
                offenders.append(str(path.relative_to(root)))
    assert offenders == []
