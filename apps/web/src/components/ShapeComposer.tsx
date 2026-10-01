/**
 * The shape composer: the workspace that folds primitives into one packable outline.
 *
 * It is the arena editor's sibling and speaks the same language: a list of parts,
 * each a primitive with an operation, an offset and a turn, sent whole to the
 * engine on every edit. What comes back is not a tree but the outline the engine
 * compiled, and the browser computes none of it.
 *
 * The canvas beside this panel is the arena's own (`ArenaCanvas`), driven by the
 * engine's answer to `POST /api/arena`: it is the only answer that carries every
 * primitive's own path and box, so a part can be grabbed where it stands, exactly
 * as in the arena. `POST /api/shape` remains the judge: its refusal is shown here
 * word for word, `Validate` is disabled while it refuses, and the shape it returns
 * is what joining the library stores.
 *
 * Validating hands the compiled shape and the stack that produced it back to the
 * application: the library keeps the outline the engine will judge and the tree
 * the composer can reopen. The engine never receives the tree.
 */

import { useI18n } from "../i18n";
import type { ArenaPartDoc, Bounds, Point, ShapePreviewDoc } from "../types";

import { ArenaPanel } from "./ArenaPanel";
import "./ShapeComposer.css";

export type ShapeComposerPanelProps = {
  name: string;
  onName: (name: string) => void;
  parts: ArenaPartDoc[];
  selectedPart: number | null;
  onSelectPart: (index: number | null) => void;
  drawing: { points: Point[] } | null;
  onFinishDrawing: () => void;
  onCancelDrawing: () => void;
  onChange: (parts: ArenaPartDoc[]) => void;
  /** Forwarded to the shared parts editor: the two ends of one undoable run. */
  onEditStart?: () => void;
  onEditEnd?: () => void;
  /** The engine's answer to `POST /api/shape`, or null while it refuses. */
  preview: ShapePreviewDoc | null;
  /** The engine's refusal, word for word. */
  error: string | null;
  busy: boolean;
  /** True when the panel reopens a shape the library already holds. */
  editing: boolean;
  onCancel: () => void;
  onValidate: () => void;
};

/**
 * The composer's right half: the name, the engine's verdict on the stack, and the
 * parts editor it shares with the arena.
 */
export function ShapeComposerPanel({
  name,
  onName,
  parts,
  selectedPart,
  onSelectPart,
  drawing,
  onFinishDrawing,
  onCancelDrawing,
  onChange,
  onEditStart,
  onEditEnd,
  preview,
  error,
  busy,
  editing,
  onCancel,
  onValidate,
}: ShapeComposerPanelProps) {
  const { t, number } = useI18n();
  return (
    <>
      <section className="panel__section shape-composer__head">
        <h2 className="panel__title">{editing ? t("Edit a shape") : t("Shape composer")}</h2>
        <p className="muted">
          {t("Build a shape from primitives combined with union, intersection and subtraction. The engine compiles it, and the outline shown is the one it will place.")}
        </p>
        {parts.length === 0 && <p className="muted">{t("Build a shape: right-click or double-click to add a primitive.")}</p>}
        <label className="field">
          <span className="field__label">{t("name")}</span>
          <input
            className="input"
            value={name}
            onChange={(event) => onName(event.target.value)}
            placeholder={t("My shape")}
          />
        </label>
        {preview !== null && (
          <p className="muted shape-composer__measure">
            {t("area")} {number(preview.area)}
            {preview.shape.type === "custom_polygon" && ` · ${preview.shape.points.length} ${t("vertices")}`}
          </p>
        )}
        {/* The engine's refusal is the judge: it is shown as it wrote it, and
            `Validate` stays disabled until the stack compiles. */}
        {error !== null ? (
          <p className="shape-composer__error" role="alert">{error}</p>
        ) : busy ? (
          <p className="muted shape-composer__measure">{t("compiling…")}</p>
        ) : (
          <p className="muted shape-composer__measure">
            {t("The outline is drawn from the engine's own measurement.")}
          </p>
        )}
        <div className="shape-composer__actions">
          <button type="button" className="button button--ghost" onClick={onCancel}>
            {t("Cancel")}
          </button>
          <button
            type="button"
            className="button button--primary"
            disabled={preview === null || error !== null || name.trim() === ""}
            onClick={onValidate}
          >
            {editing ? t("Save") : t("Validate")}
          </button>
        </div>
      </section>
      <ArenaPanel
        title="Shape parts"
        baseNote="The base cannot be deleted; every shape starts with one."
        parts={parts}
        editable
        selectedPart={selectedPart}
        onSelectPart={onSelectPart}
        drawing={drawing}
        onFinishDrawing={onFinishDrawing}
        onCancelDrawing={onCancelDrawing}
        onChange={onChange}
        onEditStart={onEditStart}
        onEditEnd={onEditEnd}
      />
    </>
  );
}

/**
 * The engine's outline, drawn from the path and the bounds it answered with.
 *
 * The only work here is a change of frame: the viewBox is built from the bounds,
 * and the group flips y once because SVG grows downwards while the domain grows
 * up. No corner, radius or area is computed.
 */
export function ShapeOutline({ path, bounds, className }: {
  path: string;
  bounds: Bounds;
  className?: string;
}) {
  const [minX, minY, maxX, maxY] = bounds;
  const width = Math.max(maxX - minX, 1e-6);
  const height = Math.max(maxY - minY, 1e-6);
  const pad = Math.max(width, height) * 0.08;
  const viewBox =
    String(minX - pad) + " " + String(-(maxY + pad)) + " " +
    String(width + 2 * pad) + " " + String(height + 2 * pad);
  return (
    <svg
      className={className ?? "shape-composer__svg"}
      viewBox={viewBox}
      preserveAspectRatio="xMidYMid meet"
      role="img"
    >
      <g transform="scale(1 -1)">
        <path className="shape-composer__outline" d={path} fillRule="evenodd" />
      </g>
    </svg>
  );
}
