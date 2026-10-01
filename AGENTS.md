# Paper Obs — contributor and agent instructions

Paper Obs is a modular lab for two-dimensional geometric packing and covering. It is both an open-source research tool and the teaching material for a video about multi-agent orchestration. Optimize for comparable, inspectable results and a workflow implementation short enough to explain on screen.

Human contributors should also read [CONTRIBUTING.md](CONTRIBUTING.md) for the fork and pull request workflow and maintainer review expectations.

## Workspace and changes

- Keep all task files and generated environments inside this repository. Do not publish `.private/`, `runs/`, local keys, working screenshots or build output; the only published screenshots are the README's, in `docs/images/`. `.private/` holds the owner's personal notes and design history; it is ignored by Git.
- Read the relevant public [documentation](docs/README.md) and code before editing. Record major implementation decisions and known limits in the public docs when they change.
- Preserve the JSON representation of stored domain objects. Use explicit `to_dict`/`from_dict` and migrate intentionally when a public field must change.
- Make a Git commit after a **significant, verified milestone**: a coherent feature, bug-fix set or documentation step. Keep commits meaningful rather than committing every small edit. Review the staged diff first and never stage private files or unrelated work. Do not push or publish without the owner's request.

Use concise [Conventional Commits](https://www.conventionalcommits.org/) messages such as `feat(search): record solver progress`, `fix(ui): keep dragged shapes under the pointer`, or `docs: clarify catalog provenance`. In the body, note verification and any JSON compatibility change when relevant. AI-generated commits follow the same review rule; do not bump versions or create release tags for every commit. Releases use `v0.y.z` tags while the public contracts are still evolving, with versions in `pyproject.toml`, `apps/web/package.json`, and its lockfile changed together only for a deliberate release.

## Architecture

```text
domain       what a problem and candidate are       pure data
geometry     validity, score, measurements and view deterministic
search       candidate transformations and baselines
workflows    LangGraph control and LLM tools
storage      JSON artefacts
cli / ui     human control and presentation
```

- `domain` and `geometry` never import an LLM client, a workflow library or a UI framework.
- Nothing outside `geometry` reimplements a geometric computation. The frontend draws the view model from `geometry/view.py`, translates world coordinates to pixels, and does not calculate radius, corners, area, distance or verdicts.
- An operator proposes; `evaluate` / `validate` judges. Invalid proposals are allowed.
- Keep workflow teaching files concise, in reading order: `state.py`, `graph.py`, `prompts/`, `manifest.json`; `agent_tools/engine.py` shows how a tool calls the engine.

## Conventions

- Python >= 3.11, `src/` layout, package `paper_obs`, distribution and console command `paper-obs`.
- Core dependencies are `numpy` and `shapely`. Web API and agents are optional extras. Do not add dependencies without a concrete need.
- Use English for identifiers, comments, docstrings and public `docs/`. The product UI is French by default and supports English: add both translations for new strings.
- Explain contracts, units and approximation direction in docstrings; explain non-obvious choices briefly in comments.
- Coordinates are usually of order 1–100. A validity tolerance is around `1e-9`; a descriptive tolerance around `1e-6`. State which you add.
- Pass a seeded `numpy.random.Generator` from the problem for reproducible search.
- Do not add unused placeholders or speculative flags; document missing features instead.

## Verification

Tests should assert observable geometry and JSON contracts rather than implementation text. LLM tests may assert structure, never the wording of a response.

```bash
python -m pytest -q
cd apps/web && npm run typecheck && npm run build
```

On a WSL environment hosted on a Google Drive mount, dependency installation and builds can be slow. Keep `.venv/`, `node_modules/` and generated files inside this repository. `paper-obs serve` binds locally by default; do not expose it on a public address unintentionally.

## Current scope

The engine, web editor, reference catalog, two classical baselines (`lattice` and `basin_hopping`) and four LangGraph workflows (W1–W4, the last with an optional Python sandbox) are implemented. Covering and total-perimeter families are represented, but catalog availability is not proof that a reference is current or that an algorithm can solve that family well. See [problems and catalog](docs/problems-and-catalog.md) and [strategies and runs](docs/strategies-and-runs.md). New workflows and search methods follow after controlled measurements of the existing ones. Heterogeneous per-placement shape families and 3D problems are outside the current model.
