/**
 * The convergence panel: one baseline run, its curve, and what the engine said
 * about it.
 *
 * The curve is the content of a comparison — the best score a strategy had
 * reached, judgement after judgement — so what is plotted here are the engine's
 * own steps, one point per step, and nothing else. This file converts numbers
 * into pixels: it does not smooth, does not rank, does not decide that a step is
 * an improvement (`accepted` is the engine's word for that, and the summary line
 * is the engine's sentence, shown verbatim), and does not re-derive a score.
 *
 * The plot is one `viewBox` stretched to the panel's width by
 * `preserveAspectRatio="none"`, with the two axes as two lines and the two labels
 * as text outside it: a resize costs a repaint and never a measurement, and the
 * labels keep their size at any width. The three curves a short run can produce
 * are all drawn rather than refused — no run yet, a single point, and a score
 * that never changes — the last two by keeping the domains wide enough that no
 * division by zero is possible.
 */

import { useState } from "react";
import { useI18n } from "../i18n";

import type { ConvergenceDoc } from "../types";

import "./ConvergencePanel.css";

export type ConvergencePanelProps = {
  /** The strategies the engine offers, in its own order. */
  baselines: string[];
  /** The last run, or null before the first one. */
  convergence: ConvergenceDoc | null;
  /** The engine's one-line description of that run; empty before the first one. */
  summary: string;
  /** The engine's message for a refused run, shown as it came. */
  error: string | null;
  busy: boolean;
  onRun: (baseline: string, budget: number) => void;
  /** The measurement the objective promotes, which the curve follows, such as container_side. */
  metric?: string;
};

/** The budget a first run asks for, and the bounds the engine accepts. */
const DEFAULT_BUDGET = 200;
const MIN_BUDGET = 1;
const MAX_BUDGET = 1000;

/** The plot's own box, in screen units: it is stretched, never measured. */
const PLOT_WIDTH = 320;
const PLOT_HEIGHT = 132;
/** Room kept inside the box, so a point on the edge of a domain clears the axes. */
const PLOT_INSET = 6;
/** Radius of the marker on the last point, in the plot's own units. */
const DOT_RADIUS = 3;

/** What the score axis is called when the objective's measurement is not known yet. */
const SCORE_AXIS_LABEL = "best score";

/** The budget a run is sent with: what was typed, brought inside the engine's bounds. */
function budgetOf(draft: string): number {
  const typed = Math.round(Number(draft));
  if (!Number.isFinite(typed)) {
    return DEFAULT_BUDGET;
  }
  return Math.min(MAX_BUDGET, Math.max(MIN_BUDGET, typed));
}

export function ConvergencePanel({
  baselines,
  convergence,
  summary,
  error,
  busy,
  onRun,
  metric,
}: ConvergencePanelProps) {
  const { t } = useI18n();
  const [chosen, setChosen] = useState("");
  const [budget, setBudget] = useState(String(DEFAULT_BUDGET));

  // The list arrives with the other startup fetches. Until it does, and if it is
  // ever empty, nothing is selected — a select whose value is not among its
  // options would show a blank control and send a name the engine does not know.
  const baseline = baselines.includes(chosen) ? chosen : (baselines[0] ?? "");

  return (
    <section className="panel__section">
      <h2 className="panel__title">{t("Convergence")}</h2>

      <div className="convergence__controls">
        <label className="convergence__control">
          <span className="convergence__label">{t("baseline")}</span>
          <select
            className="select"
            value={baseline}
            disabled={baselines.length === 0}
            onChange={(event) => setChosen(event.target.value)}
          >
            {/* The engine's names, used as they are: they are what a run is asked for by. */}
            {baselines.map((name) => (
              <option key={name} value={name}>
                {t(name.replaceAll("_", " "))}
              </option>
            ))}
          </select>
        </label>

        <label className="convergence__control">
          <span className="convergence__label">{t("budget, in evaluations")}</span>
          <input
            className="input input--narrow"
            type="number"
            min={MIN_BUDGET}
            max={MAX_BUDGET}
            value={budget}
            onChange={(event) => setBudget(event.target.value)}
            onBlur={() => setBudget(String(budgetOf(budget)))}
          />
        </label>

        <button
          className="button"
          type="button"
          disabled={busy || baseline === ""}
          onClick={() => onRun(baseline, budgetOf(budget))}
        >
          {t("Run")}
        </button>
      </div>

      {/* The engine's sentence about the run, and its refusal when there is one. */}
      {summary !== "" && convergence && <p className="convergence__summary">{t("Search complete")} · {convergence.evaluations} {t("evaluations")}</p>}
      {error !== null && <div className="error">{error}</div>}

      {convergence === null ? (
        <p className="muted">{t("No search yet — choose a baseline and run it")}</p>
      ) : (
        <Curve convergence={convergence} label={metric ? metric.replaceAll("_", " ") : SCORE_AXIS_LABEL} />
      )}
    </section>
  );
}

