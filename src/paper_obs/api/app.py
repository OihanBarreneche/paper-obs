"""The HTTP surface of the lab, for the web interface.

The API is a *translator* and nothing more: it turns JSON documents into domain
objects, calls the engine, and turns the results back into JSON. It holds no
geometry, no search strategy and no state between requests — the browser owns
the problem and the candidate it is editing, which is what makes the whole lab
usable without a database and reproducible from two files.

Two consequences worth stating, because they shape every route:

* a request body carries complete ``problem`` and ``candidate`` documents, and
  a malformed one is refused with the domain layer's own message, in the same
  words the command line would use;
* the ``view`` returned alongside every verdict is built by
  :func:`paper_obs.geometry.view.build_view`, so the browser draws exactly what
  the engine judged, without knowing how a disc is sized.
"""

from __future__ import annotations

import multiprocessing
from collections.abc import Awaitable, Callable
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any

from fastapi import BackgroundTasks, Body, FastAPI, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from paper_obs import __version__
from paper_obs.agent_tools.engine import worker_processes
from paper_obs.domain.arena import Arena, ArenaPart, ArenaShape, arena_from_parts, part
from paper_obs.domain.candidate import Candidate
from paper_obs.domain.objectives import CoverRegion, MaximizeCoveredSize, MaximizeTotalPerimeter
from paper_obs.domain.problem import Problem
from paper_obs.domain.serde import JSON
from paper_obs.domain.shapes import catalogue
from paper_obs.geometry.bounds import scale_bounds
from paper_obs.geometry.engine import Evaluation, evaluate
from paper_obs.geometry.rendering import RenderOptions, render_svg
from paper_obs.geometry.view import arena_part_views, arena_path, build_view
from paper_obs.llm.discovery import models_for
from paper_obs.llm.models import (
    ModelConfig,
    catalogue as provider_catalogue,
    key_present as provider_key_present,
    resolve_api_key,
)
from paper_obs.llm.redaction import redact, redact_document
from paper_obs.search.baselines import BASELINES
from paper_obs.search.operators.initialization import (
    cover_initialize,
    grid_initialize,
    random_initialize,
    staggered_initialize,
    varied_initialize,
)
from paper_obs.workflows import registry, runner
from paper_obs.workflows.budget import Budget, field_names

from . import library
from .shape import compose_shape

#: Initialization operators a client may ask for, by name.
INITIALIZERS: dict[str, Callable[..., Candidate]] = {
    "grid": grid_initialize,
    "staggered": staggered_initialize,
    "random": random_initialize,
    "varied": varied_initialize,
    "cover": cover_initialize,
}

#: Where the built frontend is expected, relative to this file's checkout.
FRONTEND_DIST = Path(__file__).resolve().parents[3] / "apps" / "web" / "dist"

#: Evaluations a search request spends when the client does not say, and the most
#: it may ask for. A lattice spends a few dozen; a basin hop is billed 21 and takes
#: about a second on discs, several on polygons, so the default buys about ten hops
#: and the cap keeps a request to minutes rather than holding a worker for an hour.
DEFAULT_SEARCH_BUDGET = 200
MAX_SEARCH_BUDGET = 1_000


#: How a run gets a process of its own: a fresh interpreter, which every platform offers.
SPAWN = multiprocessing.get_context("spawn")


def carry_on_apart(path: Path, **arguments: Any) -> None:
    """Carry a run on in its own process, where its agents' tools compute in worker processes."""
    # The server starts this process as a daemon, so that stopping the server ends the run;
    # a daemon may not start processes, and the run's workers end with it anyway.
    multiprocessing.current_process().daemon = False
    with worker_processes():
        runner.carry_on(path, **arguments)


