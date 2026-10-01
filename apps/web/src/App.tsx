/**
 * The application: it owns the documents being edited and nothing else.
 *
 * The problem and the candidate live here, plus the two things a direct
 * manipulation editor cannot do without: a selection and a history. Every edit
 * is sent to the engine, which answers with a fresh candidate, a verdict and a
 * picture — so what is on screen is always what was judged, and no geometry is
 * computed in the browser.
 *
 * Three rules shape the code below.
 *
 * *Requests are throttled by in-flight, not by a timer.* While one verdict is
 * being computed, newer edits replace the pending one and the last state is
 * always sent when the current answer returns. A drag therefore keeps at most
 * one round trip in flight and never shows a stale picture.
 *
 * *History records gestures, not keystrokes.* A drag snapshots the candidate
 * once, when it starts, and pushes that snapshot when it ends; dragging a shape
 * back and forth is one undoable action, not eighty. Discrete edits — delete,
 * duplicate, place, clear, initialise — snapshot immediately.
 *
 * *The layout does not move.* The verdict and the editor of whatever is being
 * edited stay in the same column, and switching between the shapes and the
 * arena changes which editor is shown there and which canvas is drawn — never
 * where a panel sits. A layout that rearranges itself costs the reader the
 * place they had found for every number.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";

import { ApiError, api } from "./api";
import {
  newComposedShapeId,
  readComposedShapes,
  removeComposedShape,
  saveComposedShapes,
  upsertComposedShape,
} from "./composedShapes";
import { ARENA_BASE, ELEMENTARY_SHAPES, describePrimitive, elementaryShape, primitiveFromMenu } from "./arenaPrimitives";
import { MEASURED_COVER_TARGETS, measureCoverTargets } from "./equalCopiesCatalog";
import type { CoverTarget } from "./equalCopiesCatalog";
import { ArenaCanvas } from "./components/ArenaCanvas";
import { ArenaPanel } from "./components/ArenaPanel";
import { CreateMenu } from "./components/CreateMenu";
import { ShapeComposerPanel } from "./components/ShapeComposer";
import { ShapeLibrary } from "./components/ShapeLibrary";
import type { CreateGroup, CreateItem } from "./components/CreateMenu";
import { PackingCanvas } from "./components/PackingCanvas";
import { ImportPanel } from "./components/ImportPanel";
import type { ImportedPositions } from "./components/ImportPanel";
import { DEFAULT_OBJECTIVE_KIND, ProblemEditor } from "./components/ProblemEditor";
import { ProviderPanel, readModelSettings } from "./components/ProviderPanel";
import { RunWorkspace } from "./components/RunWorkspace";
import { QuickStart, QUICK_START_STEPS } from "./components/QuickStart";
import { SearchWorkspace } from "./components/SearchWorkspace";
import { ReferencePanel } from "./components/ReferencePanel";
import { NotesPanel } from "./components/NotesPanel";
import { PALETTE, ShapeInspector } from "./components/ShapeInspector";
import { StatusPanel } from "./components/StatusPanel";
import { StatisticsPage } from "./components/StatisticsPage";
import { Toolbar } from "./components/Toolbar";
import { WorkspaceTabs } from "./components/WorkspaceTabs";
import { PAGE_EDGE_WIDTH, pageEdges } from "./workspaceTabs";
import { addTranslations, useI18n } from "./i18n";
import { useViewport } from "./viewport";
import { builtInReference, readReference, SQUARE_RECORDS, squareProblem } from "./catalog";
import type { ProblemReference } from "./catalog";
import { STARTER_CATEGORY_ID, includeProfile, readLibrary, removeCategory, removeProfile, replaceProfile, saveLibrary } from "./profileLibrary";
import type {
  AgentRunDoc,
  AgentRunStepDoc,
  AgentRunSummaryDoc,
  ArenaPartDoc,
  ArenaPartOp,
  ArenaPartParams,
  ArenaPreviewDoc,
  BestScoreDoc,
  Bounds,
  CapabilitiesDoc,
  CandidateDoc,
  ComposedShapeDoc,
  ComposerPartDoc,
  ConvergenceDoc,
  EvaluationDoc,
  ExampleSummaryDoc,
  InitStrategy,
  ObjectiveDoc,
  PlacementDoc,
  Point,
  ProblemDoc,
  ScaleBoundsDoc,
  ShapeDoc,
  ShapeFamilyDoc,
  ShapePreviewDoc,
  SummaryDoc,
  VerdictDoc,
  ViewDoc,
  WorkflowManifestDoc,
  WorkspaceMode,
} from "./types";

/** How many states the undo stack keeps before the oldest is dropped. */
const HISTORY_LIMIT = 60;

/** How often a run being watched is read back, in milliseconds. */
const RUN_POLL_MS = 1000;
const REFERENCE_STORAGE = "paper-obs-reference-edits-v1";
const ACTIVE_PROFILE_STORAGE = "paper-obs-active-profile";

function readReferenceEdits(): Record<string, ProblemReference> {
  try {
    const saved = JSON.parse(window.localStorage.getItem(REFERENCE_STORAGE) ?? "{}") as Record<string, unknown>;
    return Object.fromEntries(Object.entries(saved).flatMap(([id, value]) => {
      const record = readReference(value);
      return record === null ? [] : [[id, record]];
    }));
  } catch { return {}; }
}

type Pending = { problem: ProblemDoc; candidate: CandidateDoc; refit?: boolean; snap?: { ids: string[]; distance: number; motion: Point } };

/** One undoable state: what was judged, and the problem it was judged against. */
type Snapshot = { problem: ProblemDoc; candidate: CandidateDoc };

/** What the engine needs to compile one part: operation, primitive, position, turn. */
type PartRequest = { op: ArenaPartOp; params: ArenaPartParams; offset: Point; angle: number };

/**
 * What Ctrl+C put aside, and which workspace put it there.
 *
 * The buffer is the window's own, not the system clipboard: copying a shape must
 * never overwrite the text someone copied from another application, and pasting
 * here must never turn pasted prose into a placement. A workspace only reads the
 * kind it wrote, so a shape copied in the shapes editor cannot become an arena
 * primitive by accident.
 */
type Clipboard =
  | { kind: "shapes"; placements: PlacementDoc[] }
  | { kind: "arena"; part: ArenaPartDoc }
  | { kind: "compose"; part: ArenaPartDoc };

/**
 * One part's own copy, at a new index and under a new operation.
 *
 * A polygon's points are cloned rather than shared, so editing the pasted part
 * can never show in the part it came from; everything else — params, offset,
 * angle — is carried over unchanged, which is what "keeps its properties" means.
 */
function copyPart(part: ArenaPartDoc, index: number, op: ArenaPartOp): ArenaPartDoc {
  return {
    ...part,
    index,
    op,
    offset: [part.offset[0], part.offset[1]],
    params:
      part.params.kind === "polygon"
        ? { kind: "polygon", points: part.params.points.map((point): Point => [point[0], point[1]]) }
        : { ...part.params },
  };
}

/** A click that asked for the creation menu: where it landed, and where to show it. */
type Create = { world: Point; at: Point };

/** The polygon being drawn on the arena canvas, in world coordinates. */
type Drawing = { op: ArenaPartOp; points: Point[] };

/** A price typed in the model dialog, or undefined: an empty field is not a price of zero. */
function money(typed: string): number | undefined {
  const value = Number(typed);
  return typed.trim() !== "" && Number.isFinite(value) && value >= 0 ? value : undefined;
}

/** Read a typed temperature: a number from 0 to 2, or nothing so the run keeps its default. */
function temperature(typed: string): number | undefined {
  const value = Number(typed);
  return typed.trim() !== "" && Number.isFinite(value) && value >= 0 && value <= 2 ? value : undefined;
}

function describeError(cause: unknown): string {
  if (cause instanceof ApiError) {
    return cause.message;
  }
  return cause instanceof Error ? cause.message : String(cause);
}

/** Mint an identifier for a shape added by hand, following the engine's convention. */
function nextShapeId(placements: PlacementDoc[]): string {
  let highest = -1;
  for (const placement of placements) {
    const match = /^s(\d+)$/.exec(placement.shape_id);
    if (match !== null) {
      highest = Math.max(highest, Number(match[1]));
    }
  }
  return `s${String(highest + 1).padStart(3, "0")}`;
}

/** Whether two shape documents describe the same family at the same size. */
function sameShape(left: ShapeDoc, right: ShapeDoc): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

/**
 * One workspace's menu entries, from the one elementary-shape list.
 *
 * The identifier carries the workspace, so the pick knows which stack to add to;
 * the entry itself is the same in every workspace.
 */
function elementaryItems(workspace: "compose" | "arena"): CreateItem[] {
  return ELEMENTARY_SHAPES.filter((entry) => entry.workspaces.includes(workspace)).map((entry) => ({
    id: `${workspace}:${entry.id}`,
    label: entry.label,
    sides: entry.sides,
    axes: entry.axes,
  }));
}

/**
 * The input types a mouse drives, as opposed to the ones a keyboard types into.
 *
 * An `<input>` that is not one of these — including one with no `type` at all — is
 * read as a field with text in it, so a type this application never uses cannot take
 * a shortcut away from a selection by mistake.
 */
const POINTED_INPUT_TYPES: Record<string, true> = {
  button: true,
  checkbox: true,
  color: true,
  file: true,
  radio: true,
  range: true,
  reset: true,
  submit: true,
};

/**
 * The initialisers the engine defines for each shape family.
 *
 * A staggered lattice is a hexagonal arrangement of discs and of nothing else: the
 * engine refuses it for every other family in its own words, so offering it there
 * would be offering a refusal. A grid and a random draw are defined for all of them.
 */
const INIT_STRATEGIES: Record<ShapeDoc["type"], InitStrategy[]> = {
  circle: ["grid", "staggered", "random", "varied", "cover"],
  regular_polygon: ["grid", "random", "varied", "cover"],
  custom_polygon: ["grid", "random", "varied", "cover"],
};

/**
 * The initialisers an objective replaces the family's list with.
 *
 * A total-perimeter problem gives every copy its own size, and only the varied
 * start builds one: a grid or a scatter sizes every copy alike and proposes a
 * candidate the objective's fixed common scale cannot describe. The engine says
 * the same thing in its capability list, and this is the fallback a document uses
 * while that answer is still in flight, so a family never opens on an operator its
 * objective cannot honour.
 */
const OBJECTIVE_STRATEGIES: Partial<Record<ObjectiveDoc["type"], InitStrategy[]>> = {
  maximize_total_perimeter: ["varied"],
  cover_region: ["cover"],
  // The derived covering hands unit copies to a fill, so the two family-safe
  // starts are the fallback while the engine's own capability answer is in flight.
  maximize_covered_size: ["grid", "random"],
};

/** The engine's description of a part, as the request that rebuilds it. */
function partRequest(part: ArenaPartDoc): PartRequest {
  return { op: part.op, params: part.params, offset: part.offset, angle: part.angle };
}

/**
 * The window a composer with no primitive yet looks through.
 *
 * A composition starts from nothing, so the engine has no frame to answer with:
 * the canvas shows this bare grid until the first primitive gives it a shape.
 */
const EMPTY_COMPOSER_FRAME: Bounds = [-6, -6, 6, 6];

/**
 * One stored composer part as the editor holds it.
 *
 * The engine has not described it yet — there is no path and no box — so those two
 * stand empty until the first compile answers; everything a field edits is here.
 */
function seedPart(part: ComposerPartDoc, index: number, t: (english: string) => string): ArenaPartDoc {
  return {
    index,
    op: part.op,
    label: describePrimitive(part.params, t),
    offset: part.offset,
    angle: part.angle,
    bounds: [0, 0, 0, 0],
    path: "",
    params: part.params,
  };
}

/**
 * Whether a covering's verdict should carry the engine's union of the copies.
 *
 * The union is the optional overlay the canvas offers for a covering; asking for
 * it at every verdict that draws one keeps the toggle a matter of paint rather
 * than another round trip. The derived covering is the one covering model the
 * product exposes; a document that already carries the legacy fixed-arena
 * objective still gets the same overlay. Every other objective asks for nothing.
 */
function wantsUnion(problem: ProblemDoc | null): boolean {
  return problem !== null
    && (problem.objective.type === "maximize_covered_size" || problem.objective.type === "cover_region");
}

/**
 * Whether the packing canvas should draw its copies translucent and multiplied.
 *
 * Only a covering needs it "a priori": its copies overlap by meaning, and drawing
 * them translucent lets the arena show through and a point covered by several
 * copies darken with the number of layers over it. The owner asked for covering
 * only, so a total-perimeter family -- which may overlap too -- and every packing
 * draw solid copies. The arena and composer canvases never take this.
 */
function wantsTranslucentCopies(problem: ProblemDoc | null): boolean {
  return problem !== null
    && (problem.objective.type === "maximize_covered_size" || problem.objective.type === "cover_region");
}

