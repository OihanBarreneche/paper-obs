import { useEffect, useState } from "react";
import { api } from "../api";
import { containerNoun, copyNoun } from "../equalCopiesCatalog";
import { useI18n } from "../i18n";
import type { ResearchEntryDoc, ResearchSessionDoc, ResearchSessionSummaryDoc } from "../types";

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

/** Below this relative gap a session only ties the record. */
const TIE = 1e-9;
/** A session whose best beats the published record. */
const beats = (item: ResearchSessionSummaryDoc) => (item.best?.record_gap ?? 0) > TIE;

/**
 * Every free research session (docs/research-mode.md), read again every few seconds while
 * one is active: an outside agent writes them, the page only follows.
 */
export function useResearchSessions(): [ResearchSessionSummaryDoc[], () => void] {
  const [sessions, setSessions] = useState<ResearchSessionSummaryDoc[]>([]);
  const [reads, setReads] = useState(0);
  const active = sessions.some((item) => item.status === "active");
  useEffect(() => {
    let live = true;
    const read = () => api.researchSessions().then((list) => { if (live) setSessions(list); }, () => undefined);
    void read();
    const timer = active ? window.setInterval(read, POLL_MS) : undefined;
    return () => { live = false; window.clearInterval(timer); };
  }, [active, reads]);
  return [sessions, () => setReads((count) => count + 1)];
}

type Props = {
  /** Every session; the open problem's are shown one at a time, the others listed to open. */
  sessions: ResearchSessionSummaryDoc[];
  problemId: string | undefined;
  /** Open a session: its problem, when another one is open, and its best arrangement. */
  onOpen: (sessionId: string) => void;
  /** Read the sessions again, after one was deleted. */
  onChange: () => void;
};

