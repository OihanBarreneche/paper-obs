import { useState } from "react";
import { useI18n } from "../i18n";
import { orientationColor } from "../orientationColors";
import type { BestScoreDoc, EvaluationDoc, ProblemDoc, SummaryDoc, ViewDoc } from "../types";
import "./StatusPanel.css";

type Props = {
  evaluation: EvaluationDoc | null;
  summary: SummaryDoc | null;
  busy: boolean;
  best: BestScoreDoc | null;
  /** The problem judged, so the panel can describe the covering's measured region. */
  problem?: ProblemDoc | null;
  view?: ViewDoc | null;
  showOrientations?: boolean;
  onToggleOrientations?: () => void;
};

const MEANING: Record<string, string> = {
  density: "Share of the arena covered by shapes",
  void_area: "Area left uncovered, in square world units",
  n_shapes: "Number of placed shapes",
  boundary_contacts: "Shapes touching the arena boundary",
  packed_area: "Total area of placed shapes, in square world units",
  covered_area: "Area of the arena the union of the shapes covers, in square world units",
  arena_area: "Area of the arena, in square world units",
  covered_size: "Size of the largest target the union of the copies contains",
  container_side: "Side length of the smallest measured container",
  container_area: "Area of the measured container",
  common_scale: "The shared shape size; increasing it improves this problem's score",
  total_scale: "Sum of the copies' sizes — the source's own Σr or Σs for these unit copies",
  total_perimeter: "Total perimeter of the copies, in world length units",
  max_scale: "Largest local size of one copy",
  min_scale: "Smallest local size of one copy",
  covered_circle_radius:
    "Radius of the largest circle the copies actually contain in the target",
  equivalent_container_side: "Side of the equivalent container around unit copies",
  "covered square area": "Area of the largest square covered by the copies",
};

/**
 * The covering the verdict is scoring, in one sentence.
 *
 * The product exposes one covering model: `maximize_covered_size` derives the
 * arena from the union of the unit copies and scores its size. The panel states
 * which target the arena is, and how the score relates to the published value, so
 * a reader never has to guess which object the source measured.
 */
type Reading = {
  /** The covering on screen, in one sentence. */
  base: string;
  /** How its score relates to the published value; empty when there is no reference. */
  comparison: string;
};

function readingNote(problem: ProblemDoc | null | undefined, t: (english: string) => string): Reading {
  if (problem == null) return { base: "", comparison: "" };
  if (problem.objective.type === "maximize_covered_size") {
    const which = problem.objective.target === "circle"
      ? "The arena is the largest disc contained in the union of the unit copies, and the score is its radius."
      : problem.objective.target === "square"
        ? "The arena is the largest axis-aligned square contained in the union of the unit copies, and the score is its side."
        : "The arena is the largest triangle contained in the union of the unit copies, and the score is its side.";
    // The reference says what the source published for this family; the comparison
    // sentence names that object rather than assuming the two scores are one.
    const unit = referenceUnit(problem);
    const compare = unit.includes("area")
      ? "The displayed area is directly comparable to the source; the side length remains in all measurements."
      : unit.includes("radius")
        ? "The score is directly comparable to the published radius."
        : unit.includes("side")
          ? "The score is directly comparable to the published side."
          : "";
    return { base: t(which), comparison: compare === "" ? "" : t(compare) };
  }
  if (problem.objective.type === "maximize_scale" && referenceUnit(problem).includes("container side")) {
    return { base: t("The engine scales copies inside a unit container."),
      comparison: t("The displayed equivalent side uses unit copies, matching the published reference.") };
  }
  return { base: "", comparison: "" };
}

/** What the family's published number measures, read from the carried reference. */
function referenceUnit(problem: ProblemDoc): string {
  const reference = problem.metadata.reference;
  if (typeof reference !== "object" || reference === null) return "";
  const unit = (reference as { unit?: unknown }).unit;
  return typeof unit === "string" ? unit : "";
}

