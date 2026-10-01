"""Command-line entry point: the lab without a user interface.

Everything the UI will do to a *single* problem and a *single* candidate is
available here first, because a command is the cheapest way to make the engine
usable, testable and scriptable. A run is then reproducible with a shell line
rather than a screenshot.

``validate`` and ``evaluate`` exit with status 1 on an invalid candidate, so a
script can use them as a gate without parsing the output.
"""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
import webbrowser
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from paper_obs import __version__
from paper_obs import research as research_sessions
from paper_obs.domain import (
    ARENA_FAMILIES,
    ROTATION_MODES,
    PALETTE,
    GeneratorSpec,
    generate,
)
from paper_obs.domain.candidate import Candidate
from paper_obs.domain.serde import dump
from paper_obs.geometry.bounds import scale_bounds
from paper_obs.geometry.engine import Evaluation, analyze, evaluate, validate
from paper_obs.geometry.rendering import RenderOptions, render_svg
from paper_obs.geometry.validation import Validation
from paper_obs.search import BASELINES, Convergence, Step, convergence_svg
from paper_obs.search.operators.initialization import (
    cover_initialize,
    grid_initialize,
    random_initialize,
    staggered_initialize,
    varied_initialize,
)
from paper_obs.storage.files import (
    load_candidate,
    load_problem,
    save_candidate,
    save_problem,
)

#: Port the interface is served on when nothing else holds it.
DEFAULT_PORT = 8000

#: Engine evaluations a ``search`` run is allowed when the caller does not say.
DEFAULT_BUDGET = 200

#: Rows the curve of a run is printed with: enough to read it without a file, few
#: enough that three baselines stay on one screen.
CURVE_ROWS = 10

INITIALIZERS: dict[str, Callable[..., Candidate]] = {
    "grid": grid_initialize,
    "staggered": staggered_initialize,
    "random": random_initialize,
    "varied": varied_initialize,
    "cover": cover_initialize,
}


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line and return the process exit status.

    ``0`` on success, ``1`` when the candidate is invalid, ``2`` when the
    command itself could not run: a missing file, a malformed document, or a
    candidate that belongs to another problem.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


