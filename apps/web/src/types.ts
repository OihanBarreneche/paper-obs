/**
 * The JSON documents exchanged with the Python engine.
 *
 * These types mirror the engine's `to_dict` output and are the contract of the
 * whole interface: the browser never derives a coordinate, a radius or a
 * verdict on its own, it displays what the engine sent and sends back the
 * documents it edited. Nothing here may be computed locally — a radius, a
 * bounding box or a score computed in this file would be a second engine.
 */

export type Bounds = [number, number, number, number];
export type Point = [number, number];

export type ArenaNodeDoc =
  | { type: "rect"; width: number; height: number }
  | { type: "disk"; radius: number }
  | { type: "ellipse"; a: number; b: number }
  | { type: "regular_ngon"; sides: number; circumradius: number }
  | { type: "polygon"; points: Point[] }
  | { type: "union" | "difference" | "intersection"; left: ArenaNodeDoc; right: ArenaNodeDoc };

/** `reference_length`: the length a published size of this container measures (a
 * tan's leg, an L's short side), in arena units; the engine then reports the
 * equivalent container side around unit copies. */
export type ArenaDoc = { name: string; shape: ArenaNodeDoc; reference_length?: number };

export type ShapeDoc =
  | { type: "circle"; radius: number }
  | { type: "regular_polygon"; sides: number; side: number }
  | { type: "custom_polygon"; points: Point[] };

/**
 * One entry of the engine's palette: a family, and the shape that choice builds.
 *
 * `sides` is present only on a family whose side count the caller chooses — a
 * regular polygon, whose `shape.sides` is then just the count it starts from.
 */
export type ShapeFamilyDoc = {
  id: string;
  label: string;
  shape: ShapeDoc;
  sides?: number;
};

export type ObjectiveDoc =
  | { type: "maximize_scale"; count: number }
  | { type: "maximize_count"; scale: number }
  | { type: "minimize_container"; count: number; container?: string }
  /**
   * Legacy fixed-arena covering: cover the arena with `count` shapes at the
   * smallest common scale. The engine still accepts it; the catalogue, the editor
   * and the panel no longer offer it.
   */
  | { type: "cover_region"; count: number }
  /**
   * Derive the largest target of `target`'s family contained in the union of
   * `count` unit copies, and maximise its size. This is the one covering model the
   * product exposes: the copies are fixed at scale 1 and the target is measured
   * inside their union, which is also what the canvas draws.
   */
  | { type: "maximize_covered_size"; count: number; target: "circle" | "square" | "triangle" }
  /**
   * Pack `count` shapes of independent sizes and maximise the total perimeter.
   * The common scale is fixed at 1; each placement's own `scale` carries its size.
   */
  | { type: "maximize_total_perimeter"; count: number };

export type RotationDoc = {
  type: "rotation_policy";
  mode: "fixed" | "discrete" | "free";
  angles: number[];
};

export type ConstraintDoc = { type: string; [field: string]: unknown };

export type ProblemDoc = {
  problem_id: string;
  name: string;
  description: string;
  seed: number | null;
  /** Absent exactly when the objective measures its own region: nothing to declare. */
  arena?: ArenaDoc;
  shape: ShapeDoc;
  objective: ObjectiveDoc;
  rotation: RotationDoc;
  constraints: ConstraintDoc[];
  metadata: Record<string, unknown>;
};

export type PlacementDoc = {
  shape_id: string;
  x: number;
  y: number;
  rotation?: number;
  scale?: number;
  /**
   * How to paint this shape: a lower-case `#rrggbb` string, which the engine keeps
   * only if it is exactly that. Absent or null means the theme's own fill, and the
   * engine leaves such a placement out of the document it sends back — so this is
   * decoration carried with the placement, never a geometric decision.
   */
  color?: string | null;
};

export type CandidateDoc = {
  candidate_id: string;
  problem_id: string;
  scale: number;
  origin: string;
  generation: number;
  parents: string[];
  placements: PlacementDoc[];
  metadata: Record<string, unknown>;
};

