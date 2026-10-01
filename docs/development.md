# Development

## Local setup

The repository uses Python 3.11+, a `src/` package and a React frontend. The deterministic engine depends on NumPy and Shapely; FastAPI and LangGraph are optional extras. For a complete checkout:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,api,agents]"
.venv/bin/python -m pytest -q
cd apps/web && npm ci && npm run build
cd ../..
.venv/bin/paper-obs serve
```

On Windows, `paper-obs.bat` launches WSL from the repository folder. The API binds locally and chooses the first free port starting at 8000. For frontend editing, `npm run dev` in `apps/web` uses a local API proxy. `npm run typecheck` checks TypeScript without building.

The first visit opens a fifteen-step, dismissible quick start. It compares two squares, a naive five-square placement and the proved five-square construction, then shows the best-known 11- and 17-square layouts before the problem lists, catalog, model settings and workspaces. **Try it** reduces the guide to a small control so the current example remains editable. The **Quick start** button restarts it. The guide changes tabs and the loaded example, but does not create a solver run or save a candidate.

Do not commit `.venv/`, `node_modules/`, `dist/`, `runs/`, `out/`, `.env` or `.private/`. The last is for the owner's personal notes and design history. The repository's published documentation is `docs/`. The checked-in catalog lives in `apps/web/public/catalog/`.

Use `PAPER_OBS_API_KEY`, `PAPER_OBS_EXAMPLES`, and `PAPER_OBS_RUNS` for local overrides.

## A reliable change

1. Keep data, geometry, search, workflow and UI responsibilities separate; use the engine for every geometric verdict.
2. For a new objective or shape, add deterministic tests of the observable contract: validity at tangency, overlap or uncovered area, exact scoring units, JSON round-trip and view output.
3. Update both French and English interface strings where a user-facing label changes. Inspect the 1280×720 and desktop layouts for changes that affect controls or dialogs.
4. Run `python -m pytest -q`, `npm run typecheck` and `npm run build` as relevant. Record a significant verified milestone in a focused commit, after checking the staged diff.

The Python tests run in CI on 3.11 and 3.12; the frontend builds on Node 20. A local build on a Google Drive mount can be slower or can fail when an old build directory has locked files. Rebuild to a fresh output directory to distinguish a code failure from a file-lock failure.

Commit coherent, verified changes with [Conventional Commits](https://www.conventionalcommits.org/) messages; for example, `feat(geometry): support a new packing objective` or `fix(ui): keep drag movement precise`. Versions follow [SemVer](https://semver.org/) from `0.1.0` while the public JSON and solver contracts mature. Keep package versions aligned, bump them only for a release, and create the matching `v0.y.z` tag after the release checks. An agent must not tag or publish on its own.

## Data, sources and deployment

The maintainers generate the reference JSON, candidate files and previews with builders kept outside the repository; the catalog is maintained here, not rebuilt by contributors. Generated assets should keep source links, attribution, proof status and a last-verification date. Do not silently promote a source construction into a proved optimum. The collection includes linked images and coordinates from third-party sites; review their reuse terms before a public release.

The server is designed for local use. Do not bind it publicly or set a server-wide paid-provider key for untrusted visitors without authentication, rate limits and a deployment review. A user-entered provider key is intended for that run only. Uploaded or dropped user code is **not** a safe extension mechanism for a shared server; external heuristics should initially run as trusted local processes under a documented adapter.

## Known gaps

- The four agent workflows still need controlled outcome measurements across problem families, and against `basin_hopping` at an equal cost.
- The catalog can judge more families than the current initializers and baselines can solve well.
- The editor has not been performance-validated for large, complicated configurations.
- The problem model is not a symbolic constraint language. Mixed per-placement shapes, many free container parameters and 3D geometry require domain and engine work.
- The run cost ceiling is checked from provider-reported usage; without streaming it cannot interrupt one provider response at an exact spend threshold.
