/**
 * Building a problem without writing JSON.
 *
 * The form edits a *document*, not a problem object: what it hands back is
 * exactly the shape of a problem file, so the engine's own validation messages
 * are what the user sees when something is wrong.
 *
 * The form is a sequence of sections — what the problem is called, its
 * objective, its arena, its shape family, its rotation policy, its seed — in the
 * order a person decides them, each with one sentence saying what it decides.
 * Pasting
 * Importing a known solution is not here: that is what one does *in* a problem,
 * not what one does to create it, so the dialog lives beside the toolbar.
 * is the one thing here that does not build a problem one field at a time.
 *
 * The arena is the one part of the document the form cannot always edit: a
 * composite arena (union, difference, intersection, polygon) has no field here,
 * and the form says so rather than quietly replacing it with a rectangle. It is
 * also the one section that can be absent altogether: an objective that measures
 * its own region declares no arena, and `buildProblem` then writes none, so the
 * form hides the whole section instead of offering fields it would discard.
 *
 * Which shape families exist, and how big one is by nature, is the engine's
 * palette, fetched by the application and passed in: the form chooses a family
 * and, when that family leaves the side count open, asks for the count.
 */
import { useState, type ReactNode } from "react";
import type { CoverTarget } from "../equalCopiesCatalog";
import { useI18n } from "../i18n";
import type {
  ArenaDoc,
  ArenaNodeDoc,
  ObjectiveDoc,
  ProblemDoc,
  RotationDoc,
  ShapeDoc,
  ShapeFamilyDoc,
} from "../types";
import { familyForShape } from "./ImportPanel";
export type ProblemEditorProps = {
  open: boolean;
  /** Problem to prefill the form with, or null to start from a default. */
  current: ProblemDoc | null;
  /** The engine's palette: which families exist, and what each one builds. */
  shapes: ShapeFamilyDoc[];
  /** The cover targets the engine measures: which one the derived reading may name. */
  coverTargets: readonly CoverTarget[];
  onClose: () => void;
  /** Called with a complete problem document, ready to be sent to the engine. */
  onApply: (problem: ProblemDoc) => void;
};
type ArenaKind = "rect" | "disk" | "regular_ngon" | "keep";
type ObjectiveKind =
  | "maximize_scale"
  | "maximize_count"
  | "minimize_container"
  | "maximize_covered_size"
  | "maximize_total_perimeter";
/**
 * The objective a new problem starts on.
 *
 * Exported because the page opens the tool on an example of the same family: the
 * default the form builds and the default the lab shows are one decision, and two
 * constants would drift apart. It is the family the channel explains last.
 */
