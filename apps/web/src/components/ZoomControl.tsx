import { useI18n } from "../i18n";
import type { CanvasViewport } from "../viewport";

/** Restore the picture's original framing after a pan or wheel zoom. */
export function ZoomControl({ view }: { view: CanvasViewport }) {
  const { t } = useI18n();
  return <button className="canvas-reset" type="button" aria-label={t("Recenter view")}
    onClick={() => view.reset()}>
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11a8 8 0 1 1-2.4-5.6M20 3v6h-6" /></svg>
  </button>;
}
