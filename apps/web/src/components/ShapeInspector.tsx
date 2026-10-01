/**
 * The editor for the current selection: a numeric form when one shape is
 * selected, a summary and a bulk delete when several are — and nothing at all
 * when there is none. The panel exists for a selection, so with an empty canvas
 * it is not there: what a click, a drag, an arrow key or `Delete` does is visible
 * on the canvas itself, and a column of instructions for gestures nobody has
 * asked about yet is noise in front of the verdict.
 *
 * Dragging on the canvas is convenient and imprecise; this is where a position,
 * a rotation or a local scale is set exactly. Every change is reported upwards
 * as a patch on the placement, never written locally.
 *
 * A field keeps what is being typed and reports it once, on Enter or blur: a
 * half-typed coordinate is not a coordinate, and asking the engine to judge
 * every keystroke would fill the panel with verdicts nobody asked for.
 *
 * The rotation has two controls: the field, and a knob beside it. A drag on the
 * knob turns an arrow to follow the pointer and reports the angle it settled on
 * once, when the button comes back up — the field's own discipline, so that one
 * drag is one edit and one entry in the undo stack, however many pointer moves
 * it took.
 *
 * Several shapes are moved together on the canvas and with the arrow keys, but a
 * numeric form is a form for one shape: it follows the anchor — the shape
 * selected most recently — and says so, rather than pretending to edit the whole
 * selection.
 *
 * The rotation policy is shown, never enforced: the engine is the one that
 * judges a candidate, and it says what an edited angle costs. This panel only
 * saves the user a round trip by repeating the rule before the edit is sent.
 *
 * The colours live here rather than in the control strip because this panel only
 * exists with a selection: a swatch click always has at least one shape to paint,
 * where the same row in the top bar was a control that did nothing visible until
 * something happened to be selected.
 */

import { useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";

import type { CandidateDoc, PlacementDoc, ProblemDoc, RotationDoc, ScaleBoundsDoc } from "../types";
import { useI18n } from "../i18n";
import { snapAngle } from "../snap";
import "./ShapeInspector.css";

export type ShapeInspectorProps = {
  problem: ProblemDoc | null;
  candidate: CandidateDoc | null;
  /**
   * The engine's interval for one copy's local size. It bounds the resize gesture
   * for the one family whose copies carry independent sizes, and is null for every
   * other family, where the control is not offered at all.
   */
  scaleBounds?: ScaleBoundsDoc | null;
  /** Selected shape identifiers, in selection order. */
  selectedIds: string[];
  /** The colour the swatches hold in hand, marked on its own swatch; null is the theme. */
  ink: string | null;
  /** Paint the selection with one colour; null hands it back to the theme's fill. */
  onPaint: (color: string | null) => void;
  /** Paint every shape of the candidate with the colour in hand. */
  onPaintAll: () => void;
  /** Commit one field of one placement. */
  onChange: (shapeId: string, patch: Partial<PlacementDoc>) => void;
  /**
   * Report a local scale while the slider is being dragged.
   *
   * The canvas draws the engine's own answer, so a copy only grows while the
   * number is sent: the slider reports every move, and the application asks the
   * engine to judge the arrangement in flight. One gesture stays one undo step
   * because the report is paired with :attr:`onScaleCommit`.
   */
  onScalePreview: (shapeId: string, scale: number) => void;
  /** The local-scale gesture ended: one verdict and one entry in the undo stack. */
  onScaleCommit: () => void;
  onDuplicate: (shapeId: string) => void;
  /** Delete every given shape, in one action. */
  onDelete: (shapeIds: string[]) => void;
};

/**
 * The colours a shape can be painted with.
 *
 * Thirteen hues far enough apart to tell regions of an arrangement by eye, all bright
 * enough to read on the canvas's dark background and none of them the theme's own
 * blue or the red and green of the verdict, so a painted shape still says what the
 * engine decided about it. With the theme's entry they fill two rows of seven. They are lower-case `#rrggbb` because that is the only
 * colour form the engine keeps: anything else comes back as a refusal.
 *
 * Exported because the colour in hand is the application's — two controls read it —
 * and the first of these is what it starts as.
 */
export const PALETTE = [
  "#fbbf24", "#22d3ee", "#a78bfa", "#f472b6", "#a3e635", "#94a3b8", "#fb923c",
  "#e879f9", "#fef08a", "#d4a373", "#818cf8", "#fda4af", "#f1f5f9",
] as const;

/**
 * A swatch's classes.
 *
 * The geometry is the stylesheet's; the border alone says which colour is in hand,
 * so the mark cannot be mistaken for another hue. The theme entry is the one
 * swatch with no colour to show, and the stylesheet draws it struck through.
 */
function swatchClass(color: string | null, ink: string | null): string {
  const theme = color === null ? " paint__swatch--theme" : "";
  const current = color === ink ? " paint__swatch--current" : "";
  return `paint__swatch${theme}${current}`;
}

/** Rotation tolerance in degrees, the one the engine's `RotationPolicy` compares with. */
const ANGLE_TOLERANCE = 1e-6;

export function ShapeInspector({
  problem,
  candidate,
  scaleBounds = null,
  selectedIds,
  ink,
  onPaint,
  onPaintAll,
  onChange,
  onScalePreview,
  onScaleCommit,
  onDuplicate,
  onDelete,
}: ShapeInspectorProps) {
  const { t } = useI18n();
  // The panel is the editor of a selection, so it exists only when there is one:
  // empty, it was a column of instructions for gestures the canvas already shows —
  // and the verdict, the metrics and the run panel above and below it are what the
  // eye should find there instead.
  if (selectedIds.length === 0) {
    return null;
  }

  // The form edits one shape at a time. With several selected it follows the
  // anchor, which is the last one added to the selection: the shape the user
  // clicked or nudged most recently.
  const anchorId = selectedIds[selectedIds.length - 1] ?? null;
  const anchor =
    anchorId === null
      ? null
      : (candidate?.placements.find((item) => item.shape_id === anchorId) ?? null);

  if (anchor === null) {
    return (
      <section className="panel__section">
        <h2 className="panel__title">{t("Shape")}</h2>
        <p className="muted">{t("Not in the current candidate")}: {selectedIds.join(", ")}</p>
      </section>
    );
  }

  const many = selectedIds.length > 1;

  return (
    <section className="panel__section">
      <h2 className="panel__title">{t(many ? "Shapes" : "Shape")}</h2>
      {many ? (
        <>
          <p className="readout">
            <span className="muted">{t("selected")}</span>
            <span>{selectedIds.length}</span>
          </p>
          <p className="readout">
            <span className="muted">{t("shape_id")}</span>
            <span>{selectedIds.join(", ")}</span>
          </p>
          <button
            className="button button--danger"
            type="button"
            onClick={() => onDelete(selectedIds)}
          >
            {t("Delete all")} {selectedIds.length} {t("shapes")}
          </button>
          {/* A form is a form for one shape: the sentence says which one it edits,
              and says nothing else. */}
          <p className="muted">{t("Fields below edit")} {anchor.shape_id}</p>
        </>
      ) : (
        <p className="readout">
          <span className="muted">{t("shape_id")}</span>
          <span>{anchor.shape_id}</span>
        </p>
      )}

      {/* One form instance per shape: switching shapes must not carry a draft over. */}
      <PlacementFields
        key={anchor.shape_id}
        problem={problem}
        placement={anchor}
        scaleBounds={scaleBounds}
        onChange={onChange}
        onScalePreview={onScalePreview}
        onScaleCommit={onScaleCommit}
      />

      {/* The colour is a property of the placement, like `x` or `rotation`, so its row
          sits with the numbers and follows the panel's label/value shape. A swatch
          paints the whole selection — the shapes `Ctrl`-click already extends — with
          the colour it carries, and the panel exists only with a selection, so a click
          always has something to paint. */}
      <div className="field">
        <span className="field__label">{t("paint")}</span>
        <div className="paint" role="group" aria-label={t("paint the selection")}>
          {PALETTE.map((color) => (
            <button
              key={color}
              type="button"
              className={swatchClass(color, ink)}
              style={{ background: color }}
              aria-label={`${t("paint the selection")} ${color}`}
              onClick={() => onPaint(color)}
            />
          ))}
          <button
            type="button"
            className={swatchClass(null, ink)}
            aria-label={t("back to the theme's own fill")}
            onClick={() => onPaint(null)}
          />
        </div>
      </div>
      <button
        type="button"
        className="button paint__all"
        onClick={onPaintAll}
      >
        {t("paint every shape")}
      </button>

      {!many && (
        <div className="grid-2">
          <button className="button" type="button" onClick={() => onDuplicate(anchor.shape_id)}>
            {t("Duplicate")}
          </button>
          <button
            className="button button--danger"
            type="button"
            onClick={() => onDelete([anchor.shape_id])}
          >
            {t("Delete")}
          </button>
        </div>
      )}
    </section>
  );
}

type PlacementFieldsProps = {
  problem: ProblemDoc | null;
  placement: PlacementDoc;
  scaleBounds: ScaleBoundsDoc | null;
  onChange: (shapeId: string, patch: Partial<PlacementDoc>) => void;
  onScalePreview: (shapeId: string, scale: number) => void;
  onScaleCommit: () => void;
};

/** The numbers of one placement: where it is, how it is turned, how big it is. */
function PlacementFields({
  problem,
  placement,
  scaleBounds,
  onChange,
  onScalePreview,
  onScaleCommit,
}: PlacementFieldsProps) {
  const { t } = useI18n();
  const shapeId = placement.shape_id;
  // The engine omits a rotation left at zero and a scale left unset; the form shows
  // the defaults rather than an empty field.
  const rotation = placement.rotation ?? 0;
  const policy = problem === null ? null : problem.rotation;
  const forbidden = policy !== null && !angleAllowed(policy, rotation);
  // Only the total-perimeter family gives each copy its own size: the objective is
  // the API's own discriminator, so the field and the gesture exist exactly where
  // the engine reads a local scale, and nowhere else.
  const localScales = problem !== null && problem.objective.type === "maximize_total_perimeter";

  return (
    <>
      <div className="grid-2">
        <NumberField
          label="x"
          value={formatNumber(placement.x)}
          onCommit={(value) => onChange(shapeId, { x: value })}
        />
        <NumberField
          label="y"
          value={formatNumber(placement.y)}
          onCommit={(value) => onChange(shapeId, { y: value })}
        />
      </div>
      <RotationControl
        rotation={rotation}
        policy={policy}
        onCommit={(value) => onChange(shapeId, { rotation: value })}
      />
      {localScales && (
        <>
          <NumberField
            label="local scale"
            value={placement.scale === undefined ? "" : formatNumber(placement.scale)}
            placeholder="common"
            onCommit={(value) => onChange(shapeId, { scale: value })}
            onClear={() => onChange(shapeId, { scale: undefined })}
          />
          <SizeSlider
            value={placement.scale ?? 1}
            bounds={scaleBounds}
            onPreview={(value) => onScalePreview(shapeId, value)}
            onCommit={onScaleCommit}
          />
        </>
      )}
      {policy !== null && (
        <>
          {/* The engine's rule in one word each, beside the field it constrains; the
              refusal itself comes back from the engine and is shown as it came. */}
          <p className="muted">{t("policy")} {t(describePolicy(policy))}</p>
          {forbidden && (
            <div className="violation">
              <span className="violation__kind">{t("rotation")} {formatNumber(rotation)}°</span> {t("is outside the policy")}
            </div>
          )}
        </>
      )}
    </>
  );
}

type SizeSliderProps = {
  /** The copy's local size, as the engine reads it. */
  value: number;
  /** The engine's interval for that size, or null while no verdict has arrived. */
  bounds: ScaleBoundsDoc | null;
  /** Called with every size the slider reaches while it is dragged. */
  onPreview: (value: number) => void;
  /** Called when the gesture ends: one undo step and one final verdict. */
  onCommit: () => void;
};

/**
 * The copy's local size as a drag, beside the field that types it.
 *
 * The slider spans the interval the engine derived for one copy's size
 * (scale_bounds), so its ends are the engine's own reasoning rather than numbers
 * the panel invented. It reports every move while it is dragged, so the copy on
 * the canvas grows and shrinks under the hand instead of waiting for the release:
 * the canvas draws the engine's own geometry, so the engine is asked to judge the
 * arrangement in flight, coalesced by the application so a fast drag does not
 * spend one round trip per pixel. The pointer coming back up closes the gesture
 * once, which is what makes one drag one entry in the undo stack. A family that
 * fixes the size leaves no room to move, and no slider is offered.
 */
function SizeSlider({ value, bounds, onPreview, onCommit }: SizeSliderProps) {
  const { t } = useI18n();
  const [draft, setDraft] = useState<number | null>(null);
  const shown = draft ?? value;
  // Whether a move was reported since the press, so a click on the thumb with no
  // move costs neither a round trip nor an undo step.
  const moved = useRef(false);

  // Read through a ref so the unmount below sees the latest callbacks: a gesture
  // interrupted by the selection changing is closed from here, the move itself
  // having already been reported by `live`.
  const latest = useRef({ moved, onCommit });
  latest.current = { moved, onCommit };
  useEffect(
    () => () => {
      const state = latest.current;
      if (state.moved.current) {
        state.moved.current = false;
        state.onCommit();
      }
    },
    [],
  );

  const live = (next: number) => {
    moved.current = true;
    setDraft(next);
    onPreview(next);
  };

  const commit = () => {
    if (moved.current) {
      moved.current = false;
      onCommit();
    }
    setDraft(null);
  };

  const low = bounds?.low ?? null;
  const high = bounds?.high ?? null;
  if (low === null || high === null || !(high > low)) {
    return null;
  }
  return (
    <div className="field">
      <span className="field__label">{t("drag to resize")}</span>
      <input
        className="input"
        type="range"
        min={low}
        max={high}
        step="any"
        value={shown}
        aria-label={t("local scale")}
        onChange={(event) => live(Number(event.target.value))}
        onPointerUp={commit}
        onKeyUp={commit}
        onBlur={commit}
      />
      <span className="muted" style={{ fontFamily: "var(--mono)", minWidth: "3.5rem", textAlign: "right" }}>
        {formatNumber(shown)}
      </span>
    </div>
  );
}

type RotationControlProps = {
  /** The placement's rotation in degrees, as the engine reads it and the form shows it. */
  rotation: number;
  /** The policy in force; shown, never enforced. */
  policy: RotationDoc | null;
  /** Called with the angle the knob settled on, once per turn. */
  onCommit: (value: number) => void;
};

/** The dial's geometry, in the units of its own view box. */
const DIAL_HALF = 40;
const DIAL_RADIUS = 32;
/** One tick every thirty degrees, the zero one heavier. */
const DIAL_TICK_STEP = 30;

/**
 * The rotation, as the number a field holds and as a knob turned by hand.
 *
 * A turn follows the pointer's angle around the knob's centre — the interface's
 * own arithmetic, which knows nothing of the shape's geometry — and the degrees
 * beside the arrow say what that angle is. Nearby five-degree guides attract
 * the pointer, while `Shift` forces those steps; the field is left exact, because a typed
 * number is already the number its author meant.
 *
 * The knob keeps the field's commitment: the arrow and both numbers move on
 * every pointer move, but the placement is written once, when the button comes
 * back up, or when the shape goes away under a turn in flight — the field's own
 * habit of reporting its draft when it is unmounted rather than blurred. A knob
 * let go where it started writes nothing, as a field holding the digits it
 * already shows reports nothing.
 *
 * A press captures the pointer, so a turn that leaves the knob — and a full turn
 * leaves it on every pass — goes on arriving here. The policy is drawn, never
 * enforced: an angle it forbids turns the arrow red and is still written, because
 * the engine is the one that judges a candidate.
 */
function RotationControl({ rotation, policy, onCommit }: RotationControlProps) {
  const { t } = useI18n();
  // The turn in flight, if any: what the knob shows instead of the placement.
  const [turn, setTurn] = useState<Turn | null>(null);
  const angle = turn === null ? rotation : turn.angle;
  const forbidden = policy !== null && !angleAllowed(policy, angle);
  const ink = forbidden ? "var(--invalid)" : "var(--accent-strong)";

  // A turn cut short by the shape changing under it — another selected, the
  // selection cleared — is written from here, where the field writes its own
  // draft when it is unmounted rather than blurred.
  const end = useRef<() => void>(() => {});
  useEffect(() => {
    end.current = () => {
      if (turn !== null && turn.angle !== rotation) {
        onCommit(turn.angle);
      }
    };
  });
  useEffect(() => () => end.current(), []);

  const start = (event: ReactPointerEvent<SVGSVGElement>) => {
    // The primary button, and one turn at a time: a second pointer on the knob
    // would otherwise take the first one's capture.
    if (event.button !== 0 || turn !== null) {
      return;
    }
    // As on the canvas, stopping the default keeps the drag from selecting the
    // text it sweeps over.
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    setTurn({ pointerId: event.pointerId, angle: pointerAngle(event.currentTarget, event) });
  };

  const move = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (turn === null || event.pointerId !== turn.pointerId) {
      return;
    }
    setTurn({ pointerId: event.pointerId, angle: pointerAngle(event.currentTarget, event) });
  };

  const release = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (turn === null || event.pointerId !== turn.pointerId) {
      return;
    }
    const settled = turn.angle;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    setTurn(null);
    if (settled !== rotation) {
      onCommit(settled);
    }
  };

  return (
    <>
      <NumberField label="rotation (deg)" value={formatNumber(angle)} onCommit={onCommit} />
      <div className="field">
        <span className="field__label">{t("drag to turn")}</span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: "0.5rem" }}>
          <svg
            width={DIAL_HALF * 2}
            height={DIAL_HALF * 2}
            viewBox={`${-DIAL_HALF} ${-DIAL_HALF} ${DIAL_HALF * 2} ${DIAL_HALF * 2}`}
            // A knob is for a mouse; the field above it is the way to type the same
            // angle, and the one a screen reader reads.
            aria-hidden="true"
            style={{
              display: "block",
              flex: "none",
              touchAction: "none",
              cursor: turn === null ? "grab" : "grabbing",
            }}
            onPointerDown={start}
            onPointerMove={move}
            onPointerUp={release}
            onPointerCancel={release}
          >
            <circle
              r={DIAL_RADIUS}
              strokeWidth={1}
              style={{ fill: "var(--surface-2)", stroke: "var(--border)" }}
            />
            {Array.from({ length: 360 / DIAL_TICK_STEP }, (_, index) => index * DIAL_TICK_STEP).map(
              (degrees) => {
                // Zero is the `+x` axis and SVG's `y` grows downwards, so a tick for
                // an angle sits at (cos, -sin): the same convention as the arrow.
                const radians = (degrees * Math.PI) / 180;
                const cosine = Math.cos(radians);
                const sine = -Math.sin(radians);
                const outer = DIAL_RADIUS - 3;
                const inner = outer - 4;
                return (
                  <line
                    key={degrees}
                    x1={cosine * outer}
                    y1={sine * outer}
                    x2={cosine * inner}
                    y2={sine * inner}
                    strokeWidth={degrees === 0 ? 2 : 1}
                    style={{ stroke: degrees === 0 ? "var(--text-muted)" : "var(--border)" }}
                  />
                );
              },
            )}
            {/* The arrow is the angle: drawn along the zero axis, turned by the
                negative of it, since SVG rotates clockwise and the engine measures
                its rotations counter-clockwise. */}
            <g transform={`rotate(${-angle})`} style={{ fill: ink, stroke: ink }}>
              <line x1={0} y1={0} x2={17} y2={0} strokeWidth={3} strokeLinecap="round" />
              <polygon points="15,-4.5 24,0 15,4.5" strokeWidth={0} />
            </g>
            <circle r={2.5} style={{ fill: ink }} />
          </svg>
          <span
            className="muted"
            style={{ fontFamily: "var(--mono)", minWidth: "4.75rem", textAlign: "right" }}
          >
            {formatNumber(angle)}°
          </span>
        </span>
      </div>
    </>
  );
}