export type ViolationDoc = {
  kind: string;
  message: string;
  shape_ids: string[];
  magnitude: number;
};

export type ConstraintResultDoc = {
  constraint: string;
  valid: boolean;
  severity: number;
  message: string;
  violations: ViolationDoc[];
};

export type ValidationDoc = {
  valid: boolean;
  severity: number;
  results: ConstraintResultDoc[];
};

export type ScoreDoc = {
  primary: number;
  label: string;
  secondary: Record<string, number>;
};

export type EvaluationDoc = {
  problem_id: string;
  candidate_id: string;
  valid: boolean;
  score: ScoreDoc;
  metrics: Record<string, number>;
  /** Metric the interface puts in front of the others, named by the objective. */
  promoted_metric?: string;
  validation: ValidationDoc;
};

/** One drawable shape: a disc, or a convex polygon, already positioned and sized. */
export type ShapePrimitiveDoc = {
  shape_id: string;
  kind: "circle" | "polygon";
  center: Point;
  bounds: Bounds;
  radius?: number;
  points?: Point[];
  /** Face-centred rotation grip supplied by geometry, in world coordinates. */
  turn_anchor?: Point;
  turn_direction?: Point;
  invalid: boolean;
  /** A symmetry group's representative angle and identifier, assigned by geometry. */
  orientation_group?: number;
  orientation_deg?: number;
  /**
   * The placement's own colour, already validated by the engine, or null (or absent,
   * in a document written before the field existed) for a shape the theme paints. The
   * canvas reads this one field and paints nothing with a colour of its own choosing;
   * a shape the engine marked invalid keeps the violation colours whatever it is
   * painted with.
   */
  color?: string | null;
};

export type VoidDoc = { area: number; bounds: Bounds };

/** How a part combines with everything before it; the first part is the base. */
export type ArenaPartOp = "base" | "union" | "difference" | "intersection";

/**
 * The numbers of one arena primitive, tagged with its kind so a form can render
 * the right fields without knowing anything about arenas.
 */
export type ArenaPartParams =
  | { kind: "rect"; width: number; height: number }
  | { kind: "disk"; radius: number }
  | { kind: "ellipse"; a: number; b: number }
  | { kind: "regular_ngon"; sides: number; circumradius: number }
  | { kind: "polygon"; points: Point[] };

/** One primitive of a composite arena: what an editor moves, resizes and reorders. */
export type ArenaPartDoc = {
  index: number;
  op: ArenaPartOp;
  label: string;
  offset: Point;
  bounds: Bounds;
  /**
   * How far the primitive is turned about its own origin, in degrees, counter-clockwise.
   * The engine turns the part where it stands and places the turned thing afterwards, so
   * the offset is always read in the arena's coordinates whatever the angle.
   */
  angle: number;
  /**
   * The primitive's own outline as SVG path data, in world coordinates — the same
   * frame as the compiled arena path. It is the shape the user sees, so it is what
   * a canvas draws, hit-tests and drags; `bounds` is a convenience box beside it.
   */
  path: string;
  params: ArenaPartParams;
};

export type ArenaViewDoc = {
  path: string;
  bounds: Bounds;
  /** False when the arena is not a stack of primitives and cannot be edited. */
  editable: boolean;
  /**
   * True when the objective owns the arena — a covering's target, a
   * total-perimeter container — so editing it would change the question. The
   * interface reads this to explain *why* the workspace is read-only, rather
   * than showing the generic "not a stack of parts" sentence.
   */
  objective_fixed?: boolean;
  parts: ArenaPartDoc[];
};

export type ViewDoc = {
  problem_id: string;
  candidate_id: string;
  arena: ArenaViewDoc;
  frame: Bounds;
  shapes: ShapePrimitiveDoc[];
  /**
   * The union of the shape footprints, as SVG path data, present only when the
   * view was asked for it. It is the engine's own union — the browser never
   * merges two shapes — and the canvas draws it as an optional overlay.
   */
  union?: { path: string };
  voids?: VoidDoc[];
};

