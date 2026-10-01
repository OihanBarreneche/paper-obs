# Writing a workflow

A workflow is a folder. Add one under `src/paper_obs/workflows/`, and the API and the web interface find it without any other file changing: its identifier is the folder name, its run form, diagram and French text come from its manifest, and its runs are written, resumed, stopped and shown like every other run. This page is the contract. The four existing workflows are the worked examples, in increasing order of structure: `basic_agent_loop/`, `strategist_executor/`, `parallel_exploration/`, `research_lab/`.

## The folder

```text
workflows/my_workflow/
  __init__.py       one docstring: what the workflow is, and what to read first
  state.py          the graph state, as a TypedDict
  graph.py          build(...) -> compiled LangGraph graph
  manifest.json     name, parameters, diagram and translations
  prompts/*.md      system prompts and message templates
```

`registry.WORKFLOWS` lists every folder of the package that holds a `manifest.json`; `registry.build` imports `graph.py` only when a run starts, so listing workflows never needs the agents extra. Keep the folder short enough to explain on screen: reach for a LangChain or LangGraph primitive (`create_agent`, its middlewares, structured output, `Send`, subgraphs) before writing a mechanism by hand.

## The `build` contract

```python
def build(problem, *, model, budget, settings=None, guard=None, start=None):
    ...
    return graph.compile()
```

| Argument | What it is |
| --- | --- |
| `problem` | the `Problem` to solve |
| `model` | a LangChain chat model, already configured with the run's key and output ceiling |
| `budget` | the run's `Budget`: `rounds` counts turns from the start of the run, even after a resumption |
| `settings` | the manifest parameters that are not `Budget` fields, as the run form sent them |
| `guard` | the run's `RunGuard` middleware: add it to every agent, it counts calls, tokens, time and cost for the whole run, stops it on a ceiling or on Stop, and answers any tool call a request would carry without a reply, which a provider refuses |
| `start` | the arrangement a resumed run had kept, or `None` |

The runner starts the graph with `session.new_state(...)` plus the run's `round`, `trace` and `notes`, and streams its values: after each super-step it writes the document from `state["trace"]`, `state["round"]`, `state["notes"]` and `state["spend"]`. Your state must therefore carry those fields (copy `basic_agent_loop/state.py`), and each finished turn must append one step to `trace`. Let the shared session write it rather than building the dict yourself.

## Shared helpers

| Helper | Use |
| --- | --- |
| `agent_tools.engine.Workbench`, `basic_agent_tools(bench)` | the engine tools an agent holds, sharing one bench: the arrangement under work, the run's best and the turn's best. Give a parallel agent its own `Workbench(problem=..., candidate=bench.candidate, best=bench.best)` |
| `session.AgentSession(problem, bench)` | `open_turn()` starts a turn on the run's best; `record(state, messages, seconds, note=None, **extra)` returns the state update of a finished turn, `extra` fields such as `plan` going into the step; `merge(branch_bench)` takes in what a parallel agent reached; `lane(name, branch_bench, messages, **extra)` describes one parallel agent's part, for `record(..., lanes=[...])` |
| `session.spent(messages)`, `session.note_of(messages)` | what an agent's messages cost, and its closing note, for a node that does not record a turn (a strategist) |
| `turns.TurnNote(prompt, replies=, tools=)` | the middleware that asks for a last reply without tools: the note the next turn reads |
| `turns.AnswerBrokenCalls()` | the middleware that answers a tool call whose arguments do not parse, which an OpenAI-compatible provider would otherwise refuse: add it to every agent that holds tools |
| `turns.allowance(per_turn, total, spent)` | a turn's share of a ceiling, never more than the run has left |
| `turns.keep_going(state, budget=, guard=, stall_limit=)` | the common rule to end a run: a ceiling, a stop, `give_up`, or too many turns without progress |
| `briefing.opening(template, problem, bench, state, ...)` | fills a message template: `{problem}`, `{reference}`, `{environment}`, `{standing}`, `{journal}`, `{note}`, and your own placeholders passed as keyword arguments |