export const DEFAULT_OBJECTIVE_KIND: ObjectiveKind = "minimize_container";
type RotationMode = "fixed" | "discrete" | "free";
/** Every field is held as text: the form never parses halfway through a keystroke. */
type FormState = {
  problemId: string;
  /** Whether the identifier was typed by hand: it then stops following the name. */
  problemIdTouched: boolean;
  name: string;
  seed: string;
  arenaKind: ArenaKind;
  /** The arena exactly as it was loaded, for the "keep" case. */
  arenaLoaded: ArenaDoc | null;
  arenaWidth: string;
  arenaHeight: string;
  arenaRadius: string;
  arenaSides: string;
  arenaCircumradius: string;
  /** Identifier of the palette entry the form is on, once one has been chosen. */
  shapeFamily: string;
  /** The shape exactly as it was loaded, for the case of a palette that is absent. */
  shapeLoaded: ShapeDoc | null;
  circleRadius: string;
  polygonSides: string;
  polygonSide: string;
  objectiveKind: ObjectiveKind;
  objectiveCount: string;
  objectiveScale: string;
  /** The target the derived covering measures; absent on every other objective. */
  objectiveTarget: CoverTarget;
  rotationMode: RotationMode;
  angles: string;
};
/** A 10 x 10 rectangle, 25 discs of natural diameter 1, maximising the scale. */
const DEFAULT_STATE: FormState = {
  problemId: "new-problem",
  problemIdTouched: false,
  name: "New problem",
  seed: "",
  arenaKind: "rect",
  arenaLoaded: null,
  arenaWidth: "10",
  arenaHeight: "10",
  arenaRadius: "5",
  arenaSides: "6",
  arenaCircumradius: "5",
  shapeFamily: "",
  shapeLoaded: null,
  circleRadius: "0.5",
  polygonSides: "4",
  polygonSide: "1",
  objectiveKind: DEFAULT_OBJECTIVE_KIND,
  objectiveCount: "25",
  objectiveScale: "1",
  objectiveTarget: "circle",
  rotationMode: "fixed",
  angles: "0",
};
const ARENA_OPTIONS: readonly { value: ArenaKind; label: string }[] = [
  { value: "rect", label: "rectangle" },
  { value: "disk", label: "disc" },
  { value: "regular_ngon", label: "regular polygon" },
  { value: "keep", label: "as loaded" },
];
const OBJECTIVE_OPTIONS: readonly { value: ObjectiveKind; label: string }[] = [
  { value: "maximize_scale", label: "maximise the scale" },
  { value: "maximize_count", label: "maximise the count" },
  { value: "minimize_container", label: "minimise the container" },
  { value: "maximize_covered_size", label: "maximise the covered target" },
  { value: "maximize_total_perimeter", label: "maximise the total perimeter" },
];
const ROTATION_OPTIONS: readonly { value: RotationMode; label: string }[] = [
  { value: "fixed", label: "fixed" },
  { value: "discrete", label: "discrete" },
  { value: "free", label: "free" },
];
function isEditableArena(kind: string): kind is ArenaKind {
  return kind === "rect" || kind === "disk" || kind === "regular_ngon";
}
/**
 * The identifier a name suggests: lower case, accents folded to their base
 * letters, runs of anything else collapsed to one hyphen, and no hyphen left at
 * either end — the shape of the engine's own example identifiers.
 */
function identifierFrom(name: string): string {
  return name
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}
/** One decision of the form: its heading, one sentence, and the fields it takes. */
function Section({
  title,
  note,
  children,
}: {
  title: string;
  note: string;
  children: ReactNode;
}) {
  const { t } = useI18n();
  return (
    <section className="panel__section">
      <h3 className="panel__title">{t(title)}</h3>
      <p className="muted">{t(note)}</p>
      <div className="grid-2">{children}</div>
    </section>
  );
}
function TextField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const { t } = useI18n();
  return (
    <label className="field">
      <span className="field__label">{t(label)}</span>
      <input className="input" value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}
function NumberField({
  label,
  value,
  min,
  step = "any",
  narrow = false,
  onChange,
}: {
  label: string;
  value: string;
  /** The smallest value the field offers, when the engine refuses to go below it. */
  min?: number;
  /** The step the spinner walks: 1 for a count, any for a size. */
  step?: number | "any";
  /** A field for a small number, which does not need the whole cell. */
  narrow?: boolean;
  onChange: (value: string) => void;
}) {
  const { t } = useI18n();
  return (
    <label className="field">
      <span className="field__label">{t(label)}</span>
      <input
        className={narrow ? "input input--narrow" : "input"}
        type="number"
        min={min}
        step={step}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}
function SelectField<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: readonly { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  const { t } = useI18n();
  return (
    <label className="field">
      <span className="field__label">{t(label)}</span>
      <select
        className="select"
        value={value}
        onChange={(event) => onChange(event.target.value as T)}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {t(option.label)}
          </option>
        ))}
      </select>
    </label>
  );
}
/**
 * The target a legacy fixed-arena covering names, read from the unit arena it
 * declared. The product no longer offers that reading, so a document that still
 * carries it opens the editor on the derived model at the same target.
 */