/** The answer to a composition request: the arena document, and its picture. */
export type ArenaPreviewDoc = {
  arena: ArenaDoc;
  path: string;
  parts: ArenaPartDoc[];
  area: number;
  bounds: Bounds;
  summary: string;
};

/**
 * The answer to `POST /api/shape`: the composed outline, as the engine measured it.
 *
 * `path` and `bounds` are read from the shape the engine will draw a placement with,
 * not from the composed frame, so the preview and the packed shape cannot sit in two
 * different places.
 */
export type ShapePreviewDoc = {
  shape: ShapeDoc;
  path: string;
  bounds: Bounds;
  area: number;
  summary: string;
};

/**
 * Ask the engine to compile a stack of primitives into a packable shape.
 *
 * The parts are the arena editor's own — operation, primitive numbers, offset,
 * angle — so one vocabulary builds both, and the browser never assembles a tree.
 */
export type ComposeShapeRequest = ComposeArenaRequest;

/**
 * One primitive of a composed shape, exactly as the composer holds it.
 *
 * The engine reads the same four fields for an arena part, so one record builds both.
 * This tree lives in the browser only: it is what makes a composed shape editable again,
 * while the authoritative definition the engine judges stays the outline in `shape`.
 */
export type ComposerPartDoc = {
  op: ArenaPartOp;
  params: ArenaPartParams;
  offset: Point;
  angle: number;
};

/**
 * One composed shape kept in the browser's library.
 *
 * The `shape` is a plain ShapeDoc, so a composed shape is used in a problem exactly
 * like a built-in one; `path` and `bounds` are kept beside it so the library draws a
 * thumbnail without asking the engine again. This document lives in localStorage and
 * is never sent to the engine whole: only its `shape` travels, inside a problem.
 */
export type ComposedShapeDoc = {
  id: string;
  name: string;
  shape: ShapeDoc;
  /** The stack that produced `shape`, kept so the composer can reopen it. */
  parts: ComposerPartDoc[];
  path: string;
  bounds: Bounds;
  area: number;
  summary: string;
};

/**
 * The scale interval the engine considers worth exploring.
 *
 * `fixed` is the common scale the objective pins, when it pins one, or null when
 * the scale is free. A total-perimeter problem reports both: a real interval over a
 * copy's local size *and* the common scale fixed at 1, because those are two
 * different numbers. The interface shows `fixed` rather than a slider when it is
 * set, so a control never offers to drive a number the objective refuses.
 */
export type ScaleBoundsDoc = {
  low: number;
  high: number;
  rationale: string;
  fixed?: number | null;
};

/**
 * What the left half of the window is showing.
 *
 * `shapes` and `arena` are workspaces the user edits; `run` is a workspace a
 * workflow drives — the canvas replays the arrangement a run reached, and the
 * panel beside it starts runs and scrubs through their turns.
 */
export type WorkspaceMode = "shapes" | "arena" | "compose" | "run" | "search";

/** The best valid score seen since the current problem was loaded. */
export type BestScoreDoc = { score: number; label: string; candidateId: string };

export type SummaryDoc = {
  problem: string;
  arena: string;
  shape: string;
  objective: string;
  score: string;
  verdict: "valid" | "invalid";
};

/**
 * One rung of the ladder, as the picker shows it.
 *
 * `rung` is the order the backend wants the instances tried in, and `why` is the
 * reason it sits there: what the instance proves, not how hard it feels.
 */
export type ExampleSummaryDoc = {
  problem_id: string;
  name: string;
  description: string;
  arena: string;
  shape: string;
  objective: string;
  objective_kind: string;
  rung: number | null;
  why: string;
};

/** What every mutating route answers: the candidate, its verdict, and its picture. */
export type VerdictDoc = {
  problem_id: string;
  candidate: CandidateDoc;
  evaluation: EvaluationDoc;
  view: ViewDoc;
  scale_bounds: ScaleBoundsDoc;
  summary: SummaryDoc;
};