def create_app(*, static_directory: Path | None = None, processes: bool = True) -> FastAPI:
    """Build the application, optionally serving a built frontend from ``static_directory``.

    With ``processes``, each agent run goes on in a process of its own: model calls wait on
    the network, but the tools compute in Python, and runs sharing one interpreter would share
    one core. Within a run, the tools' operators compute in worker processes, so that agents
    working at once do not share one core either. Without it a run is a background task of this process, where a test can replace
    what the run calls.
    """
    app = FastAPI(
        title="Paper Obs",
        version=__version__,
        description="Judge, draw and initialise 2D packing candidates.",
    )
    directory = FRONTEND_DIST if static_directory is None else static_directory
    app.state.frontend_directory = directory

    # Every refusal leaves through here, so a detail that quotes the request it refused
    # — an unknown field name, a malformed document — cannot carry a key-shaped string
    # back to the browser. The validation case matters for the same reason: FastAPI
    # echoes the offending input, and that input is a request body.
    @app.exception_handler(HTTPException)
    async def redacted_http_error(request: Request, error: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={"detail": redact_document(error.detail)},
            headers=error.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def redacted_validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": redact_document(jsonable_encoder(error.errors()))},
        )

    _register_routes(app, processes=processes)

    # A rebuilt page must not keep running the previous bundle out of the browser's
    # cache. The document names its bundle by a hash and carries no version of its
    # own, so with no explicit freshness Chrome applies a heuristic lifetime and
    # reuses it without ever asking the server — the old `index.html` and the old
    # bundle both still in the cache, the whole previous page runs on. The hashed
    # assets under `assets/` are the opposite case: their name changes with their
    # content, so they can be kept for ever. API answers are never stored.
    @app.middleware("http")
    async def cache_policy(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        elif path.startswith("/assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response

    if directory.is_dir():
        # Mounted last on purpose: every /api route is declared before it, and a
        # mount at the root would otherwise swallow them.
        app.mount("/", StaticFiles(directory=directory, html=True), name="web")
    return app


def _register_routes(app: FastAPI, *, processes: bool) -> None:
    """Declare every route of the API."""
    active_runs: dict[str, Any] = {}
    active_lock = Lock()
    app.state.active_runs = active_runs

    @app.get("/api/health")
    def health() -> JSON:
        """Report the version, the frontend being served, and where examples come from."""
        directory = app.state.frontend_directory
        return {
            "status": "ok",
            "version": __version__,
            "frontend": directory.is_dir(),
            "frontend_directory": str(directory),
            "example_directories": [str(path) for path in library.example_directories()],
        }

    @app.get("/api/examples")
    def list_examples() -> JSON:
        """List the example problems available to the client."""
        return {"examples": library.summaries()}

    @app.get("/api/examples/{problem_id}")
    def read_example(problem_id: str) -> JSON:
        """Return one example problem, its search interval, and its default candidate.

        ``candidate`` is the arrangement the example is known for — the published
        optimum for the instances that have one, the best this lab's own search
        finds for the others — or ``null`` when the example ships none. The
        interface opens on it, and the engine still judges it on arrival: what the
        file carries is coordinates, never a verdict.
        """
        problem = _problem_or_404(problem_id)
        shipped = library.default_candidate(problem_id)
        return {
            "problem": problem.to_dict(),
            "candidate": None if shipped is None else shipped.to_dict(),
            "scale_bounds": _bounds(problem),
            "text": problem.describe(),
        }

    @app.get("/api/shapes")
    def list_shapes() -> JSON:
        """List the packable shapes a problem can be built from.

        The interface shows them when a click on the canvas has to add a shape.
        Which families exist, and how big one is by default, is the domain's
        decision — the browser only stores the shape it was handed.
        """
        return {"shapes": list(catalogue())}

    @app.get("/api/baselines")
    def list_baselines() -> JSON:
        """List the search strategies a client can run, in the order they are shown."""
        return {"baselines": list(BASELINES)}

    @app.get("/api/providers")
    def list_providers() -> JSON:
        """List the model providers a client may choose from.

        The providers are a table in ``paper_obs.llm.models``, not a branch in a
        client, so this is the same list the command line would print. Per provider
        it also says whether a key is already configured in the environment — never
        the key itself, which no route of this lab returns.
        """
        return {"providers": provider_catalogue(), "key_present": provider_key_present()}

    @app.post("/api/providers/models")
    def list_provider_models(body: dict[str, Any] = Body(...)) -> JSON:
        """Ask a provider which model ids it serves, with the caller's own key.

        Model ids drift, so this route exists to make a stale default never the only
        option. The ids are returned and forgotten: nothing is cached, nothing is
        written down, and the key travels in a request header — never in the URL, the
        answer or a log line. A provider whose base URL has no /models (Gemini's
        compatibility path) answers with the endpoint's own refusal, redacted.
        """
        _only(body, {"provider", "api_key", "base_url"})
        name = body.get("provider")
        if not isinstance(name, str) or not name:
            raise HTTPException(status_code=400, detail="the body needs a 'provider' name")
        try:
            config = ModelConfig(provider=name, base_url=str(body.get("base_url") or ""))
            # Resolve the endpoint before any request, so "custom" without a base URL is
            # a bad request rather than a failed connection.
            config.endpoint
        except (KeyError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        supplied = body.get("api_key")
        try:
            key = resolve_api_key(config, provided=None if supplied is None else str(supplied))
        except ValueError:
            # Some catalogues answer without a key (OpenRouter's does): ask anyway, and let
            # an endpoint that needs one say so.
            key = ""
        try:
            models = models_for(config, api_key=key)
        except (OSError, ValueError) as error:
            refused = getattr(error, "code", None) in (401, 403)
            detail = (
                "this provider lists its models only with a key: enter one first"
                if refused and not key
                else f"could not list models: {redact(str(error), secrets=(key,))}"
            )
            raise HTTPException(status_code=502, detail=detail) from error
        return {"provider": config.provider, "models": models}

    @app.get("/api/workflows")
    def list_workflows() -> JSON:
        """List the workflows a client may run, with their parameters and their shape.

        The topology travels with them, as nodes and edges: the interface draws the
        workflow it is about to run without knowing any of its names.
        """
        return {"workflows": registry.manifests()}

    @app.get("/api/workflows/{workflow_id}/tools")
    def list_workflow_tools(workflow_id: str) -> JSON:
        """List the tools a workflow's agents may call, read from the tools themselves.

        Each one comes with the description and the argument schema a model receives, and the
        objectives on which the workflow offers it: the list follows the code it is built from.
        """
        try:
            return registry.tools(workflow_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ImportError as error:
            raise HTTPException(
                status_code=503, detail="listing tools needs the agents extra"
            ) from error

    @app.get("/api/agent-runs")
    def list_agent_runs() -> JSON:
        """List the runs already written, for a run picker."""
        return {"runs": runner.listing()}

    @app.get("/api/agent-runs/{run_id}")
    def read_agent_run(run_id: str) -> JSON:
        """Return one run: what it was asked, every turn it took, and what it reached.

        The document is read from disk, so a client that polls it watches a run that is
        still going and reads it back afterwards through the same call — one code path
        for watching and for replaying.
        """
        try:
            document = runner.load(run_id)
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}") from error
        # A stop takes effect once the model calls under way have answered: until the run writes
        # its end, a client that reloads still learns that one was asked for.
        with active_lock:
            signal = active_runs.get(run_id)
        if signal is not None and signal.is_set():
            document["stop_requested"] = True
        return document

    @app.post("/api/agent-runs")
    def start_agent_run(background: BackgroundTasks, body: dict[str, Any] = Body(...)) -> JSON:
        """Start one workflow on one problem, and answer with the identifier to watch.

        The run happens after the answer is sent: it takes minutes, and holding a request
        open for minutes is what makes an interface fragile. The client polls the
        identifier instead, and the document is written after every turn. A key sent here
        is used for this run only, and never written to the document. With ``resume``, the
        named run is taken up again where it stopped, in its own document.
        """
        problem = _problem_of(body)
        _only(
            body,
            {
                "problem",
                "problem_id",
                "workflow",
                "name",
                "provider",
                "model",
                "base_url",
                "temperature",
                "max_tokens",
                "reasoning_effort",
                "cost_per_million_in",
                "cost_per_million_out",
                "cost_per_million_cached",
                "api_key",
                "budget",
                "resume",
            },
        )
        resumed = None if body.get("resume") is None else str(body["resume"])
        workflow = str(body.get("workflow", "basic_agent_loop"))
        try:
            if resumed is not None:
                workflow = str(runner.load(resumed)["workflow"])
            manifest = registry.manifest(workflow)
            name = runner.validate_name(body["name"]) if "name" in body else None
            config = ModelConfig.from_dict(body)
            budget, settings = _parameters(
                body.get("budget") or {},
                {str(item["name"]) for item in manifest.get("parameters", [])},
            )
            if budget.max_cost is not None and (
                config.cost_per_million_in is None or config.cost_per_million_out is None
            ):
                raise ValueError("A cost ceiling requires both model token prices")
        except (KeyError, ValueError, OSError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        run_id = runner.new_run_id() if resumed is None else resumed
        key = None if body.get("api_key") is None else str(body["api_key"])
        stop_signal = SPAWN.Event() if processes else Event()
        with active_lock:
            if run_id in active_runs:
                raise HTTPException(status_code=409, detail="this run is still going")
            active_runs[run_id] = stop_signal

        def forget() -> None:
            with active_lock:
                active_runs.pop(run_id, None)

        # The document says the run is going before anything else happens, so a client that
        # reads it at once follows it rather than finding it missing or finished.
        try:
            path = runner.open_run(
                problem, workflow=workflow, config=config, budget=budget, settings=settings,
                run_id=run_id, name=name,
            ) if resumed is None else runner.reopen(run_id, config=config, settings=settings)
        except (OSError, ValueError) as error:
            forget()
            raise HTTPException(status_code=400, detail=str(error)) from error
        # The key reaches the run in memory, as an argument, and never through a file.
        arguments = {"config": config, "budget": budget, "api_key": key, "stop_requested": stop_signal}
        if processes:
            child = SPAWN.Process(target=carry_on_apart, args=(path,), kwargs=arguments, daemon=True)
            child.start()
            Thread(target=lambda: (child.join(), forget()), daemon=True).start()
        else:
            def execute() -> None:
                try:
                    runner.carry_on(path, **arguments)
                finally:
                    forget()

            background.add_task(execute)
        return {"run_id": run_id, "status": "running"}

    @app.post("/api/agent-runs/{run_id}/stop")
    def stop_agent_run(run_id: str) -> JSON:
        """Request a cooperative stop after the current model call or turn returns."""
        with active_lock:
            signal = active_runs.get(run_id)
            if signal is None:
                raise HTTPException(status_code=409, detail="run is not active")
            signal.set()
        return {"run_id": run_id, "status": "stop_requested"}

    @app.delete("/api/agent-runs/{run_id}")
    def delete_agent_run(run_id: str) -> JSON:
        """Delete one saved run.

        A run still being written is refused rather than raced: the process that owns it
        would recreate the file on its next turn, and a picker that offers to delete it
        would be offering something it cannot do.
        """
        with active_lock:
            if run_id in active_runs:
                raise HTTPException(status_code=409, detail="run is still active")
        try:
            runner.delete(run_id)
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}") from error
        return {"run_id": run_id, "status": "deleted"}

    @app.post("/api/agent-runs/{run_id}/restore")
    def restore_agent_run(run_id: str) -> JSON:
        """Bring a deleted run back among the saved runs."""
        try:
            runner.restore(run_id)
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=404, detail=f"no deleted run {run_id!r}") from error
        return {"run_id": run_id, "status": "restored"}

    @app.post("/api/search")
    def search(body: dict[str, Any] = Body(...)) -> JSON:
        """Run one baseline on a problem, and return its curve with its best candidate.

        The whole convergence comes back, not only the winner: comparing two
        strategies is what the lab is for, and a comparison needs the shape of the
        curve as much as its last point. The best candidate is judged and drawn
        like any other, so a client can put it on its canvas without a second trip.

        ``budget`` is a number of engine evaluations, capped so that one request
        cannot hold a worker for minutes; a client that wants more asks for more
        than one run, which is also how a budget-controlled comparison is done.
        """
        problem = _problem_of(body)
        _only(body, {"problem", "problem_id", "baseline", "budget", "seed", "with_voids"})
        strategy = str(body.get("baseline", "basin_hopping"))
        baseline = BASELINES.get(strategy)
        if baseline is None:
            raise HTTPException(
                status_code=400,
                detail=f"unknown baseline {strategy!r}; known baselines: {', '.join(BASELINES)}",
            )
        requested_budget = _optional_int(body.get("budget"), "budget")
        # Absent means "the default"; zero means zero, and it is refused below.
        budget = DEFAULT_SEARCH_BUDGET if requested_budget is None else requested_budget
        if budget < 1:
            raise HTTPException(status_code=400, detail=f"budget must be at least 1, got {budget}")
        if budget > MAX_SEARCH_BUDGET:
            raise HTTPException(
                status_code=400,
                detail=f"budget must not exceed {MAX_SEARCH_BUDGET}, got {budget}",
            )
        seed = _optional_int(body.get("seed"), "seed")
        try:
            convergence = baseline.run(problem, budget=budget, seed=seed)
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {
            "convergence": convergence.to_dict(),
            # The engine's own one-line summary, so a client shows the same wording
            # the command line would rather than re-deriving it from the numbers.
            "summary": convergence.describe(),
            "verdict": _verdict(
                problem, convergence.best, with_voids=bool(body.get("with_voids", False))
            ),
        }

    @app.post("/api/init")
    def initialize(body: dict[str, Any] = Body(...)) -> JSON:
        """Build a starting candidate for a problem and judge it.

        The candidate is returned with its verdict and its drawable form, so a
        client never needs a second round trip to display what it just asked for.
        """
        problem = _problem_of(body)
        _only(
            body,
            {"problem", "problem_id", "strategy", "scale", "count", "with_voids", "with_union"},
        )
        strategy = str(body.get("strategy", "grid"))
        initializer = INITIALIZERS.get(strategy)
        if initializer is None:
            raise HTTPException(
                status_code=400,
                detail=f"unknown strategy {strategy!r}; known strategies: {', '.join(sorted(INITIALIZERS))}",
            )
        scale = _optional_float(body.get("scale"), "scale")
        count = _optional_int(body.get("count"), "count")
        try:
            candidate = initializer(problem, scale=scale, count=count)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return _verdict(
            problem,
            candidate,
            with_voids=bool(body.get("with_voids", False)),
            with_union=bool(body.get("with_union", False)),
        )

    @app.post("/api/capabilities")
    def problem_capabilities(body: dict[str, Any] = Body(...)) -> JSON:
        """Report what the lab can build for a problem: its initialisers and baselines.

        A problem type the search layer has no reasoning for has nothing to
        propose and no strategy to run, so a client must be able to *ask* before
        it offers a Start button that can only fail. The answer is derived from
        the objective and the arena the engine already holds. A document the
        domain refuses answers with both lists empty and the engine's own
        sentence as the reason — it never fails, because "can this be built?" is
        a question with a true answer even for a document that cannot.

        The alternative — letting the client show the controls and read a 400 —
        is what this route exists to remove: an interface that offers a control
        it cannot honour is lying, in the same font as a working one.
        """
        _only(body, {"problem", "problem_id"})
        try:
            problem = _problem_of(body)
        except HTTPException as error:
            return {
                "initialize": [],
                "search": [],
                "reason": str(error.detail),
                "arena_fixed": False,
            }
        return _capabilities(problem)

    @app.post("/api/arena")
    def compose_arena(body: dict[str, Any] = Body(...)) -> JSON:
        """Compile a stack of primitives into an arena and describe it.

        The editor sends the list of parts it holds; the domain folds them into
        a tree and the engine compiles it. That is what lets a sandbox preview
        the arena it is building on every keystroke, and — more usefully — lets
        it show the domain's own refusal, in the domain's own words, when the
        stack describes nothing ("the operation produced an empty region") or
        describes an impossible outline.
        """
        _only(body, {"parts"})
        items = body.get("parts")
        if not isinstance(items, list) or not items:
            raise HTTPException(status_code=400, detail="the body needs a non-empty 'parts' list")
        try:
            requested = tuple(_part_from_request(item) for item in items)
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=f"invalid arena part: {error}") from error
        try:
            arena = Arena(shape=arena_from_parts(requested))
        except (TypeError, ValueError) as error:
            # The parts are readable: it is the *result* that cannot exist.
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {
            "arena": arena.to_dict(),
            "path": arena_path(arena),
            "parts": [item.to_dict() for item in arena_part_views(arena)],
            "area": arena.area,
            "bounds": list(arena.bounds),
            "summary": arena.describe(),
        }

    @app.post("/api/shape")
    def compose_shape_route(body: dict[str, Any] = Body(...)) -> JSON:
        """Compile a stack of primitives into a packable shape and describe it.

        The shape composer sends the same stack the arena editor does, so one
        vocabulary builds both. The domain folds the stack, compiles it with
        shapely and the shape layer then reads that outline: the answer carries
        the shape document, the outline as SVG path data, its bounds, its area
        and its one-line description, so the browser previews exactly what the
        engine measured.

        A composed shape is stored as a polygon outline rather than as the tree
        that produced it. The engine's shape layer judges outlines — a
        CustomPolygon is a coordinate list, and its area, vertices and predicates
        all read that one ring — so a tree kept beside the shape would be a second
        definition of the same shape, free to disagree with the first when it is
        recompiled. The tree stays in the browser, where it is edited; the shape
        the engine files is the outline it measured.

        A stack is refused, in the domain's words, when it is empty, when the
        result is not a single connected outline, when it carries a hole a
        packable outline cannot store, or when its area is zero.
        """
        _only(body, {"parts"})
        items = body.get("parts")
        if not isinstance(items, list):
            raise HTTPException(status_code=400, detail="'parts' must be a list of primitives")
        try:
            requested = tuple(_part_from_request(item) for item in items)
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=f"invalid shape part: {error}") from error
        try:
            return compose_shape(requested)
        except (TypeError, ValueError) as error:
            # The parts are readable: it is the *result* that cannot be a shape.
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/evaluate")
    def judge(body: dict[str, Any] = Body(...)) -> JSON:
        """Judge a candidate: score, validity, metrics, violations and drawable form."""
        _only(body, {
            "problem", "problem_id", "candidate", "with_voids", "with_union",
            "snap_shape_ids", "snap_distance", "snap_motion",
        })
        problem = _problem_of(body)
        candidate = _candidate_of(body)
        if any(key in body for key in ("snap_shape_ids", "snap_distance", "snap_motion")):
            names = body.get("snap_shape_ids")
            if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
                raise HTTPException(status_code=400, detail="snap_shape_ids must be a list of strings")
            distance = _optional_float(body.get("snap_distance"), "snap_distance")
            if distance is None:
                raise HTTPException(status_code=400, detail="snap_distance is required")
            motion = body.get("snap_motion")
            if not isinstance(motion, list) or len(motion) != 2 or any(
                isinstance(value, bool) or not isinstance(value, (int, float)) for value in motion
            ):
                raise HTTPException(status_code=400, detail="snap_motion must contain two numbers")
            from paper_obs.geometry.contact_snap import snap_to_contact

            try:
                candidate = snap_to_contact(
                    problem, candidate, tuple(names), distance,
                    (float(motion[0]), float(motion[1])),
                )
            except ValueError as error:
                raise HTTPException(status_code=400, detail=str(error)) from error
        return _verdict(
            problem,
            candidate,
            with_voids=bool(body.get("with_voids", False)),
            with_union=bool(body.get("with_union", False)),
        )

    @app.post("/api/problems/validate")
    def validate_problem(body: dict[str, Any] = Body(...)) -> JSON:
        """Decode an imported problem and return its canonical public JSON form."""
        _only(body, {"problem"})
        return _problem_of(body).to_dict()

    @app.post("/api/rotate-selection")
    def turn_selection(body: dict[str, Any] = Body(...)) -> JSON:
        """Turn a group about its visible centre, then return the engine verdict."""
        _only(body, {"problem", "problem_id", "candidate", "shape_ids", "degrees", "with_union"})
        problem = _problem_of(body)
        candidate = _candidate_of(body)
        names = body.get("shape_ids")
        if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
            raise HTTPException(status_code=400, detail="shape_ids must be a list of strings")
        degrees = _optional_float(body.get("degrees"), "degrees")
        if degrees is None:
            raise HTTPException(status_code=400, detail="degrees is required")
        from paper_obs.geometry.transforms import rotate_selection

        try:
            turned = rotate_selection(problem, candidate, tuple(names), degrees)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return _verdict(
            problem,
            turned,
            with_voids=False,
            with_union=bool(body.get("with_union", False)),
        )

    @app.post("/api/render", response_class=PlainTextResponse)
    def render(body: dict[str, Any] = Body(...)) -> str:
        """Return the SVG document of a candidate, for download or export."""
        problem = _problem_of(body)
        candidate = _candidate_of(body)
        _only(body, {"problem", "problem_id", "candidate", "options"})
        options = body.get("options") or {}
        try:
            return render_svg(problem, candidate, _render_options(options))
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error