function coverTargetFromArena(arena: ArenaDoc | undefined): CoverTarget | null {
  const shape = arena?.shape;
  if (shape === undefined) return null;
  if (shape.type === "disk") return "circle";
  if (shape.type === "rect") return "square";
  if (shape.type === "regular_ngon" && shape.sides === 3) return "triangle";
  return null;
}

/** Put an engine-authored arena document into the form's arena fields. */
function applyArenaFields(state: FormState, arena: ArenaDoc | null): void {
  const shape = arena?.shape;
  if (shape === undefined) {
    state.arenaKind = "rect";
  } else if (shape.type === "rect") {
    state.arenaKind = "rect";
    state.arenaWidth = String(shape.width);
    state.arenaHeight = String(shape.height);
  } else if (shape.type === "disk") {
    state.arenaKind = "disk";
    state.arenaRadius = String(shape.radius);
  } else if (shape.type === "regular_ngon") {
    state.arenaKind = "regular_ngon";
    state.arenaSides = String(shape.sides);
    state.arenaCircumradius = String(shape.circumradius);
  } else {
    // A composite arena — a stack of primitives built in the arena editor, or a
    // rectangle with a hole in it — has no three numbers to show. Keeping the
    // document is the only honest answer: flattening it here would destroy work
    // the form never displayed.
    state.arenaKind = "keep";
    state.arenaLoaded = { name: arena?.name ?? "arena", shape };
  }
}

/** Read the fields of an editable problem back into the form. */
function stateFrom(problem: ProblemDoc, shapes: ShapeFamilyDoc[]): FormState {
  const state: FormState = {
    ...DEFAULT_STATE,
    problemId: problem.problem_id,
    name: problem.name,
    seed: problem.seed === null ? "" : String(problem.seed),
    rotationMode: problem.rotation.mode,
    angles: problem.rotation.angles.join(", "),
    shapeLoaded: problem.shape,
  };
  // A problem whose objective measures its own region declares no arena; the form
  // then holds whatever the objective is, and the arena fields are not shown. A
  // derived covering declares no arena at all, so there is nothing to prefill.
  const loaded = problem.arena;
  applyArenaFields(state, loaded ?? null);
  const family = familyForShape(shapes, problem.shape);
  state.shapeFamily = family?.id ?? "";
  if (problem.shape.type === "circle") {
    state.circleRadius = String(problem.shape.radius);
  } else {
    // A hand-drawn outline has no side count to edit, so the form shows the
    // family that stands for it: this editor builds a shape out of a family and
    // its numbers, and it says which fields it is replacing rather than
    // pretending to edit a drawing it cannot show.
    const familyShape = family === null ? null : family.shape;
    const polygon =
      familyShape !== null && familyShape.type === "regular_polygon" ? familyShape : null;
    state.polygonSides = String(
      problem.shape.type === "regular_polygon"
        ? problem.shape.sides
        : polygon?.sides ?? Number(DEFAULT_STATE.polygonSides),
    );
    state.polygonSide = String(
      problem.shape.type === "regular_polygon"
        ? problem.shape.side
        : polygon?.side ?? Number(DEFAULT_STATE.polygonSide),
    );
  }
  if (problem.objective.type === "maximize_count") {
    state.objectiveKind = "maximize_count";
    state.objectiveScale = String(problem.objective.scale);
  } else if (problem.objective.type === "maximize_covered_size") {
    state.objectiveKind = "maximize_covered_size";
    state.objectiveCount = String(problem.objective.count);
    state.objectiveTarget = problem.objective.target;
  } else if (problem.objective.type === "cover_region") {
    // A legacy fixed-arena covering: the product no longer offers that reading, so
    // the form opens on the derived model with the target its unit arena named.
    state.objectiveKind = "maximize_covered_size";
    state.objectiveCount = String(problem.objective.count);
    state.objectiveTarget = coverTargetFromArena(problem.arena) ?? state.objectiveTarget;
  } else {
    state.objectiveKind = problem.objective.type;
    state.objectiveCount = String(problem.objective.count);
  }
  return state;
}
/** Choose a family: the numbers that follow are the new family's own. */
function withFamily(state: FormState, family: ShapeFamilyDoc): FormState {
  const shape = family.shape;
  if (shape.type === "circle") {
    return { ...state, shapeFamily: family.id, circleRadius: String(shape.radius) };
  }
  if (shape.type !== "regular_polygon") {
    // The catalogue offers no outline; a family that were one would have no
    // count to show, and the form keeps the numbers it holds.
    return { ...state, shapeFamily: family.id };
  }
  return {
    ...state,
    shapeFamily: family.id,
    polygonSides: String(family.sides ?? shape.sides),
    polygonSide: String(shape.side),
  };
}
function buildArena(state: FormState): ArenaNodeDoc {
  if (state.arenaKind === "keep") {
    // `stateFrom` fills this in for every problem whose arena needs keeping.
    return state.arenaLoaded?.shape ?? { type: "rect", width: 10, height: 10 };
  }
  if (state.arenaKind === "disk") {
    return { type: "disk", radius: Number(state.arenaRadius) };
  }
  if (state.arenaKind === "regular_ngon") {
    return {
      type: "regular_ngon",
      sides: Number(state.arenaSides),
      circumradius: Number(state.arenaCircumradius),
    };
  }
  return { type: "rect", width: Number(state.arenaWidth), height: Number(state.arenaHeight) };
}
/**
 * The shape the form describes.
 *
 * A family with a fixed count is the shape the palette hands over, once its side
 * has been read; a family whose count is the caller's builds a regular polygon
 * at that count. Without a palette there is nothing to choose from, and the
 * shape the form was handed is kept — except for an outline it cannot show,
 * which becomes the polygon its fields describe, as this form has always done
 * with one.
 */