export type ExampleDoc = {
  problem: ProblemDoc;
  /** The arrangement the example is known for, or null when it ships none. */
  candidate: CandidateDoc | null;
  scale_bounds: ScaleBoundsDoc;
  text: string;
};

export type InitStrategy = "grid" | "staggered" | "random" | "varied" | "cover";

/**
 * What the engine says can be built for a problem.
 *
 * `initialize` and `search` list what actually applies to this shape, arena
 * and objective; an empty list is the engine saying a control cannot be
 * honoured, and `reason` is its own sentence explaining why. The interface
 * hides that control rather than offering one that can only fail.
 */
export type CapabilitiesDoc = {
  initialize: InitStrategy[];
  search: string[];
  reason: string;
  /**
   * Whether the objective owns its arena. Reported by the engine, so a client
   * that has no candidate yet still knows the arena workspace is read-only.
   */
  arena_fixed?: boolean;
};

export type InitRequest = {
  problem: ProblemDoc;
  strategy: InitStrategy;
  scale?: number | null;
  count?: number | null;
  with_voids?: boolean;
  with_union?: boolean;
};

export type EvaluateRequest = {
  problem: ProblemDoc;
  candidate: CandidateDoc;
  with_voids?: boolean;
  /** Ask the engine to include the union of the shape footprints in the view. */
  with_union?: boolean;
  /** Optional manual-drag contact guide: selected ids and a world-length limit. */
  snap_shape_ids?: string[];
  snap_distance?: number;
  snap_motion?: Point;
};

/**
 * Ask the engine to compile a stack of primitives into an arena.
 *
 * A part is sent back exactly as the engine described it — operation, primitive
 * numbers, offset — so that assembling arena nodes stays on the server side,
 * where the arena's own JSON is defined.
 */
export type ComposeArenaRequest = {
  parts: { op: ArenaPartOp; params: ArenaPartParams; offset: Point; angle: number }[];
};

/** One point of a baseline's curve: what the run had reached after that judgement. */
export type ConvergenceStepDoc = {
  /** Engine judgements billed so far, 1-based. */
  evaluations: number;
  /** Primary score of the best candidate seen so far. */
  best_primary: number;
  /** The incumbent's measurement the objective promotes, such as a container's side. */
  best_measure: number;
  /** Whether that best candidate is valid. */
  best_valid: boolean;
  /** Total violation severity of that best candidate, 0 when it is valid. */
  severity: number;
  /** Whether this evaluation replaced the incumbent. */
  accepted: boolean;
};

/**
 * One run of one search strategy, in full.
 *
 * `steps` is the curve and `incumbents` the candidates behind it: only the ones
 * the engine ranked higher, in order, so a run of thousands of judgements stays
 * thousands of numbers and a handful of candidates.
 */
export type ConvergenceDoc = {
  strategy: string;
  problem_id: string;
  seed: number;
  budget: number;
  /** Judgements actually spent, never more than the budget asked for. */
  evaluations: number;
  steps: ConvergenceStepDoc[];
  /** The best candidate of the run, judged and drawn like any other. */
  best: CandidateDoc;
  incumbents: CandidateDoc[];
};

/** What `POST /api/search` answers: the curve, the engine's summary, and the verdict. */
export type SearchResponseDoc = {
  convergence: ConvergenceDoc;
  /** The engine's one-line description of the run, shown verbatim. */
  summary: string;
  verdict: VerdictDoc;
};

/** One reachable model provider, as the backend describes it. */
export type ProviderDoc = {
  name: string;
  base_url: string;
  /** The *name* of the environment variable holding a key — never a key. */
  api_key_env: string;
  models: string[];
  note: string;
  /** False for a local server that ignores the key, such as Ollama. */
  needs_key: boolean;
  /** False for an endpoint that refuses a temperature; the run then uses its default. */
  accepts_temperature: boolean;
  /** True for a CLI signed in to a monthly subscription (Claude Code, Codex): no key, no token price. */
  subscription: boolean;
};

