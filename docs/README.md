# Paper Obs documentation

This is the public, implementation-oriented documentation. It describes the current project rather than an aspirational specification. Start with [architecture](architecture.md), then read the area relevant to your change.

| Document | What it covers |
| --- | --- |
| [Architecture](architecture.md) | Layer boundaries, JSON data flow and where to extend the system |
| [Problems and catalog](problems-and-catalog.md) | Objectives, shapes, catalog support and reference provenance |
| [Catalog check: 2026-10-14](catalog-update-2026-10-14.md) | Source changes, removed counts, corrections and remaining source anomalies |
| [Precision and performance](precision-and-performance.md) | Exact paths, polygon approximations, tolerances and current measurements |
| [Strategies and runs](strategies-and-runs.md) | Baselines, the LangGraph workflows, budgets and a future solver interface |
| [Research mode](research-mode.md) | Free sessions: an outside agent searches, the engine judges and the lab keeps the journal |
| [Writing a workflow](writing-a-workflow.md) | The folder, `build` contract, manifest and shared helpers of an agent workflow |
| [Development](development.md) | Installation, tests, assets, contributing and deployment boundaries |

The app is usable as a local research workbench. It is not a proof assistant, a continuously updated world-record database or a general-purpose 3D optimizer. A reference number and an engine score can have different units or assumptions; check each family before comparing them.

To propose a change, read [CONTRIBUTING.md](../CONTRIBUTING.md); contributors and coding agents should also read [AGENTS.md](../AGENTS.md). For a quick introduction, see the [project README](../README.md).