def _part_from_request(item: dict[str, Any]) -> ArenaPart:
    """Read one part the way the interface sends it back.

    The interface receives parts as ``{op, params: {kind, ...}, offset, angle}``
    and sends them back in the same shape, so it never has to know what an arena
    node looks like. Building the node — including wrapping the primitive in its
    turn and its position — happens here, once. The angle is in degrees and is
    optional: a part sent without one is a part that is not turned, which is what
    a client that never received an angle sends.
    """
    params = dict(item["params"])
    kind = params.pop("kind")
    primitive = ArenaShape.from_dict({"type": kind, **params})
    offset = item.get("offset") or (0.0, 0.0)
    angle = item.get("angle") or 0.0
    return part(str(item["op"]), primitive, float(offset[0]), float(offset[1]), float(angle))


def _parameters(
    raw: dict[str, Any], declared: set[str]
) -> tuple[Budget, dict[str, Any]]:
    """Return the shared ceilings and the workflow's own settings from one record of parameters.

    A panel sends every parameter a manifest declares in one flat record, because that is what
    a form is. Which of them are the ceilings every run shares and which belong to the workflow
    is the workflow's own business, and this is where the two part.

    ``declared`` is what the manifest names, and a setting outside it is refused: an unknown
    field is either a typo or an attempt to persist something through a field no graph reads —
    a key pasted into ``budget``, say — and a run document is not the place for either.
    """
    names = field_names()
    ceilings = {name: value for name, value in raw.items() if name in names}
    settings = {name: value for name, value in raw.items() if name not in names}
    unknown = sorted(set(settings) - declared)
    if unknown:
        known = ", ".join(sorted(declared))
        raise ValueError(
            f"unknown workflow parameter(s) {', '.join(repr(name) for name in unknown)}; "
            f"this workflow declares {known}"
        )
    return Budget.from_dict(ceilings), settings