/**
 * What ``GET /api/providers`` answers: the table, and where a key already is.
 *
 * ``key_present`` says whether a key is configured, per provider and for the lab's
 * own variable. The key itself is never part of an answer, by design: a browser
 * only needs to know whether to ask for one.
 */
export type ProvidersDoc = {
  providers: ProviderDoc[];
  key_present: {
    environment_key: string;
    environment_key_set: boolean;
    providers: Record<string, boolean>;
  };
};

/**
 * What `POST /api/providers/models` answers: the ids one endpoint served, and nothing else.
 *
 * The answer depends on the key and on a catalogue that moves weekly, so it is neither
 * cached nor written down, and the key it was asked with is not part of it.
 */
export type ProviderModelsDoc = {
  provider: string;
  models: string[];
};

/** One ceiling of a run, as the workflow's own manifest declares it. */
export type WorkflowParameterDoc = {
  name: string;
  /** What the run form calls it, in English; the manifest carries its translations. */
  label: string;
  /** A number field, a checkbox sending 0 or 1, or minutes and seconds sending seconds. */
  type: "integer" | "number" | "flag" | "duration";
  default: number;
  help: string;
};

/** One step of a workflow: what it does, and whether it costs a model call. */
export type WorkflowNodeDoc = {
  id: string;
  label: string;
  kind: string;
  help: string;
  /** False for an agent that holds no tools, such as a strategist. */
  tools?: boolean;
  /** What the step does, one sentence each, for the diagram's detail panel. */
  details?: string[];
  /** The parameter saying how many copies of the step run at once: the diagram draws 1 ⋯ n. */
  parallel?: string;
  /** Where the diagram draws it, when the automatic layout would not do. */
  position?: { x: number; y: number };
};

/** How one step leads to another; \`to\` may be the end rather than a node. */
export type WorkflowEdgeDoc = { from: string; to: string; label: string };

/**
 * A workflow the backend can run, as the backend describes it.
 *
 * The topology arrives as data — nodes and edges — so the panel draws the shape of
 * a workflow it does not know: it adds no node, and decides nothing about what an
 * edge means. \`parameters\` are the ceilings of a run, with the defaults the
 * manifest gives them.
 */
export type WorkflowManifestDoc = {
  id: string;
  name: string;
  description: string;
  parameters: WorkflowParameterDoc[];
  nodes: WorkflowNodeDoc[];
  edges: WorkflowEdgeDoc[];
  /** Every English string above with its translation, by language: `{fr: {English: French}}`. */
  translations?: Record<string, Record<string, string>>;
};

/** A JSON Schema, as a chat model receives a tool's arguments. */
export type JsonSchemaDoc = {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
  items?: JsonSchemaDoc;
  anyOf?: JsonSchemaDoc[];
  properties?: Record<string, JsonSchemaDoc>;
  required?: string[];
};

/**
 * One tool a workflow's agents may call, read from the tool itself: its docstring as
 * paragraphs, the argument schema a model is sent, and the objectives it is offered on.
 */
export type AgentToolDoc = {
  name: string;
  description: string[];
  parameters: JsonSchemaDoc;
  objectives: string[];
  /** A call on a small problem, with the reply the tool really gave; null when none is written. */
  example: AgentToolExampleDoc | null;
};

export type AgentToolExampleDoc = {
  caption: string;
  arguments: Record<string, unknown>;
  reply: string;
};

export type WorkflowToolsDoc = { objectives: string[]; tools: AgentToolDoc[] };

/** What one run may spend: the parameter names the manifest declares. */
export type RunBudgetDoc = {
  rounds: number;
  llm_calls: number;
  tool_calls: number;
  seconds: number;
  max_cost?: number | null;
};

/**
 * What a run has spent so far, counted in calls.
 *
 * Tokens and money come from provider usage and configured prices.
 */