/** The open problem's sessions one at a time (best, progress, journal), or every session. */
export function ResearchSessions({ sessions, problemId, onOpen, onChange }: Props) {
  const { t, number, language } = useI18n();
  const here = sessions.filter((item) => item.problem_id === problemId);
  const [scope, setScope] = useState<"problem" | "all" | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const [session, setSession] = useState<ResearchSessionDoc | null>(null);
  const [whole, setWhole] = useState(false);
  const [deleting, setDeleting] = useState<"confirm" | "failed" | null>(null);
  // The list of every session: which row asks to confirm a deletion, and its filters.
  const [confirming, setConfirming] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [order, setOrder] = useState<"recent" | "gain">("recent");
  const [shapeFilter, setShapeFilter] = useState("");
  const [containerFilter, setContainerFilter] = useState("");
  const [batchSelection, setBatchSelection] = useState<string[]>([]);
  const [batchBusy, setBatchBusy] = useState(false);
  const [batchError, setBatchError] = useState("");
  const downloadBatch = async () => {
    setBatchBusy(true); setBatchError("");
    try {
      const valid = batchSelection.filter((id) => sessions.some((item) => item.session_id === id && item.submission_prepared));
      const blob = await api.researchSubmissionBatch(valid);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a"); link.href = url; link.download = "packing-submissions.zip";
      link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { setBatchError(error instanceof Error ? error.message : String(error)); }
    finally { setBatchBusy(false); }
  };
  // The tab opens on the problem, so a problem without a session shows how to start one.
  const shown = scope ?? "problem";
  const line = shown === "problem" ? here.find((item) => item.session_id === chosen) ?? here[0] : undefined;
  useEffect(() => {
    if (line === undefined) { setSession(null); return; }
    let live = true;
    api.researchSession(line.session_id).then((document) => { if (live) setSession(document); }, () => undefined);
    return () => { live = false; };
  }, [line?.session_id, line?.updated]);

  const date = (iso: string) => new Intl.DateTimeFormat(language === "fr" ? "fr-FR" : "en-GB", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
  const remove = (sessionId: string) => api.deleteResearchSession(sessionId).then(() => {
    setConfirming(null);
    if (chosen === sessionId) setChosen(null);
    onChange();
  }, () => setFailed(sessionId));
  const scopes = <div className="run-picker__scope research-sessions__scope" role="tablist" aria-label={t("Sessions to show")}>
    <button type="button" role="tab" aria-selected={shown === "problem"} onClick={() => setScope("problem")}>
      {t("This problem")} <small>{here.length}</small></button>
    <button type="button" role="tab" aria-selected={shown === "all"} onClick={() => setScope("all")}>
      {t("All sessions")} <small>{sessions.length}</small></button>
  </div>;

  if (shown === "all") {
    const values = (key: "shape" | "container") =>
      [...new Set(sessions.map((item) => item[key]).filter((value): value is string => value !== null))].sort();
    const shapes = values("shape"), containers = values("container");
    const listed = sessions
      .filter((item) => (shapeFilter === "" || item.shape === shapeFilter)
        && (containerFilter === "" || item.container === containerFilter))
      .sort((a, b) => order === "gain"
        ? (b.best?.record_gap ?? -Infinity) - (a.best?.record_gap ?? -Infinity)
        : b.created.localeCompare(a.created));
    return <div className="research-sessions">
      {scopes}
      <p className="research-sessions__quiet">{t("Session gains use the reference saved during the search. Submission dossiers are checked against the current catalog.")}</p>
      <p>{t("Prepared dossiers keep coordinates and checks locally. The batch contains replacement images, values and an email draft.")}</p>
      <button type="button" disabled={batchBusy || !batchSelection.some((id) => sessions.some((item) => item.session_id === id && item.submission_prepared))}
        onClick={() => void downloadBatch()}>{t(batchBusy ? "Preparing batch…" : "Download selected submissions")}</button>
      {batchError && <p role="alert">{batchError}</p>}
      <div className="research-sessions__tools">
        <label>{t("Sort")}<select value={order} onChange={(event) => setOrder(event.target.value as "recent" | "gain")}>
          <option value="recent">{t("Most recent")}</option>
          <option value="gain">{t("Largest improvement")}</option>
        </select></label>
        <label>{t("Shape")}<select value={shapeFilter} onChange={(event) => setShapeFilter(event.target.value)}>
          <option value="">{t("All")}</option>
          {shapes.map((shape) => <option key={shape} value={shape}>{t(copyNoun(shape, 2))}</option>)}
        </select></label>
        <label>{t("Container")}<select value={containerFilter} onChange={(event) => setContainerFilter(event.target.value)}>
          <option value="">{t("All")}</option>
          {containers.map((container) => <option key={container} value={container}>{t(containerNoun(container))}</option>)}
        </select></label>
      </div>
      {listed.length === 0 && <p className="research-sessions__quiet">{t("No session matches these filters.")}</p>}
      <ul className="research-sessions__list">
        {listed.map((item) => <li key={item.session_id} className={beats(item) ? "is-record" : undefined}>
          {item.submission_prepared && <input type="checkbox" aria-label={`${t("Include in submission batch")}: ${item.name}`}
            checked={batchSelection.includes(item.session_id)} onChange={(event) => setBatchSelection((selected) =>
              event.target.checked ? [...selected, item.session_id] : selected.filter((id) => id !== item.session_id))} />}
          <button type="button" className="research-sessions__open" onClick={() => {
            setChosen(item.session_id);
            setScope("problem");
            setWhole(false);
            onOpen(item.session_id);
          }}>
            <span>{item.name}{item.example && <em className="run-picker__tag">{t("example")}</em>}</span>
            <small>{t(item.problem_name)} · {date(item.created)}
              {item.best?.measure != null && <> · {number(item.best.measure, 6)}</>}</small>
            <Verdict gap={item.best?.record_gap ?? null} />
            {failed === item.session_id && <small className="research-sessions__violation">{t("The session could not be deleted.")}</small>}
          </button>
          {confirming === item.session_id
            ? <span className="run-picker__confirm">
                <button type="button" onClick={() => setConfirming(null)}>{t("Cancel")}</button>
                <button type="button" className="run-picker__delete" onClick={() => void remove(item.session_id)}>{t("Delete")}</button>
              </span>
            : <button type="button" className="run-picker__icon" title={t("Delete session")}
                aria-label={`${t("Delete session")}: ${item.name}`} onClick={() => { setFailed(null); setConfirming(item.session_id); }}>
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3m-9 0 1 13h10l1-13M10 11v6m4-6v6" /></svg>
              </button>}
        </li>)}
      </ul>
    </div>;
  }
  if (line === undefined) {
    return <div className="research-sessions__empty">
      {scopes}
      <p>{t("No free research session on this problem yet.")}</p>
      <p>{t("To start one, open this project in an agent such as Claude Code or Codex and ask it for a free research, on this problem or any other. The agent proposes how much of the processor to use, then searches as it likes: the engine judges every arrangement it submits, and this page follows its ideas, computations, dead ends and records live.")}
        {" "}{t("The method is in docs/research-mode.md.")}</p>
    </div>;
  }
  const reference = session?.session_id === line.session_id ? session.problem.metadata?.reference as
    { value?: number; unit?: string; verified_on?: string } | undefined : undefined;
  const best = line.best;
  const journal = session?.session_id === line.session_id ? session.journal : [];
  const hidden = whole ? 0 : Math.max(0, journal.length - JOURNAL_LINES);
  return <div className="research-sessions">
    {scopes}
    {here.length > 1 && <select className="research-sessions__picker" value={line.session_id}
      aria-label={t("Research session")} onChange={(event) => {
        setChosen(event.target.value);
        setWhole(false);
        onOpen(event.target.value);
      }}>
      {here.map((item) => <option key={item.session_id} value={item.session_id}>
        {item.name} · {date(item.created)}</option>)}
    </select>}
    <header className="research-sessions__head">
      <h3>{line.name}{line.example && <em className="run-picker__tag">{t("example")}</em>}</h3>
      <p>{line.agent || t("unnamed agent")} · <span className={`research-sessions__status is-${line.status}`}>{t(line.status)}</span>
        {" "}· {line.submissions} {t(line.submissions === 1 ? "submission" : "submissions")}</p>
      {session?.goal && <p className="research-sessions__goal">{session.goal}</p>}
      {line.submission_prepared && <p>{t("Submission dossier ready. Select it in All sessions to download a batch.")}</p>}
      {deleting === "confirm"
        ? <span className="run-picker__confirm research-sessions__delete">
            <button type="button" onClick={() => setDeleting(null)}>{t("Cancel")}</button>
            <button type="button" className="run-picker__delete" onClick={() => {
              setDeleting(null);
              api.deleteResearchSession(line.session_id).then(() => { setChosen(null); onChange(); },
                () => setDeleting("failed"));
            }}>{t("Delete")}</button>
          </span>
        : <button type="button" className="run-picker__icon research-sessions__delete" title={t("Delete session")}
            aria-label={`${t("Delete session")}: ${line.name}`} onClick={() => setDeleting("confirm")}>
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3m-9 0 1 13h10l1-13M10 11v6m4-6v6" /></svg>
          </button>}
      {deleting === "failed" && <p className="research-sessions__violation">{t("The session could not be deleted.")}</p>}
    </header>
    <dl className="research-sessions__figures">
      <div><dt>{t("Session best")}</dt><dd>{best?.measure == null ? "—" : number(best.measure, 6)}</dd></div>
      <div><dt>{t("Published record")}</dt><dd>{reference?.value == null ? "—" : number(reference.value, 6)}</dd></div>
      <div><dt>{t("Against the record")}</dt><dd>{best?.record_gap == null ? "—" : <Verdict gap={best.record_gap} />}</dd></div>
    </dl>
    <p className="research-sessions__quiet">{t("Session gains use the reference saved during the search. Submission dossiers are checked against the current catalog.")}
      {reference?.verified_on && <> {t("Source checked")}: {reference.verified_on}.</>}</p>
    {best && <p className="research-sessions__unit">{t(best.metric.replaceAll("_", " "))}</p>}
    <Track track={line.track} record={reference?.value ?? null} />
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

/** Whether a session beats the published record, ties it or stays short of it, at a glance. */
function Verdict({ gap }: { gap: number | null }) {
  const { t, number } = useI18n();
  if (gap === null) return null;
  const size = `${number(Math.abs(gap) * 100, 3)} %`;
  if (gap > TIE) return <span className="research-sessions__verdict is-record">
    <span aria-hidden="true">✓</span> {t("Record beaten by {size}").replace("{size}", size)}</span>;
  if (gap >= -TIE) return <span className="research-sessions__verdict is-tie">{t("Ties the record")}</span>;
  return <span className="research-sessions__verdict is-short">{t("{size} short of the record").replace("{size}", size)}</span>;
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
  const kind = entry.accepted ? "is-best" : entry.valid ? "is-worse" : "is-invalid";
  const verdict = entry.accepted ? <><span aria-hidden="true">✓</span> {t("new best")}</>
    : entry.valid ? t("not better") : <><span aria-hidden="true">✗</span> {t("invalid")}</>;
  return <li className={`research-sessions__submission ${kind}`}>
    <small>{when} · #{entry.index + 1}<MethodTag method={entry.method} /></small>
    <p><span className={`research-sessions__outcome ${kind}`}>{verdict}</span>{" "}
      <strong>{entry.measure == null ? "—" : number(entry.measure, 6)}</strong>
      {entry.note && <> · {entry.note}</>}</p>
    {!entry.valid && entry.violations.length > 0 && <p className="research-sessions__violation">{entry.violations[0]}</p>}
  </li>;
}

/** The chart's frame, in its own units: the plot sits inside, leaving room for the axis labels. */
const TRACK = { width: 340, height: 150, left: 62, right: 12, top: 12, bottom: 30 };

/**
 * Each new best of the session as a step, against the published record drawn dashed: the
 * vertical axis is the session's measure, with the first and last best and the record marked,
 * and the horizontal axis numbers the submissions.
 */
function Track({ track, record }: { track: ResearchSessionSummaryDoc["track"]; record: number | null }) {
  const { t, number } = useI18n();
  const points = track.filter((item): item is [number, number, number | null] => item[1] !== null);
  if (points.length < 2) return null;
  const values = [...points.map((item) => item[1]), ...(record === null ? [] : [record])];
  const low = Math.min(...values), high = Math.max(...values), span = high - low || 1;
  const first = points[0]![0], last = Math.max(points[points.length - 1]![0], first + 1);
  const right = TRACK.width - TRACK.right, bottom = TRACK.height - TRACK.bottom;
  const x = (index: number) => TRACK.left + (index - first) / (last - first) * (right - TRACK.left);
  const y = (value: number) => TRACK.top + (high - value) / span * (bottom - TRACK.top);
  const path = points.map(([index, value], at) => at === 0 ? `M${x(index)},${y(value)}`
    : `H${x(index)}V${y(value)}`).join("") + `H${right}`;
  // The values worth reading on the axis: where the session ended, the record, and where it
  // started, each dropped when it would print over one before it.
  const marks = [points[points.length - 1]![1], ...(record === null ? [] : [record]), points[0]![1]]
    .filter((value, at, all) => all.findIndex((other) => Math.abs(y(other) - y(value)) < 14) === at);
  return <figure className="research-sessions__track">
    <figcaption>{t("Progress of the session's best")}</figcaption>
    <svg viewBox={`0 0 ${TRACK.width} ${TRACK.height}`} role="img"
      aria-label={t("Each new best of the session, against the published record")}>
      <line className="research-sessions__axis" x1={TRACK.left} x2={TRACK.left} y1={TRACK.top} y2={bottom} />
      <line className="research-sessions__axis" x1={TRACK.left} x2={right} y1={bottom} y2={bottom} />
      {marks.map((value) => <g key={value}>
        <line className="research-sessions__tick" x1={TRACK.left - 4} x2={TRACK.left} y1={y(value)} y2={y(value)} />
        <text x={TRACK.left - 7} y={y(value) + 3.5} textAnchor="end">{number(value, 5)}</text>
      </g>)}
      {[first, last].map((index) => <text key={index} x={x(index)} y={bottom + 14} textAnchor="middle">{index + 1}</text>)}
      <text x={(TRACK.left + right) / 2} y={TRACK.height - 2} textAnchor="middle">{t("submission")}</text>
      {record !== null && <>
        <line className="research-sessions__record" x1={TRACK.left} x2={right} y1={y(record)} y2={y(record)} />
        <text className="research-sessions__record-label" x={right} y={y(record) - 4} textAnchor="end">{t("published record")}</text>
      </>}
      <path d={path} />
      {points.map(([index, value]) => <circle key={index} cx={x(index)} cy={y(value)} r="2.6" />)}
    </svg>
  </figure>;
}
