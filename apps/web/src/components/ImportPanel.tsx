/**
 * Importing a known solution, to play with it.
 *
 * Posted solutions are lists of positions for one shape family, at the natural
 * size of that family — a disc of diameter 1, a polygon of side 1 — so the panel
 * asks for three things: which family, at which uniform scale, and the
 * positions. The text is read one line at a time; the first line it cannot read
 * refuses the whole paste and names its line, because an import that quietly
 * dropped a line would hand over fewer shapes than the solution it claims to
 * carry.
 *
 * The panel builds a document out of the palette and the numbers the user typed,
 * and stops there: how those positions become a candidate, and whether they
 * pack, is the engine's judgement and the application's decision.
 *
 * This file also answers the two questions the shape section of the editor asks
 * of the palette — which family a shape document belongs to, and what a family
 * builds for a chosen side count. Which families exist, and how big each one is
 * by nature, is never written here: it is what the engine sends.
 */

import { useMemo, useState } from "react";
import { useI18n } from "../i18n";

import type { ShapeDoc, ShapeFamilyDoc } from "../types";

import "./ImportPanel.css";

/**
 * One position read from the text: world coordinates, and an angle in degrees.
 *
 * The rotation is always degrees, whatever the pasted file held: degrees are the
 * unit of every placement in this project, and the conversion happens once, here,
 * rather than downstream.
 */
export type ImportedPositions = { x: number; y: number; rotation: number };

/** Unit the pasted angles are written in. Degrees are the project's own. */
type AngleUnit = "degrees" | "radians";

const DEGREES_PER_RADIAN = 180 / Math.PI;

export type ImportPanelProps = {
  /** Whether the dialog is up; a closed panel renders nothing at all. */
  open: boolean;
  /** The engine's palette, the same list the shape section offers. */
  shapes: ShapeFamilyDoc[];
  /** The shape the problem packs today, or null before one is loaded: the picker opens on its family. */
  shape: ShapeDoc | null;
  /** Called with the shape to build, the positions to place, and their common scale. */
  onImport: (shape: ShapeDoc, positions: ImportedPositions[], scale: number) => void;
  onImportCandidate: (candidate: unknown) => Promise<void>;
  onClose: () => void;
};

/** Whether two shape documents name the same family at the same size. */
function sameShape(left: ShapeDoc, right: ShapeDoc): boolean {
  if (left.type === "circle" && right.type === "circle") {
    return left.radius === right.radius;
  }
  if (left.type === "regular_polygon" && right.type === "regular_polygon") {
    return left.sides === right.sides && left.side === right.side;
  }
  if (left.type === "custom_polygon" && right.type === "custom_polygon") {
    return JSON.stringify(left.points) === JSON.stringify(right.points);
  }
  return false;
}

/**
 * The palette entry a shape belongs to.
 *
 * An exact match wins. Failing that, an entry that carries `sides` takes any
 * count of its kind, so a pentagon no fixed family describes is still a regular
 * polygon; and a hand-drawn outline, which has no count to match, stands for the
 * first family of its kind, the one whose side count its numbers replace.
 */
export function familyForShape(shapes: ShapeFamilyDoc[], shape: ShapeDoc): ShapeFamilyDoc | null {
  const exact = shapes.find((entry) => sameShape(entry.shape, shape));
  if (exact !== undefined) {
    return exact;
  }
  const open =
    shape.type === "regular_polygon"
      ? shapes.find((entry) => entry.shape.type === "regular_polygon" && entry.sides !== undefined)
      : undefined;
  const kind = shape.type === "circle" ? "circle" : "regular_polygon";
  return open ?? shapes.find((entry) => entry.shape.type === kind) ?? null;
}

/**
 * The shape a family builds for a side count.
 *
 * A family whose count is fixed builds its own shape: only an entry that carries
 * `sides` was handed a count the caller chooses, and it takes that count with
 * the side the family is naturally drawn at.
 */
function shapeForFamily(family: ShapeFamilyDoc, sides: number): ShapeDoc {
  if (family.shape.type !== "regular_polygon" || family.sides === undefined) {
    return family.shape;
  }
  return { type: "regular_polygon", sides, side: family.shape.side };
}

/** What one paste holds: the positions it names, or the line that stopped it. */
type ParseResult = {
  positions: ImportedPositions[];
  error: string | null;
  /** Set when the angles are small enough to have been written in radians. */
  radiansHint: boolean;
};