type CurveProps = { convergence: ConvergenceDoc; label: string };

/** The run's steps as a picture: one polyline, one marker, two axes. */
function Curve({ convergence, label }: CurveProps) {
  const { t } = useI18n();
  const steps = convergence.steps;

  // Evaluations are 1-based, so the domain opens at the first one, and it is never
  // narrower than one evaluation: every x being equal is exactly what a one-step
  // curve looks like, and an axis of zero width would be a division by zero.
  const xLow = 1;
  const xHigh = Math.max(xLow + 1, steps[steps.length - 1]?.evaluations ?? xLow);

  // A run whose scores never change is drawn on a padded axis rather than on a
  // zero-height one — the same padding the engine's own chart applies.
  let yLow = steps.length === 0 ? 0 : Number.POSITIVE_INFINITY;
  let yHigh = steps.length === 0 ? 1 : Number.NEGATIVE_INFINITY;
  for (const step of steps) {
    yLow = Math.min(yLow, step.best_measure);
    yHigh = Math.max(yHigh, step.best_measure);
  }
  if (yHigh <= yLow) {
    const pad = Math.abs(yHigh) * 0.05 || 1;
    yLow -= pad;
    yHigh += pad;
  }

  // One pass from the engine's numbers to the plot's own coordinates. The two
  // projections are written where they are used rather than behind helpers: this
  // is the whole of the arithmetic the panel does and it is easier to audit in
  // one place.
  const plotted = steps.map((step) => ({
    x: PLOT_INSET + ((step.evaluations - xLow) / (xHigh - xLow)) * (PLOT_WIDTH - 2 * PLOT_INSET),
    y:
      PLOT_HEIGHT -
      PLOT_INSET -
      ((step.best_measure - yLow) / (yHigh - yLow)) * (PLOT_HEIGHT - 2 * PLOT_INSET),
    valid: step.best_valid,
  }));

  const points = plotted.map((point) => `${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(" ");
  // The last step carries the marker, and its class is the engine's `best_valid`:
  // nothing here decides whether the run ended well.
  const marker = plotted[plotted.length - 1] ?? null;

  return (
    <div className="convergence__plot">
      <span className="convergence__axis convergence__axis--score">{t(label)}</span>
      <svg
        className="convergence__curve"
        viewBox={`0 0 ${PLOT_WIDTH} ${PLOT_HEIGHT}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`${t(label)} / ${t("evaluations")}`}
      >
        {/* The two axes: one line each, drawn between the plot's inset corners. */}
        <line
          className="convergence__axis-line"
          x1={PLOT_INSET}
          y1={PLOT_HEIGHT - PLOT_INSET}
          x2={PLOT_WIDTH - PLOT_INSET}
          y2={PLOT_HEIGHT - PLOT_INSET}
        />
        <line
          className="convergence__axis-line"
          x1={PLOT_INSET}
          y1={PLOT_INSET}
          x2={PLOT_INSET}
          y2={PLOT_HEIGHT - PLOT_INSET}
        />
        {plotted.length > 0 && <polyline className="convergence__line" points={points} />}
        {marker !== null && (
          <circle
            className={
              marker.valid
                ? "convergence__dot convergence__dot--valid"
                : "convergence__dot convergence__dot--invalid"
            }
            cx={marker.x}
            cy={marker.y}
            r={DOT_RADIUS}
          />
        )}
      </svg>
      <span className="convergence__axis convergence__axis--evaluations">{t("evaluations")}</span>
    </div>
  );
}