def _build_parser() -> argparse.ArgumentParser:
    """Return the argument parser with every sub-command registered."""
    parser = argparse.ArgumentParser(
        prog="paper-obs",
        description="Explore 2D packing problems: validate, score, render, initialize.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    info = subparsers.add_parser("info", help="describe a problem file")
    info.add_argument("--problem", "-p", required=True, type=Path)
    info.set_defaults(handler=_cmd_info)

    generate_cmd = subparsers.add_parser("generate", help="draw a problem from a seed")
    generate_cmd.add_argument("--seed", type=int, required=True, help="the number that names the instance")
    generate_cmd.add_argument(
        "--arena",
        action="append",
        choices=ARENA_FAMILIES,
        help="arena family to draw from, repeatable (default: every family)",
    )
    generate_cmd.add_argument(
        "--shape",
        action="append",
        choices=sorted(name for name, *_ in PALETTE),
        help="shape family to draw from, repeatable (default: every family)",
    )
    generate_cmd.add_argument(
        "--counts",
        type=int,
        nargs=2,
        default=None,
        metavar=("LOW", "HIGH"),
        help="range of the demanded shape count, bounds included (default: 4 to 40)",
    )
    generate_cmd.add_argument(
        "--rotation",
        action="append",
        choices=ROTATION_MODES,
        help="rotation policy to draw from, repeatable (default: fixed)",
    )
    generate_cmd.add_argument(
        "--objective",
        choices=("maximize_scale", "maximize_count"),
        default=None,
        help="what the problem maximises (default: maximize_scale)",
    )
    generate_cmd.add_argument("--prefix", default=None, help="prefix of the produced identifier")
    generate_cmd.add_argument(
        "--out",
        "-o",
        required=True,
        type=Path,
        help="where to write the problem: a .json path is the file, anything else is a directory",
    )
    generate_cmd.set_defaults(handler=_cmd_generate)

    init = subparsers.add_parser("init", help="build a starting candidate with an initialization operator")
    init.add_argument("--problem", "-p", required=True, type=Path)
    init.add_argument("--strategy", "-s", default="grid", choices=sorted(INITIALIZERS))
    init.add_argument("--scale", type=float, default=None, help="common scale, defaults to the tightest lattice")
    init.add_argument("--count", type=int, default=None, help="number of shapes, defaults to the objective")
    init.add_argument("--out", "-o", required=True, type=Path, help="where to write the candidate JSON")
    init.add_argument("--svg", type=Path, default=None, help="also render the candidate")
    init.set_defaults(handler=_cmd_init)

    validate_cmd = subparsers.add_parser("validate", help="check a candidate against its problem")
    _add_problem_candidate(validate_cmd)
    validate_cmd.set_defaults(handler=_cmd_validate)

    evaluate_cmd = subparsers.add_parser("evaluate", help="score a candidate and list its metrics")
    _add_problem_candidate(evaluate_cmd)
    evaluate_cmd.add_argument("--json", type=Path, default=None, help="also write the evaluation as JSON")
    evaluate_cmd.add_argument("--svg", type=Path, default=None, help="also render the candidate")
    evaluate_cmd.add_argument("--voids", action="store_true", help="draw the empty regions")
    evaluate_cmd.set_defaults(handler=_cmd_evaluate)

    render = subparsers.add_parser("render", help="write the SVG picture of a candidate")
    _add_problem_candidate(render)
    render.add_argument("--out", "-o", required=True, type=Path)
    render.add_argument("--width", type=int, default=900)
    render.add_argument("--ids", action="store_true", help="label every shape")
    render.add_argument("--centers", action="store_true", help="mark every shape centre")
    render.add_argument("--voids", action="store_true", help="outline the empty regions")
    render.add_argument("--no-violations", action="store_true", help="do not highlight invalid shapes")
    render.set_defaults(handler=_cmd_render)

    analysis = subparsers.add_parser("analyze", help="read the empty regions of a candidate")
    _add_problem_candidate(analysis)
    analysis.add_argument("--void-limit", type=int, default=5)
    analysis.set_defaults(handler=_cmd_analyze)

    search = subparsers.add_parser("search", help="run baselines on a problem and print their curves")
    search.add_argument("--problem", "-p", required=True, type=Path)
    search.add_argument(
        "--baseline",
        "-b",
        action="append",
        choices=sorted(BASELINES),
        help="strategy to run, repeatable (default: every baseline)",
    )
    search.add_argument(
        "--budget", type=int, default=DEFAULT_BUDGET, help="engine evaluations per baseline"
    )
    search.add_argument("--seed", type=int, default=None, help="defaults to the problem's seed")
    search.add_argument(
        "--json",
        type=Path,
        default=None,
        help="also write each run: a .json path is the file, anything else is a directory",
    )
    search.add_argument(
        "--svg",
        type=Path,
        default=None,
        help="also chart each run: a .svg path is the file, anything else is a directory",
    )
    search.set_defaults(handler=_cmd_search)

    _add_research(subparsers)

    serve = subparsers.add_parser("serve", help="run the web interface (needs the 'api' extra)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT, help="a busy port is replaced by a free one")
    serve.add_argument("--reload", action="store_true", help="restart when a Python file changes")
    serve.add_argument("--no-open", dest="open_browser", action="store_false", help="do not open a browser")
    serve.set_defaults(handler=_cmd_serve, open_browser=True)

    return parser


def _add_research(subparsers: Any) -> None:
    """Register ``research``: the free sessions of docs/research-mode.md, answered in JSON."""
    research = subparsers.add_parser("research", help="free research sessions: an agent searches, the lab judges and logs")
    actions = research.add_subparsers(dest="action", required=True)
    problem = actions.add_parser("problem", help="write a catalog problem with its published record")
    problem.add_argument("slug", help="catalog family, such as squintri")
    problem.add_argument("count", type=int)
    problem.add_argument("--out", "-o", type=Path, default=None, help="default: print it")
    start = actions.add_parser("start", help="open a session on a problem file")
    start.add_argument("--problem", "-p", required=True, type=Path)
    start.add_argument("--name", required=True)
    start.add_argument("--agent", required=True, help="who searches, such as 'Claude Code · Opus 5.5'")
    start.add_argument("--goal", default="")
    submit = actions.add_parser("submit", help="have the engine judge an arrangement and log it")
    submit.add_argument("session")
    submit.add_argument("--candidate", "-c", required=True, type=Path)
    submit.add_argument("--note", default="")
    note = actions.add_parser("note", help="append a note to a session's journal")
    note.add_argument("session")
    note.add_argument("text")
    status = actions.add_parser("status", help="print a session's best and record, or set its status")
    status.add_argument("session")
    status.add_argument("--set", dest="new_status", choices=research_sessions.STATUSES, default=None)
    listing = actions.add_parser("list", help="list the sessions, newest first")
    listing.add_argument("--problem-id", default=None)
    research.set_defaults(handler=_cmd_research)


def _cmd_research(args: argparse.Namespace) -> int:
    """Run one research action and print its answer as JSON; an invalid submission exits 1."""
    answer: Any
    if args.action == "problem":
        problem = research_sessions.catalog_problem(args.slug, args.count)
        if args.out is None:
            print(json.dumps(problem.to_dict(), indent=2, ensure_ascii=False))
            return 0
        answer = {"wrote": str(save_problem(problem, args.out))}
    elif args.action == "start":
        document = research_sessions.start(load_problem(args.problem), name=args.name, agent=args.agent, goal=args.goal)
        folder = research_sessions.sessions_directory() / document["session_id"]
        answer = {"session_id": document["session_id"], "folder": str(folder), "work": str(folder / "work")}
    elif args.action == "submit":
        entry = research_sessions.submit(args.session, load_candidate(args.candidate), args.note)
        answer = {key: value for key, value in entry.items() if key not in ("candidate", "verdict")}
    elif args.action == "note":
        answer = research_sessions.add_note(args.session, args.text)
    elif args.action == "status":
        document = (research_sessions.set_status(args.session, args.new_status) if args.new_status
                    else research_sessions.load(args.session))
        reference = document["problem"].get("metadata", {}).get("reference") or {}
        answer = {key: document[key] for key in ("session_id", "name", "agent", "status", "problem_id", "best")}
        answer["record"] = {key: reference.get(key) for key in ("value", "unit", "note", "verified_on")} if reference else None
        answer["submissions"] = sum(item["kind"] == "submission" for item in document["journal"])
    else:
        answer = research_sessions.listing(args.problem_id)
    print(json.dumps(answer, indent=2, ensure_ascii=False))
    return 1 if args.action == "submit" and not answer["valid"] else 0


def _add_problem_candidate(parser: argparse.ArgumentParser) -> None:
    """Add the two arguments every command on a candidate needs."""
    parser.add_argument("--problem", "-p", required=True, type=Path)
    parser.add_argument("--candidate", "-c", required=True, type=Path)


def _cmd_info(args: argparse.Namespace) -> int:
    """Print the description of a problem and the scale interval worth exploring."""
    problem = load_problem(args.problem)
    print(problem.describe())
    bounds = scale_bounds(problem)
    print(f"scale       {bounds.low:.6g} .. {bounds.high:.6g}   ({bounds.rationale})")
    if problem.arena is None:
        # Nothing is declared, so the line names the frame a construction starts in
        # rather than the region the shapes are judged against: the region is the
        # container the engine measures, and its size depends on the candidate.
        min_x, min_y, max_x, max_y = problem.draft_region.bounds
        print(f"draft       x [{min_x:.6g}, {max_x:.6g}]  y [{min_y:.6g}, {max_y:.6g}]")
    else:
        min_x, min_y, max_x, max_y = problem.arena.bounds
        print(f"bounds      x [{min_x:.6g}, {max_x:.6g}]  y [{min_y:.6g}, {max_y:.6g}]")
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    """Draw a problem from a seed and write it, so that a run can be rebuilt later.

    The seed and the spec name the instance: the same pair writes the same
    document, which is what makes a measurement taken on a generated instance
    comparable to the next one. The recipe travels inside the document itself,
    under its ``generator`` metadata.
    """
    overrides: dict[str, Any] = {}
    if args.arena:
        overrides["arenas"] = tuple(args.arena)
    if args.shape:
        overrides["shapes"] = tuple(args.shape)
    if args.counts:
        overrides["counts"] = (int(args.counts[0]), int(args.counts[1]))
    if args.rotation:
        overrides["rotations"] = tuple(args.rotation)
    if args.objective:
        overrides["objective"] = args.objective
    if args.prefix:
        overrides["name_prefix"] = args.prefix
    problem = generate(GeneratorSpec(seed=args.seed, **overrides))
    path = args.out if args.out.suffix == ".json" else args.out / f"{problem.problem_id}.json"
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)
    save_problem(problem, path)
    print(problem.describe())
    print(f"wrote {path}")
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    """Build a starting candidate, save it, and report its score."""
    problem = load_problem(args.problem)
    initializer = INITIALIZERS[args.strategy]
    candidate = initializer(problem, scale=args.scale, count=args.count)
    evaluation = evaluate(problem, candidate)
    save_candidate(candidate, args.out)
    print(f"{args.strategy}: {evaluation.summary()}")
    print(f"wrote {args.out}")
    if args.svg is not None:
        _write_svg(args.svg, render_svg(problem, candidate))
        print(f"wrote {args.svg}")
    return 0 if evaluation.valid else 1


def _cmd_validate(args: argparse.Namespace) -> int:
    """Report whether a candidate is valid, and why not."""
    problem = load_problem(args.problem)
    candidate = load_candidate(args.candidate)
    validation = validate(problem, candidate)
    print("VALID" if validation.valid else "INVALID")
    _print_violations(validation)
    return 0 if validation.valid else 1


def _cmd_evaluate(args: argparse.Namespace) -> int:
    """Score a candidate, print its metrics, and optionally save the verdict."""
    problem = load_problem(args.problem)
    candidate = load_candidate(args.candidate)
    evaluation = evaluate(problem, candidate)
    print(f"candidate   {candidate.candidate_id} ({candidate.origin}, generation {candidate.generation})")
    print(f"score       {evaluation.summary()}")
    _print_metrics(evaluation)
    _print_violations(evaluation.validation)
    if args.json is not None:
        dump(evaluation.to_dict(), args.json)
        print(f"wrote {args.json}")
    if args.svg is not None:
        _write_svg(args.svg, render_svg(problem, candidate, RenderOptions(show_voids=args.voids)))
        print(f"wrote {args.svg}")
    return 0 if evaluation.valid else 1


def _cmd_render(args: argparse.Namespace) -> int:
    """Write the SVG picture of a candidate."""
    problem = load_problem(args.problem)
    candidate = load_candidate(args.candidate)
    options = RenderOptions(
        width=args.width,
        show_ids=args.ids,
        show_centers=args.centers,
        show_voids=args.voids,
        show_violations=not args.no_violations,
    )
    _write_svg(args.out, render_svg(problem, candidate, options))
    print(f"wrote {args.out}")
    return 0


def _cmd_analyze(args: argparse.Namespace) -> int:
    """Print the empty regions of a candidate."""
    problem = load_problem(args.problem)
    candidate = load_candidate(args.candidate)
    analysis = analyze(problem, candidate, void_limit=args.void_limit)
    largest = analysis.largest_void
    print(
        f"voids       {len(analysis.voids)} region(s), "
        f"largest area {0.0 if largest is None else largest.area:.6g}"
    )
    for index, void in enumerate(analysis.voids):
        print(
            f"  {index}: area {void.area:.6g}  centre ({void.centroid[0]:.6g}, {void.centroid[1]:.6g})"
        )
    print(f"contacts    mean {analysis.mean_contacts:.3f} per shape")
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    """Run baselines on a problem and report the curve each one reached.

    Always exits ``0``: unlike ``validate`` or ``evaluate`` this command does not
    gate on a verdict, it reports a search. A baseline that ends invalid is a
    measurement, not a failure of the command.
    """
    problem = load_problem(args.problem)
    names = list(dict.fromkeys(args.baseline)) if args.baseline else sorted(BASELINES)
    print(f"problem     {problem.title} ({problem.problem_id})")
    print(f"budget      {args.budget} evaluation(s) per baseline")
    for name in names:
        convergence = BASELINES[name].run(problem, budget=args.budget, seed=args.seed)
        # The run is over, so this verdict is not billed to it: it is the engine's
        # word on the candidate the baseline hands back, the same figure ``init``
        # and ``evaluate`` report.
        verdict = evaluate(problem, convergence.best)
        density = verdict.metrics.get("density")
        summary = f"{convergence.describe()}  {problem.title}"
        print(summary if density is None else f"{summary}  density={density:.4f}")
        _print_curve(convergence)
        if args.json is not None:
            path = _artefact_path(args.json, name, ".json", len(names))
            dump(convergence.to_dict(), path)
            print(f"wrote {path}")
        if args.svg is not None:
            path = _artefact_path(args.svg, name, ".svg", len(names))
            _write_svg(path, convergence_svg(convergence))
            print(f"wrote {path}")
    return 0


def _print_curve(convergence: Convergence) -> None:
    """Print the curve of a run as a compact table, sampled to :data:`CURVE_ROWS` rows."""
    print(f"  {'evaluations':>11}  {'best':>12}  {'verdict':<7}  {'severity':>10}")
    for step in _sampled(convergence.steps):
        verdict = "valid" if step.best_valid else "invalid"
        print(f"  {step.evaluations:>11}  {step.best_measure:>12.6g}  {verdict:<7}  {step.severity:>10.4g}")


def _sampled(steps: Sequence[Step]) -> list[Step]:
    """Return at most :data:`CURVE_ROWS` steps, evenly spread and ending on the last one.

    A curve of a few thousand points says the same thing as one of ten rows, and the
    terminal is not a plot: the first and the last point are always kept, so the
    start of the run and what it ended on are both readable.
    """
    if len(steps) <= CURVE_ROWS:
        return list(steps)
    stride = (len(steps) - 1) / (CURVE_ROWS - 1)
    return [steps[round(index * stride)] for index in range(CURVE_ROWS)]


def _artefact_path(requested: Path, strategy: str, suffix: str, runs: int) -> Path:
    """Return where one baseline's artefact goes.

    A path that carries a suffix names a file; a path that carries none names a
    directory, created if needed, and the artefact goes inside it under the
    strategy's name. A single baseline writes exactly the file it was given;
    several write beside it, named after the strategy, since one file per object is
    the storage rule here and two convergences in one file would be neither.
    """
    if not requested.suffix:
        requested.mkdir(parents=True, exist_ok=True)
        return requested / f"{strategy}{suffix}"
    if runs < 2:
        return requested
    return requested.with_name(f"{requested.stem}-{strategy}{requested.suffix}")


def _cmd_serve(args: argparse.Namespace) -> int:
    """Run the HTTP interface, open it, and keep it in the foreground.

    Meant to be the only command someone has to remember, and to be double
    clickable from a launcher: a busy port is replaced by a free one instead of
    ending in an error nobody reads, and the browser is opened once the page is
    actually answerable.

    The frontend is optional: without it the API answers on its own, which is
    enough to drive the lab from a script or from the interactive documentation
    FastAPI publishes at ``/docs``.
    """
    try:
        import uvicorn
    except ImportError:
        print(
            "the web interface needs extra dependencies: pip install -e '.[api]'",
            file=sys.stderr,
        )
        return 2
    from paper_obs.api import FRONTEND_DIST, create_app
    from paper_obs.workflows import runner

    # A run is written by the process that started it, so a run left saying it is still
    # going is one nobody can finish: closing it here is what keeps a client from waiting
    # for a turn that will never come.
    abandoned = runner.close_orphans()

    port = _available_port(args.host, args.port)
    address = f"http://{_browsable_host(args.host)}:{port}"
    print(f"paper-obs serving on {address}")
    print(f"  interface  {FRONTEND_DIST if FRONTEND_DIST.is_dir() else 'not built'}")
    if not FRONTEND_DIST.is_dir():
        print("  build it with: cd apps/web && npm install && npm run build")
    if abandoned:
        print(f"  closed {len(abandoned)} run(s) a stopped lab had left going: {', '.join(abandoned)}")
    if port != args.port:
        print(f"  port {args.port} was busy, using {port} instead")
    if args.open_browser:
        _open_browser(address)
    if args.reload:
        uvicorn.run("paper_obs.api:create_app", factory=True, host=args.host, port=port, reload=True)
        return 0
    uvicorn.run(create_app(), host=args.host, port=port)
    return 0


def _available_port(host: str, port: int) -> int:
    """Return ``port`` when it is free, another one otherwise.

    Binding is the only honest test of availability, and the socket is closed
    immediately: the window before the server claims it is tiny, and a launcher
    that refuses to start because something else holds 8000 is worse than the
    race.

    The probe binds with ``SO_REUSEADDR``, exactly as a server does. Without it,
    a port left in ``TIME_WAIT`` by a previous run — which is what restarting a
    few times in a row leaves behind — looks busy while the server could have
    taken it, and the launcher would walk up the port numbers for no reason.
    """
    if port == 0:
        with _probe_socket() as probe:
            probe.bind((host, 0))
            return int(probe.getsockname()[1])
    for candidate in range(port, port + 10):
        with _probe_socket() as probe:
            try:
                probe.bind((host, candidate))
            except OSError:
                continue
            return candidate
    with _probe_socket() as probe:
        probe.bind((host, 0))
        return int(probe.getsockname()[1])


def _probe_socket() -> socket.socket:
    """Return a socket that can bind where a server could."""
    probe = socket.socket()
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    return probe


def _browsable_host(host: str) -> str:
    """Return the host to put in a URL: a wildcard address is not one."""
    return "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host


def _open_browser(url: str) -> None:
    """Open ``url``, from WSL as well as from a plain Linux session.

    ``cmd.exe`` comes before ``xdg-open`` on purpose: inside WSL the latter is
    often installed and often opens nothing, while the Windows interop always
    reaches the browser the person is actually looking at.
    """
    candidates = [
        ["wslview", url],
        ["cmd.exe", "/c", "start", "", url],
        ["xdg-open", url],
        ["open", url],
    ]
    for command in candidates:
        if shutil.which(command[0]) is None:
            continue
        try:
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            continue
        return
    webbrowser.open(url)


def _print_metrics(evaluation: Evaluation) -> None:
    """Print the descriptive metrics of an evaluation, aligned on the longest name."""
    width = max((len(name) for name in evaluation.metrics), default=0) + 2
    for name, value in evaluation.metrics.items():
        print(f"  {name:<{width}}{value:.6g}")


def _print_violations(validation: Validation) -> None:
    """Print the first violations of a validation, with the shapes involved."""
    violations = validation.violations
    for violation in violations[:10]:
        shapes = ", ".join(violation.shape_ids) or "candidate"
        print(f"  {violation.kind:<24}{shapes:<24}{violation.message}")
    if len(violations) > 10:
        print(f"  ... {len(violations) - 10} more violation(s)")


def _write_svg(path: Path, content: str) -> None:
    """Write an SVG document, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover - module entry point
    sys.exit(main())