export type SpendDoc = {
  llm_calls: number;
  tool_calls: number;
  seconds: number;
  tokens_in: number;
  tokens_out: number;
  tokens_cached?: number;
  /** Seconds spent waiting for the provider; the rest of the duration is the lab's own work. */
  model_seconds?: number;
  cost: number | null;
};

/**
 * One turn of a run, as the run document keeps it.
 *
 * The engine judged the turn, so \`valid\` and \`primary\` are its verdict, not a
 * reading of the arrangement; \`accepted\` says whether that verdict beat the
 * incumbent. \`candidate\` is the arrangement itself, kept only when it was
 * accepted — an identifier alone draws nothing, and the replay needs the geometry.
 */
export type AgentRunStepDoc = {
  round: number;
  outcome: string;
  /** Why the turn ended as it did, in the agent's own words when it had any. */
  reason: string;
  candidate_id: string | null;
  valid: boolean | null;
  primary: number | null;
  accepted: boolean;
  tool_calls: number;
  llm_calls: number;
  /** What the turn actually did, in order: a count says how long, the names say how. */
  tools: string[];
  candidate: CandidateDoc | null;
  /** The engine's document on this turn, kept so a refused attempt can be read back. */
  verdict: EvaluationDoc | null;
  /** The note this turn ended on, empty when it wrote none; absent from older runs. */
  note?: string;
  /** The plan a strategist gave the turn, in a workflow that has one. */
  plan?: string;
  /** What the agent had written down by the end of this turn: its only memory. */
  notes: string[];
  /** Ordered tool calls with their inputs, outputs and intermediate candidates. */
  events?: AgentToolEventDoc[];
  /** Assistant text and provider-visible reasoning, when returned, with the agent that wrote it. */
  model_messages?: { index: number; message_index?: number; branch_id?: string | null; content: string;
    reasoning: string | null; tool_calls?: number; tokens_in?: number | null; tokens_out?: number | null }[];
  /** What each parallel agent of the turn reached, in a workflow that runs several. */
  lanes?: AgentLaneDoc[];
};

/**
 * One parallel agent's part in a turn: its best arrangement with the engine's verdict, and
 * whether it beat that agent's own best of earlier turns. `id` is its name, which its tool
 * calls and replies carry as `branch_id`.
 */
export type AgentLaneDoc = {
  id: string;
  candidate: CandidateDoc | null;
  valid: boolean | null;
  primary: number | null;
  accepted: boolean;
  note: string;
  verdict: EvaluationDoc | null;
  /** The idea it was given, in a workflow whose agents each get one. */
  idea?: string;
  /** The agents whose replies and tool calls make up this lane, when it is not one agent alone. */
  agents?: string[];
  /** What a critic found in the lane's arrangement, in a workflow that criticises. */
  critique?: { flaw: string; evidence: string; move: string };
  /** How the builder answered the critique: its best before and after, and whether it gained. */
  revision?: { before: number | null; after: number | null; paid: boolean; answer: string };
};

export type AgentToolEventDoc = {
  index: number;
  message_index?: number;
  node_id: string;
  branch_id: string | null;
  tool: string;
  input: unknown;
  result: unknown;
  candidate: CandidateDoc | null;
  status: "pending" | "done" | "error";
};

/** One run in full: what it was asked, every turn it took, and what it reached. */
export type AgentRunDoc = {
  kind: string;
  format: number;
  run_id: string;
  /** A run shipped with the lab for reading, which cannot be resumed. */
  example?: boolean;
  /** Editable label saved with the run; older files receive a fallback on read. */
  name?: string;
  workflow: string;
  workflow_name: string;
  problem_id: string;
  /** Exact input of this run. Older files do not contain it. */
  problem?: ProblemDoc;
  /** The model that answered, without its key: a run file never carries one. */
  model: Record<string, unknown>;
  budget: RunBudgetDoc;
  /** The workflow's own settings, past the shared ceilings. Absent in older run files. */
  settings?: Record<string, number>;
  /** \`running\` while the run is being written, then how it ended. */
  status: "running" | "done" | "failed" | "stopped";
  stopped_by?: string | null;
  /** A stop was asked for and the run has not written its end yet. */
  stop_requested?: boolean;
  /** Why a run stopped, in the backend's own words, or null when it did not fail. */
  error: string | null;
  round: number;
  seconds: number;
  spend: SpendDoc;
  steps: AgentRunStepDoc[];
  /** The agent's notes at the end of the run, the same list its last turn ended on. */
  notes: string[];
  champion: CandidateDoc | null;
};

