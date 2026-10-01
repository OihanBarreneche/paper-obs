"""The manual contact request keeps the JSON verdict contract intact."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from paper_obs.api import create_app  # noqa: E402
from paper_obs.domain import Arena, Candidate, Circle, MaximizeCount, Placement, Problem  # noqa: E402


def test_evaluate_can_finish_a_manual_drag_at_the_wall() -> None:
    problem = Problem(
        problem_id="contact-api", arena=Arena.rectangle(10, 10),
        shape=Circle(), objective=MaximizeCount(scale=1),
    )
    candidate = Candidate(
        candidate_id="drag", problem_id=problem.problem_id, scale=1,
        placements=(Placement("s0", 4.485, 0),),
    )
    client = TestClient(create_app(static_directory=Path("/nonexistent-frontend")))
    body = {
        "problem": problem.to_dict(), "candidate": candidate.to_dict(),
        "snap_shape_ids": ["s0"], "snap_distance": 0.02,
        "snap_motion": [0.3, 0],
    }
    result = client.post("/api/evaluate", json=body)
    assert result.status_code == 200
    verdict = result.json()
    assert verdict["candidate"]["placements"][0]["x"] == pytest.approx(4.5)
    assert verdict["evaluation"]["valid"]
    assert verdict["view"]["shapes"][0]["center"][0] == pytest.approx(4.5)
