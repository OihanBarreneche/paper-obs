import { useEffect, useState } from "react";
import { api } from "../api";
import { useI18n } from "../i18n";
import type { CandidateDoc, ResearchEntryDoc, ResearchSessionDoc, ResearchSessionSummaryDoc } from "../types";

/** How often an open session is read again while an agent may still be writing it. */
const POLL_MS = 5000;
/** The latest journal lines shown before "show the whole journal". */
const JOURNAL_LINES = 12;
/** What a note records, singular and plural, in the order of docs/research-mode.md. */
const STEPS: Record<string, [string, string]> = {
  idea: ["idea", "ideas"], program: ["program", "programs"], search: ["computation", "computations"],
  "dead-end": ["dead end", "dead ends"], check: ["check", "checks"],
};
/** Where a submitted arrangement comes from. */
const METHODS: Record<string, string> = {
  reasoning: "reasoning", composition: "composition", search: "automatic search", refinement: "local refinement",
};

type Submission = Extract<ResearchEntryDoc, { kind: "submission" }>;

/**
 * Every free research session (docs/research-mode.md), read again every few seconds while
 * one is active: an outside agent writes them, the page only follows.
 */
export function useResearchSessions(): ResearchSessionSummaryDoc[] {
  const [sessions, setSessions] = useState<ResearchSessionSummaryDoc[]>([]);
  const active = sessions.some((item) => item.status === "active");
  useEffect(() => {
    let live = true;
    const read = () => api.researchSessions().then((list) => { if (live) setSessions(list); }, () => undefined);
    void read();
    const timer = active ? window.setInterval(read, POLL_MS) : undefined;
    return () => { live = false; window.clearInterval(timer); };
  }, [active]);
  return sessions;
}

type Props = {
  /** Every session; the open problem's are shown one at a time, the others listed to open. */
  sessions: ResearchSessionSummaryDoc[];
  problemId: string | undefined;
  onShow: (candidate: CandidateDoc) => void;
  /** Open a session of another problem: its problem and its best arrangement. */
  onOpen: (sessionId: string) => void;
};