/** One turn of the knob: which pointer is turning it, and the angle it stands at now. */
type Turn = { pointerId: number; angle: number };

/**
 * Where a pointer is around an element's centre, in degrees, folded into the
 * range the engine compares angles in.
 *
 * Screen `y` grows downwards while the engine measures its rotations
 * counter-clockwise from the `+x` axis, so the vertical offset is negated: a
 * pointer straight above the centre reads 90°, to the right 0°, to the left 180°.
 *
 * Nearby five-degree guides attract the angle; `Shift` forces a step.
 */
function pointerAngle(
  element: Element,
  event: { clientX: number; clientY: number; shiftKey: boolean },
): number {
  const box = element.getBoundingClientRect();
  const dx = event.clientX - (box.left + box.width / 2);
  const dy = box.top + box.height / 2 - event.clientY;
  const degrees = (Math.atan2(dy, dx) * 180) / Math.PI;
  const snapped = snapAngle(degrees, event.shiftKey);
  return foldAngle(snapped);
}

type NumberFieldProps = {
  label: string;
  /** The placement's own value, formatted; "" when it is unset. */
  value: string;
  /** Called with the number the field holds when the draft is committed. */
  onCommit: (value: number) => void;
  /** Called instead when the field is emptied; without it, an empty field changes nothing. */
  onClear?: () => void;
  placeholder?: string;
};

