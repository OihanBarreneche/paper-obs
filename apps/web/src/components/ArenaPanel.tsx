/**
 * The arena editor's stack of parts and the controls that edit them.
 *
 * Parts are not created here: the canvas's right-click menu adds one, with the
 * operation the host hands it, and this panel is where an existing part is edited.
 * The one creation gesture that stays is the drawing of a polygon, whose finish and
 * cancel buttons are drawn under the list while it is being drawn.
 *
 * Nothing here decides geometry either. A field reports the number it was typed,
 * an operation is one the domain defines, and every edit hands the whole list
 * back through `onChange` — which is where the application compiles it, once, and
 * judges the result.
 *
 * Which part is selected belongs to the application as well: a card reports the
 * click that lands on it, and marks itself when the selection it is given names
 * it — the same part the canvas marks and the application's `Delete` acts on.
 *
 * An edit is reported as soon as it is read, not when the control is let go: a
 * slider says what it passes through and a field says what it holds, so the picture
 * follows the hand — and what a control shows while the hand is on it is the number
 * under the hand, since the answer for it is still on its way.
 *
 * The list is the only thing this section knows: a part is described by what the
 * engine answered for it, and the index a card shows is the position the engine
 * numbers it at.
 *
 * The rows are drawn newest first, so a part just added is at the top where the eye
 * already is. Only the drawing order is reversed: `part.index` and the operation
 * select keep addressing the engine's own stack positions, which is the frame
 * `base` and the fold order are defined in, and Up/Down are mapped to the row the
 * user sees — Up moves a card towards the newest part, Down towards the base — while
 * the index handed to the stack underneath is still the true one. A card's head is a
 * band carrying its number and its name, so two instances are told apart before any
 * field is read.
 */

import { useEffect, useRef, useState } from "react";

import { useI18n } from "../i18n";
import type {
  ArenaPartDoc,
  ArenaPartOp,
  ArenaPartParams,
  Point,
} from "../types";

import { MIN_SIZE } from "./ArenaCanvas";
import "./ArenaPanel.css";

export type ArenaPanelProps = {
  parts: ArenaPartDoc[];
  editable: boolean;
  /**
   * True when the objective owns the arena, so it is fixed for a reason of meaning
   * rather than because it is not a stack of parts. The panel then says which.
   */
  fixedByObjective?: boolean;
  /** The part the application has selected, or null; index into `parts`. */
  selectedPart: number | null;
  /** Report the selected part: the index of a chosen one, or null for none. */
  onSelectPart: (index: number | null) => void;
  /** The part being drawn, or null: shows the "drawing" row with its two buttons. */
  drawing: { points: Point[] } | null;
  /** Report the vertices drawn so far as a finished part. */
  onFinishDrawing: () => void;
  /** Throw the drawing away. */
  onCancelDrawing: () => void;
  /** Replace the whole stack. */
  onChange: (parts: ArenaPartDoc[]) => void;
  /** The section's heading, for a panel editing something else than an arena. */
  title?: string;
  /** The note under the base card, which names what is being built. */
  baseNote?: string;
  /**
   * Called as a run of changes to the stack opens, and `onEditEnd` as it closes.
   * The composer pairs them into one undo step per gesture; an arena leaves both
   * out, so they are no-ops there.
   */
  onEditStart?: () => void;
  onEditEnd?: () => void;
};

/** The operations the domain defines, in the order a stack reads them. */
const OPERATIONS: ArenaPartOp[] = ["base", "union", "difference", "intersection"];