export function StatusPanel({ evaluation, busy, best, problem, view, showOrientations = false, onToggleOrientations }: Props) {
  const { t, number } = useI18n();
  const [measureOpen, setMeasureOpen] = useState(true);
  if (evaluation === null) return <section className="panel__section">
    <h2 className="panel__title">{t("Verdict")}</h2>
    <p className="muted">{t(busy ? "evaluating…" : "no candidate yet: choose a problem")}</p>
  </section>;

  const sourceUnit = problem ? referenceUnit(problem) : "";
  const sourceArea = problem?.objective.type === "maximize_covered_size"
    && problem.objective.target === "square" && sourceUnit.includes("area")
    && evaluation.metrics.arena_area != null;
  const sourceSide = problem?.objective.type === "maximize_scale" && sourceUnit.includes("container side")
    && evaluation.metrics.equivalent_container_side != null;
  const promoted = sourceArea ? "arena_area" : sourceSide ? "equivalent_container_side"
    : evaluation.promoted_metric ?? "density";
  const headlineValue = evaluation.metrics[promoted] ?? evaluation.score.primary;
  const headlineName = sourceArea ? "covered square area"
    : evaluation.metrics[promoted] == null ? evaluation.score.label : promoted;
  const primary = ["density", "void_area", "n_shapes"].filter((key) => key in evaluation.metrics && key !== promoted);
  const rest = Object.entries(evaluation.metrics).filter(([key]) => key !== promoted && !primary.includes(key));
  const failed = evaluation.validation.results.filter((item) => !item.valid);
  const orientationGroups = new Map<number, { angle: number; count: number }>();
  for (const shape of view?.shapes ?? []) {
    const group = shape.orientation_group ?? 0;
    const previous = orientationGroups.get(group);
    orientationGroups.set(group, previous
      ? { ...previous, count: previous.count + 1 }
      : { angle: shape.orientation_deg ?? 0, count: 1 });
  }
  const orientations = [...orientationGroups.entries()].sort((a, b) => a[0] - b[0]);
  const format = (name: string, value: number) => name === "density" ? `${number(value * 100, 1)} %` : number(value, 5);
  // The one covering sentence: which target the measured arena is, and how the
  // score relates to the published value. A legacy fixed-arena document has none.
  const reading = readingNote(problem, t);
  // The engine's own sentence for the first constraint it refused, which is what an
  // invalid verdict shows in place of any comparison with the published value.
  const blocking = failed[0];
  return <>
    <section className="panel__section verdict-panel">
      <h2 className="panel__title">{t("Verdict")}</h2>
      <div className="hero">
        <span className="hero__value">{format(headlineName, headlineValue)}</span>
        <span className="hero__label">{t(headlineName.replaceAll("_", " "))}</span>
        <span className={evaluation.valid ? "status status--valid" : "status status--invalid"}>{t(evaluation.valid ? "valid" : "invalid")}</span>
      </div>
      <p className="verdict-panel__explain">{t(MEANING[headlineName] ?? "Metric promoted by the objective")}</p>
      {/* An invalid score is not a comparable score: the panel shows the engine's
          own sentence for the first broken constraint ("expected 4 shapes, found
          5") instead of the reading's comparison with the published value. */}
      {!evaluation.valid && blocking !== undefined && (
        <p className="verdict-panel__violation">{t(blocking.message)}</p>
      )}
      {evaluation.valid && reading.base !== "" && (
        <p className="verdict-panel__reading">
          {reading.base}{reading.comparison === "" ? "" : ` ${reading.comparison}`}
        </p>
      )}
      {evaluation.valid && best?.candidateId === evaluation.candidate_id && <span className="verdict-panel__best">✳ {t("best so far")}</span>}
      {busy && <span className="muted">{t("evaluating…")}</span>}
      {primary.length > 0 && <div className="verdict-panel__primary">{primary.map((key) => <div key={key} title={t(MEANING[key] ?? key)}>
        <span>{t(key.replaceAll("_", " "))}</span><strong>{format(key, evaluation.metrics[key] ?? 0)}</strong>
      </div>)}</div>}
      {problem?.shape.type !== "circle" && onToggleOrientations && orientations.length > 0 && <div className={`orientation-metric${showOrientations ? " orientation-metric--active" : ""}`}>
        <button type="button" aria-expanded={showOrientations} aria-pressed={showOrientations} onClick={onToggleOrientations}>
          <span><b>{t("Distinct orientations")}</b><small>{t(showOrientations ? "Shapes colored by angle" : "Click to color shapes by angle")}</small></span>
          <strong>{orientations.length}</strong><span aria-hidden="true">{showOrientations ? "−" : "+"}</span>
        </button>
        {showOrientations && <div className="orientation-metric__legend">{orientations.map(([group, { angle, count }]) =>
          <span key={group}><i style={{ background: orientationColor(group) }} />{number(angle, 3)}° <small>· {count} {t(count === 1 ? "shape" : "shapes")}</small></span>)}</div>}
      </div>}
      {rest.length > 0 && <details className="verdict-panel__more" open={measureOpen}
        onToggle={(event) => setMeasureOpen(event.currentTarget.open)}><summary>{t("All measurements")} ({rest.length})</summary>
        <dl className="metrics">{rest.map(([key, value]) => <div key={key} title={t(MEANING[key] ?? key)}>
          <dt>{t(key.replaceAll("_", " "))}</dt><dd>{format(key, value)}</dd>
        </div>)}</dl>
      </details>}
    </section>
    {failed.length > 0 && <section className="panel__section verdict-panel__violations">
      <h2 className="panel__title">{t("Violations")} ({failed.reduce((sum, item) => sum + item.violations.length, 0)})</h2>
      {failed.map((item) => <details key={item.constraint} open><summary>{t(item.constraint.replaceAll("_", " "))}</summary>
        <ul>{item.violations.slice(0, 10).map((violation, index) => <li key={index}>
          {t(violation.kind.replaceAll("_", " "))} · {violation.shape_ids.join(", ")} · {number(violation.magnitude, 5)}
        </li>)}</ul>
      </details>)}
    </section>}
  </>;
}