/** One line of the run listing, enough to pick a past run without reading it. */
/** One line of a free research session's journal (docs/research-mode.md): a note the agent
 * wrote, or an arrangement it submitted and the engine judged. Only an improvement keeps its
 * arrangement. `metric` is the record's unit, or the engine metric without a record. */
export type ResearchEntryDoc =
  | { kind: "note"; at: string; text: string }
  | { kind: "submission"; at: string; index: number; note: string; valid: boolean; primary: number;
      measure: number | null; metric: string; record_gap: number | null; accepted: boolean;
      violations: string[]; candidate: CandidateDoc | null };

export type ResearchBestDoc = { at: string; index: number; measure: number | null; metric: string;
  record_gap: number | null; primary: number };

/** A session as the picker lists it; `track` holds each new best as [submission, measure, gap]. */
export type ResearchSessionSummaryDoc = {
  session_id: string; name: string; agent: string; status: string; created: string; updated: string;
  problem_id: string; problem_name: string; submissions: number; best: ResearchBestDoc | null;
  track: [number, number | null, number | null][];
  /** A session shipped with the lab for reading, such as a record hunt reconstructed afterwards. */
  example: boolean;
};

export type ResearchSessionDoc = {
  session_id: string; name: string; agent: string; goal: string; status: string;
  created_at: string; updated_at: string; problem_id: string; problem: ProblemDoc;
  journal: ResearchEntryDoc[]; best: ResearchBestDoc | null; champion: CandidateDoc | null;
};

export type AgentRunSummaryDoc = {
  run_id: string;
  /** When the run was written, in UTC: what a picker sorts a history by. */
  created: string;
  /** When the run last started, first or resumed, in UTC: how long a running one has been going. */
  started: string;
  name?: string;
  workflow: string;
  problem_id: string;
  problem_name: string;
  status: string;
  round: number;
  seconds: number;
  spend: SpendDoc;
  /** The run's best: the engine's primary score, and the measurement its objective promotes. */
  champion: { valid: boolean | null; primary: number | null; measure: number | null } | null;
  provider: string;
  model: string;
  /** How far the run's best is from the problem's published record, as a signed fraction:
   * positive when it beats the record, null without a record the engine can compare with. */
  record_gap: number | null;
  /** Each new best as [turn index, score, gap to the record]: how the run progressed. */
  track: [number, number | null, number | null][];
  /** Whether the run was deleted: out of the pickers, still counted in the statistics, restorable. */
  deleted: boolean;
  /** A run shipped with the lab for reading: listed, never counted in the statistics. */
  example: boolean;
};

/**
 * Ask the backend for a run.
 *
 * The key is optional and travels with this request only: the backend uses it for
 * this run and never writes it down.
 */
export type StartAgentRunRequest = {
  problem: ProblemDoc;
  workflow: string;
  name?: string;
  /** A finished run to take up again where it stopped, in its own document. */
  resume?: string;
  provider?: string;
  model?: string;
  base_url?: string;
  max_tokens?: number;
  /** Sampling temperature from 0 to 2; left out, the run uses 0. */
  temperature?: number;
  api_key?: string;
  /** What a million tokens cost in and out, when the caller knows the price. */
  cost_per_million_in?: number;
  cost_per_million_out?: number;
  cost_per_million_cached?: number;
  budget: Record<string, number>;
};
