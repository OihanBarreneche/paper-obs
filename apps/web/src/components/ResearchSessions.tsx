import { useEffect, useState } from "react";
import { api } from "../api";
import { useI18n } from "../i18n";
import type { CandidateDoc, ResearchEntryDoc, ResearchSessionDoc, ResearchSessionSummaryDoc } from "../types";

/** How often an open session is read again while an agent may still be writing it. */
const POLL_MS = 5000;
/** Journal lines shown before "show the whole journal". */
const JOURNAL_LINES = 12;

/**
 * The free research sessions of one problem (docs/research-mode.md), read again every few
 * seconds while one is active: an outside agent writes them, the page only follows.
 */
export function useResearchSessions(problemId: string | undefined): ResearchSessionSummaryDoc[] {
  const [sessions, setSessions] = useState<ResearchSessionSummaryDoc[]>([]);
  const active = sessions.some((item) => item.status === "active");
  useEffect(() => {
    if (!problemId) { setSessions([]); return; }
    let live = true;
    const read = () => api.researchSessions(problemId).then((list) => { if (live) setSessions(list); }, () => undefined);
    void read();
    const timer = active ? window.setInterval(read, POLL_MS) : undefined;
    return () => { live = false; window.clearInterval(timer); };
  }, [problemId, active]);
  return sessions;
}

type Props = {
  sessions: ResearchSessionSummaryDoc[];
  onShow: (candidate: CandidateDoc) => void;
};

/** One session at a time: its best against the record, its progress, and its journal. */
export function ResearchSessions({ sessions, onShow }: Props) {
  const { t, number, language } = useI18n();
  const [chosen, setChosen] = useState<string | null>(null);
  const [session, setSession] = useState<ResearchSessionDoc | null>(null);
  const [whole, setWhole] = useState(false);
  const line = sessions.find((item) => item.session_id === chosen) ?? sessions[0];
  useEffect(() => {
    if (line === undefined) { setSession(null); return; }
    let live = true;
    api.researchSession(line.session_id).then((document) => { if (live) setSession(document); }, () => undefined);
    return () => { live = false; };
  }, [line?.session_id, line?.updated]);

  if (line === undefined) {
    return <div className="research-sessions__empty">
      <p>{t("No free research session on this problem yet.")}</p>
      <p>{t("An outside agent (Claude Code, Codex, your own scripts) opens one with")} <code>paper-obs research start</code>.
        {" "}{t("It searches as it likes; the engine judges each arrangement it submits and this page follows it.")}
        {" "}{t("The method is in docs/research-mode.md.")}</p>
    </div>;
  }
  const date = (iso: string) => new Intl.DateTimeFormat(language === "fr" ? "fr-FR" : "en-GB", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
  const reference = session?.session_id === line.session_id ? session.problem.metadata?.reference as
    { value?: number; unit?: string } | undefined : undefined;
  const best = line.best;
  const journal = session?.session_id === line.session_id ? [...session.journal].reverse() : [];
  return <div className="research-sessions">
    {sessions.length > 1 && <select className="research-sessions__picker" value={line.session_id}
      aria-label={t("Research session")} onChange={(event) => { setChosen(event.target.value); setWhole(false); }}>
      {sessions.map((item) => <option key={item.session_id} value={item.session_id}>
        {item.name} · {date(item.created)}</option>)}
    </select>}
    <header className="research-sessions__head">
      <h3>{line.name}{line.example && <em className="run-picker__tag">{t("example")}</em>}</h3>
      <p>{line.agent || t("unnamed agent")} · <span className={`research-sessions__status is-${line.status}`}>{t(line.status)}</span>
        {" "}· {line.submissions} {t(line.submissions === 1 ? "submission" : "submissions")}</p>
      {session?.goal && <p className="research-sessions__goal">{session.goal}</p>}
    </header>
    <dl className="research-sessions__figures">
      <div><dt>{t("Session best")}</dt><dd>{best?.measure == null ? "—" : number(best.measure, 6)}</dd></div>
      <div><dt>{t("Published record")}</dt><dd>{reference?.value == null ? "—" : number(reference.value, 6)}</dd></div>
      <div><dt>{t("Gap")}</dt><dd className={best?.record_gap != null && best.record_gap > 0 ? "is-beaten" : ""}>
        {best?.record_gap == null ? "—" : `${best.record_gap > 0 ? "+" : "−"}${number(Math.abs(best.record_gap) * 100, 3)} %`}</dd></div>
    </dl>
    {best && <p className="research-sessions__unit">{t(best.metric.replaceAll("_", " "))}</p>}
    <Track track={line.track} record={reference?.value ?? null} />
    <button type="button" className="research-sessions__show" disabled={!session?.champion}
      onClick={() => session?.champion && onShow(session.champion)}>{t("Show the best arrangement")}</button>
    <h4>{t("Journal")}</h4>
    {journal.length === 0 && <p className="research-sessions__quiet">{t("Nothing written yet.")}</p>}
    <ol className="research-sessions__journal">
      {(whole ? journal : journal.slice(0, JOURNAL_LINES)).map((entry, index) =>
        <JournalLine key={`${entry.at}-${index}`} entry={entry} when={date(entry.at)} />)}
    </ol>
    {!whole && journal.length > JOURNAL_LINES && <button type="button" className="search-workspace__how"
      onClick={() => setWhole(true)}>{t("Show the whole journal")} ({journal.length})</button>}
  </div>;
}

function JournalLine({ entry, when }: { entry: ResearchEntryDoc; when: string }) {
  const { t, number } = useI18n();
  if (entry.kind === "note") {
    return <li className="research-sessions__note"><small>{when}</small><p>{entry.text}</p></li>;
  }
  const verdict = entry.accepted ? t("new best") : entry.valid ? t("not better") : t("invalid");
  return <li className={entry.accepted ? "research-sessions__submission is-best" : "research-sessions__submission"}>
    <small>{when} · #{entry.index + 1}</small>
    <p><strong>{entry.measure == null ? "—" : number(entry.measure, 6)}</strong> · {verdict}
      {entry.note && <> · {entry.note}</>}</p>
    {!entry.valid && entry.violations.length > 0 && <p className="research-sessions__violation">{entry.violations[0]}</p>}
  </li>;
}

/** Each new best of the session as a step, against the published record drawn dashed. */
function Track({ track, record }: { track: ResearchSessionSummaryDoc["track"]; record: number | null }) {
  const { t } = useI18n();
  const points = track.filter((item): item is [number, number, number | null] => item[1] !== null);
  if (points.length < 2) return null;
  const values = [...points.map((item) => item[1]), ...(record === null ? [] : [record])];
  const low = Math.min(...values), high = Math.max(...values), span = high - low || 1;
  const last = points[points.length - 1]![0] || 1;
  const x = (index: number) => 4 + index / last * 292;
  const y = (value: number) => 8 + (high - value) / span * 64;
  const path = points.map(([index, value], at) => at === 0 ? `M${x(index)},${y(value)}`
    : `H${x(index)}V${y(value)}`).join("");
  return <svg className="research-sessions__track" viewBox="0 0 300 80" role="img"
    aria-label={t("Each new best of the session, against the published record")}>
    {record !== null && <line x1="0" x2="300" y1={y(record)} y2={y(record)} className="research-sessions__record" />}
    <path d={path} />
    {points.map(([index, value]) => <circle key={index} cx={x(index)} cy={y(value)} r="2.4" />)}
  </svg>;
}