The geometry is never judged by a model: tools call the engine, and `record` and `lane` read its verdicts.

## The manifest

```json
{
  "name": "W4 · My workflow",
  "description": "One sentence for the workflow picker.",
  "parameters": [
    {"name": "rounds", "label": "Maximum turns", "type": "integer", "default": 0, "help": "..."},
    {"name": "share_reference", "label": "Tell the agent the published record", "type": "flag", "default": 0, "help": "..."},
    {"name": "seconds", "label": "Maximum total duration", "type": "duration", "default": 0, "help": "..."}
  ],
  "nodes": [
    {"id": "turn", "label": "Turn", "kind": "agent", "help": "...", "details": ["..."]},
    {"id": "route", "label": "End the run?", "kind": "route", "help": "..."}
  ],
  "edges": [
    {"from": "turn", "to": "route", "label": ""},
    {"from": "route", "to": "turn", "label": "again"},
    {"from": "route", "to": "end", "label": "done"}
  ],
  "translations": {"fr": {"W4 · My workflow": "W4 · Mon workflow", "...": "..."}}
}
```

- **Name**: the picker lists workflows sorted by name, so a `W<n> · ` prefix sets their order.
- **Parameters** become the run form, in their order. `type` is `integer` or `number` (a text field where a dash means no ceiling, sent as 0), `flag` (a checkbox sent as 0 or 1) or `duration` (minutes and seconds, sent in seconds). A name that is a `Budget` field (`rounds`, `seconds`, `llm_calls`, `tool_calls`, `max_cost`) is a run ceiling; any other name reaches `build` in `settings`, and the API refuses a setting the manifest does not declare. Cost and output tokens are on every form and need no parameter.
- **Nodes** are the graph's nodes, drawn in the diagram. `kind` is `agent` (it holds the engine tools unless `"tools": false`, as a strategist), `engine` (a deterministic step), or `route`: a route node draws the router of the node before it, and its edges' labels are the keys the router returns. `details` fill the diagram's side panel. A node that runs as several agents at once (a `Send` fan-out) carries `"parallel": "<parameter>"`, the parameter giving how many: the diagram draws it as its first copy, a `⋯` and its `n`th, with every arrow fanning out to and back from them; two parallel nodes in a row are joined copy to copy. A node that is a compiled subgraph is drawn as its steps, each named `node:step` (`team:build`, `team:critique`). A node may carry `"position": {"x": ..., "y": ...}` when the automatic layout does not suit it.
- **Edges** use `start` and `end` for the graph's ends; the arrow from `start` to the first node is drawn for you. The diagram places each node one row below the lowest node leading to it, puts nodes of the same row side by side, draws an edge back to an earlier node as a loop, and sets `end` beside the node that ends the run.
- **Translations** give the French of every string above that the interface shows: name, description, parameter labels and help, node labels, help and details, and the word of any agent name used as a lane (`"explorer"` for `explorer 2`).

## What the interface does with it

- The run form, the diagram and the French text come from the manifest alone.
- Tool calls and model replies carry `branch_id`, the name an agent was given (`create_agent(..., name="explorer 2")`); the trace labels each call with it.
- When steps carry `lanes`, the run view adds one tab per lane beside the whole run: each has its own turn list, slider, personal record and trace. A workflow without parallel agents shows no tabs. A lane whose trace gathers several agents lists their names in `agents`; a lane with a `critique` (and its `revision`) shows it as a card in the trace.
- A `plan` field on a step is shown as the turn's plan; `note` is the turn's memory.

## Tests

Two tests cover every workflow without a line of yours: `tests/workflows/test_manifests.py` checks that the manifest draws exactly the compiled graph, and `tests/test_workflow_translations.py` that every string it shows has a French sentence in the manifest. Add an offline test of your own with a scripted model: `tests/workflows/test_basic_agent_loop.py` has the helpers (`call`, `answer`, `grid_spots`), and `test_parallel_exploration.py` shows a model that answers by what it is shown, so parallel agents cannot take each other's turn. Assert the trace and the geometry, never the wording of a reply.

Then start a run from the web interface: the workflow is in the picker once the server restarts.
