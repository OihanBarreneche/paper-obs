"""A Python sandbox as an agent tool: the agent writes a program, the engine judges its result.

The program runs in Pyodide — CPython compiled to WebAssembly — inside Deno, through LangChain's
sandbox runner (``jsr:@langchain/pyodide-sandbox``). Deno grants it nothing but its own package
cache and the hosts packages are downloaded from: it cannot read the lab's files, start a
process or reach any other address. LangChain's Python wrapper of that runner is archived and
pins an older LangChain, so the lab calls the runner itself.

Deno is looked up on the ``PATH``, then in ``.sandbox/deno/bin`` beside the runs folder, where
the documentation installs it. Pyodide and the packages a program imports are downloaded into
``.sandbox`` on first use.
"""

from __future__ import annotations

import ast
import base64
import json
import os
import shutil
import subprocess
import threading
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, tool

from .engine import Workbench, engine_tools, problem_facts

#: LangChain's runner: Pyodide in Deno, with the program's imports installed on the way.
RUNNER = "jsr:@langchain/pyodide-sandbox@0.0.4"

#: The only hosts a program's packages come from: Pyodide's own builds, and PyPI for the rest.
HOSTS = "cdn.jsdelivr.net,pypi.org,files.pythonhosted.org"

#: Longest a program may run, in seconds; the first run also downloads Pyodide.
SECONDS = 120

#: Longest printed text or value a reply carries back to the model, in characters.
SHOWN = 3000

#: The first run downloads into the cache; runs that start meanwhile wait rather than race it.
_first = threading.Lock()
_warm = False


def home() -> Path:
    """Return the sandbox's folder: its Deno, its cache and Pyodide."""
    return Path(os.environ.get("PAPER_OBS_SANDBOX") or Path.cwd() / ".sandbox")


def deno() -> str | None:
    """Return the Deno executable, or None when it is not installed."""
    local = home() / "deno" / "bin" / "deno"
    return shutil.which("deno") or (str(local) if local.is_file() else None)


