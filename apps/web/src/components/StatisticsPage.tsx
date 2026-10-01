import { useEffect, useMemo, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { useI18n } from "../i18n";
import type { AgentRunSummaryDoc, WorkflowManifestDoc } from "../types";
import { elapsed } from "./RunWorkspace";
import { useWidth } from "./useWidth";

/** One colour per workflow, in the order the manifests list them. */
const COLOURS = ["#7c5aa6", "#c9748f", "#3f8a9e", "#c29a4a", "#5f9468", "#9a6f55"];
/** Colours for the parts of a share that are not workflows: models, problems. */
const PARTS = ["#5b6fb3", "#c29a4a", "#3f8a9e", "#c9748f", "#5f9468", "#9a6f55", "#7c5aa6"];
/** The periods offered, in days; zero is the whole history. */
const PERIODS = [7, 30, 0];
/** How a count of runs in each status reads. */
const STATUSES: Record<string, string> = { done: "completed", stopped: "interrupted", failed: "unsuccessful", running: "in progress" };
/** Rows of the run list shown folded, then on each page once it is unfolded. */
const FIRST = 8;
const PAGE = 20;
/** Parts a share names before it gathers the rest as "others". */
const SHARE_PARTS = 6;

type Filters = { model: string; workflow: string; problem: string; status: string };
const NONE: Filters = { model: "", workflow: "", problem: "", status: "" };
type Run = AgentRunSummaryDoc;

const sum = (values: number[]) => values.reduce((total, value) => total + value, 0);
const mean = (values: number[]) => values.length === 0 ? null : sum(values) / values.length;
const day = (run: Run) => run.created.slice(0, 10);
const tokens = (run: Run) => run.spend.tokens_in + run.spend.tokens_out;
const modelOf = (run: Run) => run.model ? `${run.provider} · ${run.model}` : "—";
/** The turn a run reached its best on, counted from one; null before any valid best. */
const bestTurn = (run: Run) => { const last = run.track[run.track.length - 1]; return last ? last[0] + 1 : null; };

/** The runs as rows of a spreadsheet: every figure the listing holds, in machine-readable form. */
function csv(runs: Run[]): string {
  const head = ["run_id", "created", "name", "workflow", "problem_id", "provider", "model", "status", "turns",
    "llm_calls", "tool_calls", "tokens_in", "tokens_cached", "tokens_out", "cost", "seconds", "model_seconds",
    "best_primary", "best_measure", "record_gap", "best_turn", "deleted"];
  const cell = (value: unknown) => {
    const text = value == null ? "" : String(value);
    return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  return [head, ...runs.map((run) => [run.run_id, run.created, run.name, run.workflow, run.problem_id, run.provider,
    run.model, run.status, run.round, run.spend.llm_calls, run.spend.tool_calls, run.spend.tokens_in,
    run.spend.tokens_cached, run.spend.tokens_out, run.spend.cost, run.seconds, run.spend.model_seconds,
    run.champion?.primary, run.champion?.measure, run.record_gap, bestTurn(run), run.deleted])].map((row) => row.map(cell).join(",")).join("\n") + "\n";
}

/** Formatting shared by every part of the page. */
function useFormat() {
  const { t, number, language } = useI18n();
  return {
    t, number,
    money: (value: number) => `${number(value, value < 0.1 ? 3 : 2)} $`,
    gap: (value: number | null, digits = 2) => value == null ? "—"
      : `${value > 0 ? "+" : value < 0 ? "−" : ""}${number(Math.abs(value) * 100, digits)} %`,
    count: (value: number) => value >= 1e6 ? `${number(value / 1e6, 1)} M` : value >= 1e4 ? `${number(value / 1e3, 0)} k` : number(value, 0),
    date: (iso: string) => new Intl.DateTimeFormat(language, { day: "numeric", month: "short", timeZone: "UTC" }).format(new Date(`${iso}T00:00:00Z`)),
  };
}

/** A section of the page: a title that folds it, a line that says what it shows, then its content. */
function Section({ title, note, open = true, children }: { title: string; note?: string; open?: boolean; children: ReactNode }) {
  return <details className="stats__section" open={open}>
    <summary><h2>{title}</h2></summary>
    {note && <p>{note}</p>}
    {children}
  </details>;
}

export function StatisticsPage({ runs, workflows, onClose, onOpen, onDownload }: {
  runs: Run[];
  workflows: WorkflowManifestDoc[];
  onClose: () => void;
  onOpen: (runId: string) => void;
  onDownload: (name: string, content: string, type: string) => void;
}) {
  const { t, money, gap, count } = useFormat();
  const [period, setPeriod] = useState(0);
  const [filters, setFilters] = useState<Filters>(NONE);
  const [filtering, setFiltering] = useState(false);
  /** The problems compared, newest pick first; until a pick, the problem of the latest run. */
  const [picked, setPicked] = useState<string[] | null>(null);
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [onClose]);

  const order = (id: string) => { const index = workflows.findIndex((item) => item.id === id); return index < 0 ? workflows.length : index; };
  const colour = (id: string) => COLOURS[order(id) % COLOURS.length] ?? "#888";
  const workflowName = (id: string) => t(workflows.find((item) => item.id === id)?.name ?? id);
  const choices = (of: (run: Run) => string) => [...new Set(runs.map(of))].sort();
  const since = period ? new Date(Date.now() - period * 864e5).toISOString() : "";
  const shown = useMemo(() => runs.filter((run) => run.created >= since
    && (!filters.model || modelOf(run) === filters.model) && (!filters.workflow || run.workflow === filters.workflow)
    && (!filters.problem || run.problem_id === filters.problem) && (!filters.status || run.status === filters.status)),
  [runs, since, filters]);
  const active = Object.values(filters).filter(Boolean).length;

  const priced = shown.filter((run) => run.spend.cost != null);
  const tokensIn = sum(shown.map((run) => run.spend.tokens_in));
  const cached = sum(shown.map((run) => run.spend.tokens_cached ?? 0));
  const compared = shown.filter((run) => run.record_gap != null);
  const closest = compared.reduce<Run | null>((best, run) => best === null || (run.record_gap ?? 0) > (best.record_gap ?? 0) ? run : best, null);
  const beaten = compared.filter((run) => (run.record_gap ?? 0) > 0).length;
  const statuses = choices((run) => run.status).map((status) => [status, shown.filter((run) => run.status === status).length] as const)
    .filter(([, n]) => n > 0).map(([status, n]) => `${n} ${t(STATUSES[status] ?? status)}`).join(" · ");
  const problems = [...new Set(shown.map((run) => run.problem_id))]
    .map((id) => shown.filter((run) => run.problem_id === id))
    .sort((a, b) => t(a[0]?.problem_name ?? "").localeCompare(t(b[0]?.problem_name ?? "")));
  const present = [...new Set(shown.map((run) => run.workflow))].sort((a, b) => order(a) - order(b));
  const groups = new Map(problems.map((group) => [group[0]?.problem_id ?? "", group]));
  const latest = shown.reduce<Run | null>((last, run) => last === null || run.created > last.created ? run : last, null);
  const chosen = (picked ?? (latest ? [latest.problem_id] : [])).filter((id) => groups.has(id));
  const toggle = (id: string) => setPicked(chosen.includes(id) ? chosen.filter((item) => item !== id) : [id, ...chosen]);

  const select = (key: keyof Filters, all: string, options: [string, string][]) =>
    <select className="select" value={filters[key]} onChange={(event) => setFilters({ ...filters, [key]: event.target.value })}>
      <option value="">{t(all)}</option>
      {options.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
    </select>;

  const legend = <ul className="stats__legend">{present.map((id) =>
    <li key={id}><i style={{ background: colour(id) }} />{workflowName(id)}</li>)}</ul>;

  return createPortal(<div className="stats" role="dialog" aria-modal="true" aria-label={t("Statistics")}>
    <div className="stats__bar">
      <button type="button" className="stats__back" onClick={onClose}>← {t("Back to the lab")}</button>
      <div className="stats__tools">
        <div className="stats__segments" role="group" aria-label={t("Period")}>{PERIODS.map((days) =>
          <button key={days} type="button" aria-pressed={period === days} onClick={() => setPeriod(days)}>
            {days ? `${days} ${t("days")}` : t("All")}</button>)}</div>
        <button type="button" className="stats__tool" aria-expanded={filtering} onClick={() => setFiltering(!filtering)}>
          {t("Filters")}{active > 0 && <b>{active}</b>}</button>
        <button type="button" className="stats__tool" disabled={shown.length === 0} title={t("Export the runs shown as CSV")}
          onClick={() => onDownload(`paper-obs-runs-${new Date().toISOString().slice(0, 10)}.csv`, csv(shown), "text/csv")}>⤓ CSV</button>
      </div>
    </div>
    <main className="stats__page">
      <h1>{t("Statistics")}</h1>
      {filtering && <div className="stats__filters">
        {select("workflow", "All workflows", choices((run) => run.workflow).map((id) => [id, workflowName(id)]))}
        {select("problem", "All problems", choices((run) => run.problem_id).map((id) =>
          [id, t(runs.find((run) => run.problem_id === id)?.problem_name ?? id)]))}
        {select("model", "All models", choices(modelOf).map((item) => [item, item]))}
        {select("status", "All statuses", choices((run) => run.status).map((item) => [item, t(item)]))}
        {active > 0 && <button type="button" className="stats__reset" onClick={() => setFilters(NONE)}>{t("Reset")}</button>}
      </div>}

      {shown.length === 0 ? <p className="stats__empty">{t(runs.length ? "No run matches these filters." : "No run yet.")}</p> : <>
        <section className="stats__figures">
          <div><span>{t("Closest to the record")}</span>
            <strong className={closest && (closest.record_gap ?? 0) > 0 ? "is-ahead" : undefined}>{gap(closest?.record_gap ?? null)}</strong>
            <small>{closest === null ? t("no comparable record") : <>
              <button type="button" className="stats__link" disabled={closest.deleted} onClick={() => onOpen(closest.run_id)}>
                {closest.name ?? closest.run_id}</button> · {t(closest.problem_name)}
              {beaten > 0 && <> · <b className="stats__ahead">{beaten} {t(beaten > 1 ? "records beaten" : "record beaten")}</b></>}
              <br />{t("mean")} {gap(mean(compared.map((run) => run.record_gap ?? 0)))} {t("over")} {compared.length} {t("comparable runs")}</>}</small></div>
          <div><span>{t("Estimated spend")}</span><strong>{priced.length ? money(sum(priced.map((run) => run.spend.cost ?? 0))) : "—"}</strong>
            <small>{count(tokensIn + sum(shown.map((run) => run.spend.tokens_out)))} {t("tokens")}
              {tokensIn > 0 && ` · ${Math.round((cached / tokensIn) * 100)} % ${t("from the cache")}`}
              {priced.length < shown.length && ` · ${shown.length - priced.length} ${t("without prices")}`}</small></div>
          <div><span>{t("Runs")}</span><strong>{shown.length}</strong>
            <small>{statuses} · {elapsed(sum(shown.map((run) => run.seconds)), t)}</small></div>
        </section>

        <Section title={t("Every run")} note={t("The closest to the record come first; sort by any column, and open a run by clicking it.")}>
          <RunFeed runs={shown} colour={colour} workflowName={workflowName} onOpen={onOpen} />
        </Section>

        <Section title={t("Compare the workflows")}
          note={t("Pick the problems to compare, with their number of runs. The dot is each workflow's best run on the problem, the band spans all its runs; the tick is the published record.")}>
          <div className="stats__chips" role="group" aria-label={t("Problems to compare")}>{problems.map((group) => {
            const id = group[0]?.problem_id ?? "";
            return <button key={id} type="button" aria-pressed={chosen.includes(id)} onClick={() => toggle(id)}
              title={`${group.length} ${t(group.length > 1 ? "runs" : "run")}`}>{t(group[0]?.problem_name ?? id)}<small>{group.length}</small></button>;
          })}</div>
          <div className="stats__problems">{chosen.map((id) =>
            <ProblemCard key={id} runs={groups.get(id) ?? []} workflows={present} colour={colour} workflowName={workflowName}
              onClose={() => toggle(id)} />)}
          </div>
        </Section>

        <Section title={t("Cost and result")}
          note={t("Each point is a run: the higher, the closer to the record; the further left, the less it cost.")}>
          {legend}
          <Scatter runs={shown} colour={colour} workflowName={workflowName} />
        </Section>

        <Section title={t("What the runs used")}>
          <Shares runs={shown} colour={colour} workflowName={workflowName} order={order} />
        </Section>

        <Section title={t("Spending over time")}>
          {legend}
          <Days runs={shown} colour={colour} workflowName={workflowName} order={present} />
        </Section>

        <details className="stats__about">
          <summary>{t("How these figures are computed")}</summary>
          <p>{t("A gap is measured on a run's best valid arrangement, in the record's own unit, and is positive when it beats the published record. Costs are estimates at the prices entered for each run; runs without prices are left out of them.")}</p>
          <p>{t("Deleted runs still count here: they wait in the trash of the run list, where they can be restored.")}</p>
        </details>
      </>}
    </main>
  </div>, document.body);
}

/** A workflow's name is "W1 · Basic agent loop": its code, then what it is. */
const code = (name: string) => name.split(" · ")[0] ?? name;
const rest = (name: string) => name.split(" · ").slice(1).join(" · ");

type SortKey = "name" | "workflow" | "model" | "gap" | "turns" | "seconds" | "tokens" | "cost" | "created";
/** What each column sorts by, and the order a first click asks for. */
const SORTS: Record<SortKey, { of: (run: Run) => number | string | null; first: 1 | -1 }> = {
  name: { of: (run) => run.name ?? run.run_id, first: 1 },
  workflow: { of: (run) => run.workflow, first: 1 },
  model: { of: (run) => run.model || null, first: 1 },
  gap: { of: (run) => run.record_gap, first: -1 },
  turns: { of: (run) => run.round, first: -1 },
  seconds: { of: (run) => run.seconds, first: -1 },
  tokens: { of: tokens, first: -1 },
  cost: { of: (run) => run.spend.cost ?? null, first: -1 },
  created: { of: (run) => run.created, first: -1 },
};

/** Every run as a row, sorted by any column, the closest to the record first. */
function RunFeed({ runs, colour, workflowName, onOpen }: {
  runs: Run[];
  colour: (workflow: string) => string;
  workflowName: (workflow: string) => string;
  onOpen: (runId: string) => void;
}) {
  const { t, money, gap, count, date } = useFormat();
  const [sort, setSort] = useState<{ key: SortKey; direction: 1 | -1 }>({ key: "gap", direction: -1 });
  /** The page shown once the list is unfolded; null while it shows its first rows only. */
  const [page, setPage] = useState<number | null>(null);
  const sorted = useMemo(() => {
    const of = SORTS[sort.key].of;
    // A run without the figure goes last whichever way the column is read.
    return [...runs].sort((a, b) => {
      const x = of(a), y = of(b);
      if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1;
      return (typeof x === "string" ? x.localeCompare(String(y)) : x - Number(y)) * sort.direction;
    });
  }, [runs, sort]);
  const pages = Math.max(1, Math.ceil(sorted.length / PAGE));
  const current = page === null ? null : Math.min(page, pages - 1);
  const rows = current === null ? sorted.slice(0, FIRST) : sorted.slice(current * PAGE, (current + 1) * PAGE);
  const head = (key: SortKey, label: string) => <th aria-sort={sort.key === key ? (sort.direction > 0 ? "ascending" : "descending") : undefined}>
    <button type="button" onClick={() => { setSort(sort.key === key ? { key, direction: sort.direction === 1 ? -1 : 1 } : { key, direction: SORTS[key].first }); setPage(current === null ? null : 0); }}>
      {t(label)}<i>{sort.key === key ? (sort.direction > 0 ? "↑" : "↓") : ""}</i></button></th>;
  return <>
    <div className="stats__table"><table>
      <thead><tr>{head("name", "Name")}{head("workflow", "Workflow")}{head("model", "Model")}{head("gap", "Gap to the record")}
        {head("turns", "Turns")}{head("seconds", "Duration")}{head("tokens", "Tokens")}{head("cost", "Cost")}{head("created", "Date")}</tr></thead>
      <tbody>{rows.map((run) => {
        const turn = bestTurn(run);
        const ahead = (run.record_gap ?? 0) > 0;
        return <tr key={run.run_id} className={run.deleted ? "is-deleted" : undefined}
          onClick={run.deleted ? undefined : () => onOpen(run.run_id)}>
          <td title={run.name ?? run.run_id}><strong>{run.name ?? run.run_id}</strong>
            <small>{t(run.problem_name)}
              {run.status === "running" && <em className="stats__tag">{t("in progress")}</em>}
              {run.deleted && <em className="stats__tag">{t("deleted")}</em>}</small></td>
          <td title={workflowName(run.workflow)}><i style={{ background: colour(run.workflow) }} />{code(workflowName(run.workflow))}</td>
          <td title={modelOf(run)}>{run.model || "—"}</td>
          <td className={ahead ? "is-ahead" : undefined}><strong>{gap(run.record_gap, 3)}</strong>
            {ahead && <small>{t("record beaten")}</small>}</td>
          <td>{run.round}{turn !== null && <small>{t("best at")} {turn}</small>}</td>
          <td>{elapsed(run.seconds, t)}</td>
          <td title={`${run.spend.tokens_in} in · ${run.spend.tokens_cached ?? 0} cached · ${run.spend.tokens_out} out`}>{count(tokens(run))}</td>
          <td>{run.spend.cost == null ? "—" : money(run.spend.cost)}</td>
          <td>{date(day(run))}</td>
        </tr>;
      })}</tbody>
    </table></div>
    {current === null ? sorted.length > FIRST && <button type="button" className="stats__more" onClick={() => setPage(0)}>
      {t("Show all")} <small>({sorted.length})</small></button>
      : <div className="stats__pager">
        {pages > 1 && <>
          <button type="button" disabled={current === 0} aria-label={t("Previous page")} onClick={() => setPage(current - 1)}>‹</button>
          <span>{current + 1} / {pages}</span>
          <button type="button" disabled={current === pages - 1} aria-label={t("Next page")} onClick={() => setPage(current + 1)}>›</button>
        </>}
        <button type="button" className="stats__fold" onClick={() => setPage(null)}>{t("Show less")}</button>
      </div>}
  </>;
}

/** One problem: each workflow's best gap as a dot on a line that reaches the record, or passes it. */
function ProblemCard({ runs, workflows, colour, workflowName, onClose }: {
  runs: Run[];
  workflows: string[];
  colour: (workflow: string) => string;
  workflowName: (workflow: string) => string;
  onClose: () => void;
}) {
  const { t, money, gap } = useFormat();
  const gaps = runs.map((run) => run.record_gap).filter((value): value is number => value != null);
  // The line runs from a little past the farthest run to the record, or past it when a run beat it.
  const far = Math.min(-0.005, ...gaps) * 1.15;
  const near = Math.max(0, ...gaps) * 1.15;
  const at = (value: number) => `${((value - far) / (near - far)) * 100}%`;
  return <article className="stats__problem">
    <header><h3>{t(runs[0]?.problem_name ?? "")}</h3>
      <button type="button" className="stats__close" aria-label={t("Remove from the comparison")} onClick={onClose}>×</button></header>
    {workflows.filter((id) => runs.some((run) => run.workflow === id)).map((id) => {
      const own = runs.filter((run) => run.workflow === id);
      const values = own.map((run) => run.record_gap).filter((value): value is number => value != null);
      const best = values.length ? Math.max(...values) : null;
      const costs = own.map((run) => run.spend.cost).filter((value): value is number => value != null);
      return <div key={id} className="stats__row">
        <span className="stats__name"><i style={{ background: colour(id) }} />
          <span><b>{code(workflowName(id))}</b> {rest(workflowName(id))}
            <small>{own.length} {t(own.length > 1 ? "runs" : "run")}</small></span></span>
        <span className="stats__track">{gaps.length > 0 && <u style={{ left: at(0) }} title={t("record")} />}
          {best != null && <>
            {values.length > 1 && <b style={{ left: at(Math.min(...values)), right: `calc(100% - ${at(best)})`, background: colour(id) }} />}
            <i style={{ left: at(best), background: colour(id) }} title={gap(best, 3)} />
          </>}</span>
        <span className="stats__value"><strong className={best != null && best > 0 ? "is-ahead" : undefined}>{gap(best)}</strong>
          <small>{costs.length ? money(mean(costs) ?? 0) : ""}</small></span>
      </div>;
    })}
    {gaps.length > 0 && <div className="stats__scale"><span /><span><em>{gap(far)}</em>
      <em>{near > 0 ? gap(near) : t("record")}</em></span><span /></div>}
  </article>;
}

/** What the runs shown used: how they split between models, workflows and families of problems. */
function Shares({ runs, colour, workflowName, order }: {
  runs: Run[];
  colour: (workflow: string) => string;
  workflowName: (workflow: string) => string;
  order: (workflow: string) => number;
}) {
  const { t, money } = useFormat();
  const [byCost, setByCost] = useState(false);
  const priced = runs.some((run) => run.spend.cost != null);
  // A family is a problem without its count: "8 pentagons in the smallest square" is one of "Pentagons in the smallest square".
  const family = (run: Run) => { const name = t(run.problem_name).replace(/^\d+\s+/, ""); return name.charAt(0).toUpperCase() + name.slice(1); };
  const weight = (group: Run[]) => byCost ? sum(group.map((run) => run.spend.cost ?? 0)) : group.length;
  const split = (of: (run: Run) => string, label: (key: string) => string, paint: (key: string, index: number) => string, sorted?: (a: string, b: string) => number) => {
    const keys = [...new Set(runs.map(of))];
    const parts = keys.map((key) => ({ key, label: label(key), group: runs.filter((run) => of(run) === key) }))
      .sort((a, b) => sorted ? sorted(a.key, b.key) : weight(b.group) - weight(a.group));
    const named = parts.slice(0, SHARE_PARTS), others = parts.slice(SHARE_PARTS).flatMap((part) => part.group);
    return [...named.map((part, index) => ({ ...part, colour: paint(part.key, index) })),
      ...(others.length ? [{ key: "others", label: t("Others"), group: others, colour: "#c9bccc" }] : [])];
  };
  return <>
    {priced && <div className="stats__segments stats__segments--small" role="group" aria-label={t("Share of")}>
      <button type="button" aria-pressed={!byCost} onClick={() => setByCost(false)}>{t("Runs")}</button>
      <button type="button" aria-pressed={byCost} onClick={() => setByCost(true)}>{t("Estimated spend")}</button></div>}
    <div className="stats__shares">
      <Donut title={t("Models")} parts={split((run) => run.model || "—", (key) => key, (_, index) => PARTS[index % PARTS.length] ?? "#888")}
        weight={weight} format={byCost ? money : String} />
      <Donut title={t("Workflows")} parts={split((run) => run.workflow, workflowName, colour, (a, b) => order(a) - order(b))}
        weight={weight} format={byCost ? money : String} />
      <Donut title={t("Problem families")} parts={split(family, (key) => key, (_, index) => PARTS[(index + 2) % PARTS.length] ?? "#888")}
        weight={weight} format={byCost ? money : String} />
    </div>
  </>;
}

/** One share as a ring, with its parts named beside it. */
function Donut({ title, parts, weight, format }: {
  title: string;
  parts: { key: string; label: string; group: Run[]; colour: string }[];
  weight: (group: Run[]) => number;
  format: (value: number) => string;
}) {
  const total = sum(parts.map((part) => weight(part.group)));
  const radius = 42, around = 2 * Math.PI * radius;
  let offset = 0;
  return <figure className="stats__donut">
    <figcaption>{title}</figcaption>
    <svg viewBox="0 0 110 110" width={110} height={110} role="img" aria-label={title}>
      <circle cx={55} cy={55} r={radius} fill="none" stroke="#efe8f0" strokeWidth={14} />
      {total > 0 && parts.map((part) => {
        const length = (weight(part.group) / total) * around;
        const arc = <circle key={part.key} cx={55} cy={55} r={radius} fill="none" stroke={part.colour} strokeWidth={14}
          strokeDasharray={`${length} ${around - length}`} strokeDashoffset={-offset} transform="rotate(-90 55 55)">
          <title>{`${part.label} · ${format(weight(part.group))}`}</title></circle>;
        offset += length;
        return arc;
      })}
    </svg>
    <ul>{parts.map((part) => <li key={part.key} title={part.label}><i style={{ background: part.colour }} />
      <span>{part.label}</span><b>{total > 0 ? Math.round((weight(part.group) / total) * 100) : 0} %</b></li>)}</ul>
  </figure>;
}

/** Each run as a point: what it spent across, how far its best is from the record up. */
function Scatter({ runs, colour, workflowName }: {
  runs: Run[];
  colour: (workflow: string) => string;
  workflowName: (workflow: string) => string;
}) {
  const { t, money, gap, count } = useFormat();
  const [ref, width] = useWidth();
  const byCost = runs.some((run) => run.spend.cost != null);
  const x = (run: Run) => byCost ? run.spend.cost ?? 0 : tokens(run);
  const points = runs.filter((run) => run.record_gap != null && (!byCost || run.spend.cost != null));
  const height = 260, left = 62, right = 18, top = 14, bottom = 34;
  const gaps = points.map((run) => run.record_gap ?? 0);
  const low = Math.min(-0.005, ...gaps) * 1.1, high = Math.max(0, ...gaps) * 1.1;
  const most = Math.max(1e-12, ...points.map(x)) * 1.08;
  const px = (value: number) => left + (value / most) * (width - left - right);
  const py = (value: number) => top + ((high - value) / (high - low)) * (height - top - bottom);
  const ticks = [low / 1.1, low / 2.2].map((value) => Math.round(value * 1000) / 1000);
  return <div ref={ref} className="stats__chart">
    {points.length === 0 ? <p className="stats__empty">{t("No run here has a record to compare with.")}</p>
      : width > 0 && <svg width={width} height={height} role="img" aria-label={t("Cost and result")}>
        {ticks.map((value) => <g key={value}>
          <line x1={left} x2={width - right} y1={py(value)} y2={py(value)} className="stats__grid" />
          <text x={left - 8} y={py(value) + 4} textAnchor="end">{gap(value)}</text></g>)}
        <line x1={left} x2={width - right} y1={py(0)} y2={py(0)} className="stats__record" />
        <text x={left - 8} y={py(0) + 4} textAnchor="end" className="stats__strong">{t("record")}</text>
        <line x1={left} x2={width - right} y1={height - bottom} y2={height - bottom} className="stats__axis" />
        <text x={left} y={height - 12}>0</text>
        <text x={width - right} y={height - 12} textAnchor="end">{byCost ? money(most) : count(most)}</text>
        <text x={(left + width - right) / 2} y={height - 12} textAnchor="middle">{t(byCost ? "estimated cost" : "tokens")}</text>
        {points.map((run) => <circle key={run.run_id} cx={px(x(run))} cy={py(run.record_gap ?? 0)} r={6} fill={colour(run.workflow)}>
          <title>{`${run.name ?? run.run_id}\n${workflowName(run.workflow)} · ${t(run.problem_name)}\n${gap(run.record_gap)} · ${byCost ? money(x(run)) : count(x(run))}`}</title>
        </circle>)}
      </svg>}
  </div>;
}

/** One bar per day from the first run shown to the last, stacked by workflow. */
function Days({ runs, colour, workflowName, order }: {
  runs: Run[];
  colour: (workflow: string) => string;
  workflowName: (workflow: string) => string;
  order: string[];
}) {
  const { t, money, date } = useFormat();
  const [ref, width] = useWidth();
  const priced = runs.filter((run) => run.spend.cost != null);
  const dates = priced.map(day).sort();
  const first = dates[0] ?? "", last = dates[dates.length - 1] ?? "";
  const start = Date.parse(`${first}T00:00:00Z`);
  const days = Array.from({ length: Math.round((Date.parse(`${last}T00:00:00Z`) - start) / 864e5) + 1 },
    (_, index) => new Date(start + index * 864e5).toISOString().slice(0, 10));
  const stacks = days.map((when) => order.map((workflow) => ({
    workflow, value: sum(priced.filter((run) => day(run) === when && run.workflow === workflow).map((run) => run.spend.cost ?? 0)),
  })));
  const top = Math.max(1e-12, ...stacks.map((stack) => sum(stack.map((part) => part.value))));
  const height = 210, left = 62, right = 18, head = 14, bottom = 30;
  const slot = (width - left - right) / days.length, bar = Math.min(46, slot * 0.6);
  const py = (value: number) => head + (1 - value / top) * (height - head - bottom);
  const labelled = days.length <= 7 ? days : [days[0], days[Math.floor(days.length / 2)], days[days.length - 1]];
  return <div ref={ref} className="stats__chart">
    {priced.length === 0 ? <p className="stats__empty">{t("No run here has prices.")}</p>
      : width > 0 && <svg width={width} height={height} role="img" aria-label={t("Spending over time")}>
      {[top, top / 2].map((value) => <g key={value}>
        <line x1={left} x2={width - right} y1={py(value)} y2={py(value)} className="stats__grid" />
        <text x={left - 8} y={py(value) + 4} textAnchor="end">{money(value)}</text></g>)}
      {stacks.map((stack, index) => {
        let base = height - bottom;
        return <g key={days[index]}>{stack.map((part) => {
          const tall = (part.value / top) * (height - head - bottom);
          base -= tall;
          return tall > 0 && <rect key={part.workflow} x={left + index * slot + (slot - bar) / 2} y={base} width={bar} height={tall}
            rx={2} fill={colour(part.workflow)}><title>{`${date(days[index] ?? "")} · ${workflowName(part.workflow)} · ${money(part.value)}`}</title></rect>;
        })}</g>;
      })}
      <line x1={left} x2={width - right} y1={height - bottom} y2={height - bottom} className="stats__axis" />
      {labelled.map((when) => when && <text key={when} x={left + (days.indexOf(when) + 0.5) * slot} y={height - 10} textAnchor="middle">{date(when)}</text>)}
    </svg>}
  </div>;
}
