# Contributing to Paper Obs

Paper Obs welcomes bug reports, documentation fixes, tests, interface improvements, new geometric problem families and search strategies. Contributions do not have to involve an LLM.

## Forks and pull requests

You are welcome to fork the project and develop your own version. The project's original code is available under the [MIT License](LICENSE); keep its copyright and license notice when redistributing it. A fork does not need to send changes back.

If you would like a change included in Paper Obs, open a pull request (PR). Small, focused PRs are easier to review. For a substantial new objective, workflow, dependency or data import, open an issue first to discuss the contract and scope; a new agent workflow follows [Writing a workflow](docs/writing-a-workflow.md). Straightforward bug fixes and documentation corrections can go directly to a PR.

This is maintained as an independent project with limited review time. There is no guaranteed response or merge schedule. The maintainer decides what fits the project's goals and may request changes, defer or decline a PR. You can continue using and maintaining your fork regardless of that decision.

## Prepare a change

1. Read the [documentation](docs/README.md) and the repository's [contributor and agent instructions](AGENTS.md), especially the architecture boundaries and JSON compatibility rules.
2. Create a branch in your fork and make one coherent change. Explain the problem it solves and any tradeoffs.
3. Add or update tests for behavior and data contracts when relevant. Update both French and English UI strings for user-facing changes.
4. Run the relevant checks:

   ```bash
   python -m pytest -q
   cd apps/web && npm run typecheck && npm run build
   ```

5. In the PR, summarize the change and report which checks you ran. Include before/after screenshots for visible UI changes. Note JSON migrations, new dependencies and data provenance when applicable.

Do not include local runs, credentials, personal notes, generated environments or build output. For catalog additions, link the source, preserve its status and verification date, and check whether third-party coordinates or images may be redistributed. The repository's MIT License does not grant rights over material owned by other sites.

AI-assisted contributions are welcome. Please understand and verify the proposed code and describe its behavior and tests; the contributor remains responsible for the PR.