def _only(body: dict[str, Any], known: set[str]) -> None:
    """Refuse a body carrying a field the route does not read.

    Every route reads its body by name, so a misspelled field falls back to the
    default and the request answers a question nobody asked — the worst kind of
    answer, because it looks like one. Naming the fields a route does read turns
    that into something a client can fix, which is worth the four lines.
    """
    unknown = sorted(set(body) - known)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=(
                f"unknown field(s) {', '.join(repr(name) for name in unknown)}; "
                f"this route reads {', '.join(sorted(known))}"
            ),
        )


def _problem_of(body: dict[str, Any]) -> Problem:
    """Read the ``problem`` document of a request body, or a named example."""
    document = body.get("problem")
    if document is None:
        problem_id = body.get("problem_id")
        if problem_id is None:
            raise HTTPException(status_code=400, detail="the body needs a 'problem' document or a 'problem_id'")
        return _problem_or_404(str(problem_id))
    try:
        return Problem.from_dict(document)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=f"invalid problem: {error}") from error


def _candidate_of(body: dict[str, Any]) -> Candidate:
    """Read the ``candidate`` document of a request body."""
    document = body.get("candidate")
    if document is None:
        raise HTTPException(status_code=400, detail="the body needs a 'candidate' document")
    try:
        return Candidate.from_dict(document)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=f"invalid candidate: {error}") from error


