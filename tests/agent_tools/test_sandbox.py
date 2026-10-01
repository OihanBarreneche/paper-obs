"""The Python sandbox: the program it runs, and what the agent's tool makes of the answer."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("langchain_core")

from paper_obs.agent_tools import sandbox  # noqa: E402
from paper_obs.agent_tools.engine import Workbench  # noqa: E402
from paper_obs.storage import load_problem  # noqa: E402

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
GRID = [{"x": -4.0 + 2 * (i % 5), "y": -4.0 + 2 * (i // 5)} for i in range(25)]


def tool(monkeypatch: pytest.MonkeyPatch, answer: dict) -> tuple[Workbench, object]:
    """Return a workbench and its sandbox tool, the sandbox answering ``answer``."""
    monkeypatch.setattr(sandbox, "run", lambda source: answer)
    bench = Workbench(problem=load_problem(EXAMPLES / "circle_25_in_square.json"))
    return bench, sandbox.sandbox_tools(bench)[0]


def test_the_program_starts_with_the_problem_and_ends_on_its_last_expression() -> None:
    code = "import math\nprint('one\\ntwo')\nside = PROBLEM['count']\nmath.sqrt(side)"
    source = sandbox.program(code, {"count": 4}, None)
    *body, last = source.splitlines()
    scope: dict = {}
    exec("\n".join(body), scope)  # the sandbox runs the same text with Pyodide
    assert eval(last, scope) == {"value": 2.0, "printed": "one\ntwo\n"}


def test_an_arrangement_the_program_returns_is_placed_and_judged(monkeypatch: pytest.MonkeyPatch) -> None:
    bench, run_python = tool(monkeypatch, {"success": True, "result": {
        "value": {"placements": GRID, "scale": 2.0}, "printed": "computed"}})
    reply = json.loads(run_python.invoke({"code": "..."}))
    assert reply["printed"] == "computed" and reply["valid"]
    assert bench.candidate is not None and bench.candidate.scale == pytest.approx(2.0)


def test_any_other_value_comes_back_with_what_was_printed(monkeypatch: pytest.MonkeyPatch) -> None:
    bench, run_python = tool(monkeypatch, {"success": True, "result": {"value": [1, 2], "printed": "hi"}})
    assert json.loads(run_python.invoke({"code": "..."})) == {"value": "[1, 2]", "printed": "hi"}
    assert bench.candidate is None


def test_a_failure_shows_the_program_s_own_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    stderr = 'Traceback:\n  File "/lib/python3.12/site-packages/_pyodide.py"\n  File "program", line 2\nNameError: x'
    _, run_python = tool(monkeypatch, {"success": False, "stderr": stderr})
    assert run_python.invoke({"code": "..."}) == 'the program failed:\n  File "program", line 2\nNameError: x'


def test_a_program_that_does_not_parse_never_reaches_the_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    _, run_python = tool(monkeypatch, {})
    assert run_python.invoke({"code": "def ("}).startswith("the program does not parse")


def test_a_program_that_runs_too_long_is_stopped_in_a_few_words(monkeypatch: pytest.MonkeyPatch) -> None:
    def slow(source: str) -> dict:
        raise subprocess.TimeoutExpired(["deno", "run", source], sandbox.SECONDS)

    _, run_python = tool(monkeypatch, {})
    monkeypatch.setattr(sandbox, "run", slow)
    # Not the command line, which carries the whole program.
    assert run_python.invoke({"code": "while True: pass"}) == (
        f"the program ran longer than {sandbox.SECONDS} seconds and was stopped")


@pytest.mark.skipif(sandbox.deno() is None, reason="Deno is not installed")
def test_the_sandbox_runs_python_and_cannot_read_the_lab() -> None:
    assert sandbox.run(sandbox.program("sum(range(5))", {}, None))["result"]["value"] == 10
    answer = sandbox.run(sandbox.program("import js\njs.Deno.readTextFileSync('pyproject.toml')", {}, None))
    assert answer["success"] is False
