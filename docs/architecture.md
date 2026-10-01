# Architecture

Paper Obs has one judge for all strategies. The same `Problem` and `Candidate` JSON can reach the geometry engine from the CLI, web editor, a baseline or a LangGraph tool. This is why a run's image, violations and score can be inspected independently of how the candidate was produced.

```text
Problem JSON + Candidate JSON
          ↓
     domain objects
          ↓
  geometry.evaluate / validate
          ├── verdict, score, violations, metrics
          ├── geometry.view → API view model → React canvas
          └── geometry.rendering → SVG
```

| Layer | Responsibility | Import boundary |
| --- | --- | --- |
| `src/paper_obs/domain/` | Shapes, arenas, objectives, constraints, placements, JSON serialization and seeded generation | Pure data; no UI or LLM |
| `geometry/` | Compile geometry, judge validity, score, measure, analyze gaps, build a view and render SVG; an exact rational check for claimed records (`exact_check.py`) | Deterministic; no UI or LLM |
| `search/` | Generate and alter candidates; run classical baselines; exact contact refinement (`refine.py`, optional `research` extra) | Can ask geometry to judge |
| `workflows/`, `agent_tools/`, `llm/` | LangGraph control, provider calls and engine-backed tools | Optional `agents` extra |
| `storage/` | Read and write JSON artefacts | No strategy decisions |
| `research/` | Free research sessions: log what an outside agent submits, judged by the engine ([research mode](research-mode.md)); dissection leads on the catalog; submission pictures | No search of its own; no LLM; pictures need the optional `research` extra |
| `api/`, `cli.py`, `apps/web/` | User controls and presentation | No independent geometric verdicts |

An operator can propose an invalid candidate; `geometry.evaluate` alone decides validity and ranking. The browser receives coordinates, paths and measurements from `geometry.view` and converts world coordinates to pixels. JSON is a public contract: `to_dict` and `from_dict` explicitly preserve stored fields.

The video-facing workflow is intentionally small. Read `workflows/basic_agent_loop/state.py`, `graph.py`, `prompts/placer.md`, `manifest.json`, then `agent_tools/engine.py`. A *turn* is one pass of a fresh agent over the geometry tools, which share one `Workbench`: the arrangement under work, the run's best and the turn's best. `graph.py` is what decides whether the run takes another, and `workflows/session.py` turns a finished turn into the run's step; provider details and the run monitor also live outside the teaching files. The second workflow, `workflows/strategist_executor/`, reads the same way; what the turn-based workflows share (the closing reply, the per-turn allowance, the rule that ends a run) is in `workflows/turns.py`.

The API accepts full problem and candidate documents for engine requests. The Python package needs only NumPy and Shapely; FastAPI, the agent stack and research mode's tools (SciPy, Pillow, resvg) are optional extras. A built React frontend is served separately by the local API server.

## Extension points

- New objective or constraint: add a domain contract and the corresponding geometry measurements and tests. Keep the stored discriminator stable.
- New shape or arena primitive: add domain serialization, geometry compilation/predicates and a view model, then expose it in the editor.
- New search method: transform candidates, call the engine for every judgement, and record the cost and best valid candidate.
- New workflow: add a small manifest/state/graph/prompt package; use engine tools rather than duplicating geometry. The manifest's steps and arrows are hand-written for the diagram, and `tests/workflows/test_manifests.py` checks them against the compiled graph's `get_graph()`: a `route` step stands for the conditional edges of the step before it, and each arrow's label is the router's answer. A compiled subgraph used as a node is compared step by step.

The current domain uses one shape family per problem. Placements may have local scales for maximum-total-perimeter problems, but a problem cannot yet assign unrelated shape families to individual placements.