def _problem_or_404(problem_id: str) -> Problem:
    """Return a shipped example problem, or a 404 naming the known ones."""
    try:
        return library.example(problem_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error.args[0])) from error


def _verdict(
    problem: Problem, candidate: Candidate, *, with_voids: bool, with_union: bool = False
) -> JSON:
    """Return the evaluation of a candidate together with its drawable form.

    with_union is the optional overlay: the engine computes the union of the shape
    footprints and serialises it as a path, only when the caller asks for it.
    """
    try:
        evaluation = evaluate(problem, candidate)
        view = build_view(problem, candidate, with_voids=with_voids, with_union=with_union)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {
        "problem_id": problem.problem_id,
        "candidate": candidate.to_dict(),
        "evaluation": evaluation.to_dict(),
        "view": view.to_dict(),
        "scale_bounds": _bounds(problem),
        "summary": _summary(problem, evaluation),
    }


def _summary(problem: Problem, evaluation: Evaluation) -> JSON:
    """Return the line the interface shows above the score."""
    return {
        "problem": problem.title,
        "arena": problem.describe_region(),
        "shape": problem.shape.describe(),
        "objective": problem.objective.describe(),
        "score": str(evaluation.score),
        "verdict": "valid" if evaluation.valid else "invalid",
    }


def _bounds(problem: Problem) -> JSON:
    """Return the scale interval worth exploring, as found by the engine.

    The common scale an objective fixes, when it fixes one, travels beside the
    interval: for those families the interval is degenerate and a client shows
    the fixed value rather than a slider the objective would refuse. A family
    whose interval describes a local size instead -- the total-perimeter one --
    reports both, and its fixed common scale is what a client shows.
    """
    bounds = scale_bounds(problem)
    return {
        "low": bounds.low,
        "high": bounds.high,
        "rationale": bounds.rationale,
        "fixed": problem.objective.preset_scale(),
    }