/** One editable number: a draft while it is typed, one report when it is done. */
function NumberField({ label, value, onCommit, onClear, placeholder }: NumberFieldProps) {
  const { t } = useI18n();
  const [draft, setDraft] = useState(value);
  const [typing, setTyping] = useState(false);

  // A drag on the canvas rewrites the placement: the field follows it, as long as
  // nobody is typing in it.
  useEffect(() => {
    if (!typing) {
      setDraft(value);
    }
  }, [value, typing]);

  const commit = () => {
    const text = draft.trim();
    if (text === value) {
      // Nothing typed, or nothing but the digits the rounded display shows: the
      // placement stays as it is.
      return;
    }
    if (text === "") {
      if (onClear === undefined) {
        setDraft(value);
      } else {
        onClear();
      }
      return;
    }
    const parsed = Number(text);
    if (!Number.isFinite(parsed)) {
      setDraft(value);
      return;
    }
    onCommit(parsed);
  };

  // Leaving a field commits it. When the field is unmounted rather than blurred —
  // another shape is selected, the selection is cleared — React takes the element
  // away before the browser blurs it, so the last draft is reported from here.
  const lastCommit = useRef(commit);
  useEffect(() => {
    lastCommit.current = commit;
  });
  useEffect(() => () => lastCommit.current(), []);

  return (
    <label className="field">
      <span className="field__label">{t(label)}</span>
      <input
        className="input input--narrow"
        type="text"
        inputMode="decimal"
        value={draft}
        placeholder={placeholder === undefined ? undefined : t(placeholder)}
        onChange={(event) => setDraft(event.target.value)}
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
    </label>
  );
}

