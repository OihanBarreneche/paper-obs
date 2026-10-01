import { useState, type ReactNode } from "react";
import { useI18n } from "../i18n";
import type {
  BestScoreDoc, CandidateDoc, ConvergenceDoc, EvaluationDoc, ProblemDoc, SummaryDoc, ViewDoc,
} from "../types";
import { BaselineGuide } from "./BaselineGuide";
import { ConvergencePanel } from "./ConvergencePanel";
import { ResearchSessions, useResearchSessions } from "./ResearchSessions";
import { StatusPanel } from "./StatusPanel";

type Props = {
  baselines: string[];
  convergence: ConvergenceDoc | null;
  searchSummary: string;
  searchError: string | null;
  onRun: (baseline: string, budget: number) => void;
  onShowCandidate: (candidate: CandidateDoc) => void;
  onOpenSession: (sessionId: string) => void;
  canvas: ReactNode;
  evaluation: EvaluationDoc | null;
  verdictSummary: SummaryDoc | null;
  best: BestScoreDoc | null;
  problem: ProblemDoc | null;
  view: ViewDoc | null;
  busy: boolean;
  showOrientations: boolean;
  onToggleOrientations: () => void;
};

const possibleMethods = [
  "Constructive heuristics",
  "Genetic and evolutionary algorithms",
  "Constraint and numerical solvers",
  "Custom programs and plugins",
] as const;

/** One strategy-agnostic page: the classical baselines the lab runs, and the free sessions
 * outside agents run and the lab only judges (docs/research-mode.md). */
export function SearchWorkspace(props: Props) {
  const { t } = useI18n();
  const [guide, setGuide] = useState(false);
  const [sessions, readSessions] = useResearchSessions();
  const here = sessions.filter((item) => item.problem_id === props.problem?.problem_id).length;
  const [picked, setPicked] = useState<"classical" | "free" | null>(null);
  // A problem an agent is researching opens on its sessions; otherwise on the baselines.
  const tab = picked ?? (here > 0 ? "free" : "classical");
  return <main className="run-workspace search-workspace">
    <div className="run-workspace__spread">
      <section className="run-workspace__process search-workspace__methods">
        <header className="search-workspace__intro">
          <span className="eyebrow">Paper Obs / {t("Search")}</span>
          <h1>{t("Search methods")}</h1>
          <p>{t("Each method proposes candidates to the same geometry engine, which judges them and records their progress.")}</p>
        </header>
        <div className="search-workspace__tabs" role="tablist" aria-label={t("Search methods")}>
          <button type="button" role="tab" aria-selected={tab === "classical"}
            onClick={() => setPicked("classical")}>{t("Classical methods")}</button>
          <button type="button" role="tab" aria-selected={tab === "free"}
            onClick={() => setPicked("free")}>{t("Free research")} <small>{here}</small></button>
        </div>
        {tab === "free" ? <ResearchSessions sessions={sessions} problemId={props.problem?.problem_id}
          onShow={props.onShowCandidate} onOpen={props.onOpenSession} onChange={readSessions} /> : <>
          <div className="section-heading"><h2>{t("Classical methods")}</h2>
            <button type="button" className="search-workspace__how" onClick={() => setGuide(true)}>{t("How do they work?")}</button></div>
          {guide && <BaselineGuide onClose={() => setGuide(false)} />}
          {props.baselines.length > 0 ? <ConvergencePanel
            baselines={props.baselines} convergence={props.convergence}
            summary={props.searchSummary} error={props.searchError}
            busy={props.busy} onRun={props.onRun} metric={props.evaluation?.promoted_metric}
          /> : <p className="search-workspace__empty">{t("No classical method is available for this objective yet.")}</p>}
          <section className="search-workspace__planned" aria-labelledby="possible-methods">
            <div className="section-heading"><h2 id="possible-methods">{t("Possible methods")}</h2></div>
            <p>{t("Non-exhaustive examples for future integrations, not a fixed roadmap.")}</p>
            <ol>{possibleMethods.map((name) => <li key={name}>{t(name)}</li>)}</ol>
          </section>
        </>}
      </section>
      <section className="run-workspace__solution">
        <div className="section-heading"><h2>{t("Current solution")}</h2></div>
        <div className="run-workspace__canvas">{props.canvas}</div>
        <div className="run-workspace__verdict"><StatusPanel
          evaluation={props.evaluation} summary={props.verdictSummary} busy={props.busy}
          best={props.best} view={props.view} problem={props.problem}
          showOrientations={props.showOrientations} onToggleOrientations={props.onToggleOrientations}
        /></div>
      </section>
    </div>
  </main>;
}
