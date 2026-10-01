/**
 * The composed shapes this browser has made.
 *
 * A composed shape is an outline the engine compiled, so a tile is drawn from the
 * engine's own path and bounds — the library measures nothing. Every entry can be
 * placed in the problem, reopened in the composer, or deleted; a delete asks once,
 * because the outline and the stack that made it are the only copy there is.
 *
 * The library is reached from the shape palette rather than from the canvas menu:
 * listing every composed shape at a right-click would crowd out the families the
 * engine ships, which is exactly what the palette must keep visible.
 */

import { useState } from "react";

import { useI18n } from "../i18n";
import type { ComposedShapeDoc } from "../types";

import { ShapeOutline } from "./ShapeComposer";
import "./ShapeLibrary.css";

export type ShapeLibraryProps = {
  open: boolean;
  /** The composed shapes the browser holds, in creation order. */
  shapes: ComposedShapeDoc[];
  onClose: () => void;
  /** Open the composer on an empty stack. */
  onNew: () => void;
  /** Reopen one shape in the composer. */
  onEdit: (shape: ComposedShapeDoc) => void;
  /** Forget one shape; its outline and its stack are the only copy. */
  onDelete: (id: string) => void;
  /** Add one shape to the problem being edited, where the palette was opened. */
  onPlace: (shape: ComposedShapeDoc) => void;
};

export function ShapeLibrary({
  open,
  shapes,
  onClose,
  onNew,
  onEdit,
  onDelete,
  onPlace,
}: ShapeLibraryProps) {
  const { t, number } = useI18n();
  // Which tile is asking to be deleted: a delete is one click, a mis-click would
  // throw away an outline nobody can rebuild by hand.
  const [confirming, setConfirming] = useState<string | null>(null);
  if (!open) {
    return null;
  }
  return (
    <div className="modal">
      <div className="modal__panel modal__panel--library">
        <section className="panel__section">
          <h2 className="panel__title">{t("Composed shapes")}</h2>
          <p className="muted">
            {t("Shapes you built from primitives. Place one in the problem, edit it, or delete it.")}
          </p>
        </section>
        {shapes.length === 0 ? (
          <p className="muted shape-library__empty">
            {t("No composed shape yet. Create one from primitives and boolean operations.")}
          </p>
        ) : (
          <ul className="shape-library__list">
            {shapes.map((shape) => (
              <li key={shape.id} className="shape-library__card">
                <ShapeOutline className="shape-library__thumb" path={shape.path} bounds={shape.bounds} />
                <div className="shape-library__info">
                  <strong>{shape.name}</strong>
                  <span className="muted">
                    {t("area")} {number(shape.area)} · {shape.summary}
                  </span>
                  <span className="muted">
                    {shape.parts.length} {t("primitives")}
                  </span>
                </div>
                <div className="shape-library__actions">
                  <button type="button" className="button button--primary" onClick={() => onPlace(shape)}>
                    {t("Place")}
                  </button>
                  <button type="button" className="button" onClick={() => onEdit(shape)}>
                    {t("Edit")}
                  </button>
                  {confirming === shape.id ? (
                    <>
                      <button
                        type="button"
                        className="button button--danger"
                        onClick={() => {
                          onDelete(shape.id);
                          setConfirming(null);
                        }}
                      >
                        {t("Delete")}
                      </button>
                      <button type="button" className="button button--ghost" onClick={() => setConfirming(null)}>
                        {t("Cancel")}
                      </button>
                    </>
                  ) : (
                    <button type="button" className="button button--ghost" onClick={() => setConfirming(shape.id)}>
                      {t("Delete")}
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
        <div className="modal__actions">
          <button type="button" className="button button--ghost" onClick={onClose}>
            {t("Close")}
          </button>
          <button type="button" className="button button--primary" onClick={onNew}>
            {t("Create a shape")}
          </button>
        </div>
      </div>
    </div>
  );
}