def _capabilities(problem: Problem) -> JSON:
    """Return the initialisers and baselines that apply to ``problem``.

    Four rules, each read from the layer that owns it rather than restated here:

    * the staggered lattice is defined for discs only, so it is filtered on the
      shape family — the same condition ``staggered_initialize`` states in its
      own refusal, and the one a client would otherwise repeat;
    * every baseline needs the search interval ``scale_bounds`` derives, so an
      objective that leaves the engine no honest interval has none to run — and
      no initialiser either, since the lattice they build is sized from that
      same reasoning;
    * a total-perimeter family carries each copy's size on its placement, so the
      varied start is the only initialiser that can build a meaningful candidate
      for it; the others size every copy alike and are not offered — and no
      baseline varies a copy's own size either, so none is offered to run there;
    * a covering objective reads the scale the other way round, growing it until
      the copies contain the arena, so the covering start is the only
      construction written for it; the fill-oriented initialisers descend the
      scale and propose a pile the coverage constraint refuses.

    Both lists empty is the honest signal that this problem cannot be built yet,
    with the engine's own sentence as the reason.
    """
    try:
        scale_bounds(problem)
    except TypeError as error:
        return {
            "initialize": [],
            "search": [],
            "reason": str(error),
            "arena_fixed": problem.objective.arena_is_fixed,
        }
    if isinstance(problem.objective, MaximizeTotalPerimeter):
        # A total-perimeter family carries each copy's size on its placement, and
        # every other initialiser builds one common size: it can only propose a
        # start the objective's own fixed scale cannot describe. The varied start
        # is the one that speaks that family's language, so it is the only one
        # offered for it. No baseline varies a copy's local size either, so a run
        # would be a search that can never improve on its own first judgement.
        return {
            "initialize": ["varied"],
            "search": [],
            "reason": "",
            "arena_fixed": problem.objective.arena_is_fixed,
        }
    if isinstance(problem.objective, CoverRegion):
        # A covering minimises the common scale, the opposite reading to every
        # fill: the covering start is the one written for it. The baselines pack
        # shapes inside an arena and can never cover one, so no run is offered.
        return {
            "initialize": ["cover"],
            "search": [],
            "reason": "",
            "arena_fixed": problem.objective.arena_is_fixed,
        }
    if isinstance(problem.objective, MaximizeCoveredSize):
        # The derived covering measures the target *inside* the union of unit
        # copies, so a lattice of unit copies is exactly the start it needs: the
        # fill initialisers apply. The covering start reads the scale the other way
        # round, and the varied start gives copies different sizes the fixed common
        # scale would refuse. A run is offered: the score is the measured covered
        # size, which is exactly what polish's translations and turns grow in a
        # basin hop, and the lattice reads the same number.
        return {
            "initialize": [
                name
                for name in INITIALIZERS
                if name not in ("cover", "varied")
                and (name != "staggered" or problem.shape.is_circle)
            ],
            "search": list(BASELINES),
            "reason": "",
            "arena_fixed": problem.objective.arena_is_fixed,
        }
    initialize = [
        name
        for name in INITIALIZERS
        if name != "cover" and (name != "staggered" or problem.shape.is_circle)
    ]
    return {
        "initialize": initialize,
        "search": list(BASELINES),
        "reason": "",
        "arena_fixed": problem.objective.arena_is_fixed,
    }


def _render_options(overrides: dict[str, Any]) -> RenderOptions:
    """Build render options from a request, rejecting unknown field names."""
    known = {field: getattr(RenderOptions(), field) for field in RenderOptions().__dataclass_fields__}
    unknown = sorted(set(overrides) - set(known))
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"unknown render option(s): {', '.join(unknown)}; known options: {', '.join(sorted(known))}",
        )
    return RenderOptions(**overrides)


def _optional_float(value: Any, name: str) -> float | None:
    """Return a request value as a float, or ``None`` when it is absent."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HTTPException(status_code=400, detail=f"{name} must be a number")
    return float(value)


def _optional_int(value: Any, name: str) -> int | None:
    """Return a request value as an int, or ``None`` when it is absent."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise HTTPException(status_code=400, detail=f"{name} must be an integer")
    return int(value)


__all__ = ["FRONTEND_DIST", "INITIALIZERS", "create_app"]