/**
 * Read a pasted list of positions.
 *
 * One shape per line, `x y` or `x y angle`; the numbers are separated by
 * whitespace or commas, `#` starts a comment, and blank lines are ignored.
 * Angles are read in ``unit`` and converted to the project's degrees. The first
 * line that cannot be read fails the whole paste and says which line it was — a
 * line dropped in silence would make the count a lie.
 *
 * ``radiansHint`` is set when nothing in the file settles the question by itself:
 * a list of angles that are all within one turn is a list of degrees that could
 * equally have been written in radians, and the panel says so instead of choosing.
 * The hint never changes what was parsed.
 */
function parsePositions(text: string, unit: AngleUnit, t: (text: string) => string): ParseResult {
  const positions: ImportedPositions[] = [];
  for (const [row, raw] of text.split("\n").entries()) {
    const line = raw.replace(/#.*/, "").trim();
    if (line === "") {
      continue;
    }
    const lineNumber = row + 1;
    const fields = line.split(/[\s,]+/).filter((field) => field !== "");
    if (fields.length !== 2 && fields.length !== 3) {
      return {
        positions: [],
        error: `${t("Line")} ${lineNumber}: ${t("expected two or three numbers, found")} ${fields.length}.`,
        radiansHint: false,
      };
    }
    const values = fields.map((field) => Number(field));
    const wrong = values.findIndex((value) => !Number.isFinite(value));
    if (wrong !== -1) {
      return {
        positions: [],
        error: `${t("Line")} ${lineNumber}: “${fields[wrong]}” ${t("is not a number")}.`,
        radiansHint: false,
      };
    }
    // The length was checked above: the two coordinates are always there, and a
    // line without an angle leaves the rotation at 0.
    const [x = Number.NaN, y = Number.NaN, angle] = values;
    positions.push({
      x,
      y,
      rotation: angle === undefined ? 0 : unit === "radians" ? angle * DEGREES_PER_RADIAN : angle,
    });
  }
  const angles = positions.map((position) => position.rotation);
  const hint =
    unit === "degrees" &&
    angles.some((angle) => angle !== 0) &&
    angles.every((angle) => Math.abs(angle) <= 2 * Math.PI);
  return { positions, error: null, radiansHint: hint };
}

/** What the panel holds: the family to build, and the count it starts from. */
type ImportChoice = { familyId: string; sides: string };

export function ImportPanel({ open, shapes, shape, onImport, onImportCandidate, onClose }: ImportPanelProps) {
  const { t } = useI18n();
  // The picker opens on the family the problem uses and then belongs to the
  // panel: editing the shape section above must not move a choice made here.
  const [choice, setChoice] = useState<ImportChoice>(() => {
    const chosen = shape === null ? null : familyForShape(shapes, shape);
    return chosen === null
      ? { familyId: "", sides: "" }
      : { familyId: chosen.id, sides: chosen.sides === undefined ? "" : String(chosen.sides) };
  });
  const [scale, setScale] = useState("1");
  // Degrees are the project's own unit, so they are what the panel starts on; the
  // hint below is what makes a radians file one click away rather than a guess.
  const [unit, setUnit] = useState<AngleUnit>("degrees");
  const [text, setText] = useState("");
  const [format, setFormat] = useState<"positions" | "json">("positions");
  const [jsonText, setJsonText] = useState("");
  const [jsonError, setJsonError] = useState("");

  const parsed = useMemo(() => parsePositions(text, unit, t), [text, unit, t]);
  const positions = parsed.positions;
  // The picker opens on the family the problem uses, and falls back on the first
  // one the palette offers so a dialog opened before any problem loads still has
  // something to build; a choice made here then answers first.
  const family =
    shapes.find((entry) => entry.id === choice.familyId) ??
    (shape === null ? null : familyForShape(shapes, shape)) ??
    shapes[0] ??
    null;
  const sides =
    choice.sides === "" && family !== null && family.sides !== undefined
      ? String(family.sides)
      : choice.sides;

  const count = `${positions.length} ${t(positions.length === 1 ? "shape" : "shapes")}`;

  if (!open) {
    return null;
  }

  return (
    <div className="modal">
      <section className="modal__panel import-panel" role="dialog" aria-label={t("import a solution")}>
        <h2 className="panel__title">{t("Import a solution")}</h2>
        <div className="import-panel__formats">
          <button type="button" className={format === "positions" ? "is-active" : ""} onClick={() => setFormat("positions")}>{t("Positions")}</button>
          <button type="button" className={format === "json" ? "is-active" : ""} onClick={() => setFormat("json")}>{t("Paper Obs JSON")}</button>
        </div>
        {format === "positions" ? <>
        <p className="muted">
          {t("Paste one shape per line: x y or x y angle. Use spaces or commas; # starts a comment. Coordinates use the family's natural size. Choose the angle unit below.")}
        </p>
        <div className="grid-2">
          <label className="field">
            <span className="field__label">{t("family")}</span>
            <select
              className="select"
              // The picker shows the family the panel would actually build, which is
              // the derived one until a choice is made: bound to the raw state it
              // displayed the first entry of the palette while another family was
              // loaded, so the panel lied about what it was about to import.
              value={family === null ? "" : family.id}
              onChange={(event) => {
                const count = shapes.find((entry) => entry.id === event.target.value)?.sides;
                setChoice({
                  familyId: event.target.value,
                  sides: count === undefined ? "" : String(count),
                });
              }}
            >
              {shapes.map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {t(entry.label)}
                </option>
              ))}
            </select>
          </label>
          {family !== null && family.sides !== undefined && (
            <label className="field">
              <span className="field__label">{t("sides")}</span>
              <input
                className="input input--narrow"
                type="number"
                min={3}
                step={1}
                value={sides}
                onChange={(event) => setChoice({ ...choice, sides: event.target.value })}
              />
            </label>
          )}
          <label className="field">
            <span className="field__label">{t("angle unit")}</span>
            <select
              className="select"
              value={unit}
              onChange={(event) => setUnit(event.target.value as AngleUnit)}
            >
              <option value="degrees">{t("degrees")}</option>
              <option value="radians">{t("radians")}</option>
            </select>
          </label>
          <label className="field">
            <span className="field__label">{t("scale")}</span>
            <input
              className="input input--narrow"
              type="number"
              step="any"
              value={scale}
              onChange={(event) => setScale(event.target.value)}
            />
          </label>
        </div>
        <label className="import-panel__paste-label" htmlFor="import-positions">{t("Positions to import")}</label>
        <textarea
          id="import-positions"
          className="input import-panel__text"
          rows={8}
          spellCheck={false}
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
        {parsed.radiansHint && (
          <p className="muted">
            {t("These angles could be radians.")}{" "}
            <button
              type="button"
              className="button button--ghost"
              onClick={() => setUnit("radians")}
            >
              {t("read them as radians")}
            </button>
          </p>
        )}
        <div className="import-panel__footer">
          {parsed.error === null ? (
            <span className="import-panel__count">{count}</span>
          ) : (
            <span className="import-panel__error">{parsed.error}</span>
          )}
        </div>
        </> : <>
          <p className="muted">{t("Paste an exported solution JSON file or choose one below. Its problem ID must match the open problem.")}</p>
          <label className="import-panel__paste-label" htmlFor="import-candidate-file">{t("Choose a JSON file")}</label>
          <input id="import-candidate-file" type="file" accept=".json,application/json" onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void file.text().then((value) => { setJsonText(value); setJsonError(""); }).catch((cause) => setJsonError(String(cause)));
          }} />
          <label className="import-panel__paste-label" htmlFor="import-candidate-json">{t("Solution JSON")}</label>
          <textarea id="import-candidate-json" className="input import-panel__text" rows={9} spellCheck={false}
            value={jsonText} onChange={(event) => { setJsonText(event.target.value); setJsonError(""); }} />
          {jsonError && <p className="import-panel__error" role="alert">{jsonError}</p>}
        </>}
        <div className="modal__actions">
          <button type="button" className="button button--ghost" onClick={onClose}>
            {t("Close")}
          </button>
          <button
            type="button"
            className="button button--primary"
            disabled={format === "positions" ? family === null || positions.length === 0 : !jsonText.trim()}
            onClick={() => {
              if (format === "json") {
                try {
                  const document: unknown = JSON.parse(jsonText);
                  void onImportCandidate(document).catch((cause) => setJsonError(cause instanceof Error ? cause.message : String(cause)));
                } catch (cause) { setJsonError(cause instanceof Error ? cause.message : String(cause)); }
                return;
              }
              if (family === null) {
                return;
              }
              onImport(shapeForFamily(family, Number(sides)), positions, Number(scale));
            }}
          >
            {t("Import")}
          </button>
        </div>
      </section>
    </div>
  );
}