def program(code: str, problem: dict[str, Any], current: dict[str, Any] | None) -> str:
    """Wrap the agent's code so that it reads the problem and returns its value and what it printed.

    The runner joins printed lines without their line breaks, so printing is captured here. The
    code's own imports are repeated at the top, where the runner looks for packages to install.
    The runner also turns every ``\\n`` it is handed into a line break, so text travels in base64.
    Raises SyntaxError, which the tool reports without starting the sandbox.
    """
    tree = ast.parse(code)
    imports = [ast.unparse(node) for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    # The last expression is the program's value; the lines before it keep their numbers, so an
    # error names the line the agent wrote.
    end = tree.body[-1] if tree.body else None
    last = end if isinstance(end, ast.Expr) and end.col_offset == 0 else None
    body = code if last is None else "\n".join(code.splitlines()[:last.lineno - 1])
    value = "" if last is None else ast.get_source_segment(code, last) or ""
    packed = lambda text: f"_text({base64.b64encode(text.encode()).decode()!r})"  # noqa: E731
    return "\n".join([
        *imports,
        "import base64 as _base64, contextlib as _contextlib, io as _io, json as _json",
        "_text = lambda packed: _base64.b64decode(packed).decode()",
        f"PROBLEM = _json.loads({packed(json.dumps(problem))})",
        f"CURRENT = _json.loads({packed(json.dumps(current))})",
        "_scope = {'PROBLEM': PROBLEM, 'CURRENT': CURRENT, '__name__': '__main__'}",
        "_printed = _io.StringIO()",
        "with _contextlib.redirect_stdout(_printed):",
        f"    exec(compile({packed(body)}, 'program', 'exec'), _scope)",
        f"    _value = eval(compile({packed(value)}, 'program', 'eval'), _scope) if {bool(value)} else None",
        "{'value': _value, 'printed': _printed.getvalue()}",
    ])


def run(source: str) -> dict[str, Any]:
    """Run a program in the sandbox and return the runner's answer: success, result, stderr."""
    global _warm
    executable = deno()
    if executable is None:
        raise FileNotFoundError("the Python sandbox needs Deno: see docs/strategies-and-runs.md")
    folder = home()
    folder.mkdir(parents=True, exist_ok=True)
    command = [
        executable, "run", "--quiet", "--node-modules-dir=auto",
        "--allow-read=node_modules", "--allow-write=node_modules", f"--allow-net={HOSTS}",
        RUNNER, "-c", source,
    ]
    environment = {**os.environ, "DENO_DIR": str(folder / "cache"), "NO_COLOR": "1"}
    with _first if not _warm else nullcontext():
        done = subprocess.run(command, cwd=folder, env=environment, capture_output=True, text=True,
                              timeout=SECONDS, check=False)
        answer = _answer(done.stdout)
        _warm = _warm or answer.get("success") is True
    if not answer:
        raise RuntimeError((done.stderr or "the sandbox gave no answer").strip()[-SHOWN:])
    return answer


def _answer(stdout: str) -> dict[str, Any]:
    """Return the runner's JSON answer, its last line of output, or an empty dict."""
    for line in reversed(stdout.strip().splitlines()):
        try:
            found = json.loads(line)
        except ValueError:
            continue
        if isinstance(found, dict):
            return found
    return {}


def _cut(text: str) -> str:
    return text if len(text) <= SHOWN else text[:SHOWN] + " […]"


def sandbox_tools(bench: Workbench) -> list[BaseTool]:
    """Return the sandbox tool, bound to the run's working arrangement."""
    place = next(item for item in engine_tools(bench) if item.name == "place_shapes")

    @tool
    def run_python(code: str) -> str:
        """Run a Python program in an isolated sandbox, to compute rather than guess.

        numpy, math and the standard library are available. The program starts with PROBLEM,
        what the engine says of the problem, and CURRENT, the arrangement under work (its scale
        and placements) or None. It cannot read files, reach the network or judge anything:
        only the engine can.

        End the program with an expression. An arrangement, {'placements': [{'x', 'y',
        'rotation'}, ...], 'scale': optional}, is placed and judged as place_shapes would;
        any other value comes back with what the program printed. Each run starts afresh and
        takes a few seconds.
        """
        current = None if bench.candidate is None else {
            "scale": bench.candidate.scale,
            "placements": [{"shape_id": item.shape_id, "x": item.x, "y": item.y, "rotation": item.rotation,
                            **({} if item.scale is None else {"size": item.scale})}
                           for item in bench.candidate.placements],
        }
        try:
            answer = run(program(code, problem_facts(bench.problem), current))
        except SyntaxError as error:
            return f"the program does not parse: {error}"
        except subprocess.TimeoutExpired:
            return f"the program ran longer than {SECONDS} seconds and was stopped"
        except (OSError, RuntimeError) as error:
            return f"the sandbox could not run the program: {error}"
        if answer.get("success") is not True:
            # The sandbox's own frames come first; the agent's start at its program.
            lines = str(answer.get("stderr") or "").strip().splitlines()
            own = next((index for index, line in enumerate(lines) if 'File "program"' in line), max(0, len(lines) - 3))
            return "the program failed:\n" + _cut("\n".join(lines[own:]))
        result = answer.get("result") or {}
        value, printed = result.get("value"), _cut(str(result.get("printed") or ""))
        if isinstance(value, dict) and isinstance(value.get("placements"), list):
            arguments = {"placements": value["placements"]}
            if value.get("scale") is not None:
                arguments["scale"] = value["scale"]
            try:
                reply = place.invoke(arguments)
            except ValueError as error:  # an arrangement the tool's schema refuses
                return json.dumps({"refused": str(error), "printed": printed}, ensure_ascii=False)
            try:
                return json.dumps({**json.loads(reply), "printed": printed}, ensure_ascii=False)
            except ValueError:
                return json.dumps({"refused": reply, "printed": printed}, ensure_ascii=False)
        return json.dumps({"value": _cut(json.dumps(value, ensure_ascii=False, default=str)), "printed": printed},
                          ensure_ascii=False)

    return [run_python]


__all__ = ["RUNNER", "deno", "home", "program", "run", "sandbox_tools"]