/** The open problem's sessions one at a time (best, progress, journal), or every session. */
export function ResearchSessions({ sessions, problemId, onShow, onOpen }: Props) {
  const { t, number, language } = useI18n();
  const here = sessions.filter((item) => item.problem_id === problemId);
  const [scope, setScope] = useState<"problem" | "all" | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const [session, setSession] = useState<ResearchSessionDoc | null>(null);
  const [whole, setWhole] = useState(false);
  // Without a session of its own, the problem opens on the list of every session.
  const shown = scope ?? (here.length > 0 || sessions.length === 0 ? "problem" : "all");
  const line = shown === "problem" ? here.find((item) => item.session_id === chosen) ?? here[0] : undefined;
  useEffect(() => {
    if (line === undefined) { setSession(null); return; }
    let live = true;
    api.researchSession(line.session_id).then((document) => { if (live) setSession(document); }, () => undefined);
    return () => { live = false; };
  }, [line?.session_id, line?.updated]);

  const date = (iso: string) => new Intl.DateTimeFormat(language === "fr" ? "fr-FR" : "en-GB", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
  const gap = (value: number) => `${value > 0 ? "+" : "−"}${number(Math.abs(value) * 100, 3)} %`;
  const scopes = <div className="run-picker__scope research-sessions__scope" role="tablist" aria-label={t("Sessions to show")}>
    <button type="button" role="tab" aria-selected={shown === "problem"} onClick={() => setScope("problem")}>
      {t("This problem")} <small>{here.length}</small></button>
    <button type="button" role="tab" aria-selected={shown === "all"} onClick={() => setScope("all")}>
      {t("All sessions")} <small>{sessions.length}</small></button>
  </div>;

  if (shown === "all") {
    return <div className="research-sessions">
      {scopes}
      <ul className="research-sessions__list">
        {sessions.map((item) => <li key={item.session_id}>
          <button type="button" onClick={() => {
            setChosen(item.session_id);
            setScope("problem");
            setWhole(false);
            if (item.problem_id !== problemId) onOpen(item.session_id);
          }}>
            <span>{item.name}{item.example && <em className="run-picker__tag">{t("example")}</em>}</span>
            <small>{t(item.problem_name)} · {date(item.created)}
              {item.best?.measure != null && <> · {number(item.best.measure, 6)}</>}
              {item.best?.record_gap != null && <> ({gap(item.best.record_gap)})</>}</small>
          </button>
        </li>)}
      </ul>
    </div>;
  }
  if (line === undefined) {
    return <div className="research-sessions__empty">
      {sessions.length > 0 && scopes}
      <p>{t("No free research session on this problem yet.")}</p>
      <p>{t("An outside agent (Claude Code, Codex, your own scripts) opens one with")} <code>paper-obs research start</code>.
        {" "}{t("It searches as it likes; the engine judges each arrangement it submits and this page follows it.")}
        {" "}{t("The method is in docs/research-mode.md.")}</p>
    </div>;
  }
  const reference = session?.session_id === line.session_id ? session.problem.metadata?.reference as
    { value?: number; unit?: string } | undefined : undefined;
  const best = line.best;
  const journal = session?.session_id === line.session_id ? session.journal : [];
  const hidden = whole ? 0 : Math.max(0, journal.length - JOURNAL_LINES);
  return <div className="research-sessions">
    {scopes}
    {here.length > 1 && <select className="research-sessions__picker" value={line.session_id}
      aria-label={t("Research session")} onChange={(event) => { setChosen(event.target.value); setWhole(false); }}>
      {here.map((item) => <option key={item.session_id} value={item.session_id}>
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
        {best?.record_gap == null ? "—" : gap(best.record_gap)}</dd></div>
    </dl>
    {best && <p className="research-sessions__unit">{t(best.metric.replaceAll("_", " "))}</p>}
    <Track track={line.track} record={reference?.value ?? null} />
    <button type="button" className="research-sessions__show" disabled={!session?.champion}
      onClick={() => session?.champion && onShow(session.champion)}>{t("Show the best arrangement")}</button>
    <HowFound journal={journal} bestIndex={best?.index} />
    <Programs sessionId={line.session_id} journal={journal} />
    <h4>{t("Journal")}</h4>
    {journal.length === 0 && <p className="research-sessions__quiet">{t("Nothing written yet.")}</p>}
    {hidden > 0 && <button type="button" className="search-workspace__how"
      onClick={() => setWhole(true)}>{t("Show the whole journal")} ({journal.length})</button>}
    <ol className="research-sessions__journal">
      {journal.slice(hidden).map((entry, index) =>
        <JournalLine key={`${entry.at}-${hidden + index}`} entry={entry} when={date(entry.at)} />)}
    </ol>
  </div>;
}

/**
 * The submissions that led to the best arrangement, from its starting point: each one's
 * `builds_on` followed back or, when the best names none, every improvement in turn (as in
 * sessions written before submissions named what they build on).
 */
function chainTo(journal: ResearchEntryDoc[], bestIndex: number | undefined): Submission[] {
  const submissions = journal.filter((entry): entry is Submission => entry.kind === "submission");
  const best = submissions.find((entry) => entry.index === bestIndex);
  if (best === undefined) return [];
  if (best.builds_on == null) return submissions.filter((entry) => entry.accepted);
  const chain = [best];
  for (let from: Submission["builds_on"] = best.builds_on; typeof from === "number" && from < chain[0]!.index;) {
    const earlier = submissions.find((entry) => entry.index === from);
    if (earlier === undefined) break;
    chain.unshift(earlier);
    from = earlier.builds_on;
  }
  return chain;
}

/** How the best arrangement was reached, each link labelled with its method, then what the journal records. */
function HowFound({ journal, bestIndex }: { journal: ResearchEntryDoc[]; bestIndex: number | undefined }) {
  const { t, number } = useI18n();
  const chain = chainTo(journal, bestIndex);
  if (chain.length === 0) return null;
  const start = chain[0]!.builds_on;
  const tally = Object.entries(STEPS).map(([step, names]) =>
    [journal.filter((entry) => entry.kind === "note" && entry.step === step).length, names] as const)
    .filter(([count]) => count > 0);
  return <>
    <h4>{t("How this result was found")}</h4>
    <ol className="research-sessions__chain">
      {typeof start === "string" && start && <li className="is-start"><small>{t("starting point")}</small><p>{start}</p></li>}
      {chain.map((entry) => <li key={entry.index}>
        <small>#{entry.index + 1}<MethodTag method={entry.method} /></small>
        <p><strong>{entry.measure == null ? "—" : number(entry.measure, 6)}</strong>{entry.note && <> · {entry.note}</>}</p>
      </li>)}
    </ol>
    {tally.length > 0 && <p className="research-sessions__tally">
      {tally.map(([count, names]) => `${count} ${t(names[count === 1 ? 0 : 1])}`).join(" · ")}</p>}
  </>;
}

/** The programs the agent wrote in work/, with what their notes say; a click reads one's code. */
function Programs({ sessionId, journal }: { sessionId: string; journal: ResearchEntryDoc[] }) {
  const { t } = useI18n();
  const [open, setOpen] = useState<string | null>(null);
  const [code, setCode] = useState<string | null>(null);
  useEffect(() => {
    setCode(null);
    if (open === null) return;
    let live = true;
    api.researchWork(sessionId, open).then((file) => { if (live) setCode(file.text); },
      () => { if (live) setCode(t("This file cannot be read.")); });
    return () => { live = false; };
  }, [sessionId, open]);
  // The latest note on a program describes it; a program a submission names without a note still shows.
  const programs = new Map<string, string>();
  for (const entry of journal) {
    if (entry.kind === "note" && entry.step === "program" && entry.path) programs.set(entry.path, entry.text);
    if (entry.kind === "submission") (entry.programs ?? []).forEach((path) => programs.set(path, programs.get(path) ?? ""));
  }
  if (programs.size === 0) return null;
  return <>
    <h4>{t("Programs written")}</h4>
    <ul className="research-sessions__programs">
      {[...programs].map(([path, text]) => <li key={path}>
        <button type="button" aria-expanded={open === path} onClick={() => setOpen(open === path ? null : path)}>
          <code>{path}</code></button>
        {text && <p>{text}</p>}
        {open === path && <pre className="research-sessions__code">{code ?? "…"}</pre>}
      </li>)}
    </ul>
  </>;
}

function MethodTag({ method }: { method?: string | null }) {
  const { t } = useI18n();
  return method ? <> · <span className={`research-sessions__method is-${method}`}>{t(METHODS[method] ?? method)}</span></> : null;
}

function JournalLine({ entry, when }: { entry: ResearchEntryDoc; when: string }) {
  const { t, number } = useI18n();
  if (entry.kind === "note") {
    const step = entry.step ? STEPS[entry.step] : undefined;
    return <li className={entry.step ? `research-sessions__note is-${entry.step}` : "research-sessions__note"}>
      <small>{when}{step && <> · <span className="research-sessions__step">{t(step[0])}</span></>}
        {entry.path && <> · <code>{entry.path}</code></>}</small>
      <p>{entry.text}</p></li>;
  }
  const verdict = entry.accepted ? t("new best") : entry.valid ? t("not better") : t("invalid");
  return <li className={entry.accepted ? "research-sessions__submission is-best" : "research-sessions__submission"}>
    <small>{when} · #{entry.index + 1}<MethodTag method={entry.method} /></small>
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
