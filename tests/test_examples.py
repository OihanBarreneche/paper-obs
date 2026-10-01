"""Shipped example runs: copied once into the runs folder, listed as examples, never resumed."""

from __future__ import annotations

import json

import pytest

from paper_obs import examples
from paper_obs.llm.models import ModelConfig
from paper_obs.workflows import runner


def test_every_shipped_example_is_a_finished_run_marked_as_one() -> None:
    shipped = sorted((examples.EXAMPLES / "runs").glob("*.json"))
    assert len(shipped) == 4
    documents = [json.loads(path.read_text(encoding="utf-8")) for path in shipped]
    assert {document["workflow"] for document in documents} == {
        "basic_agent_loop", "strategist_executor", "parallel_exploration", "research_lab"}
    for path, document in zip(shipped, documents):
        assert document["example"] is True and document["status"] == "done"
        assert document["run_id"] == path.stem and document["kind"] == runner.FILE_KIND


def test_examples_are_copied_once_and_a_deleted_one_stays_deleted(tmp_path) -> None:
    runs = tmp_path / "runs"
    first = examples.seed(runs)
    assert len(first) >= 4
    lines = runner.listing(runs)
    assert lines and all(line["example"] for line in lines)

    removed = lines[0]["run_id"]
    runner.delete(removed, runs)
    (runs / runner.DELETED / f"{removed}.json").unlink()
    assert examples.seed(runs) == []
    assert removed not in {line["run_id"] for line in runner.listing(runs)}


def test_an_example_cannot_be_resumed(tmp_path) -> None:
    runs = tmp_path / "runs"
    examples.seed(runs)
    run_id = runner.listing(runs)[0]["run_id"]
    with pytest.raises(ValueError, match="example"):
        runner.reopen(run_id, config=ModelConfig(provider="deepseek", model="deepseek-flash"), directory=runs)