export function ArenaPanel({
  parts,
  editable,
  selectedPart,
  onSelectPart,
  drawing,
  onFinishDrawing,
  onCancelDrawing,
  onChange,
  title,
  baseNote,
  fixedByObjective = false,
  onEditStart,
  onEditEnd,
}: ArenaPanelProps) {
  const { t } = useI18n();
  /**
   * The list this panel edits, always the newest render's.
   *
   * A card's controls report the whole stack, and the callback that reports it is the
   * one that was created when the card was drawn. The control of a part that is being
   * taken away still runs one — an unmounting field commits its draft, and the blur a
   * removed field gets commits it too — and read from the render it was created in,
   * that report would rebuild the stack *with* that part: the engine compiles it back,
   * the part returns, and a Delete that did happen looks like it needs a second press.
   * Read at the moment it reports, the list is the application's own, and the number
   * of a part that is no longer in it has nothing left to change.
   */
  const liveParts = useRef(parts);
  liveParts.current = parts;

  /** Report a whole list, numbered the way the engine numbers parts. */
  const send = (next: ArenaPartDoc[]) => {
    onChange(next.map((part, index) => (part.index === index ? part : { ...part, index })));
  };

  /**
   * The two ends of one undoable run of changes.
   *
   * A run is what a person thinks of as one edit: one press on Add, or a drag
   * through many values of a slider. The panel reports the first change inside it
   * and the last when the hand lets go — a field's blur, or a pointer lifted
   * anywhere in the list — and a host that records history turns the pair into a
   * single step. An arena passes neither callback, so this costs nothing there.
   */
  const beginEdit = () => onEditStart?.();
  const endEdit = () => onEditEnd?.();

  /**
   * Report a list with one part changed, the others left exactly as they are.
   *
   * A part the application no longer holds is not reported at all: the control that
   * asked for it was built on a stack the gesture has since replaced.
   */
  const replace = (index: number, patch: (part: ArenaPartDoc) => ArenaPartDoc) => {
    const live = liveParts.current;
    if (live[index] === undefined) {
      return;
    }
    beginEdit();
    send(live.map((part, at) => (at === index ? patch(part) : part)));
  };

  const duplicatePart = (index: number) => {
    const part = parts[index];
    if (part === undefined) {
      return;
    }
    const next = [...parts];
    next.splice(index + 1, 0, {
      ...part,
      index: index + 1,
      // Only the first part is the base. A copy of it therefore joins the stack
      // with `union`, which leaves the arena exactly as it was.
      op: index === 0 ? "union" : part.op,
      offset: [part.offset[0], part.offset[1]],
      // A polygon's points are copied rather than shared, so editing the copy can
      // never show in the part it came from.
      params:
        part.params.kind === "polygon"
          ? { kind: "polygon", points: part.params.points.map((point): Point => [point[0], point[1]]) }
          : { ...part.params },
    });
    // The part above the selected one is now one further up, so the selection
    // moves with it and keeps naming the part it was put on.
    if (selectedPart !== null && selectedPart > index) {
      onSelectPart(selectedPart + 1);
    }
    // A copy placed at a point is a whole edit, not a run to be merged with the
    // next one.
    endEdit();
    beginEdit();
    send(next);
    endEdit();
  };

  const deletePart = (index: number) => {
    // The stack is read from the base: an arena is a region, so it never loses
    // the part that starts it. The rest goes one at a time.
    if (index === 0) {
      return;
    }
    // The selection names a part, and the list is one shorter: what is gone is
    // nobody, and what stood above it closed the gap.
    if (selectedPart === index) {
      onSelectPart(null);
    } else if (selectedPart !== null && selectedPart > index) {
      onSelectPart(selectedPart - 1);
    }
    // Removing a card is one gesture, whatever control asked for it.
    endEdit();
    beginEdit();
    send(parts.filter((_, at) => at !== index));
    endEdit();
  };

  const movePart = (index: number, step: number) => {
    const target = index + step;
    // The base stays where it is: it is what every other part is combined with.
    if (index === 0 || target === 0 || target < 0 || target >= parts.length) {
      return;
    }
    const part = parts[index];
    if (part === undefined) {
      return;
    }
    const next = [...parts];
    next.splice(index, 1);
    next.splice(target, 0, part);
    // Two parts swap places at most, so the selection follows whichever of the
    // two it named.
    if (selectedPart === index) {
      onSelectPart(target);
    } else if (selectedPart === target) {
      onSelectPart(index);
    }
    // Moving a part in the stack is one gesture.
    endEdit();
    beginEdit();
    send(next);
    endEdit();
  };

  return (
    <>
      <div className="panel__section">
        <h3 className="panel__title">{t(title ?? "Arena parts")}</h3>
        {!editable ? (
          <p className="muted">
            {t(
              fixedByObjective
                ? "This arena is the problem's own target or container: it is fixed, and editing it would change the question."
                : "This arena is fixed and cannot be edited as separate parts.",
            )}
          </p>
        ) : (
          <>
            {/* A blur, or a pointer lifted anywhere in the list, closes the run a
                field opened: the history a host keeps then sees one edit per hand
                gesture rather than one per keystroke. Both are bubbling handlers,
                so a control's own commit runs first and the run closes after it. */}
            <div className="parts" onBlur={endEdit} onPointerUp={endEdit}>
              {/* Newest first: the list reads top-down, but the index each card
                  acts on is the position in the engine's stack — captured by
                  `map` before the view is reversed — so `part.index`, Up/Down,
                  Delete and the operation select keep addressing the same part.
                  Nothing is renumbered: only the order of the rows changes. */}
              {parts.map((part, index) => ({ part, index })).reverse().map(({ part, index }) => {
                const isBase = index === 0;
                // A local binding: the union narrows here, and stays narrowed inside the callbacks below.
                const params = part.params;
                // Clicking anywhere on a card chooses it: it is the part the
                // application's `Delete` and its own buttons act on, and the
                // canvas marks the same one. A button on the card edits the list
                // and reports where the selection lands afterwards, so it does
                // not choose the part that happens to follow it.
                return (
                  <div
                    key={`card-${index}`}
                    className={index === selectedPart ? "part part--selected" : "part"}
                    onClick={(event) => {
                      // The card deliberately does not blur what it clicked: a click on a
                      // size field has to leave that field typable, and dropping the focus
                      // here also takes the arrow keys away from a slider. `Delete` acts on
                      // the selected part whatever holds the focus — the keyboard guard in
                      // `App` lets it through unless the field is one that keeps it — so
                      // the shortcut the card documents does not depend on this handler.
                      if ((event.target as HTMLElement).closest("button") === null) {
                        onSelectPart(index);
                      }
                    }}
                  >
                    <div className="part__head">
                      <span className="part__index">{part.index}</span>
                      <span className="part__label">{t(part.label)}</span>
                    </div>
                    <label className="field">
                      <span className="field__label">{t("operation")}</span>
                      {/* The domain's four operations read here, but only the ones
                          this part of the stack can mean are choosable: a stack
                          starts at its base, and a base is only ever its first
                          part. So the first card chooses `base`, and every card
                          above it chooses one of the three folds. */}
                      <select
                        className="select"
                        value={part.op}
                        onChange={(event) => {
                          replace(index, (item) => ({
                            ...item,
                            op: event.target.value as ArenaPartOp,
                          }));
                          // Choosing an operation is a whole edit, not the start
                          // of a run: the select keeps the focus, and the next
                          // choice must be its own undo step.
                          endEdit();
                        }}
                      >
                        {OPERATIONS.map((op) => (
                          <option
                            key={op}
                            value={op}
                            disabled={isBase ? op !== "base" : op === "base"}
                          >
                            {t(op)}
                          </option>
                        ))}
                      </select>
                    </label>
                    {params.kind === "rect" && (
                      <RectSize
                        id={`part-${index}`}
                        width={params.width}
                        height={params.height}
                        onChange={(next) => replace(index, (item) => ({ ...item, params: next }))}
                      />
                    )}
                    {params.kind === "disk" && (
                      <NumberField
                        label="radius"
                        value={params.radius}
                        onCommit={(radius) =>
                          replace(index, (item) => ({
                            ...item,
                            params: { kind: "disk", radius },
                          }))
                        }
                      />
                    )}
                    {params.kind === "ellipse" && (
                      <>
                        <NumberField
                          label="semi-axis a"
                          value={params.a}
                          onCommit={(a) =>
                            replace(index, (item) => ({
                              ...item,
                              params: { kind: "ellipse", a, b: params.b },
                            }))
                          }
                        />
                        <NumberField
                          label="semi-axis b"
                          value={params.b}
                          onCommit={(b) =>
                            replace(index, (item) => ({
                              ...item,
                              params: { kind: "ellipse", a: params.a, b },
                            }))
                          }
                        />
                      </>
                    )}
                    {params.kind === "regular_ngon" && (
                      <>
                        <NumberField
                          label="sides"
                          value={params.sides}
                          integer
                          onCommit={(sides) =>
                            replace(index, (item) => ({
                              ...item,
                              params: {
                                kind: "regular_ngon",
                                sides,
                                circumradius: params.circumradius,
                              },
                            }))
                          }
                        />
                        <NumberField
                          label="circumradius"
                          value={params.circumradius}
                          onCommit={(circumradius) =>
                            replace(index, (item) => ({
                              ...item,
                              params: {
                                kind: "regular_ngon",
                                sides: params.sides,
                                circumradius,
                              },
                            }))
                          }
                        />
                      </>
                    )}
                    {params.kind === "polygon" && (
                      <p className="muted">{params.points.length} {t("vertices")}</p>
                    )}
                    <NumberField
                      label="offset x"
                      value={part.offset[0]}
                      onCommit={(x) =>
                        replace(index, (item) => ({ ...item, offset: [x, item.offset[1]] }))
                      }
                    />
                    <NumberField
                      label="offset y"
                      value={part.offset[1]}
                      onCommit={(y) =>
                        replace(index, (item) => ({ ...item, offset: [item.offset[0], y] }))
                      }
                    />
                    {/* The turn, in degrees about the origin of the part's own frame —
                        the point the part's offset displaces, which is where the
                        engine turns it and where the canvas' turn grip is anchored.
                        It is reported the way every other field here is, and the
                        number the engine answers with is what both controls show.
                        An engine older than the turn simply does not send the
                        number, and a part that carries none is read as one that is
                        not turned: a formatter given `undefined` throws during
                        render, which takes the whole application down rather than
                        the one field. */}
                    <NumberField
                      label="rotation (deg)"
                      value={part.angle ?? 0}
                      onCommit={(angle) => replace(index, (item) => ({ ...item, angle }))}
                    />
                    <div className="builder-actions">
                      {/* The list reads newest-first, so the two buttons move the card
                          the way the eye does: Up is one row towards the newest part
                          (a higher stack index) and Down one row towards the base.
                          The stack contract is unchanged — the index handed to
                          `movePart` is still the card's true position — and the ends
                          are disabled where the base or the top blocks the move. */}
                      <button
                        className="button button--ghost"
                        disabled={index === 0 || index === parts.length - 1}
                        onClick={() => movePart(index, 1)}
                      >
                        {t("Up")}
                      </button>
                      <button
                        className="button button--ghost"
                        disabled={index <= 1}
                        onClick={() => movePart(index, -1)}
                      >
                        {t("Down")}
                      </button>
                      <button
                        className="button button--ghost"
                        onClick={() => duplicatePart(index)}
                      >
                        {t("Duplicate")}
                      </button>
                      <button
                        className="button button--danger"
                        disabled={isBase}
                        onClick={() => deletePart(index)}
                      >
                        {t("Delete")}
                      </button>
                    </div>
                    {isBase && (
                      <p className="muted">
                        {t(baseNote ?? "The base cannot be deleted; every arena starts with one.")}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
            {/* A polygon is the one primitive that is drawn rather than added, so
                while one is being drawn its own two controls stand under the list.
                There is no add row: a part is created by the canvas's right-click
                menu, and this panel only edits the parts that already exist. */}
            {drawing !== null && (
              <div className="builder-draw">
                <span className="muted">{drawing.points.length} {t("vertices drawn so far")}</span>
                <button
                  className="button button--primary"
                  disabled={drawing.points.length < 3}
                  onClick={onFinishDrawing}
                >
                  {t("Done")}
                </button>
                <button className="button button--ghost" onClick={onCancelDrawing}>
                  {t("Cancel")}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}

type NumberInputProps = {
  /** What the control is called, for a reader that has no label to follow. */
  label: string;
  value: number;
  /** Called with every number the field reads, as soon as it reads one. */
  onCommit: (value: number) => void;
  /** Whole numbers only, for a field the domain reads as a count. */
  integer?: boolean;
  /** Refuse anything below the floor a size control enforces, in world units. */
  positive?: boolean;
};

/**
 * One editable number: a draft while it is typed, and a report for every value it
 * reads — not one report when the typing is over.
 *
 * The picture is compiled from what is reported, so reporting as the text arrives
 * is what lets the outline follow the field. Text that reads as no number yet ("-",
 * or "2." on its way to "2.5") is kept exactly as it is and reports nothing: a
 * half-typed number is not a size anyone asked for.
 */
function NumberInput({
  label,
  value,
  onCommit,
  integer = false,
  positive = false,
}: NumberInputProps) {
  const { t } = useI18n();
  const [draft, setDraft] = useState(formatNumber(value));
  const [typing, setTyping] = useState(false);

  // A drag on the canvas, or the slider beside this field, moves the same number:
  // the field follows it, as long as nobody is typing in it.
  useEffect(() => {
    if (!typing) {
      setDraft(formatNumber(value));
    }
  }, [value, typing]);

  /** What a text reads as, or null while it reads as nothing this field reports. */
  const read = (text: string): number | null => {
    const trimmed = text.trim();
    if (trimmed === "") {
      return null;
    }
    const parsed = Number(trimmed);
    if (!Number.isFinite(parsed)) {
      return null;
    }
    const next = integer ? Math.round(parsed) : parsed;
    // A dimension below the floor a control may leave a primitive with is not a
    // number to report: the text stays in the field until it reads a size.
    return positive && next < MIN_SIZE ? null : next;
  };

  const commit = () => {
    const next = read(draft);
    if (next === null || next === value) {
      setDraft(formatNumber(value));
      return;
    }
    onCommit(next);
  };

  // Leaving a field commits it; unmounting one takes the element away before the
  // browser blurs it, so the last draft is reported from here as well.
  const lastCommit = useRef(commit);
  useEffect(() => {
    lastCommit.current = commit;
  });
  useEffect(() => () => lastCommit.current(), []);

  return (
    <input
      className="input input--narrow"
      type="text"
      inputMode="decimal"
      aria-label={t(label)}
      value={draft}
      onChange={(event) => {
        const text = event.target.value;
        setDraft(text);
        const next = read(text);
        if (next !== null && next !== value) {
          onCommit(next);
        }
      }}
      onFocus={() => setTyping(true)}
      onBlur={() => {
        setTyping(false);
        commit();
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.currentTarget.blur();
        }
      }}
    />
  );
}

/** One number on the line its own label opens, for everything but a size. */
function NumberField(props: NumberInputProps) {
  const { t } = useI18n();
  return (
    <label className="field">
      <span className="field__label">{t(props.label)}</span>
      <NumberInput {...props} />
    </label>
  );
}

type SizeFieldProps = {
  /** What the dimension is called: the label of the row, and the slider's own name. */
  label: string;
  /** Ties the label to the slider, so pressing the label puts the hand on the bar. */
  id: string;
  value: number;
  /** How far the slider reaches, unless the number itself reaches further. */
  reach: number;
  onCommit: (value: number) => void;
};

/**
 * One dimension of a rectangle: the bar that drags it and the number that pins it
 * down, on one line.
 *
 * Both report every value they are given, while they are being used, which is what
 * makes the outline follow the hand. What they show meanwhile is the number the
 * hand asked for: the engine's answer for it may still be on its way, and a control
 * that jumps back under the finger cannot be aimed.
 *
 * The track covers the size the card was opened at, four times over, and follows a
 * number that outgrows that: a size typed larger than the card's own reach stays
 * where it is, with the thumb at the end, instead of being pulled back to a value
 * the track happens to hold.
 */
function SizeField({ label, id, value, reach, onCommit }: SizeFieldProps) {
  const { t } = useI18n();
  const [held, setHeld] = useState<number | null>(null);
  const shown = held ?? value;
  const far = Math.max(reach, shown);

  // The engine's own number takes over again as soon as it agrees with the hand's,
  // and until then the hand's is what stands: a refusal shows itself in the words
  // the engine answers with, not by pulling this control out of the hand.
  useEffect(() => {
    if (held !== null && held === value) {
      setHeld(null);
    }
  }, [held, value]);

  const report = (next: number) => {
    setHeld(next);
    onCommit(next);
  };

  return (
    <div className="size">
      <label className="size__label" htmlFor={id}>
        {t(label)}
      </label>
      <input
        id={id}
        className="input"
        type="range"
        min={MIN_SIZE}
        max={far}
        step="any"
        value={shown}
        onChange={(event) => report(Number(event.target.value))}
      />
      <NumberInput label={`${label} value`} value={shown} positive onCommit={report} />
    </div>
  );
}

type RectSizeProps = {
  /** The prefix the two rows' ids carry, so no two controls share one. */
  id: string;
  width: number;
  height: number;
  onChange: (params: ArenaPartParams) => void;
};

/**
 * The two dimensions of a rectangle, one row each.
 *
 * Each axis has its own controls, which is what makes a pull along one of them a
 * change of that one alone. "Keep the ratio" ties them together, and then the other
 * dimension follows the same factor — the way a rectangle is enlarged without
 * becoming another shape. It is off by default: the arena is a size someone chose,
 * and it is edited one side at a time.
 */
function RectSize({ id, width, height, onChange }: RectSizeProps) {
  const { t } = useI18n();
  const [keepRatio, setKeepRatio] = useState(false);
  // The tracks reach four times the size the card was opened at, and follow a size
  // that outgrows them. A size beyond the reach is still typed into the field beside
  // the bar.
  const [reachWidth] = useState(() => Math.max(4 * width, 4 * MIN_SIZE));
  const [reachHeight] = useState(() => Math.max(4 * height, 4 * MIN_SIZE));

  return (
    <>
      <SizeField
        id={`${id}-width`}
        label="width"
        value={width}
        reach={reachWidth}
        onCommit={(next) =>
          onChange({
            kind: "rect",
            width: next,
            height: keepRatio ? (height * next) / width : height,
          })
        }
      />
      <SizeField
        id={`${id}-height`}
        label="height"
        value={height}
        reach={reachHeight}
        onCommit={(next) =>
          onChange({
            kind: "rect",
            width: keepRatio ? (width * next) / height : width,
            height: next,
          })
        }
      />
      <label
        className="checkbox"
        title={t("change one dimension, and the other follows the same factor")}
      >
        <input
          type="checkbox"
          checked={keepRatio}
          onChange={(event) => setKeepRatio(event.target.checked)}
        />
        {t("keep the ratio")}
      </label>
    </>
  );
}

/** A number as a field shows it: six significant digits, which is what the panel reads. */
function formatNumber(value: number): string {
  return String(Number(value.toPrecision(6)));
}