export function App() {
  const { t } = useI18n();
  const [examples, setExamples] = useState<ExampleSummaryDoc[]>([]);
  const [library, setLibrary] = useState(readLibrary);
  const [categoryId, setCategoryId] = useState(() => {
    const saved = window.localStorage.getItem("paper-obs-active-category");
    return library.categories.some((category) => category.id === saved)
      ? saved ?? STARTER_CATEGORY_ID : library.categories[0]?.id ?? STARTER_CATEGORY_ID;
  });
  const [referenceEdits, setReferenceEdits] = useState(readReferenceEdits);
  const [palette, setPalette] = useState<ShapeFamilyDoc[]>([]);
  // The cover targets the engine measures, asked once at start-up: a covering
  // family opens on the derived reading only for a target the engine honours, and
  // the answer decides both what a catalogue card builds and what the problem
  // editor offers. The fallback is the set the engine is known to measure.
  const [coverTargets, setCoverTargets] = useState<readonly CoverTarget[]>(MEASURED_COVER_TARGETS);
  // The composed shapes are the browser's own: the engine compiled each outline, and
  // the stack that produced it is kept here so the composer can reopen it.
  const [composed, setComposed] = useState(readComposedShapes);
  const [editingComposed, setEditingComposed] = useState<ComposedShapeDoc | null>(null);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [composedSpot, setComposedSpot] = useState<Point | null>(null);
  // The composer's own stack, and the two answers the engine gives about it: the
  // editable picture from `/api/arena`, and the packable shape from `/api/shape`.
  const [composerName, setComposerName] = useState("");
  const [composerParts, setComposerParts] = useState<ArenaPartDoc[]>([]);
  const [composerView, setComposerView] = useState<ArenaPreviewDoc | null>(null);
  const [composerPreview, setComposerPreview] = useState<ShapePreviewDoc | null>(null);
  const [composerError, setComposerError] = useState<string | null>(null);
  const [composerBusy, setComposerBusy] = useState(false);
  const [composerSelected, setComposerSelected] = useState<number | null>(null);
  const [composerFrame, setComposerFrame] = useState(0);
  // The last compile sent: a newer edit makes an older answer stale.
  const composerSeq = useRef(0);
  // The composer's own undo history: the part stacks it passed through. The
  // candidate history above cannot hold these — its entries are a problem and a
  // candidate, and the engine never sees the composer's tree as a document.
  const [composerPast, setComposerPast] = useState<ArenaPartDoc[][]>([]);
  const [composerFuture, setComposerFuture] = useState<ArenaPartDoc[][]>([]);
  // The stack a composer gesture started from, held until the gesture ends.
  const composerGesture = useRef<ArenaPartDoc[] | null>(null);
  const [problem, setProblem] = useState<ProblemDoc | null>(null);
  // What the engine says this problem can be built with, kept beside the key it
  // answers for so a stale answer is never read for a newer document.
  const [capabilities, setCapabilities] = useState<{ key: string; doc: CapabilitiesDoc } | null>(null);
  // A problem opened while the capability answer is still in flight, held until
  // that answer arrives so the interface never fires an initialiser the engine
  // has already said it cannot honour.
  const [pendingOpenInit, setPendingOpenInit] = useState<ProblemDoc | null>(null);
  const [candidate, setCandidate] = useState<CandidateDoc | null>(null);
  const [evaluation, setEvaluation] = useState<EvaluationDoc | null>(null);
  const [view, setView] = useState<ViewDoc | null>(null);
  const [framingKey, setFramingKey] = useState(0);
  const [scaleBounds, setScaleBounds] = useState<ScaleBoundsDoc | null>(null);
  const [summary, setSummary] = useState<SummaryDoc | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [showOrientations, setShowOrientations] = useState(false);
  const [showShapeIds, setShowShapeIds] = useState(false);
  // The colour the palette holds in hand. It lives here rather than in the panel
  // because two controls read it: the swatch row marks it, and "paint every shape"
  // paints with it. Before any is picked it is the first of the palette, not the
  // theme, so the common case — colour the selection — is one click.
  const [ink, setInk] = useState<string | null>(PALETTE[0]);
  const [strategy, setStrategy] = useState<InitStrategy>("grid");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorForNew, setEditorForNew] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [modelsOpen, setModelsOpen] = useState(false);
  const [statisticsOpen, setStatisticsOpen] = useState(false);
  const [requestedMode, setRequestedMode] = useState<WorkspaceMode>("shapes");
  const [guideStep, setGuideStep] = useState<number | null>(null);
  const [best, setBest] = useState<BestScoreDoc | null>(null);
  const [baselines, setBaselines] = useState<string[]>([]);
  const [convergence, setConvergence] = useState<ConvergenceDoc | null>(null);
  const [searchSummary, setSearchSummary] = useState("");
  const [searchError, setSearchError] = useState<string | null>(null);
  const [workflows, setWorkflows] = useState<WorkflowManifestDoc[]>([]);
  const [runs, setRuns] = useState<AgentRunSummaryDoc[]>([]);
  const [run, setRun] = useState<AgentRunDoc | null>(null);
  const [watching, setWatching] = useState<string | null>(null);
  const [stopping, setStopping] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [arenaPreview, setArenaPreview] = useState<ArenaPreviewDoc | null>(null);
  const [create, setCreate] = useState<Create | null>(null);
  const [selectedPart, setSelectedPart] = useState<number | null>(null);
  const [drawing, setDrawing] = useState<Drawing | null>(null);
  const [past, setPast] = useState<Snapshot[]>([]);
  const [future, setFuture] = useState<Snapshot[]>([]);

  useEffect(() => { saveLibrary(library); }, [library]);
  useEffect(() => { saveComposedShapes(composed); }, [composed]);
  useEffect(() => { window.localStorage.setItem("paper-obs-active-category", categoryId); }, [categoryId]);
  useEffect(() => {
    window.localStorage.setItem(REFERENCE_STORAGE, JSON.stringify(referenceEdits));
  }, [referenceEdits]);
  /** The record a problem carries: the owner's edit, then the catalogue, then the file. */
  const referenceOf = useCallback((document: ProblemDoc | null): ProblemReference | null =>
    document === null ? null
      : referenceEdits[document.problem_id] ?? builtInReference(document.problem_id)
        ?? readReference(document.metadata.reference), [referenceEdits]);

  const withReferenceEdit = useCallback((document: ProblemDoc): ProblemDoc => {
    const reference = referenceOf(document);
    return reference === null ? document : { ...document, metadata: { ...document.metadata, reference } };
  }, [referenceOf]);

  /**
   * The workspace the window is showing, which the problem may rule out.
   *
   * An objective that measures its own region — `minimize_container` — declares no
   * arena, and the domain refuses a problem that carries one; an arena built in that
   * state would make the document inadmissible, and from then on *every* request of
   * the session would come back refused, looking like a frozen application. So the
   * arena workspace is not offered there, and a mode left over from a problem that had
   * an arena cannot open it either. Everything reads this, never the request: loading
   * such an example, restoring one with Ctrl+Z or changing the objective all pass
   * through here, and none of them can leave the window in a workspace the problem
   * cannot honour.
   */
  // A workspace the problem cannot honour falls back to the shapes one: an objective
  // that measures its own region declares no arena to build, and with no problem
  // loaded there is nothing for a workflow to run on.
  const ruledOut =
    (requestedMode === "arena" &&
      problem !== null &&
      (problem.objective.type === "minimize_container" ||
        problem.objective.type === "maximize_covered_size")) ||
    ((requestedMode === "run" || requestedMode === "search") && problem === null);
  const mode: WorkspaceMode = ruledOut ? "shapes" : requestedMode;
  // One boolean for both packing canvases: the copies are translucent for a
  // covering and solid everywhere else, and no canvas decides it for itself.
  const translucentCopies = wantsTranslucentCopies(problem);

  // The stacked page edges follow the tab list itself, in one place: the active
  // tab at index i of n leaves i pages on its left and n-1-i on its right, so the
  // first tab has none on the left, the last none on the right, and a tab added
  // or removed changes nothing else. Both blocks disappear when their count is
  // zero, which is what keeps the last tab from growing a page it does not have.
  const pages = pageEdges(mode);
  const pageStyle = {
    "--page-left": `${pages.left * PAGE_EDGE_WIDTH}px`,
    "--page-right": `${pages.right * PAGE_EDGE_WIDTH}px`,
    "--left-page-opacity": pages.left > 0 ? "1" : "0",
    "--right-page-opacity": pages.right > 0 ? "1" : "0",
  } as CSSProperties;

  // One window for both canvases: switching modes must not move the picture.
  const canvas = useViewport();
  const runCanvas = useViewport();
  const searchCanvas = useViewport();
  // The composer draws its own region, so it gets a window of its own.
  const composeCanvas = useViewport();

  const pending = useRef<Pending | null>(null);
  // What Ctrl+C has put aside, in this window only. A ref, not state: nothing
  // renders from it, and copying must not schedule a repaint.
  const clipboard = useRef<Clipboard | null>(null);
  const inFlight = useRef(false);
  const loaded = useRef(false);
  const gestureStart = useRef<CandidateDoc | null>(null);
  const gestureStartProblem = useRef<ProblemDoc | null>(null);
  // How many adopted turns of the watched run have been drawn: the run is read every
  // second, and only a turn the engine preferred is worth judging again.
  const drawn = useRef(0);

  // Ask the engine what this problem can be built with, before a control that
  // cannot work is offered. The key is exactly what the answer depends on — the
  // shape family, which decides the initialisers, and the objective, which
  // decides whether the search layer has an interval to work with — so editing a
  // placement does not ask again, and an answer about another document is never
  // read for this one.
  const capabilityKey =
    problem === null ? null : JSON.stringify([problem.shape, problem.objective]);
  useEffect(() => {
    if (problem === null || capabilityKey === null) {
      setCapabilities(null);
      return;
    }
    let live = true;
    void api.capabilities(problem)
      .then((doc) => { if (live) setCapabilities({ key: capabilityKey, doc }); })
      // An unreachable backend is not the engine saying "nothing applies": the
      // controls stay, and the request that needs them reports the failure.
      .catch(() => { if (live) setCapabilities(null); });
    return () => { live = false; };
  }, [capabilityKey]);
  const capabilitiesForCurrent =
    capabilities !== null && capabilities.key === capabilityKey ? capabilities.doc : null;

  /**
   * The initialisers a document offers: the engine's own answer when it is known
   * for that document, and the family fallback while that answer is in flight.
   *
   * The answer is keyed on exactly what it depends on — the shape family, which
   * decides the initialisers, and the objective, which decides whether the search
   * layer has an interval to work with — so an answer about another document is
   * never read for this one.
   */
  const offeredFor = useCallback((target: ProblemDoc): InitStrategy[] => {
    const key = JSON.stringify([target.shape, target.objective]);
    if (capabilities !== null && capabilities.key === key) return capabilities.doc.initialize;
    const fallback = OBJECTIVE_STRATEGIES[target.objective.type] ?? INIT_STRATEGIES[target.shape.type];
    // The covering start is the one arrangement that reads the scale the other way
    // round, so the family fallback keeps it for a covering objective only: on any
    // other one it would offer a control the engine refuses.
    return fallback.filter((name) => name !== "cover" || target.objective.type === "cover_region");
  }, [capabilities]);

  // The initialiser the toolbar shows and the Init button runs: what the engine
  // answered for this problem, or — until it has — what the loaded family offers.
  // With no problem loaded, or when the engine answers that nothing applies,
  // there is nothing to offer and the controls are hidden rather than shown
  // failing. A choice left over from another shape is resolved against the list.
  const offeredStrategies: InitStrategy[] = problem === null ? [] : offeredFor(problem);
  const activeStrategy: InitStrategy = offeredStrategies.includes(strategy)
    ? strategy
    : (offeredStrategies[0] ?? "grid");

  // The engine decides which classical methods apply to this objective. Until
  // its answer arrives the global list stands in; unsupported methods are never
  // offered as controls in the search workspace.
  const searchStrategies = capabilitiesForCurrent?.search ?? baselines;
  const searchAvailable =
    problem !== null &&
    (capabilitiesForCurrent === null ? baselines.length > 0 : searchStrategies.length > 0);

  /** Do nothing: the run workspace draws an arrangement nobody edits by hand. */
  const idle = useCallback(() => undefined, []);

  const applyVerdict = useCallback((verdict: VerdictDoc) => {
    setCandidate(verdict.candidate);
    setEvaluation(verdict.evaluation);
    setView(verdict.view);
    setScaleBounds(verdict.scale_bounds);
    setSummary(verdict.summary);
    setError(null);
    if (verdict.evaluation.valid) {
      const score = verdict.evaluation.score;
      setBest((current) =>
        current === null || score.primary > current.score
          ? { score: score.primary, label: score.label, candidateId: verdict.candidate.candidate_id }
          : current,
      );
    }
  }, []);

  /** A newly loaded solution defines a new view; an edit within it does not. */
  const showLoadedVerdict = useCallback((verdict: VerdictDoc) => {
    applyVerdict(verdict);
    setFramingKey((key) => key + 1);
    canvas.reset();
    runCanvas.reset();
  }, [applyVerdict, canvas.reset, runCanvas.reset]);

  const flush = useCallback(async () => {
    if (inFlight.current) {
      return;
    }
    const job = pending.current;
    if (job === null) {
      return;
    }
    pending.current = null;
    inFlight.current = true;
    setBusy(true);
    try {
      // The void area is a metric of every evaluation, written by the engine's own
      // `compute_metrics`; only the drawn regions were ever optional, and the lab
      // does not draw them, so the request asks for nothing extra. The metric keeps
      // its place in the verdict panel either way.
      const verdict = await api.evaluate({
        problem: job.problem,
        candidate: job.candidate,
        ...(job.snap ? { snap_shape_ids: job.snap.ids, snap_distance: job.snap.distance, snap_motion: job.snap.motion } : {}),
        // A covering's union is the optional overlay the canvas offers; the engine
        // computes it from the same cached facts the coverage constraint read.
        with_union: wantsUnion(job.problem),
      });
      if (job.refit) showLoadedVerdict(verdict);
      else applyVerdict(verdict);
    } catch (cause) {
      setError(describeError(cause));
    } finally {
      inFlight.current = false;
      setBusy(false);
      void flush();
    }
  }, [applyVerdict, showLoadedVerdict]);

  const requestVerdict = useCallback(
    (next: Pending) => {
      pending.current = next;
      void flush();
    },
    [flush],
  );

  const runInit = useCallback(
    async (target: ProblemDoc, operator: InitStrategy) => {
      setBusy(true);
      try {
        // A strategy the family does not offer — the staggered lattice on anything
        // but discs, the covering start on anything but a covering — is resolved to
        // the first one it does, here, where a strategy meets the document it will
        // run on: a caller cannot then send the engine a refusal it was warned
        // about. An empty list is the engine saying nothing can be built there, and
        // the request is not sent at all rather than answered with a refusal.
        const offered = offeredFor(target);
        if (offered.length === 0) {
          return;
        }
        const verdict = await api.init({
          problem: target,
          strategy: offered.includes(operator) ? operator : (offered[0] ?? "grid"),
          with_union: wantsUnion(target),
        });
        showLoadedVerdict(verdict);
        setSelected([]);
        setArenaPreview(null);
      } catch (cause) {
        setError(describeError(cause));
      } finally {
        setBusy(false);
      }
    },
    [offeredFor, showLoadedVerdict],
  );

  // Opening a problem no longer initialises it immediately: the capability answer
  // is what says *what* can be built there, and a document whose lists are empty
  // must show no engine refusal in the banner. The pending document waits for the
  // answer about its own shape and objective, then runs the first initialiser the
  // engine offered — nothing at all when that answer is an empty list.
  useEffect(() => {
    if (pendingOpenInit === null) return;
    const key = JSON.stringify([pendingOpenInit.shape, pendingOpenInit.objective]);
    if (capabilities === null || capabilities.key !== key) return;
    setPendingOpenInit(null);
    const [first] = capabilities.doc.initialize;
    if (first === undefined) return;
    void runInit(pendingOpenInit, first);
  }, [pendingOpenInit, capabilities, runInit]);

  /**
   * Drop the last run.
   *
   * A curve belongs to the problem it was run on, exactly as the best score
   * does: the steps the engine sent describe a document that is no longer the
   * one loaded, and a curve shown beside another problem would be read as that
   * problem's.
   */
  const forgetCurve = useCallback(() => {
    setConvergence(null);
    setSearchSummary("");
    setSearchError(null);
  }, []);

  /**
   * Run a baseline over the problem being edited, and show its curve.
   *
   * The winner comes back judged and drawn like any other candidate, so it is
   * applied through `applyVerdict` — the same path an init takes — rather than
   * through a second copy of that handling: whatever the canvas and the verdict
   * panel do for a candidate, they do here too. An error is the engine's own
   * message, and the last curve stays on screen beside it.
   */
  const runSearch = useCallback(
    async (baseline: string, budget: number) => {
      if (problem === null) {
        return;
      }
      setBusy(true);
      setSearchError(null);
      try {
        const answer = await api.search({ problem, baseline, budget });
        setConvergence(answer.convergence);
        setSearchSummary(answer.summary);
        // The best candidate of the run is the one that replaces what is being
        // edited: a search is a way of arriving at a candidate, so the canvas
        // shows where it arrived rather than only the curve of the trip.
        showLoadedVerdict(answer.verdict);
      } catch (cause) {
        setSearchError(describeError(cause));
      } finally {
        setBusy(false);
      }
    },
    [problem, showLoadedVerdict],
  );

  /** Open a research session's best arrangement on the canvas, judged again by the engine. */
  const showResearchCandidate = useCallback(async (shown: CandidateDoc) => {
    if (problem === null) {
      return;
    }
    try {
      showLoadedVerdict(await api.evaluate({ problem, candidate: shown, with_union: wantsUnion(problem) }));
    } catch (cause) {
      setSearchError(describeError(cause));
    }
  }, [problem, showLoadedVerdict]);

  /** Open a research session, loading its problem when another one is open, then its best arrangement. */
  const openResearchSession = useCallback(async (sessionId: string) => {
    try {
      const session = await api.researchSession(sessionId);
      if (problem?.problem_id !== session.problem.problem_id) {
        forgetCurve();
        setPast([]);
        setFuture([]);
        setSelected([]);
        setProblem(session.problem);
        setBest(null);
        setCandidate(null);
        setEvaluation(null);
        setView(null);
        setSummary(null);
      }
      if (session.champion !== null) {
        showLoadedVerdict(await api.evaluate({ problem: session.problem, candidate: session.champion,
          with_union: wantsUnion(session.problem) }));
      }
    } catch (cause) {
      setSearchError(describeError(cause));
    }
  }, [forgetCurve, problem, showLoadedVerdict]);

  /**
   * Draw what the run has newly reached.
   *
   * A turn that proposes nothing, or proposes something the engine prefers less,
   * leaves the canvas where it is: what is drawn is the incumbent. The count of
   * adopted turns drawn so far is what makes this idempotent — the document is read
   * every second, and judging the same arrangement again would redraw it forever.
   */
  const showNewest = useCallback(
    async (document: AgentRunDoc, target: ProblemDoc) => {
      const adopted = document.steps.filter((step) => step.accepted && step.candidate !== null);
      if (adopted.length <= drawn.current) {
        return;
      }
      drawn.current = adopted.length;
      const step = adopted[adopted.length - 1];
      if (step === undefined || step.candidate === null) {
        return;
      }
      try {
        showLoadedVerdict(await api.evaluate({ problem: target, candidate: step.candidate }));
      } catch (cause) {
        setRunError(describeError(cause));
      }
    },
    [showLoadedVerdict],
  );

  /** Read the runs already written, so a past one can be opened again. */
  const listing = useRef(false);
  const refreshRuns = useCallback(async () => {
    // A slow server is not asked again before it has answered: requests would pile up behind it.
    if (listing.current) return;
    listing.current = true;
    try {
      setRuns(await api.agentRuns());
    } catch (cause) {
      setRunError(describeError(cause));
    } finally {
      listing.current = false;
    }
  }, []);

  // While a run goes on, on any problem, the list follows it, so a count never goes stale.
  const anyRunning = runs.some((item) => item.status === "running" && !item.deleted);
  useEffect(() => {
    if (!anyRunning) return;
    const timer = window.setInterval(() => void refreshRuns(), 10_000);
    return () => window.clearInterval(timer);
  }, [anyRunning, refreshRuns]);

  /** Delete one saved run, and stop showing it when it is the one open. */
  const deleteRun = useCallback(
    async (runId: string) => {
      try {
        await api.deleteAgentRun(runId);
        setRun((current) => (current !== null && current.run_id === runId ? null : current));
        setWatching((current) => (current === runId ? null : current));
        await refreshRuns();
      } catch (cause) {
        setRunError(describeError(cause));
      }
    },
    [refreshRuns],
  );

  /** Bring a deleted run back among the saved runs. */
  const restoreRun = useCallback(
    async (runId: string) => {
      try {
        await api.restoreAgentRun(runId);
        await refreshRuns();
      } catch (cause) {
        setRunError(describeError(cause));
      }
    },
    [refreshRuns],
  );

  /**
   * Watch a run: read its document again every second, and stop when it says it stopped.
   *
   * The document *is* the run — it is written after every turn — so watching one and
   * reading a past one are the same call, and a closed tab loses nothing. A run whose
   * first turn has not been written yet answers 404, which here means "not yet".
   */
  useEffect(() => {
    if (watching === null || problem === null) {
      return;
    }
    let live = true;
    let timer = 0;
    const look = async () => {
      try {
        const document = await api.agentRun(watching);
        if (!live) {
          return;
        }
        setRun(document);
        if (document.status !== "running") {
          setWatching(null);
          setStopping(false);
        }
        await showNewest(document, problem);
        if (document.status !== "running") {
          await refreshRuns();
        }
      } catch (cause) {
        // A run is read while it is being written, so a failed read is not a failed run: the
        // answer that says the run stopped is the only one that ends the watching.
        if (live) {
          setRunError(describeError(cause));
        }
      }
      // The next read waits for this one: a large document read every second from a busy
      // server would otherwise queue reads faster than it answers, and delay every other call.
      if (live) timer = window.setTimeout(() => void look(), RUN_POLL_MS);
    };
    void look();
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [watching, problem, showNewest, refreshRuns]);

  /** Start a run on the problem being edited, and watch it. */
  // A run costs money: while one start is on its way, no other can be sent, however often the
  // button is pressed. The ref blocks at once; the state shows it.
  const launching = useRef(false);
  const [starting, setStarting] = useState(false);
  const startRun = useCallback(
    async (workflow: string, budget: Record<string, number>, name: string, maxTokens: number | null, resume?: string) => {
      // A resumed run goes on with its own problem, whatever is open in the editor.
      const target = resume === undefined ? problem : run?.problem ?? null;
      if (target === null || launching.current) {
        return;
      }
      launching.current = true;
      setStarting(true);
      // The model and its key are the choice the model dialog keeps in this browser.
      // A key travels with a run and is never written to the file the backend stores.
      const settings = readModelSettings();
      setRunError(null);
      setRun(null);
      setStopping(false);
      drawn.current = 0;
      try {
        const answer = await api.startAgentRun({
          problem: target,
          workflow,
          resume,
          name,
          provider: settings.provider,
          model: settings.model,
          base_url: settings.baseUrl,
          api_key: settings.apiKey === "" ? undefined : settings.apiKey,
          cost_per_million_in: money(settings.priceIn),
          cost_per_million_out: money(settings.priceOut),
          cost_per_million_cached: money(settings.priceCached),
          temperature: temperature(settings.temperature),
          // No ceiling unless the run's own field asked for one: the provider knows its own
          // limits better than this lab does, and a ceiling set too low truncates a reply.
          max_tokens: maxTokens ?? undefined,
          budget,
        });
        setWatching(answer.run_id);
      } catch (cause) {
        setRunError(describeError(cause));
      } finally {
        launching.current = false;
        setStarting(false);
      }
    },
    [problem, run],
  );

  const stopRun = useCallback(async () => {
    if (watching === null) return;
    setStopping(true);
    try {
      await api.stopAgentRun(watching);
    } catch (cause) {
      setStopping(false);
      setRunError(describeError(cause));
    }
  }, [watching]);

  /** Open a written run: draw what it reached, and watch it again if it is still going. */
  const openRun = useCallback(
    async (runId: string) => {
      setRunError(null);
      drawn.current = 0;
      try {
        const document = await api.agentRun(runId);
        setRun(document);
        setWatching(document.status === "running" ? runId : null);
        setStopping(false);
        const target = document.problem ?? (problem?.problem_id === document.problem_id ? problem : null);
        if (target !== null) {
          if (document.problem) {
            forgetCurve();
            setPast([]);
            setFuture([]);
            setSelected([]);
            setProblem(document.problem);
            setBest(null);
            setCandidate(null);
            setEvaluation(null);
            setView(null);
            setSummary(null);
          }
          await showNewest(document, target);
        }
      } catch (cause) {
        setRunError(describeError(cause));
      }
    },
    [forgetCurve, problem, showNewest],
  );

  /** Put one turn's arrangement back on the canvas, judged again by the engine. */
  const replayTurn = useCallback(
    async (step: AgentRunStepDoc) => {
      const target = run?.problem ?? problem;
      if (target === null || step.candidate === null || target.problem_id !== step.candidate.problem_id) {
        return;
      }
      try {
        showLoadedVerdict(await api.evaluate({ problem: target, candidate: step.candidate }));
      } catch (cause) {
        setRunError(describeError(cause));
      }
    },
    [problem, run, showLoadedVerdict],
  );

  const replayCandidate = useCallback(async (snapshot: CandidateDoc) => {
    const target = run?.problem ?? problem;
    if (target === null || target.problem_id !== snapshot.problem_id) return;
    try {
      showLoadedVerdict(await api.evaluate({ problem: target, candidate: snapshot }));
    } catch (cause) { setRunError(describeError(cause)); }
  }, [problem, run, showLoadedVerdict]);

  /** Stop following the run on screen: the document stays on disk, and the launcher returns. */
  const closeRun = useCallback(() => {
    setRun(null);
    setWatching(null);
    setStopping(false);
    setRunError(null);
    drawn.current = 0;
  }, []);

  /**
   * Drop the run being watched.
   *
   * A run belongs to the problem it ran on, exactly as a curve does: its turns are
   * verdicts about a document that is no longer the one loaded.
   */
  const forgetRun = useCallback(() => {
    setRun(null);
    setWatching(null);
    setStopping(false);
    setRunError(null);
    drawn.current = 0;
  }, []);

  const loadExample = useCallback(
    async (problemId: string) => {
      setBusy(true);
      try {
        const document = await api.example(problemId);
        const target = withReferenceEdit(document.problem);
        setProblem(target);
        window.localStorage.setItem(ACTIVE_PROFILE_STORAGE, target.problem_id);
        setScaleBounds(document.scale_bounds);
        // The best score to beat belongs to one problem: it is dropped before
        // the first candidate of the new one exists, never after. The curve of a
        // baseline run belongs to the same problem, and goes with it.
        setPast([]);
        setFuture([]);
        setBest(null);
        forgetCurve();
        forgetRun();
        setSelected([]);
        setCreate(null);
        setDrawing(null);
        if (document.candidate !== null) {
          // The example ships the arrangement it is known for — the published
          // optimum for the instances that have one — so the lab opens on that
          // rather than on a construction. The engine still judges it: the
          // verdict, the score and every metric beside it are computed from the
          // coordinates, exactly as they would be for a candidate the user drew.
          showLoadedVerdict(
            await api.evaluate({
              problem: target,
              candidate: document.candidate,
              with_union: wantsUnion(target),
            }),
          );
          setArenaPreview(null);
        } else {
          setPendingOpenInit(target);
        }
      } catch (cause) {
        setError(describeError(cause));
      } finally {
        // A load leaves nothing in flight, whichever branch it took: this block is
        // what makes a shipped example stop looking like a request that never
        // returns. Resetting in the `catch` alone left `busy` true for the whole
        // `document.candidate !== null` branch — the one every example takes —
        // and the Run button stayed greyed out until the next edit happened to end.
        setBusy(false);
      }
    },
    [forgetCurve, forgetRun, showLoadedVerdict, withReferenceEdit],
  );

  const activateLocal = useCallback(async (document: ProblemDoc, guideCandidate?: CandidateDoc) => {
    const target = withReferenceEdit(document);
    setProblem(target);
    window.localStorage.setItem(ACTIVE_PROFILE_STORAGE, target.problem_id);
    setPast([]);
    setFuture([]);
    setBest(null);
    setCandidate(null);
    setEvaluation(null);
    setView(null);
    setSummary(null);
    setSelected([]);
    setCreate(null);
    setDrawing(null);
    forgetCurve();
    forgetRun();
    const candidateUrl = target.metadata.catalog_candidate_url;
    if (guideCandidate || (typeof candidateUrl === "string"
      && /^\/catalog\/candidates\/(?:squares-\d+|(?:starter|record)-[a-zA-Z0-9-]+)\.json$/.test(candidateUrl))) {
      setBusy(true);
      try {
        const published = guideCandidate ?? await (async () => {
          const response = await fetch(candidateUrl as string);
          if (!response.ok) throw new Error(`Catalog candidate: HTTP ${response.status}`);
          return response.json() as Promise<CandidateDoc>;
        })();
        if (published.problem_id !== target.problem_id) throw new Error("Catalog candidate does not match the problem");
        showLoadedVerdict(await api.evaluate({ problem: target, candidate: published, with_union: wantsUnion(target) }));
        setArenaPreview(null);
      } catch (cause) {
        setPendingOpenInit(target);
        setError(t("Published construction unavailable; the engine will choose an initialiser.") + " " + describeError(cause));
      } finally { setBusy(false); }
    } else {
      setPendingOpenInit(target);
    }
  }, [forgetCurve, forgetRun, showLoadedVerdict, t, withReferenceEdit]);

  const selectProfile = useCallback((id: string) => {
    const local = library.problems[id];
    if (local) void activateLocal(local);
    else void loadExample(id);
  }, [activateLocal, library.problems, loadExample]);

  const addSquare = useCallback((count: number) => {
    const record = SQUARE_RECORDS.find((entry) => entry.count === count);
    if (!record) return;
    const target = squareProblem(record);
    const builtIn = examples.some((example) => example.problem_id === target.problem_id);
    setLibrary((current) => includeProfile(current, categoryId, builtIn ? target.problem_id : target));
    if (builtIn) void loadExample(target.problem_id);
    else void activateLocal(target);
  }, [activateLocal, categoryId, examples, loadExample]);

  // Ask the engine which cover targets it measures, by asking it to build one:
  // there is no list to read, and the answer must come from the engine that will
  // judge the problem. A failed probe leaves the known set in place.
  useEffect(() => {
    let live = true;
    void measureCoverTargets()
      .then((measured) => { if (live && measured.length > 0) setCoverTargets(measured); })
      .catch(() => undefined);
    return () => { live = false; };
  }, []);

  useEffect(() => {
    if (loaded.current) {
      return;
    }
    loaded.current = true;
    void (async () => {
      try {
        // The palette is the engine's, so it is fetched with the examples rather
        // than written here: which shapes exist is not the browser's to know. The
        // search strategies are fetched the same way, and in the engine's order.
        const [listed, families, strategies, available, past] = await Promise.all([
          api.examples(),
          api.shapes(),
          api.baselines(),
          api.workflows(),
          api.agentRuns(),
        ]);
        setPalette(families.shapes);
        setExamples(listed.examples);
        setBaselines(strategies);
        for (const item of available) addTranslations(item.translations ?? {});
        setWorkflows(available);
        setRuns(past);
        // The lab opens on an example of the family the editor defaults to, so the
        // tool starts on the question it currently asks rather than on whichever
        // instance happens to sort first. One constant decides both, so they cannot
        // drift: an example of that family is the default document, and the same
        // family is what a new problem is built as.
        const first =
          listed.examples.find((entry) => entry.objective_kind === DEFAULT_OBJECTIVE_KIND) ??
          listed.examples[0];
        const activeCategory = library.categories.find((entry) => entry.id === categoryId);
        const savedId = window.localStorage.getItem(ACTIVE_PROFILE_STORAGE);
        const preferred = savedId && activeCategory?.problemIds.includes(savedId)
          ? savedId : activeCategory?.problemIds[0];
        if (preferred && library.problems[preferred]) await activateLocal(library.problems[preferred]);
        else if (preferred && listed.examples.some((entry) => entry.problem_id === preferred)) await loadExample(preferred);
        else if (first !== undefined) {
          setCategoryId(library.categories[0]?.id ?? STARTER_CATEGORY_ID);
          await loadExample(first.problem_id);
        }
      } catch (cause) {
        setError(describeError(cause));
      }
    })();
  }, [activateLocal, categoryId, library, loadExample]);

  /** Apply a local edit and ask for a new verdict, without touching the history. */
  const editCandidate = useCallback(
    (change: (current: CandidateDoc) => CandidateDoc, target: ProblemDoc | null = problem, refit = false,
      snap?: { ids: string[]; distance: number; motion: Point }) => {
      if (target === null || candidate === null) {
        return;
      }
      const next = change(candidate);
      setCandidate(next);
      requestVerdict({ problem: target, candidate: next, refit, snap });
    },
    [candidate, problem, requestVerdict],
  );

  /**
   * Record a state in the undo stack, and drop any redo branch.
   *
   * The *problem* is recorded with the candidate, not just the candidate. An
   * edit here can change the problem too — the automatic shape count follows
   * what is placed, and the arena editor rewrites the arena — and undoing only
   * half of what an action did leaves the other half to contradict it.
   */
  const remember = useCallback(
    (snapshot: CandidateDoc | null, target: ProblemDoc | null = problem) => {
      if (snapshot === null || target === null) {
        return;
      }
      setPast((current) => [...current.slice(-(HISTORY_LIMIT - 1)), { problem: target, candidate: snapshot }]);
      setFuture([]);
    },
    [problem],
  );

  // Called on every move of a drag as well as at its start: the snapshot is
  // taken once, from the state *before* the first move, and kept until the
  // gesture ends. Taking it again mid-drag would record the drag itself.
  const beginGesture = useCallback(() => {
    if (gestureStart.current === null) {
      gestureStart.current = candidate;
      gestureStartProblem.current = problem;
    }
  }, [candidate, problem]);

  const endGesture = useCallback(() => {
    remember(gestureStart.current, gestureStartProblem.current);
    gestureStart.current = null;
    gestureStartProblem.current = null;
  }, [remember]);

  const dragSelection = useCallback(
    (dx: number, dy: number, shapeIds: string[], contactDistance: number) => {
      const start = gestureStart.current;
      if (start === null || shapeIds.length === 0) {
        return;
      }
      const chosen = new Set(shapeIds);
      editCandidate((current) => ({
        ...current,
        placements: current.placements.map((placement) => {
          if (!chosen.has(placement.shape_id)) {
            return placement;
          }
          const origin = start.placements.find((item) => item.shape_id === placement.shape_id);
          if (origin === undefined) {
            return placement;
          }
          return { ...placement, x: origin.x + dx, y: origin.y + dy };
        }),
      }), problem, false, { ids: shapeIds, distance: contactDistance, motion: [dx, dy] });
    },
    [editCandidate, problem],
  );

  /**
   * A local size in flight, from the inspector's slider or the canvas' handle.
   *
   * Both controls propose the same number through this one write, so there is a
   * single path from a gesture to a placement's `scale`. It is not recorded in
   * the undo stack here: `beginGesture` takes the snapshot once, at the first
   * report, and the matching `endGesture` records the whole drag as one step.
   * The engine is asked to judge each arrangement the application holds,
   * coalesced, so the copy on the canvas grows while the hand moves.
   */
  const previewScale = useCallback(
    (shapeId: string, value: number) => {
      beginGesture();
      editCandidate((current) => ({
        ...current,
        placements: current.placements.map((placement) =>
          placement.shape_id === shapeId ? { ...placement, scale: value } : placement,
        ),
      }));
    },
    [beginGesture, editCandidate],
  );

  /** Turn one shape in place, or a group about its visible centre. */
  const turnSelection = useCallback(
    (degrees: number) => {
      if (candidate === null || problem === null || selected.length === 0) {
        return;
      }
      remember(candidate);
      if (selected.length > 1) {
        setBusy(true);
        void api.rotateSelection({
          problem,
          candidate,
          shape_ids: selected,
          degrees,
          with_union: wantsUnion(problem),
        })
          .then(applyVerdict)
          .catch((cause) => setError(describeError(cause)))
          .finally(() => setBusy(false));
        return;
      }
      const chosen = new Set(selected);
      editCandidate((current) => ({
        ...current,
        placements: current.placements.map((placement) =>
          chosen.has(placement.shape_id)
            ? { ...placement, rotation: (placement.rotation ?? 0) + degrees }
            : placement,
        ),
      }));
    },
    [applyVerdict, candidate, editCandidate, problem, remember, selected],
  );

  /**
   * Paint the selection, or every shape, in one colour.
   *
   * The colour is carried by the placement, like `x`, `y` and `rotation`, so it is
   * written through the same update path as the other fields: one gesture, one entry
   * in the undo stack, one verdict. `null` is the theme's own fill, which the engine
   * then leaves out of the document it sends back. Nothing here decides what a shape
   * looks like: the canvas reads `color` off the view the engine returns.
   */
  const paint = useCallback(
    (color: string | null, scope: "selection" | "all") => {
      if (candidate === null) {
        return;
      }
      // Painting everything is not a selection of everything: every placement is
      // written, and the selection is not consulted at all — a default colour for all
      // the shapes is asked for with nothing selected as often as with ten.
      const paintingEverything = scope === "all";
      const chosen = paintingEverything ? null : new Set(selected);
      if (chosen !== null && chosen.size === 0) {
        return;
      }
      if (paintingEverything && candidate.placements.length === 0) {
        return;
      }
      remember(candidate);
      editCandidate((current) => ({
        ...current,
        placements: current.placements.map((placement) =>
          chosen === null || chosen.has(placement.shape_id) ? { ...placement, color } : placement,
        ),
      }));
    },
    [candidate, editCandidate, remember, selected],
  );

  /**
   * Take a colour in hand and paint the selection with it, in one gesture.
   *
   * A swatch is the whole of that gesture: it marks itself as the colour being held
   * and paints what is selected, so the colour the next "paint every shape" uses is
   * the one the panel is pointing at. `null` is the theme's own fill, exactly as it
   * is in `paint` above.
   */
  const paintSelection = useCallback(
    (color: string | null) => {
      setInk(color);
      paint(color, "selection");
    },
    [paint],
  );

  /**
   * Add a shape where the creation menu was opened.
   *
   * The shape is a parameter because the menu can offer another one than the
   * problem's: a problem holds a single shape family, so choosing a different
   * one changes the problem, and the engine judges every placement at once.
   */
  const placeShape = useCallback(
    (shape: ShapeDoc, x: number, y: number) => {
      if (candidate === null || problem === null) {
        return;
      }
      remember(candidate);
      const shapeId = nextShapeId(candidate.placements);
      const placements = [...candidate.placements, { shape_id: shapeId, x, y }];
      // The count belongs to the problem, not to the placements: adding a shape
      // makes the verdict invalid until the editor's count agrees, which is the
      // engine's own rule and never rewritten here.
      const next = { ...problem, shape };
      setProblem(next);
      setSelected([shapeId]);
      editCandidate((current) => ({ ...current, placements }), next);
    },
    [candidate, editCandidate, problem, remember],
  );

  /**
   * Take a list of positions as the whole candidate, for the family they were written for.
   *
   * A posted solution is positions for shapes of a known family and size, so
   * importing one means changing the problem to that family and handing the
   * engine the placements exactly as they were written. Nothing is checked here:
   * whether the solution is the one it claims to be is the engine's answer, and
   * a fake solution has to be reported as one, not repaired into looking right.
   */
  const importPositions = useCallback(
    (shape: ShapeDoc, positions: ImportedPositions[], scale: number) => {
      if (candidate === null || problem === null || positions.length === 0) {
        return;
      }
      const placements: PlacementDoc[] = positions.map((position, index) => ({
        shape_id: `s${String(index).padStart(3, "0")}`,
        x: position.x,
        y: position.y,
        // A rotation of zero is what a placement without one means, so it is left
        // out rather than written: the document stays as short as the file was.
        ...(position.rotation === 0 ? {} : { rotation: position.rotation }),
      }));
      remember(candidate);
      const next = { ...problem, shape };
      setProblem(next);
      setSelected([]);
      setImportOpen(false);
      // A solution from elsewhere is another problem's answer: the curve of a run
      // on the previous one is not a curve of this one.
      forgetCurve();
      editCandidate((current) => ({ ...current, scale, placements }), next, true);
    },
    [candidate, editCandidate, forgetCurve, problem, remember],
  );

  const importCandidate = useCallback(async (document: unknown) => {
    if (problem === null) throw new Error(t("No problem is open."));
    const imported = document as CandidateDoc;
    if (imported?.problem_id !== problem.problem_id) {
      throw new Error(`${t("This solution belongs to a different problem.")} ${imported?.problem_id ?? "?"} ≠ ${problem.problem_id}`);
    }
    const verdict = await api.evaluate({
      problem,
      candidate: imported,
      with_union: wantsUnion(problem),
    });
    if (candidate !== null) remember(candidate);
    setSelected([]);
    forgetCurve();
    showLoadedVerdict(verdict);
    setImportOpen(false);
  }, [candidate, forgetCurve, problem, remember, showLoadedVerdict, t]);

  const importProblem = useCallback(async (document: unknown) => {
    const imported = await api.validateProblem(document);
    if (library.problems[imported.problem_id] || examples.some((item) => item.problem_id === imported.problem_id)) {
      throw new Error(`${t("A problem with this ID already exists. Change its ID before importing.")} (${imported.problem_id})`);
    }
    setLibrary((current) => includeProfile(current, categoryId, imported));
    await activateLocal(imported);
  }, [activateLocal, categoryId, examples, library.problems, t]);

  const removeShapes = useCallback(
    (shapeIds: string[]) => {
      if (candidate === null || shapeIds.length === 0) {
        return;
      }
      remember(candidate);
      const doomed = new Set(shapeIds);
      const placements = candidate.placements.filter((item) => !doomed.has(item.shape_id));
      setProblem(problem);
      setSelected([]);
      editCandidate((current) => ({ ...current, placements }), problem);
    },
    [candidate, editCandidate, problem, remember],
  );

  const clearShapes = useCallback(() => {
    if (candidate === null || candidate.placements.length === 0) {
      return;
    }
    removeShapes(candidate.placements.map((item) => item.shape_id));
  }, [candidate, removeShapes]);

  const duplicateShape = useCallback(
    (shapeId: string) => {
      const source = candidate?.placements.find((item) => item.shape_id === shapeId);
      if (candidate === null || source === undefined) {
        return;
      }
      remember(candidate);
      const copyId = nextShapeId(candidate.placements);
      const placements = [...candidate.placements, { ...source, shape_id: copyId }];
      setProblem(problem);
      setSelected([copyId]);
      editCandidate((current) => ({ ...current, placements }), problem);
    },
    [candidate, editCandidate, problem, remember],
  );

  const step = useCallback(
    (direction: "undo" | "redo") => {
      const source = direction === "undo" ? past : future;
      const target = source[source.length - 1];
      if (target === undefined || candidate === null || problem === null) {
        return;
      }
      const here = { problem, candidate };
      if (direction === "undo") {
        setPast((current) => current.slice(0, -1));
        setFuture((current) => [...current, here]);
      } else {
        setFuture((current) => current.slice(0, -1));
        setPast((current) => [...current, here]);
      }
      setProblem(target.problem);
      setCandidate(target.candidate);
      setSelected([]);
      requestVerdict({ problem: target.problem, candidate: target.candidate, refit: true });
    },
    [candidate, future, past, problem, requestVerdict],
  );

  /**
   * Compile a stack of parts into an arena, and judge the candidate against it.
   *
   * The stack is sent whole on every edit: the engine folds it and answers with
   * the outline, the parts it understood and, when the stack describes nothing,
   * its own refusal — which is what is shown rather than a guess made here.
   */
  const composeArena = useCallback(
    async (requested: PartRequest[]) => {
      if (problem === null || candidate === null) {
        return;
      }
      setBusy(true);
      try {
        const preview = await api.composeArena({ parts: requested });
        setArenaPreview(preview);
        const next = { ...problem, arena: preview.arena };
        setProblem(next);
        requestVerdict({ problem: next, candidate });
      } catch (cause) {
        setError(describeError(cause));
      } finally {
        setBusy(false);
      }
    },
    [candidate, problem, requestVerdict],
  );

  const parts = arenaPreview?.parts ?? view?.arena.parts ?? [];

  // The stack shrinks under the selection when a part is deleted, so the index is
  // read through the length rather than trusted.
  const activePart = selectedPart !== null && selectedPart < parts.length ? selectedPart : null;

  // The objective owns the arena for a covering and for a total-perimeter family:
  // the view says so once the engine has judged, and the capability answer says so
  // before the first candidate exists, so the workspace never silently edits an
  // arena that defines the question.
  const arenaFixed = view?.arena.objective_fixed ?? capabilitiesForCurrent?.arena_fixed ?? false;

  /**
   * Put what is selected aside for a paste: the shapes, or the one part.
   *
   * A workspace with nothing selected copies nothing rather than guessing, which
   * is what keeps Ctrl+C from ever replacing a useful buffer with an empty one.
   */
  const copySelection = useCallback((): Clipboard | null => {
    if (mode === "shapes") {
      if (candidate === null || selected.length === 0) {
        return null;
      }
      const chosen = new Set(selected);
      const placements = candidate.placements
        .filter((placement) => chosen.has(placement.shape_id))
        .map((placement) => ({ ...placement }));
      return placements.length === 0 ? null : { kind: "shapes", placements };
    }
    if (mode === "arena") {
      const part = activePart === null ? undefined : parts[activePart];
      return part === undefined ? null : { kind: "arena", part: copyPart(part, part.index, part.op) };
    }
    if (mode === "compose") {
      const part = composerSelected === null ? undefined : composerParts[composerSelected];
      return part === undefined ? null : { kind: "compose", part: copyPart(part, part.index, part.op) };
    }
    return null;
  }, [activePart, candidate, composerParts, composerSelected, mode, parts, selected]);

  /**
   * Paste shapes as copies of themselves, with fresh identifiers.
   *
   * The same gesture as the inspector's Duplicate button, for a whole selection:
   * the problem's own shape count follows, the pasted shapes are selected, and the
   * whole paste is one entry in the history — undo puts back everything it added.
   */
  const pasteShapes = useCallback(
    (placements: PlacementDoc[]) => {
      if (candidate === null || placements.length === 0) {
        return;
      }
      remember(candidate);
      const all = [...candidate.placements];
      const copies = placements.map((placement) => {
        const copy: PlacementDoc = { ...placement, shape_id: nextShapeId(all) };
        all.push(copy);
        return copy;
      });
      setProblem(problem);
      setSelected(copies.map((copy) => copy.shape_id));
      editCandidate((current) => ({ ...current, placements: all }), problem);
    },
    [candidate, editCandidate, problem, remember],
  );

  // The editor reports the whole stack; the request wants the three fields the
  // engine reads, and the derived ones — index, label, bounds — are left out.
  const setParts = useCallback(
    (next: ArenaPartDoc[]) => void composeArena(next.map(partRequest)),
    [composeArena],
  );

  /**
   * Compile the composer's stack, as an editable picture and as a packable shape.
   *
   * The arena answer is what the canvas draws: it is the only answer that carries
   * every primitive's own outline and box, so a part can be grabbed where it stands,
   * exactly as in the arena. The shape answer is the judge — its refusal is shown as
   * it wrote it, and it is what joining the library stores. Both are the engine's.
   *
   * A newer edit cancels the answer of an older one, so the picture is always the
   * last stack that was sent, never a stale reply that happened to arrive late.
   */
  const compileComposer = useCallback((next: ArenaPartDoc[]) => {
    setComposerParts(next);
    const ticket = ++composerSeq.current;
    if (next.length === 0) {
      setComposerView(null);
      setComposerPreview(null);
      setComposerError(null);
      setComposerBusy(false);
      return;
    }
    setComposerBusy(true);
    const request = { parts: next.map(partRequest) };
    void Promise.allSettled([api.composeArena(request), api.composeShape(request)]).then(
      ([arena, shape]) => {
        if (ticket !== composerSeq.current) {
          return;
        }
        // The engine's own parts replace the seeded ones, so the canvas has a path
        // and a box for every primitive and the panel shows the engine's labels.
        setComposerView(arena.status === "fulfilled" ? arena.value : null);
        if (arena.status === "fulfilled") {
          setComposerParts(arena.value.parts);
          // The frame follows the stack: a part moved outside the picture stays
          // visible, which is what a composer with no fixed arena wants.
          setComposerFrame((key) => key + 1);
        }
        if (shape.status === "fulfilled") {
          setComposerPreview(shape.value);
          setComposerError(null);
        } else {
          setComposerPreview(null);
          setComposerError(describeError(shape.reason));
        }
        setComposerBusy(false);
      },
    );
  }, []);

  /**
   * The composer's own history: a stack of whole part-stack snapshots.
   *
   * It follows the same rule as the shapes and the arena — one gesture, one entry —
   * but what is remembered is the composer's stack, which the engine never sees as
   * a document. `remember`, `past` and `future` belong to the candidate and the
   * problem, so the composer keeps its own pair rather than mixing stacks and
   * placements in one list.
   *
   * `begin` captures the stack a run starts from, once per run; `end` records it
   * when the run closes. A stack is immutable here — every edit builds a new array
   * — so holding the reference is enough and no copying is needed.
   */
  const beginComposerEdit = useCallback(() => {
    if (composerGesture.current === null) {
      composerGesture.current = composerParts;
    }
  }, [composerParts]);

  const endComposerEdit = useCallback(() => {
    const before = composerGesture.current;
    composerGesture.current = null;
    if (before === null) {
      return;
    }
    setComposerPast((current) => [...current.slice(-(HISTORY_LIMIT - 1)), before]);
    setComposerFuture([]);
  }, []);

  /**
   * Apply one composer edit that is a whole gesture by itself, and record it.
   *
   * Any run the panel still has open is closed first — a field that kept the focus
   * while the canvas was grabbed must not be merged with the canvas gesture — and
   * the stack this edit starts from is then captured on its own.
   */
  const editComposer = useCallback(
    (next: ArenaPartDoc[]) => {
      endComposerEdit();
      beginComposerEdit();
      compileComposer(next);
      endComposerEdit();
    },
    [beginComposerEdit, compileComposer, endComposerEdit],
  );

  /** Undo or redo one composer gesture: the remembered stack is recompiled, never guessed. */
  const composerStep = useCallback(
    (direction: "undo" | "redo") => {
      // Close any run the panel still has open first, so the edit under the hand
      // becomes its own entry before the step moves through the history.
      endComposerEdit();
      const source = direction === "undo" ? composerPast : composerFuture;
      const target = source[source.length - 1];
      if (target === undefined) {
        return;
      }
      if (direction === "undo") {
        setComposerPast((current) => current.slice(0, -1));
        setComposerFuture((current) => [...current, composerParts]);
      } else {
        setComposerFuture((current) => current.slice(0, -1));
        setComposerPast((current) => [...current, composerParts]);
      }
      setComposerSelected(null);
      compileComposer(target);
    },
    [compileComposer, composerFuture, composerParts, composerPast, endComposerEdit],
  );

  /** Start the composer's history empty, when the composer is (re)opened on a stack. */
  const resetComposerHistory = useCallback(() => {
    composerGesture.current = null;
    setComposerPast([]);
    setComposerFuture([]);
  }, []);

  // A gesture belongs to the panel that opened it, so leaving the composer closes
  // any run left open there; its snapshot is recorded rather than dropped.
  useEffect(() => {
    if (mode !== "compose") {
      endComposerEdit();
    }
  }, [mode, endComposerEdit]);

  /**
   * Paste one part into the arena or the composer.
   *
   * The copy joins the stack with `union` — unless it is the first part, which is
   * the base by definition — so an arena that already holds something is left
   * exactly as it was. Either paste is one history entry like a shape's: the
   * arena's in the candidate's own stack, the composer's in its part-stack stack.
   */
  const pastePart = useCallback(
    (kind: "arena" | "compose", part: ArenaPartDoc) => {
      if (kind === "arena") {
        remember(candidate);
        const next = [...parts, copyPart(part, parts.length, parts.length === 0 ? "base" : "union")];
        setSelectedPart(next.length - 1);
        void composeArena(next.map(partRequest));
        return;
      }
      const next = [
        ...composerParts,
        copyPart(part, composerParts.length, composerParts.length === 0 ? "base" : "union"),
      ];
      setComposerSelected(next.length - 1);
      editComposer(next);
    },
    [candidate, composeArena, composerParts, editComposer, parts, remember],
  );

  const paste = useCallback(
    (copied: Clipboard) => {
      if (copied.kind === "shapes") {
        pasteShapes(copied.placements);
      } else {
        pastePart(copied.kind, copied.part);
      }
    },
    [pastePart, pasteShapes],
  );

  /** Add one primitive to the composer's stack, at a point, and select it. */
  const addComposerPart = useCallback(
    (op: ArenaPartOp, params: ArenaPartParams, offset: Point) => {
      // The first part of an empty stack is its base, whatever was asked for.
      const next: ArenaPartDoc[] = [
        ...composerParts,
        {
          index: composerParts.length,
          op: composerParts.length === 0 ? "base" : op,
          label: describePrimitive(params, t),
          offset,
          angle: 0,
          bounds: [0, 0, 0, 0],
          path: "",
          params,
        },
      ];
      setComposerSelected(next.length - 1);
      editComposer(next);
    },
    [composerParts, editComposer, t],
  );

  /**
   * Enter the composer workspace on a stack: the one being edited, or a fresh one.
   *
   * `spot` is where the palette was opened, and is what the new shape is placed at
   * when Validate returns to the shapes canvas; it is null when the tab itself was
   * clicked, and nothing is placed then.
   */
  const openComposer = useCallback(
    (current: ComposedShapeDoc | null, spot: Point | null) => {
      setCreate(null);
      setDrawing(null);
      setSelectedPart(null);
      setEditingComposed(current);
      setComposedSpot(spot);
      setComposerName(current?.name ?? t("My shape"));
      // A new composition opens with one editable primitive as an immediate example.
      const starter = elementaryShape("square")?.primitive ?? { kind: "rect", width: 2, height: 2 };
      const seed = current
        ? current.parts.map((part, index) => seedPart(part, index, t))
        : [seedPart({ op: "base", params: starter, offset: [0, 0], angle: 0 }, 0, t)];
      setComposerSelected(seed.length > 0 ? seed.length - 1 : null);
      composeCanvas.reset();
      // A stack opened from the library starts a fresh history: its edits are the
      // ones worth undoing, not the act of opening it.
      resetComposerHistory();
      compileComposer(seed);
      setRequestedMode("compose");
    },
    [compileComposer, composeCanvas.reset, resetComposerHistory, t],
  );

  /** Abandon the composition and go back to the shapes workspace. */
  const cancelComposer = useCallback(() => {
    setCreate(null);
    setDrawing(null);
    setEditingComposed(null);
    setComposedSpot(null);
    setRequestedMode("shapes");
  }, []);

  /**
   * Keep the compiled shape in the browser's library, and return to the shapes.
   *
   * What is stored is the engine's own answer to `/api/shape`: the outline it
   * measured, with the stack that produced it so the composer can reopen it. When
   * the composer was entered from a click on the shapes canvas, the new shape is
   * placed at that point as well, which is what the owner asked for.
   */
  const validateComposed = useCallback(() => {
    if (composerPreview === null || composerError !== null) {
      return;
    }
    const entry: ComposedShapeDoc = {
      id: editingComposed?.id ?? newComposedShapeId(),
      name: composerName.trim() === "" ? t("My shape") : composerName.trim(),
      shape: composerPreview.shape,
      parts: composerParts.map(partRequest),
      path: composerPreview.path,
      bounds: composerPreview.bounds,
      area: composerPreview.area,
      summary: composerPreview.summary,
    };
    setComposed((current) => upsertComposedShape(current, entry));
    const spot = composedSpot;
    setEditingComposed(null);
    setComposedSpot(null);
    setRequestedMode("shapes");
    if (spot !== null) {
      placeShape(entry.shape, spot[0], spot[1]);
    }
  }, [composerError, composerName, composerParts, composerPreview, composedSpot, editingComposed, placeShape, t]);

  /**
   * Start the arena over: one fresh rectangle, and nothing else.
   *
   * The domain has no empty arena — an arena *is* a region, and a packing needs
   * one — so "clear" cannot mean "nothing": it means the box a person would draw
   * first, which is the same default the create menu offers.
   */
  const resetArena = useCallback(() => {
    setCreate(null);
    setDrawing(null);
    setSelectedPart(null);
    void composeArena([
      { op: "base", params: ARENA_BASE, offset: [0, 0], angle: 0 },
    ]);
  }, [composeArena]);

  const addPart = useCallback(
    (op: ArenaPartOp, params: ArenaPartParams, offset: Point) => {
      // The first part of an empty stack is its base, whatever was asked for:
      // there is nothing yet for a union to join or a difference to cut.
      const applied: ArenaPartOp = parts.length === 0 ? "base" : op;
      void composeArena([...parts.map(partRequest), { op: applied, params, offset, angle: 0 }]);
    },
    [composeArena, parts],
  );

  const startDrawing = useCallback(
    (op: ArenaPartOp) => {
      setCreate(null);
      // A drawing belongs to whichever stack the current workspace is building.
      const stack = mode === "compose" ? composerParts : parts;
      setDrawing({ op: stack.length === 0 ? "base" : op, points: [] });
    },
    [composerParts, mode, parts],
  );

  const drawPoint = useCallback((world: Point) => {
    setDrawing((current) =>
      current === null ? null : { ...current, points: [...current.points, world] },
    );
  }, []);

  const finishDrawing = useCallback(() => {
    if (drawing === null) {
      return;
    }
    setDrawing(null);
    // A drawn outline is a polygon in the workspace's own coordinates: no primitive
    // frame is involved, so no offset is needed, and the engine refuses fewer
    // than three vertices in its own words.
    const polygon: ArenaPartParams = { kind: "polygon", points: drawing.points };
    if (mode === "compose") {
      addComposerPart(drawing.op, polygon, [0, 0]);
      return;
    }
    void composeArena([
      ...parts.map(partRequest),
      { op: drawing.op, params: polygon, offset: [0, 0], angle: 0 },
    ]);
  }, [addComposerPart, composeArena, drawing, mode, parts]);

  /** Open the creation menu where a click landed. */
  const requestCreate = useCallback((world: Point, at: Point) => {
    setDrawing(null);
    setCreate({ world, at });
  }, []);

  /**
   * What the creation menu offers.
   *
   * One list decides every elementary entry — the shared `ELEMENTARY_SHAPES` — so
   * the arena, the composer and the shapes workspace show the same names in the
   * same order, and no operation rides on them. The arena and the composer offer a
   * primitive each; the shapes workspace offers the engine families it can place,
   * and keeps its two extra groups, which are not shapes: the one already open on
   * the problem, and the composed library.
   */
  const createGroups = useCallback((): CreateGroup[] => {
    if (mode === "compose") {
      return [{ title: null, items: elementaryItems("compose") }];
    }
    if (problem === null) {
      return [];
    }
    if (mode === "arena") {
      return [{ title: null, items: elementaryItems("arena") }];
    }
    const current = palette.find((entry) => sameShape(entry.shape, problem.shape));
    // The engine publishes which families exist; the shared list fixes their order
    // and their one label. A family the engine does not publish stays absent, and
    // its entry names the reason beside the list.
    const elementary: CreateItem[] = ELEMENTARY_SHAPES
      .filter((entry) => entry.workspaces.includes("shapes") && entry.paletteId !== null)
      .flatMap((entry) => {
        const published = palette.find((item) => item.id === entry.paletteId);
        if (published === undefined) {
          return [];
        }
        return [{ id: `shape:${published.id}`, label: entry.label, sides: published.sides }];
      });
    return [
      {
        title: null,
        items: [{ id: "current", label: "this problem's shape", hint: current?.label }],
      },
      {
        title: "change the problem's shape to",
        items: elementary,
      },
      {
        title: "your own shapes",
        // One entry creates a shape; the other lists the library. The composed
        // shapes themselves stay behind that list, so the engine's families are
        // never crowded out of the menu by however many the browser holds.
        items: [
          { id: "composed:new", label: "create your own shape" },
          { id: "composed:library", label: "your shapes", hint: String(composed.length) },
        ],
      },
    ];
  }, [composed.length, mode, palette, problem]);

  /**
   * What a menu entry does.
   *
   * The composer and the arena name one elementary shape: the part joins with the
   * operation the panel's own add row used to carry — a composition unions, an arena
   * cuts a hole — and the card on the panel is where that operation is changed
   * afterwards. The shapes workspace keeps its own meanings: one more of the
   * problem's shape, another family (which converts every placement and changes the
   * problem), or the composed library.
   */
  const pickFromMenu = useCallback(
    (id: string, sides?: number, axes?: [number, number]) => {
      const spot = create;
      setCreate(null);
      if (spot === null) {
        return;
      }
      const separator = id.indexOf(":");
      const scope = separator === -1 ? id : id.slice(0, separator);
      if (scope === "compose" || scope === "arena") {
        const entry = elementaryShape(id.slice(separator + 1));
        if (entry === undefined) {
          return;
        }
        const op: ArenaPartOp = scope === "compose" ? "union" : "difference";
        if (entry.drawn === true) {
          // A polygon has no size to be added at: it is drawn, in either workspace.
          startDrawing(op);
          return;
        }
        const params = primitiveFromMenu(entry, sides, axes);
        if (params === null) {
          return;
        }
        if (scope === "compose") {
          addComposerPart(op, params, spot.world);
        } else {
          addPart(op, params, spot.world);
        }
        return;
      }
      if (problem === null) {
        return;
      }
      // The composer and its library are reached from the palette, and the library
      // places where the menu was opened — the same spot every other entry uses.
      if (id === "composed:new") {
        openComposer(null, spot.world);
        return;
      }
      if (id === "composed:library") {
        setComposedSpot(spot.world);
        setLibraryOpen(true);
        return;
      }
      if (id === "current") {
        placeShape(problem.shape, spot.world[0], spot.world[1]);
        return;
      }
      if (id.startsWith("shape:")) {
        const entry = palette.find((item) => item.id === id.slice("shape:".length));
        if (entry !== undefined) {
          // A resizable family is built from the count the menu reported, falling
          // back on the one the engine offered when the field holds something that
          // is not a number yet. A count below what the domain accepts is passed
          // through: the engine refuses it in its own words.
          const count =
            entry.sides === undefined || sides === undefined || !Number.isFinite(sides)
              ? entry.sides
              : Math.round(sides);
          const shape: ShapeDoc =
            count === undefined || entry.shape.type !== "regular_polygon"
              ? entry.shape
              : { type: "regular_polygon", sides: count, side: entry.shape.side };
          placeShape(shape, spot.world[0], spot.world[1]);
        }
        return;
      }
    },
    [addComposerPart, addPart, create, openComposer, palette, placeShape, problem, startDrawing],
  );

  const forgetComposedShape = useCallback((id: string) => {
    setComposed((current) => removeComposedShape(current, id));
  }, []);

  /** Place a composed shape where the palette was opened, like any other shape. */
  const placeComposedShape = useCallback(
    (entry: ComposedShapeDoc) => {
      if (composedSpot !== null) {
        placeShape(entry.shape, composedSpot[0], composedSpot[1]);
      }
      setLibraryOpen(false);
      setComposedSpot(null);
    },
    [composedSpot, placeShape],
  );

  /**
   * The keyboard shortcuts of the whole window.
   *
   * They live here rather than in the canvas because none of them depends on
   * what has focus — except that they must *not* fire while a field is being
   * typed into, which is the first thing this checks, and except for `Delete`
   * when a selection has something to remove: the two flags below say how that
   * one is arbitrated. Escape closes whatever is open, in that order: the
   * creation menu, a drawing, the selection.
   */
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target;
      // What the delete keys can remove right now. In the arena the selection is a
      // part of the stack, and its base is the region everything else folds into —
      // the toolbar's Clear is what starts the stack over, so the base is not a part
      // anyone deletes. In the shapes, it is whatever is selected.
      const removable =
        mode === "compose"
          ? composerSelected !== null && composerSelected > 0
          : mode === "arena"
            ? activePart !== null && activePart > 0
            : selected.length > 0;
      // Which key removes the selection, and whether it is this event's meaning. The
      // click that focuses a card's control — its operation select, a size slider, one
      // of its offset fields — selects that card's part as well, so a marked part and
      // the keyboard are regularly in two different places: a `Delete` typed there
      // looked like a shortcut that had stopped working, and it now reaches the part
      // from anywhere. `Backspace` is not that key: it is how a number is corrected, so
      // a field a keyboard types into keeps it, and it must never delete the part
      // standing behind the field. A control a mouse drives — a select, a slider, a
      // checkbox — types nothing, so both keys reach the part from there; and with
      // nothing selected, the field keeps `Delete` as well and erases forward.
      const inAControl =
        target instanceof HTMLElement &&
        (target.tagName === "INPUT" ||
          target.tagName === "SELECT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable);
      const inATypedField =
        target instanceof HTMLTextAreaElement ||
        (target instanceof HTMLElement && target.isContentEditable) ||
        (target instanceof HTMLInputElement && POINTED_INPUT_TYPES[target.type] !== true);
      const removesTheSelection =
        removable &&
        (event.key === "Delete" || (event.key === "Backspace" && !inATypedField));
      if (inAControl && !removesTheSelection) {
        return;
      }
      const command = event.ctrlKey || event.metaKey;
      const key = event.key.toLowerCase();
      // Copy and paste of the selection, in the three workspaces that hold an
      // editable item. The buffer is this window's own (see `clipboard`), so a
      // copy here never touches what another application put on the system
      // clipboard, and only the workspace that wrote it can read it back.
      if (command && key === "c") {
        const copied = copySelection();
        if (copied !== null) {
          event.preventDefault();
          clipboard.current = copied;
        }
        return;
      }
      if (command && key === "v") {
        const copied = clipboard.current;
        if (copied === null) {
          return;
        }
        event.preventDefault();
        paste(copied);
        return;
      }
      if (command && key === "a" && mode === "shapes" && candidate !== null) {
        event.preventDefault();
        setSelected(candidate.placements.map((item) => item.shape_id));
        return;
      }
      if (command && key === "z") {
        event.preventDefault();
        // The composer has a history of its own, over the stack it edits; every
        // other workspace undoes the candidate and the problem.
        if (mode === "compose") {
          composerStep(event.shiftKey ? "redo" : "undo");
        } else {
          step(event.shiftKey ? "redo" : "undo");
        }
        return;
      }
      if (command && key === "y") {
        event.preventDefault();
        if (mode === "compose") {
          composerStep("redo");
        } else {
          step("redo");
        }
        return;
      }
      if (event.key === "Escape") {
        if (create !== null) {
          setCreate(null);
        } else if (drawing !== null) {
          setDrawing(null);
        } else if (mode === "compose") {
          setComposerSelected(null);
        } else {
          setSelected([]);
        }
        return;
      }
      if (removesTheSelection) {
        event.preventDefault();
        if (mode === "compose") {
          const doomed = composerSelected;
          setComposerSelected(null);
          // Removing a part is one gesture, recorded like any other composer edit.
          editComposer(composerParts.filter((_, index) => index !== doomed));
        } else if (mode === "arena") {
          setSelectedPart(null);
          void composeArena(
            parts.filter((_, index) => index !== activePart).map(partRequest),
          );
        } else {
          removeShapes(selected);
        }
        return;
      }
      const nudge = event.shiftKey ? 0.1 : 0.01;
      let shift: [number, number] | null = null;
      if (event.key === "ArrowLeft") shift = [-nudge, 0];
      else if (event.key === "ArrowRight") shift = [nudge, 0];
      else if (event.key === "ArrowUp") shift = [0, nudge];
      else if (event.key === "ArrowDown") shift = [0, -nudge];
      if (shift === null || selected.length === 0 || candidate === null) {
        return;
      }
      event.preventDefault();
      remember(candidate);
      const chosen = new Set(selected);
      editCandidate((current) => ({
        ...current,
        placements: current.placements.map((placement) =>
          chosen.has(placement.shape_id)
            ? { ...placement, x: Math.round((placement.x + shift[0]) * 100) / 100,
                y: Math.round((placement.y + shift[1]) * 100) / 100 }
            : placement,
        ),
      }));
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [
    activePart,
    candidate,
    composeArena,
    composerParts,
    composerSelected,
    composerStep,
    copySelection,
    create,
    drawing,
    editCandidate,
    editComposer,
    mode,
    parts,
    paste,
    remember,
    removeShapes,
    selected,
    step,
  ]);

  const download = useCallback((name: string, content: string, type: string) => {
    const url = URL.createObjectURL(new Blob([content], { type }));
    const link = window.document.createElement("a");
    link.href = url;
    link.download = name;
    link.click();
    URL.revokeObjectURL(url);
  }, []);

  const exportSvg = useCallback(async () => {
    if (problem === null || candidate === null) {
      return;
    }
    try {
        const document = await api.render({ problem, candidate, options: {
          background: "#ffffff", arena_fill: "#ffffff", arena_stroke: "#555555",
          shape_fill: "#b6b6b6", shape_stroke: "#4d4d4d",
          show_violations: false, honor_shape_colors: false,
        } });
      download(`${problem.problem_id}-${candidate.candidate_id}.svg`, document, "image/svg+xml");
    } catch (cause) {
      setError(describeError(cause));
    }
  }, [candidate, download, problem]);

  // The two document exports write exactly the formats the command line reads
  // back with `-p` and `-c`: what was built here can be replayed, versioned or
  // handed to someone else without any conversion.
  const exportProblem = useCallback(() => {
    if (problem !== null) {
      download(`${problem.problem_id}.json`, JSON.stringify(problem, null, 2), "application/json");
    }
  }, [download, problem]);

  const exportCandidate = useCallback(() => {
    if (candidate !== null) {
      download(
        `${candidate.candidate_id}.json`,
        JSON.stringify(candidate, null, 2),
        "application/json",
      );
    }
  }, [candidate, download]);

  const showGuideStep = useCallback((index: number) => {
    if (index < 0 || index >= QUICK_START_STEPS) return;
    if (index <= 4) {
      const count = [2, 5, 5, 11, 17][index]!;
      const record = SQUARE_RECORDS.find((entry) => entry.count === count);
      if (record) {
        setCategoryId(STARTER_CATEGORY_ID);
        const naive: CandidateDoc | undefined = index === 1 ? {
          candidate_id: "squares-5-guide-naive", problem_id: "squares-5-in-smallest-square",
          scale: 1, origin: "tutorial", generation: 0, parents: [], metadata: {},
          placements: [
            { shape_id: "s000", x: .5, y: .5 }, { shape_id: "s001", x: 1.5, y: .5 },
            { shape_id: "s002", x: .5, y: 1.5 }, { shape_id: "s003", x: 1.5, y: 1.5 },
            { shape_id: "s004", x: .5, y: 2.5 },
          ],
        } : undefined;
        void activateLocal(squareProblem(record), naive);
      }
    }
    setModelsOpen(index === 12);
    if (index === 9) {
      if (composerParts.length === 0) openComposer(null, null);
      else setRequestedMode("compose");
    } else if (index >= 11 && index <= 13) {
      setRequestedMode("run");
    } else if (index === 14) {
      setRequestedMode("search");
    } else {
      setRequestedMode("shapes");
    }
    setGuideStep(index);
  }, [activateLocal, composerParts.length, openComposer]);

  const startGuide = useCallback(() => {
    window.localStorage.setItem("paper-obs-guide-v1", "seen");
    showGuideStep(0);
  }, [showGuideStep]);

  useEffect(() => {
    if (problem !== null && candidate !== null && view !== null && !busy
      && window.localStorage.getItem("paper-obs-guide-v1") !== "seen") startGuide();
  }, [problem, candidate, view, busy, startGuide]);

  return (
    <div className={`app${error === null ? "" : " app--error"}${new URLSearchParams(window.location.search).get("nav") === "classic" ? "" : " app--book"}`} style={pageStyle}>
      <Toolbar
        examples={examples}
        categories={library.categories}
        categoryId={categoryId}
        localProblems={library.problems}
        problemId={problem?.problem_id ?? null}
        onProblemChange={selectProfile}
        onCategory={(id) => {
          setCategoryId(id);
          const firstProfile = library.categories.find((category) => category.id === id)?.problemIds[0];
          if (firstProfile) selectProfile(firstProfile);
        }}
        onDeleteCategory={(id) => {
          if (library.categories.length < 2) return;
          const remaining = library.categories.filter((category) => category.id !== id);
          setLibrary((current) => removeCategory(current, id));
          if (categoryId === id) {
            const next = remaining[0];
            if (next) {
              setCategoryId(next.id);
              if (next.problemIds[0]) selectProfile(next.problemIds[0]);
            }
          }
        }}
        onRemoveProblem={(id) => {
          const current = library.categories.find((category) => category.id === categoryId);
          const next = current?.problemIds.find((problemId) => problemId !== id);
          setLibrary((value) => removeProfile(value, categoryId, id));
          if (id === problem?.problem_id) {
            if (next) selectProfile(next);
            else {
              setProblem(null);
              setCandidate(null);
              setEvaluation(null);
              setView(null);
              setSummary(null);
              setScaleBounds(null);
              setSelected([]);
              setPast([]);
              setFuture([]);
              setBest(null);
              forgetCurve();
              forgetRun();
              window.localStorage.removeItem(ACTIVE_PROFILE_STORAGE);
            }
          }
        }}
        onEditProblem={(id) => {
          void (async () => {
            try {
              if (problem?.problem_id !== id) {
                const local = library.problems[id];
                if (local) await activateLocal(local);
                else await loadExample(id);
              }
              setEditorForNew(false);
              setEditorOpen(true);
            } catch (cause) { setError(describeError(cause)); }
          })();
        }}
        onCreateCategory={(name) => {
          const id = `category-${crypto.randomUUID()}`;
          setLibrary((current) => ({ ...current, categories: [...current.categories, { id, name, problemIds: [] }] }));
          setCategoryId(id);
        }}
        onRenameCategory={(id, name) => setLibrary((current) => ({ ...current,
          categories: current.categories.map((category) => category.id === id ? { ...category, name } : category),
        }))}
        onAddSquare={addSquare}
        // A generated catalogue instance joins the active category on the same
        // terms as a square record: an example the engine already serves is
        // referenced by identifier, so its published candidate stays the one
        // loaded; a generated document is stored as a local profile and opened.
        onAddProblem={(added: ProblemDoc) => {
          const builtIn = examples.some((example) => example.problem_id === added.problem_id);
          setLibrary((current) => includeProfile(current, categoryId, builtIn ? added.problem_id : added));
          if (builtIn) void loadExample(added.problem_id);
          else void activateLocal(added);
        }}
          onNewCustom={() => { setEditorForNew(true); setEditorOpen(true); }}
          onImportProblem={importProblem}
        strategy={activeStrategy}
        strategies={offeredStrategies}
        onStrategyChange={(next) => {
          setStrategy(next);
          if (problem !== null) {
            void runInit(problem, next);
          }
        }}
        onOpenModels={() => setModelsOpen(true)}
        onOpenImport={() => setImportOpen(true)}
        onExportSvg={() => void exportSvg()}
        onExportProblem={exportProblem}
        onExportCandidate={exportCandidate}
        scale={candidate?.scale ?? null}
        effectiveRadius={view?.shapes.find((shape) => shape.kind === "circle")?.radius ?? null}
        scaleBounds={scaleBounds}
        onScaleChange={(scale) => {
          beginGesture();
          editCandidate((current) => ({ ...current, scale }));
        }}
        onScaleCommit={endGesture}
        busy={busy}
        mode={mode}
        onClear={mode === "arena" ? resetArena : clearShapes}
        canClear={mode === "arena" || candidate !== null}
        // The composer keeps its own history, so the buttons and the keyboard read
        // whichever stack the current workspace writes.
        canUndo={mode === "compose" ? composerPast.length > 0 : past.length > 0}
        onUndo={() => (mode === "compose" ? composerStep("undo") : step("undo"))}
        canRedo={mode === "compose" ? composerFuture.length > 0 : future.length > 0}
        onRedo={() => (mode === "compose" ? composerStep("redo") : step("redo"))}
        onOpenGuide={startGuide}
        onOpenStatistics={() => { void refreshRuns(); setStatisticsOpen(true); }}
        guideReveal={guideStep === 5 ? "picker" : guideStep === 6 ? "catalog-list" : guideStep === 7 ? "catalog-family" : null}
      />
      {error !== null && <div className="error">{error}</div>}
      {statisticsOpen && <StatisticsPage runs={runs.filter((item) => !item.example)} workflows={workflows} onDownload={download}
        onClose={() => setStatisticsOpen(false)}
        onOpen={(runId) => { setStatisticsOpen(false); setRequestedMode("run"); void openRun(runId); }} />}
      <div className="workspace-shell">
        <span className="workspace-shell__left-pages" aria-hidden="true" />
      <WorkspaceTabs mode={mode}
        arenaAvailable={problem === null || (problem.objective.type !== "minimize_container" && problem.objective.type !== "maximize_covered_size")}
        problemAvailable={problem !== null}
          onChange={(next) => {
            setCreate(null);
            setDrawing(null);
            setSelectedPart(null);
            setComposerSelected(null);
            // The first visit seeds one editable primitive for orientation.
            if (next === "compose" && composerParts.length === 0 && mode !== "compose") {
              openComposer(null, null);
              return;
            }
            setRequestedMode(next);
          }} />
      {mode === "run" ? <RunWorkspace
        workflows={workflows}
        problemId={problem?.problem_id ?? null}
        problemName={problem?.name ?? null}
        starting={starting}
        objective={problem?.objective.type ?? null}
        run={run}
        runs={runs}
        watching={watching !== null}
        stopping={stopping}
        error={runError}
        onStart={(workflow, budget, name, maxTokens, resume) => void startRun(workflow, budget, name, maxTokens, resume)}
        onDelete={(runId) => void deleteRun(runId)}
        onRestore={(runId) => void restoreRun(runId)}
        onOpenModels={() => setModelsOpen(true)}
        onStop={() => void stopRun()}
        onOpen={(runId) => void openRun(runId)}
        onBrowse={() => void refreshRuns()}
        onNew={closeRun}
        onReplay={(step) => void replayTurn(step)}
        onReplayCandidate={(snapshot) => void replayCandidate(snapshot)}
        reference={referenceOf(problem)}
        evaluation={evaluation}
        summary={summary}
        best={best}
        busy={busy}
        canvas={<PackingCanvas readOnly orientationHighlights={showOrientations} showIds={showShapeIds} onToggleIds={() => setShowShapeIds((value) => !value)} framingKey={framingKey} view={view} candidate={candidate} selectedIds={selected} onSelect={setSelected}
          canvas={runCanvas} onRequestCreate={idle} onGestureStart={idle} onDrag={idle} onTurn={idle} onGestureEnd={idle}
          translucent={translucentCopies} />}
        showOrientations={showOrientations} onToggleOrientations={() => setShowOrientations((value) => !value)} view={view}
      /> : mode === "search" ? <SearchWorkspace
        baselines={searchAvailable ? searchStrategies : []}
        convergence={convergence} searchSummary={searchSummary} searchError={searchError}
        onRun={(baseline, budget) => void runSearch(baseline, budget)}
        onShowCandidate={(shown) => void showResearchCandidate(shown)}
        onOpenSession={(sessionId) => void openResearchSession(sessionId)}
        evaluation={evaluation} verdictSummary={summary} best={best} problem={problem}
        view={view} busy={busy} showOrientations={showOrientations}
        onToggleOrientations={() => setShowOrientations((value) => !value)}
        canvas={<PackingCanvas readOnly orientationHighlights={showOrientations} showIds={showShapeIds}
          onToggleIds={() => setShowShapeIds((value) => !value)} framingKey={framingKey}
          view={view} candidate={candidate} selectedIds={selected} onSelect={setSelected}
          canvas={searchCanvas} onRequestCreate={idle} onGestureStart={idle} onDrag={idle}
          onTurn={idle} onGestureEnd={idle} translucent={translucentCopies} />}
      /> : <div className="app__body">
        {mode === "arena" ? (
          <ArenaCanvas
            framingKey={framingKey}
            problemId={problem?.problem_id ?? null}
            parts={parts}
            selectedPart={activePart}
            onSelectPart={setSelectedPart}
            path={arenaPreview?.path ?? view?.arena.path ?? ""}
            frame={view?.frame ?? null}
            shapes={view?.shapes ?? []}
            editable={(view?.arena.editable ?? true) && !arenaFixed}
            canvas={canvas}
            drawing={drawing === null ? null : { points: drawing.points }}
            onRequestCreate={requestCreate}
            onDrawPoint={drawPoint}
            onFinishDrawing={finishDrawing}
            onCancelDrawing={() => setDrawing(null)}
            onChange={setParts}
          />
        ) : mode === "compose" ? (
          <ArenaCanvas
            framingKey={composerFrame}
            problemId="composer"
            parts={composerParts}
            selectedPart={composerSelected}
            onSelectPart={setComposerSelected}
            path={composerView?.path ?? ""}
            frame={composerView?.bounds ?? EMPTY_COMPOSER_FRAME}
            shapes={[]}
            editable
            canvas={composeCanvas}
            drawing={drawing === null ? null : { points: drawing.points }}
            onRequestCreate={requestCreate}
            onDrawPoint={drawPoint}
            onFinishDrawing={finishDrawing}
            onCancelDrawing={() => setDrawing(null)}
            // The canvas reports once per gesture — a move, a resize or a turn —
            // so every report here is a whole undo step of the composer's own.
            onChange={editComposer}
            emptyText={t("Build a shape: right-click or double-click to add a primitive.")}
          />
        ) : (
          <PackingCanvas
            orientationHighlights={showOrientations}
            showIds={showShapeIds}
            onToggleIds={() => setShowShapeIds((value) => !value)}
            framingKey={framingKey}
            view={view}
            candidate={candidate}
            selectedIds={selected}
            onSelect={setSelected}
            canvas={canvas}
            // A run's arrangement is read, not edited: the gestures that would
            // change it are the ones nobody is making while watching a workflow.
            onRequestCreate={requestCreate}
            onGestureStart={beginGesture}
            onDrag={dragSelection}
            onTurn={turnSelection}
            onGestureEnd={endGesture}
            // The local-size gesture exists only where the objective gives a copy
            // its own size; the resize handle is offered on that family alone.
            localScaleBounds={problem?.objective.type === "maximize_total_perimeter" ? scaleBounds : null}
            onLocalScale={previewScale}
            onLocalScaleCommit={endGesture}
            // The copies are translucent exactly for a covering; every other
            // objective draws them solid, from the one boolean above.
            translucent={translucentCopies}
          />
        )}
        <aside className="panel">
          {mode === "arena" ? <section className="panel__section arena-summary">
            <h2 className="panel__title">{t("Arena")}</h2>
            <div className="readout"><span>{t("Arena parts")}</span><strong>{parts.length}</strong></div>
            <div className="readout"><span>{t("area")}</span><strong>{arenaPreview?.area == null ? (evaluation?.metrics.arena_area == null ? "—" : evaluation.metrics.arena_area.toFixed(4)) : arenaPreview.area.toFixed(4)}</strong></div>
          </section> : mode === "compose" ? null : <><StatusPanel evaluation={evaluation} summary={summary} busy={busy} best={best} view={view} problem={problem}
            showOrientations={showOrientations} onToggleOrientations={() => setShowOrientations((value) => !value)} />
          <ReferencePanel problemId={problem?.problem_id ?? null} reference={problem ? readReference(problem.metadata.reference) : null}
            candidateOrigin={candidate?.origin ?? null}
            onChange={(reference) => {
              if (!problem) return;
              setProblem({ ...problem, metadata: { ...problem.metadata, reference } });
              setReferenceEdits((current) => ({ ...current, [problem.problem_id]: reference }));
              const local = library.problems[problem.problem_id];
              if (local) {
                setLibrary((current) => ({ ...current, problems: {
                  ...current.problems,
                  [problem.problem_id]: { ...local, metadata: {
                    ...local.metadata, reference,
                  } },
                } }));
              }
            }} /></>}
          {mode === "arena" ? (
            <ArenaPanel
              parts={parts}
              selectedPart={activePart}
              onSelectPart={setSelectedPart}
              editable={(view?.arena.editable ?? true) && !arenaFixed}
              fixedByObjective={arenaFixed}
              drawing={drawing}
              onFinishDrawing={finishDrawing}
              onCancelDrawing={() => setDrawing(null)}
              onChange={setParts}
            />
          ) : mode === "compose" ? (
            <ShapeComposerPanel
              name={composerName}
              onName={setComposerName}
              parts={composerParts}
              selectedPart={composerSelected}
              onSelectPart={setComposerSelected}
              drawing={drawing}
              onFinishDrawing={finishDrawing}
              onCancelDrawing={() => setDrawing(null)}
              // The panel reports a field while it is typed and closes the run on
              // blur or pointer-up; the pair below turns that into one undo step.
              onChange={compileComposer}
              onEditStart={beginComposerEdit}
              onEditEnd={endComposerEdit}
              preview={composerPreview}
              error={composerError}
              busy={composerBusy}
              editing={editingComposed !== null}
              onCancel={cancelComposer}
              onValidate={validateComposed}
            />
          ) : (
            <ShapeInspector
              problem={problem}
              candidate={candidate}
              scaleBounds={scaleBounds}
              selectedIds={selected}
              ink={ink}
              onPaint={paintSelection}
              // Painting every shape is not a selection of everything: it writes the
              // colour in hand on every placement, whatever is selected.
              onPaintAll={() => paint(ink, "all")}
              onChange={(shapeId, patch) => {
                remember(candidate);
                editCandidate((current) => ({
                  ...current,
                  placements: current.placements.map((placement) =>
                    placement.shape_id === shapeId ? { ...placement, ...patch } : placement,
                  ),
                }));
              }}
              // The slider reports every move and the release closes the one
              // gesture: the copy grows under the hand and one undo step remains.
              onScalePreview={previewScale}
              onScaleCommit={endGesture}
              onDuplicate={duplicateShape}
              onDelete={removeShapes}
            />
          )}
          {mode === "shapes" && <NotesPanel key={problem?.problem_id ?? "none"} problemId={problem?.problem_id ?? null} />}
        </aside>
      </div>}
      </div>
      {create !== null && (
        <CreateMenu
          at={create.at}
          title={t("add a shape here")}
          groups={createGroups()}
          onPick={pickFromMenu}
          onClose={() => setCreate(null)}
        />
      )}
      <ImportPanel
        open={importOpen}
        shapes={palette}
        shape={problem?.shape ?? null}
          onImport={importPositions}
          onImportCandidate={importCandidate}
        onClose={() => setImportOpen(false)}
      />
      <ProviderPanel open={modelsOpen} onClose={() => setModelsOpen(false)} />
      <ProblemEditor
        open={editorOpen}
        current={editorForNew ? null : problem}
        shapes={palette}
        coverTargets={coverTargets}
        onClose={() => setEditorOpen(false)}
        onApply={(next) => {
          const oldId = editorForNew ? null : problem?.problem_id ?? null;
          const shared = oldId !== null && library.categories.some((category) =>
            category.id !== categoryId && category.problemIds.includes(oldId));
          const isolated = shared && next.problem_id === oldId
            ? { ...next, problem_id: `${oldId}-edited-${crypto.randomUUID().slice(0, 8)}` } : next;
          const sameGeometry = problem !== null && !editorForNew &&
            JSON.stringify([problem.arena, problem.shape, problem.objective, problem.rotation, problem.constraints]) ===
            JSON.stringify([isolated.arena, isolated.shape, isolated.objective, isolated.rotation, isolated.constraints]);
          const target = sameGeometry ? { ...isolated, metadata: problem.metadata } : isolated;
          if (!sameGeometry) {
            setReferenceEdits((current) => {
              const updated = { ...current };
              delete updated[target.problem_id];
              return updated;
            });
          }
          setEditorOpen(false);
          setEditorForNew(false);
          setProblem(target);
          setLibrary((current) => oldId === null ? includeProfile(current, categoryId, target)
            : replaceProfile(current, categoryId, oldId, target));
          if (sameGeometry && target.problem_id === oldId) return;
          setBest(null);
          setArenaPreview(null);
          // An edited problem is another problem: neither the curve of the previous
          // one nor the run watched on it is about this document.
          forgetCurve();
          forgetRun();
          setPendingOpenInit(target);
        }}
      />
      <ShapeLibrary
        open={libraryOpen}
        shapes={composed}
        onClose={() => {
          setLibraryOpen(false);
          setComposedSpot(null);
        }}
        onNew={() => {
          // The library was opened from a click on the shapes canvas, so Validate
          // places the new shape back at that point.
          setLibraryOpen(false);
          openComposer(null, composedSpot);
        }}
        onEdit={(entry) => {
          setLibraryOpen(false);
          openComposer(entry, composedSpot);
        }}
        onDelete={forgetComposedShape}
        onPlace={placeComposedShape}
      />
      {guideStep !== null && <QuickStart stepIndex={guideStep} onStep={showGuideStep} onClose={() => { setGuideStep(null); setModelsOpen(false); }} />}
    </div>
  );
}