/** A number as a field shows it: six significant digits, which is what the panel reads. */
function formatNumber(value: number): string {
  return String(Number(value.toPrecision(6)));
}

/**
 * Whether the policy lets a rotation through, as the engine's `RotationPolicy`
 * decides it: a free policy accepts anything, a fixed one only its first angle,
 * a discrete one any of its angles.
 */
function angleAllowed(policy: RotationDoc, rotation: number): boolean {
  if (policy.mode === "free") {
    return true;
  }
  const folded = foldAngle(rotation);
  const near = (angle: number) => Math.abs(folded - foldAngle(angle)) <= ANGLE_TOLERANCE;
  const fixed = policy.angles[0];
  if (policy.mode === "fixed") {
    return fixed !== undefined && near(fixed);
  }
  return policy.angles.some(near);
}

/** Fold an angle in degrees into `[-180, 180)`, the way the engine compares angles. */
function foldAngle(angle: number): number {
  return ((((angle + 180) % 360) + 360) % 360) - 180;
}

/** The policy in the fewest words that still say what the engine accepts. */
function describePolicy(policy: RotationDoc): string {
  if (policy.mode === "free") {
    return "free";
  }
  const allowed = policy.angles.map((angle) => `${formatNumber(angle)}°`).join(", ") || "none";
  return policy.mode === "fixed" ? `fixed at ${allowed}` : `one of ${allowed}`;
}