function buildShape(state: FormState, family: ShapeFamilyDoc | null): ShapeDoc {
  if (family === null) {
    if (state.shapeLoaded === null) {
      return { type: "circle", radius: Number(state.circleRadius) };
    }
    if (state.shapeLoaded.type !== "custom_polygon") {
      return state.shapeLoaded;
    }
    return {
      type: "regular_polygon",
      sides: Number(state.polygonSides),
      side: Number(state.polygonSide),
    };
  }
  if (family.shape.type === "circle") {
    return { type: "circle", radius: Number(state.circleRadius) };
  }
  return {
    type: "regular_polygon",
    sides: Number(state.polygonSides),
    side: Number(state.polygonSide),
  };
}
function buildObjective(state: FormState): ObjectiveDoc {
  if (state.objectiveKind === "maximize_count") {
    return { type: "maximize_count", scale: Number(state.objectiveScale) };
  }
  if (state.objectiveKind === "minimize_container") {
    // The container is the engine's measurement, not a field of the problem: the
    // document says which container to measure and nothing else.
    return { type: "minimize_container", count: Number(state.objectiveCount) };
  }
  // The covering the product builds: the copies are unit-sized and the target is
  // measured inside their union, so the document states the count and which target.
  if (state.objectiveKind === "maximize_covered_size") {
    return {
      type: "maximize_covered_size",
      count: Number(state.objectiveCount),
      target: state.objectiveTarget,
    };
  }
  // A total-perimeter problem fixes the common scale at 1 in the engine and lets
  // every copy carry its own size, so the document states the count and nothing
  // about a scale.
  if (state.objectiveKind === "maximize_total_perimeter") {
    return { type: "maximize_total_perimeter", count: Number(state.objectiveCount) };
  }
  return { type: "maximize_scale", count: Number(state.objectiveCount) };
}
function buildRotation(state: FormState): RotationDoc {
  // A fixed policy keeps the engine's own default angle; the other modes read
  // what the user typed, and an empty list is the engine's error to report.
  const angles =
    state.rotationMode === "discrete"
      ? state.angles
          .split(",")
          .map((part) => Number(part.trim()))
          .filter((angle) => Number.isFinite(angle))
      : [0];
  return { type: "rotation_policy", mode: state.rotationMode, angles };
}
/** A sentence for the description, written from the fields as they are typed. */
function describeProblem(state: FormState, shape: ShapeDoc): string {
  const arena =
    state.arenaKind === "keep"
      ? "the arena it came with"
      : state.arenaKind === "disk"
      ? `a disc of radius ${state.arenaRadius}`
      : state.arenaKind === "regular_ngon"
        ? `a regular polygon of ${state.arenaSides} sides and circumradius ${state.arenaCircumradius}`
        : `a ${state.arenaWidth} x ${state.arenaHeight} rectangle`;
  // The sentence follows the document the form hands over, so a family that
  // picks the discs is described as one.
  const shapeText =
    shape.type === "circle"
      ? `discs of radius ${state.circleRadius}`
      : `regular polygons of ${state.polygonSides} sides and side ${state.polygonSide}`;
  const objective =
    state.objectiveKind === "maximize_scale"
      ? `maximising the common scale of ${state.objectiveCount} shapes`
      : state.objectiveKind === "maximize_count"
        ? `maximising the number of shapes at common scale ${state.objectiveScale}`
        : state.objectiveKind === "maximize_covered_size"
            ? `maximising the largest ${state.objectiveTarget} inside the union of ${state.objectiveCount} unit copies`
          : state.objectiveKind === "maximize_total_perimeter"
            ? `maximising the total perimeter of ${state.objectiveCount} freely sized shapes`
            : `minimising the square containing ${state.objectiveCount} of them`;
  const rotation =
    state.rotationMode === "fixed"
      ? "rotation fixed"
      : state.rotationMode === "discrete"
        ? `rotation restricted to ${state.angles} degrees`
        : "free rotation";
  if (
    state.objectiveKind === "minimize_container" ||
    state.objectiveKind === "maximize_covered_size"
  ) {
    // The document carries no arena here, so the sentence must not name one.
    return `${shapeText}, placed freely, ${objective}, ${rotation}.`;
  }
  return `${shapeText} in ${arena}, ${objective}, ${rotation}.`;
}
function buildProblem(state: FormState, family: ShapeFamilyDoc | null): ProblemDoc {
  const seed = state.seed.trim();
  const shape = buildShape(state, family);
  const objective = buildObjective(state);
  const problem: ProblemDoc = {
    problem_id: state.problemId.trim(),
    name: state.name.trim(),
    description: describeProblem(state, shape),
    seed: seed === "" ? null : Number(seed),
    shape,
    objective,
    rotation: buildRotation(state),
    constraints: [],
    metadata: {},
  };
  // An objective that measures its own region must not be handed an arena: the
  // engine refuses the pair, and it is right to — the region is what it computes.
  if (objective.type !== "minimize_container" && objective.type !== "maximize_covered_size") {
    problem.arena =
      state.arenaKind === "keep"
        ? { name: state.arenaLoaded?.name ?? "arena", shape: buildArena(state) }
        : { name: state.arenaKind, shape: buildArena(state) };
  }
  return problem;
}
export function ProblemEditor({
  open,
  current,
  shapes,
  coverTargets,
  onClose,
  onApply,
}: ProblemEditorProps) {
  // Returning null when closed unmounts the form below, so reopening always
  // rebuilds the fields from the problem currently in hand.
  if (!open) {
    return null;
  }
  return (
    <ProblemForm
      current={current}
      shapes={shapes}
      coverTargets={coverTargets}
      onClose={onClose}
      onApply={onApply}
    />
  );
}
function ProblemForm({
  current,
  shapes,
  coverTargets,
  onClose,
  onApply,
}: {
  current: ProblemDoc | null;
  shapes: ShapeFamilyDoc[];
  coverTargets: readonly CoverTarget[];
  onClose: () => void;
  onApply: (problem: ProblemDoc) => void;
}) {
  const { t } = useI18n();
  const [state, setState] = useState<FormState>(() =>
    current !== null ? stateFrom(current, shapes) : { ...DEFAULT_STATE, name: t("New problem") },
  );
  /**
   * The family the form is on.
   *
   * The identifier the user chose answers first; before any choice, the shape
   * the form holds does — which is also what settles the question when a palette
   * arrives after the form was opened. An empty palette leaves the form with no
   * family at all, and it then says so.
   */
  const family =
    shapes.find((entry) => entry.id === state.shapeFamily) ??
    familyForShape(
      shapes,
      state.shapeLoaded ?? { type: "circle", radius: Number(state.circleRadius) },
    ) ??
    shapes[0] ??
    null;
  const update = (patch: Partial<FormState>) => setState((fields) => ({ ...fields, ...patch }));
  // Only the targets the engine measures are offered: the editor never builds a
  // document whose target the engine has said it cannot read. A target already in
  // the loaded document is kept visible even then, so the field never shows blank.
  const targetValues: readonly CoverTarget[] = coverTargets.includes(state.objectiveTarget)
    ? coverTargets
    : [...coverTargets, state.objectiveTarget];
  const targetOptions: readonly { value: CoverTarget; label: string }[] =
    targetValues.map((value) => ({ value, label: value }));
  return (
    <div className="modal">
      <form
        className="modal__panel modal__panel--problem"
        onSubmit={(event) => {
          event.preventDefault();
          onApply(buildProblem(state, family));
        }}
      >
        <section className="panel__section">
          <h2 className="panel__title">{t("Edit problem")}</h2>
          {current !== null &&
            current.arena !== undefined &&
            !isEditableArena(current.arena.shape.type) && (
              <p className="muted">
                {t("This composite arena is kept while you edit the other fields.")}
              </p>
            )}
        </section>
        <Section
          title="Identity"
          note="A name to recognise the problem by, and the identifier the engine files it under — derived from the name until you type one yourself."
        >
          <TextField
            label="name"
            value={state.name}
            onChange={(name) => {
              // The identifier follows the name until it has been typed by hand,
              // and a name that yields nothing — empty, or only punctuation —
              // leaves the identifier as it was rather than blanking it.
              const derived = identifierFrom(name);
              update(
                state.problemIdTouched || derived === ""
                  ? { name }
                  : { name, problemId: derived },
              );
            }}
          />
          <TextField
            label="identifier"
            value={state.problemId}
            onChange={(problemId) => update({ problemId, problemIdTouched: true })}
          />
        </Section>
        <Section
          title="Objective"
          note={
            state.objectiveKind === "maximize_covered_size"
              ? "The copies stay at scale 1 and the engine measures the largest target contained in their union. No arena is declared."
              : state.objectiveKind === "minimize_container"
                ? "What the search should make as small as possible."
                : "What the search should maximise."
          }
        >
          <SelectField
            label="type"
            value={state.objectiveKind}
            options={OBJECTIVE_OPTIONS}
            onChange={(objectiveKind) => update({ objectiveKind })}
          />
          {state.objectiveKind === "maximize_count" ? (
            <NumberField
              label="common scale"
              value={state.objectiveScale}
              onChange={(objectiveScale) => update({ objectiveScale })}
            />
          ) : (
            <NumberField
              label="number of shapes"
              value={state.objectiveCount}
              onChange={(objectiveCount) => update({ objectiveCount })}
            />
          )}
          {state.objectiveKind === "maximize_covered_size" && (
            <SelectField
              label="target"
              value={state.objectiveTarget}
              options={targetOptions}
              onChange={(objectiveTarget) => update({ objectiveTarget })}
            />
          )}
        </Section>
        {state.objectiveKind !== "minimize_container" &&
          state.objectiveKind !== "maximize_covered_size" && (
          // `buildProblem` hands the document no arena at all when the objective
          // measures its own region, so the section is gone rather than showing
          // fields that would be discarded.
          <Section title="Arena" note="The region the shapes have to fit inside.">
            <SelectField
              label="type"
              value={state.arenaKind}
              options={ARENA_OPTIONS}
              onChange={(arenaKind) => update({ arenaKind })}
            />
            {state.arenaKind === "keep" && (
              <p className="muted">
                {t("The loaded arena is preserved. Edit its parts in the Arena workspace.")}
              </p>
            )}
            {state.arenaKind === "rect" && (
              <>
                <NumberField
                  label="width"
                  value={state.arenaWidth}
                  onChange={(arenaWidth) => update({ arenaWidth })}
                />
                <NumberField
                  label="height"
                  value={state.arenaHeight}
                  onChange={(arenaHeight) => update({ arenaHeight })}
                />
              </>
            )}
            {state.arenaKind === "disk" && (
              <NumberField
                label="radius"
                value={state.arenaRadius}
                onChange={(arenaRadius) => update({ arenaRadius })}
              />
            )}
            {state.arenaKind === "regular_ngon" && (
              <>
                <NumberField
                  label="sides"
                  value={state.arenaSides}
                  onChange={(arenaSides) => update({ arenaSides })}
                />
                <NumberField
                  label="circumradius"
                  value={state.arenaCircumradius}
                  onChange={(arenaCircumradius) => update({ arenaCircumradius })}
                />
              </>
            )}
          </Section>
        )}
        <Section
          title="Shape family"
          note="What is packed: every shape of a problem comes from one family."
        >
          {family === null ? (
            <p className="muted">
              {t("The shape palette is unavailable; the loaded shape is preserved.")}
            </p>
          ) : (
            <>
              <SelectField
                label="family"
                value={family.id}
                options={shapes.map((entry) => ({ value: entry.id, label: entry.label }))}
                onChange={(id) => {
                  const chosen = shapes.find((entry) => entry.id === id);
                  if (chosen !== undefined) {
                    update(withFamily(state, chosen));
                  }
                }}
              />
              {family.shape.type === "circle" ? (
                <NumberField
                  label="radius"
                  value={state.circleRadius}
                  onChange={(circleRadius) => update({ circleRadius })}
                />
              ) : (
                <>
                  {family.sides !== undefined && (
                    <NumberField
                      label="sides"
                      narrow
                      min={3}
                      step={1}
                      value={state.polygonSides}
                      onChange={(polygonSides) => update({ polygonSides })}
                    />
                  )}
                  <NumberField
                    label="side"
                    value={state.polygonSide}
                    onChange={(polygonSide) => update({ polygonSide })}
                  />
                </>
              )}
            </>
          )}
        </Section>
        <Section title="Rotation" note="Which orientations a shape may be given.">
          <SelectField
            label="mode"
            value={state.rotationMode}
            options={ROTATION_OPTIONS}
            onChange={(rotationMode) => update({ rotationMode })}
          />
          {state.rotationMode === "discrete" && (
            <TextField
              label="angles (degrees, comma separated)"
              value={state.angles}
              onChange={(angles) => update({ angles })}
            />
          )}
        </Section>
        <Section title="Seed" note="The seed the problem carries; leave it blank to carry none.">
          <NumberField label="value" value={state.seed} onChange={(seed) => update({ seed })} />
        </Section>
        <div className="modal__actions">
          <button type="button" className="button button--ghost" onClick={onClose}>
            {t("Cancel")}
          </button>
          <button type="submit" className="button button--primary">
            {t("Apply")}
          </button>
        </div>
      </form>
    </div>
  );
}
