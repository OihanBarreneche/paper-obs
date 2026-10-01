import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { api } from "../api";
import { useI18n } from "../i18n";
import type {
  AgentLaneDoc, AgentRunDoc, AgentRunStepDoc, AgentRunSummaryDoc, AgentToolEventDoc,
  BestScoreDoc, CandidateDoc, EvaluationDoc, SummaryDoc, ViewDoc, WorkflowManifestDoc, WorkflowParameterDoc,
} from "../types";
import type { ProblemReference } from "../catalog";
import { StatusPanel } from "./StatusPanel";
import { ToolViewer } from "./ToolViewer";
import { WorkflowGraph } from "./WorkflowGraph";
import { readModelSettings } from "./ProviderPanel";
import { RunsComparison } from "./RunsComparison";

type Props = {
  workflows: WorkflowManifestDoc[];
  problemId: string | null;
  problemName: string | null;
  /** A start is on its way to the server: no other may be sent. */
  starting: boolean;
  /** The objective of the problem at hand, which the tool viewer shows first. */
  objective: string | null;
  run: AgentRunDoc | null;
  runs: AgentRunSummaryDoc[];
  watching: boolean;
  stopping: boolean;
  error: string | null;
  canvas: ReactNode;
  evaluation: EvaluationDoc | null;
  summary: SummaryDoc | null;
  best: BestScoreDoc | null;
  busy: boolean;
  view: ViewDoc | null;
  showOrientations: boolean;
  onToggleOrientations: () => void;
  /** Start a run, or with `resume` take a finished one up again where it stopped. */
  onStart: (workflow: string, budget: Record<string, number>, name: string, maxTokens: number | null, resume?: string) => void;
  onOpen: (runId: string) => void;
  /** Read the saved runs again, as the picker opens. */
  onBrowse: () => void;
  onNew: () => void;
  onDelete: (runId: string) => void;
  onRestore: (runId: string) => void;
  onReplay: (step: AgentRunStepDoc) => void;
  onReplayCandidate: (candidate: CandidateDoc) => void;
  /** The published record of the problem, when the catalogue or the owner knows one. */
  reference: ProblemReference | null;
  onOpenModels: () => void;
  onStop: () => void;
};

/** A start the owner has asked for and not yet confirmed. */
type Launch = { workflow: string; budget: Record<string, number>; name: string; maxTokens: number | null; resume?: string };

const print = (value: unknown): string => typeof value === "string" ? value : JSON.stringify(value, null, 2);

/**
 * Read one ceiling field.
 *
 * A dash, an empty field, or anything that is not a positive number means the same thing
 * everywhere: no ceiling at all. The counts that bound a run — its turns, and what one turn
 * may spend — are ordinary numbers and never take it.
 */
const ceiling = (value: string): number | null => {
  const text = value.trim();
  if (text === "" || text === "-" || text === "—") return null;
  const number = Number(text);
  return Number.isFinite(number) && number > 0 ? number : null;
};

/** The options a reminder picture is drawn with: the page's own paper and ink. */
const REMINDER_RENDER = {
  background: "#ffffff", arena_fill: "#ffffff", arena_stroke: "#555555",
  shape_fill: "#b6b6b6", shape_stroke: "#4d4d4d",
  show_violations: false, honor_shape_colors: false,
};

/** The arrangement one turn handed back to the run, and the measurement the engine promoted. */
type Arrangement = { candidate: CandidateDoc; round: number; value: number | null; label: string };

/**
 * One arrangement per turn: the one that turn handed back to the outer loop.
 *
 * A turn produces several arrangements and keeps one, and the kept one is what the loop ever
 * sees — the intermediate ones are its own working state, not steps of the search. A turn whose
 * arrangement the engine refused is left out rather than offered as a step back.
 */
function turnArrangements(run: AgentRunDoc | null): Arrangement[] {
  if (run === null) return [];
  const label = timelineMetricLabel(run);
  const arrangements: Arrangement[] = [];
  for (const step of run.steps) {
    if (step.valid !== true || step.candidate === null) continue;
    arrangements.push({
      candidate: step.candidate, round: step.round, value: timelineMetric(step, run), label,
    });
  }
  return arrangements;
}

/** An agent's name as its workflow gives it, "explorer 2": the word is translated, the number kept. */
const agentName = (id: string, t: (key: string) => string): string =>
  id.replace(/^(.*?)(\s*\d*)$/, (_, word: string, number: string) => t(word) + number);

/**
 * One parallel agent's view of a run: every turn it took part in, with its own arrangement,
 * verdict, record, note, idea, tool calls and replies. The engine judged all of it; this only
 * picks the agent's part out of each turn. Its champion is its own last record.
 */
function laneRun(run: AgentRunDoc, lane: string): AgentRunDoc {
  const steps = run.steps.flatMap((step) => {
    const own = step.lanes?.find((item) => item.id === lane);
    if (own === undefined) return [];
    // A lane is one agent, or a team of them, such as a builder and its critic.
    const agents = own.agents ?? [lane];
    const events = (step.events ?? []).filter((item) => agents.includes(item.branch_id ?? ""));
    const messages = (step.model_messages ?? []).filter((item) => agents.includes(item.branch_id ?? ""));
    return [{
      ...step, lanes: [own], candidate: own.candidate, candidate_id: own.candidate?.candidate_id ?? null,
      valid: own.valid, primary: own.primary, accepted: own.accepted, verdict: own.verdict,
      note: own.note, plan: own.idea, events, tools: events.map((item) => item.tool), tool_calls: events.length,
      model_messages: messages, llm_calls: messages.length,
    }];
  });
  const record = [...steps].reverse().find((item) => item.accepted && item.valid);
  return { ...run, steps, champion: record?.candidate ?? null };
}

/** A spend against its ceiling: a ceiling of zero is no ceiling, and reads as a dash. */
const against = (spent: number, total: number): string => `${spent}/${total > 0 ? total : "–"}`;

/** What a run has spent, against its ceiling, short enough to hold on one line. */
const spentCost = (
  amount: number,
  limit: number | null | undefined,
  format: (value: number, digits?: number) => string,
): string => `$${format(amount, 3)}${limit == null ? "" : ` / $${format(limit, 2)}`}`;

/** A run's date as a picker row shows it: day, month, hour and minute, in the reader's locale. */
const runDate = (iso: string, language: string): string =>
  iso === "" ? "" : new Intl.DateTimeFormat(language === "fr" ? "fr-FR" : "en-GB", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  }).format(new Date(iso));

/** A run's elapsed time: seconds under a minute, minutes and seconds under an hour, then hours and minutes. */
export function elapsed(seconds: number, t: (key: string) => string): string {
  const whole = Math.max(0, Math.round(seconds));
  const pad = (value: number) => String(value).padStart(2, "0");
  if (whole < 60) return `${whole} ${t("sec")}`;
  if (whole < 3600) return `${Math.floor(whole / 60)} ${t("min")} ${pad(whole % 60)} ${t("sec")}`;
  return `${Math.floor(whole / 3600)} h ${pad(Math.floor(whole / 60) % 60)} ${t("min")}`;
}

/**
 * What a start is about to spend, said before it is sent: a run calls a paid API with the
 * owner's key, and one without a cost or turn ceiling is bounded by nothing but its own stops.
 */
function LaunchConfirm({ launch, workflow, problem, starting, onCancel, onConfirm }: {
  launch: Launch;
  workflow: WorkflowManifestDoc | null;
  problem: string;
  starting: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const { t, number } = useI18n();
  const settings = readModelSettings();
  const priced = [settings.priceIn, settings.priceOut].every((value) => value.trim() !== "" && Number.isFinite(Number(value)));
  const none = t("no limit");
  const value = (parameter: WorkflowParameterDoc) => {
    const amount = launch.budget[parameter.name] ?? 0;
    if (parameter.type === "flag") return t(amount ? "yes" : "no");
    if (amount <= 0) return none;
    return parameter.type === "duration" ? elapsed(amount, t) : number(amount, 4);
  };
  const unbounded = launch.budget.max_cost == null && !launch.budget.rounds;
  const unstoppable = unbounded && !launch.budget.stall_limit && !launch.budget.seconds;
  const parallel = workflow?.nodes.some((node) => node.parallel) ?? false;
  return createPortal(<div className="modal" onMouseDown={(event) => { if (event.target === event.currentTarget) onCancel(); }}>
    <div className="modal__panel launch-confirm" role="dialog" aria-modal="true" aria-label={t(launch.resume ? "Resume this run?" : "Start this run?")}
      onKeyDown={(event) => { if (event.key === "Escape") onCancel(); }}>
      <div className="modal__body">
        <h2>{t(launch.resume ? "Resume this run?" : "Start this run?")}</h2>
        <dl>
          <dt>{t("Workflow")}</dt><dd>{t(workflow?.name ?? launch.workflow)}</dd>
          <dt>{t("Problem")}</dt><dd>{t(problem)}</dd>
          <dt>{t("Model")}</dt><dd>{settings.provider || "—"} · {settings.model || "—"}
            <small>{priced ? `${settings.priceIn} $ / ${settings.priceOut} $ ${t("per million tokens, in / out")}` : t("no prices entered: the cost is not tracked")}</small></dd>
          {(workflow?.parameters ?? []).map((parameter) => <Fragment key={parameter.name}>
            <dt>{t(parameter.label)}</dt><dd>{value(parameter)}</dd></Fragment>)}
          <dt>{t("Maximum cost")}</dt><dd>{launch.budget.max_cost == null ? none : `${number(launch.budget.max_cost, 4)} $`}</dd>
          <dt>{t("Maximum output tokens per reply")}</dt><dd>{launch.maxTokens ?? t("left to the provider")}</dd>
        </dl>
        {launch.resume && <p>{t("These limits are added to what the run has already spent.")}</p>}
        {parallel && <p>{t("Several agents work at once each turn: a turn can spend its allowances once per agent.")}</p>}
        <p>{t("This run calls the provider's API with your key: every model reply is billed. The cost shown here is an estimate at the prices you entered.")}</p>
        {unbounded && <p className="launch-confirm__warning">
          {t("No cost ceiling and no turn ceiling: nothing bounds the spending. The run ends only when the agent gives up, when turns stop improving, when its time runs out, or when you press Stop.")}
          {unstoppable && <> {t("Neither a time limit nor a stop on turns without progress is set either: only Stop ends it.")}</>}
        </p>}
      </div>
      <div className="modal__actions">
        <button className="button" type="button" onClick={onCancel} autoFocus>{t("Cancel")}</button>
        <button className="button button--primary" type="button" disabled={starting} onClick={onConfirm}>
          {t(unbounded ? "Run anyway" : launch.resume ? "Resume" : "Run")} ↗</button>
      </div>
    </div>
  </div>, document.body);
}

/**
 * The form's fields for a workflow's parameters, from saved values or the manifest's defaults: a
 * zero shows as a dash, a flag as 0 or 1, and a duration as two fields, minutes and seconds.
 */
const fieldsOf = (parameters: WorkflowParameterDoc[], saved: Record<string, unknown> = {}): Record<string, string> =>
  Object.fromEntries(parameters.flatMap((parameter) => {
    const value = Number(saved[parameter.name] ?? parameter.default) || 0;
    const shown = (amount: number) => amount > 0 ? String(amount) : "-";
    if (parameter.type === "duration") return [
      [`${parameter.name}:min`, shown(Math.floor(value / 60))],
      [`${parameter.name}:sec`, value > 0 ? String(Math.floor(value % 60)) : "-"],
    ];
    return [[parameter.name, parameter.type === "flag" ? String(value ? 1 : 0) : shown(value)]];
  }));
const suggestedRunName = (workflowName: string, language: string): string =>
  `${workflowName} · ${new Intl.DateTimeFormat(language === "fr" ? "fr-FR" : "en-GB", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
  }).format(new Date())}`;

function stopExplanation(run: AgentRunDoc): string {
  if (run.status === "running") return "The run is still in progress. Inspecting a step does not interrupt it.";
  if (run.status === "failed") return run.error ?? "The run failed.";
  if (run.status === "stopped") return "Stopped by the user after the current model reply.";
  if (run.stopped_by === "max_cost") return "The run reached its configured cost ceiling after a model reply.";
  if (run.stopped_by === "seconds") return "The run reached its total time limit after a model reply.";
  if (run.budget.rounds > 0 && run.round >= run.budget.rounds) return "The run reached its turn limit.";
  if (run.budget.llm_calls > 0 && run.spend.llm_calls >= run.budget.llm_calls) return "The run reached its model-call limit.";
  if (run.budget.tool_calls > 0 && run.spend.tool_calls >= run.budget.tool_calls) return "The run reached its tool-call limit.";
  if (run.budget.seconds > 0 && run.spend.seconds >= run.budget.seconds) return "The run reached its time limit.";
  const last = run.steps.at(-1);
  if (last?.outcome === "gave_up") return "The agent chose to stop.";
  if (last && !last.accepted) return "The last turns improved nothing, as many in a row as the run allows.";
  return "The workflow finished.";
}

/** The measurement the objective promotes, taken from the first verdict the run kept. */
function promotedMetric(run: AgentRunDoc): string | null {
  for (const step of run.steps) {
    const promoted = step.verdict?.promoted_metric;
    if (typeof promoted === "string" && promoted !== "") return promoted;
  }
  return null;
}

/**
 * The number a turn is judged on.
 *
 * The engine promotes one measurement per objective and the verdict panel headlines it, so the
 * timeline reads the same one: a total-perimeter run is followed by the sum of its copies'
 * sizes rather than by the perimeter proportional to it, and a covering run by the size of the
 * target it contains. Quoting the primary score here made the two panels disagree.
 */
function timelineMetric(step: AgentRunStepDoc, run: AgentRunDoc): number | null {
  if (step.valid !== true) return null;
  const promoted = step.verdict?.promoted_metric;
  if (typeof promoted === "string" && promoted !== "") {
    const measured = step.verdict?.metrics[promoted];
    if (typeof measured === "number") return measured;
  }
  if (run.problem?.objective.type === "minimize_container") {
    const key = run.problem.objective.container === "circle" ? "container_radius" : "container_side";
    const measured = step.verdict?.metrics[key];
    return typeof measured === "number" ? measured : null;
  }
  return step.primary;
}

function timelineMetricLabel(run: AgentRunDoc): string {
  const promoted = promotedMetric(run);
  if (promoted !== null) return promoted.replaceAll("_", " ");
  if (run.problem?.objective.type === "minimize_container")
    return run.problem.objective.container === "circle" ? "Measured container radius" : "Measured container side";
  if (run.problem?.objective.type === "maximize_count") return "Placed shapes";
  if (run.problem?.objective.type === "maximize_covered_size") return "Covered target size";
  return "Common scale";
}

export function RunWorkspace(props: Props) {
  const { t, number, language } = useI18n();
  const [chosen, setChosen] = useState("");
  const [draft, setDraft] = useState<Record<string, string>>({});
  // The shipped defaults: a cost net under an unbounded turn loop, and room for a reply
  // without reasoning. Either can be dashed to leave it without limit.
  const [costLimit, setCostLimit] = useState("0.15");
  const [tokenLimit, setTokenLimit] = useState("4096");
  const [runsOpen, setRunsOpen] = useState(false);
  const [confirmRunId, setConfirmRunId] = useState<string | null>(null);
  const [cursor, setCursor] = useState<number | null>(null);
  const [scope, setScope] = useState<"problem" | "workflow" | "all" | "trash">("problem");
  const [reminder, setReminder] = useState("");
  const [viewing, setViewing] = useState<{ src: string; title: string; caption: string } | null>(null);
  const runPicker = useRef<HTMLDivElement | null>(null);
  const [node, setNode] = useState<string | null>(null);
  const [lane, setLane] = useState<string | null>(null);
  const [toolsOpen, setToolsOpen] = useState(false);
  const [openTurn, setOpenTurn] = useState<number | null>(null);
  const [eventIndex, setEventIndex] = useState<number | null>(null);
  const [generatedName, setGeneratedName] = useState(() => suggestedRunName(t(props.workflows[0]?.name ?? "Run"), language));
  const [customName, setCustomName] = useState<string | null>(null);
  const [rerunOpen, setRerunOpen] = useState(false);
  const [rerunName, setRerunName] = useState("");
  const [launch, setLaunch] = useState<Launch | null>(null);
  const stopping = props.stopping || props.run?.stop_requested === true;

  const workflow = props.workflows.find((item) => item.id === (props.run?.workflow ?? chosen))
    ?? props.workflows[0] ?? null;
  // The turns are read newest first, and a turn is opened where it is read: the trace belongs
  // beside its turn, not below the whole list, where reaching it on a run of thirty turns means
  // scrolling past everything.
  // A run whose turns start parallel agents offers one view per agent beside the run's own.
  const lanes = useMemo(() => [...new Set((props.run?.steps ?? [])
    .flatMap((step) => (step.lanes ?? []).map((item) => item.id)))], [props.run]);
  const viewed = useMemo(() => props.run === null || lane === null || !lanes.includes(lane)
    ? props.run : laneRun(props.run, lane), [props.run, lane, lanes]);
  const steps = useMemo(() => [...(viewed?.steps ?? [])].reverse(), [viewed]);
  const open = steps.find((item) => item.round === openTurn) ?? null;
  const event = (open?.events ?? []).find((item) => item.index === eventIndex) ?? null;
  const arrangements = useMemo(() => turnArrangements(viewed), [viewed]);
  const index = arrangements.length === 0 ? 0
    : Math.min(cursor ?? arrangements.length - 1, arrangements.length - 1);
  const current = arrangements[index] ?? null;
  // The record is what the engine kept: the last turn it preferred, and its measurement. In an
  // agent's view, it is that agent's own best.
  const record = [...(viewed?.steps ?? [])].reverse().find((item) => item.accepted && item.valid) ?? null;
  const recordValue = viewed !== null && record !== null ? timelineMetric(record, viewed) : null;
  const championId = viewed?.champion?.candidate_id ?? null;
  const adopted = lane === null ? "adopted" : "personal best";
  const published = props.reference;
  const publishedCaption = published === null ? "" : [
    published.status === "proved" ? t("Proved optimum")
      : published.status === "best_known" ? t("Best known") : "",
    published.verified_on === "" ? "" : `${t("Last checked")}: ${published.verified_on}`,
    published.author === "" ? ""
      : `${t("Construction")}: ${published.author}${published.date === "" ? "" : ` · ${published.date}`}`,
  ].filter((part) => part !== "").join(" · ");
  const recordCaption = props.run === null || record === null ? ""
    : `${t(timelineMetricLabel(props.run))} · ${t("Reached at turn")} ${record.round + 1}`;
  // A run belongs to its problem, and so does a comparison: the runs of the problem at hand
  // are the ones worth opening, and the whole history is the exception one switches to.
  const scopeProblem = props.run?.problem_id ?? props.problemId;
  // A deleted run leaves the lists and waits in the trash, where it can be restored.
  const saved = props.runs.filter((item) => !item.deleted);
  const trash = props.runs.filter((item) => item.deleted);
  const byProblem = scopeProblem === null ? [] : saved.filter((item) => item.problem_id === scopeProblem);
  // The runs of one workflow, on any problem, follow how that workflow behaves across problems.
  const scopeWorkflow = props.run?.workflow ?? workflow?.id ?? null;
  const byWorkflow = saved.filter((item) => item.workflow === scopeWorkflow);
  const scopedRuns = scope === "all" ? saved : scope === "workflow" ? byWorkflow : scope === "trash" ? trash : byProblem;
  // Runs going on in the server, on any problem: several may run at once, for a long time.
  const running = saved.filter((item) => item.status === "running");
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!runsOpen || running.length === 0) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [runsOpen, running.length]);

  useEffect(() => {
    if (workflow) {
      setGeneratedName(suggestedRunName(t(workflow.name), language));
      setCustomName(null);
    }
  }, [workflow?.id, language]);

  useEffect(() => {
    setOpenTurn(null);
    setEventIndex(null);
    setConfirmRunId(null);
    // A new run is a new history: the slider follows its own end until it is moved.
    setCursor(null);
    setLane(null);
  }, [props.run?.run_id]);
  // The reminder is redrawn when the run or its incumbent changes, never on every poll: the
  // document is re-read every second, so its objects are new each time while its ids are not.
  const runProblem = props.run?.problem ?? null;
  const champion = viewed?.champion ?? null;
  useEffect(() => {
    if (runProblem === null || champion === null) {
      setReminder("");
      return;
    }
    let live = true;
    void api.render({ problem: runProblem, candidate: champion, options: REMINDER_RENDER })
      .then((svg) => {
        if (live) setReminder(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`);
      })
      .catch(() => { if (live) setReminder(""); });
    return () => { live = false; };
  }, [props.run?.run_id, championId]);

  useEffect(() => {
    const outside = (event: PointerEvent) => {
      if (runsOpen && !runPicker.current?.contains(event.target as Node)) setRunsOpen(false);
    };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setRunsOpen(false); };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [runsOpen]);

  const parameters = workflow?.parameters ?? [];
  // An untouched field keeps the manifest's default; one emptied or dashed means none of that
  // ceiling, which is what a zero says everywhere in a budget.
  const fields = { ...fieldsOf(parameters), ...draft };
  const read = (key: string): number => ceiling(fields[key] ?? "-") ?? 0;
  // Run-wide call totals stay open unless a workflow declares them: its per-turn allowances, time
  // and cost bound a run, and a total would have to guess how many agents a turn starts.
  const budget: Record<string, number> = { llm_calls: 0, tool_calls: 0 };
  for (const parameter of parameters) {
    const value = parameter.type === "duration"
      ? read(`${parameter.name}:min`) * 60 + read(`${parameter.name}:sec`) : read(parameter.name);
    budget[parameter.name] = parameter.type === "number" ? value : Math.floor(value);
  }
  /** No entry, or a dash, leaves the output ceiling to the provider: no field is sent at all. */
  const outputTokens = (): number | null => ceiling(tokenLimit);
  const modelSettings = readModelSettings();
  const hasPrices = [modelSettings.priceIn, modelSettings.priceOut].every((value) =>
    value.trim() !== "" && Number.isFinite(Number(value)) && Number(value) >= 0);
  const priceCeiling = ceiling(costLimit);
  if (hasPrices && priceCeiling !== null) budget.max_cost = priceCeiling;

  const configureFromRun = () => {
    if (!props.run) return;
    setChosen(props.run.workflow);
    setDraft(fieldsOf(parameters, { ...props.run.budget, ...props.run.settings }));
    setCostLimit(props.run.budget.max_cost == null ? "-" : String(props.run.budget.max_cost));
    const tokens = props.run.model?.max_tokens;
    setTokenLimit(typeof tokens === "number" ? String(tokens) : "-");
    setGeneratedName(rerunName.trim() || suggestedRunName(t(props.run.workflow_name), language));
    setCustomName(null);
    setRerunOpen(false);
    props.onNew();
  };

  const startFromRun = () => {
    if (!props.run || !rerunName.trim()) return;
    const previous = Object.fromEntries(Object.entries({ ...props.run.budget, ...props.run.settings })
      .filter(([, value]) => typeof value === "number")) as Record<string, number>;
    // A rerun repeats the ceiling the run was saved with, not whatever the form last held.
    const tokens = props.run.model?.max_tokens;
    setLaunch({ workflow: props.run.workflow, budget: previous, name: rerunName.trim(),
      maxTokens: typeof tokens === "number" ? tokens : null });
    setRerunOpen(false);
  };

  // The agent tabs sit where they act, above the trace and above the solution; both read and
  // set the same choice, so the two stay in step.
  const laneTabs = props.run && lanes.length > 0 && <div className="run-workspace__lanes" role="tablist" aria-label={t("Agents of the run")}>
    {[null, ...lanes].map((item) => <button type="button" role="tab" key={item ?? ""} aria-selected={lane === item}
      onClick={() => {
        setLane(item); setCursor(null); setOpenTurn(null); setEventIndex(null);
        const last = turnArrangements(item === null ? props.run : laneRun(props.run!, item)).at(-1);
        if (last) props.onReplayCandidate(last.candidate);
      }}>
      {item === null ? t("Whole run") : agentName(item, t)}
    </button>)}
  </div>;

  return <main className="run-workspace">
    <header className="run-workspace__intro">
       <div><span className="eyebrow">Paper Obs / {t("Agents")}</span>
         <h1>{t("Agent workflows")}</h1>
         {props.run && <p className="run-workspace__run-name">{props.run.name ?? t(props.run.workflow_name)} <small>· {props.run.run_id}</small></p>}
      </div>
       <div className="run-workspace__actions">
         {/* A run goes on in the server while another starts: the picker's running list follows each one. */}
         {props.run !== null && <button type="button" className="button" disabled={props.starting} onClick={() => {
           setRerunName(suggestedRunName(t(props.run!.workflow_name), language));
           setRerunOpen(true);
         }}>{t("New run")}</button>}
         {props.run !== null && props.run.status !== "running" && !props.watching && <button type="button" className="button"
           title={t("Go on from this run's best arrangement, journal and notes; the limits of the form are added to what it has spent")}
           disabled={props.starting}
           onClick={() => setLaunch({ workflow: props.run!.workflow, budget, name: props.run!.name ?? props.run!.run_id,
             maxTokens: outputTokens(), resume: props.run!.run_id })}>
           {t("Resume")}</button>}
         <div className="run-picker" ref={runPicker}>
           <button type="button" className="run-picker__trigger" aria-expanded={runsOpen}
             onClick={() => { if (!runsOpen) props.onBrowse(); setRunsOpen((value) => !value); setConfirmRunId(null); }}>
             <span className="run-picker__caption">{t("past runs")}</span>
             <strong>{props.run?.name ?? t("Open a saved run")}</strong>
             {running.length > 0 && <span className="run-picker__going" title={t("Runs going on")}>● {running.length}</span>}
             <span aria-hidden="true">⌄</span>
           </button>
           {runsOpen && <div className="run-picker__popover">
             {running.length > 0 && <div className="run-picker__running">
               <span className="run-picker__heading">{t("Running")}</span>
               {running.map((item) => <button type="button" key={item.run_id} className="run-picker__name"
                 onClick={() => { props.onOpen(item.run_id); setRunsOpen(false); }}>
                 <span>{item.name ?? item.run_id} <small>· {t(item.problem_name)}</small></span>
                 <small>{elapsed((now - Date.parse(item.started)) / 1000, t)}</small>
               </button>)}
             </div>}
             <div className="run-picker__scope" role="tablist" aria-label={t("Runs to show")}>
               <button type="button" role="tab" aria-selected={scope === "problem"}
                 onClick={() => setScope("problem")}>{t("This problem")} <small>{byProblem.length}</small></button>
               <button type="button" role="tab" aria-selected={scope === "workflow"}
                 onClick={() => setScope("workflow")}>{t("This workflow")} <small>{byWorkflow.length}</small></button>
               <button type="button" role="tab" aria-selected={scope === "all"}
                 onClick={() => setScope("all")}>{t("All runs")} <small>{saved.length}</small></button>
             </div>
             {scopedRuns.length === 0 && <p className="run-picker__empty">
               {t(scope === "all" ? "No saved run yet." : scope === "workflow" ? "No run for this workflow yet." : scope === "trash" ? "The trash is empty." : "No run for this problem yet.")}</p>}
             {scope === "trash" && scopedRuns.length > 0 && <p className="run-picker__hint">{t("Deleted runs still count in the statistics.")}</p>}
             {scope === "trash" && scopedRuns.map((item) => <div key={item.run_id} className="run-picker__run is-deleted">
               <span className="run-picker__name">
                 <span>{item.name ?? t(props.workflows.find((entry) => entry.id === item.workflow)?.name ?? item.workflow)}</span>
                 <small>{runDate(item.created, language)} · {t(item.problem_name)}</small>
               </span>
               <button type="button" className="run-picker__restore" onClick={() => props.onRestore(item.run_id)}>{t("Restore")}</button>
             </div>)}
             {scope !== "trash" && scopedRuns.map((item) => {
               const name = item.name ?? t(props.workflows.find((entry) => entry.id === item.workflow)?.name ?? item.workflow);
               const active = props.watching && item.run_id === props.run?.run_id;
               return <div key={item.run_id} className={item.run_id === props.run?.run_id ? "run-picker__run is-active" : "run-picker__run"}>
                 <button type="button" className="run-picker__name"
                   onClick={() => { props.onOpen(item.run_id); setRunsOpen(false); }}>
                   <span>{name}</span>
                   <small>{runDate(item.created, language)} · <span className="run-picker__score"
                     title={t("The engine's score of the run's best arrangement, and its gap to the published record")}>
                     {item.champion?.primary == null ? t("no valid arrangement") : number(item.champion.measure ?? item.champion.primary, 4)}
                     {item.record_gap != null && ` (${item.record_gap > 0 ? "+" : "−"}${number(Math.abs(item.record_gap) * 100, 2)} %)`}
                   </span></small>
                 </button>
                 {confirmRunId === item.run_id
                   ? <span className="run-picker__confirm">
                       <button type="button" onClick={() => setConfirmRunId(null)}>{t("Cancel")}</button>
                       <button type="button" className="run-picker__delete"
                         onClick={() => { setConfirmRunId(null); props.onDelete(item.run_id); }}>{t("Delete")}</button>
                     </span>
                   : <button type="button" className="run-picker__icon" disabled={active} title={t("Delete run")}
                       aria-label={`${t("Delete run")}: ${name}`} onClick={() => setConfirmRunId(item.run_id)}>
                       <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3m-9 0 1 13h10l1-13M10 11v6m4-6v6" /></svg>
                     </button>}
               </div>;
             })}
             {trash.length > 0 && scope !== "trash" && <button type="button" className="run-picker__trash"
               onClick={() => setScope("trash")}>{t("Trash")} · {trash.length}</button>}
             {scope === "trash" && <button type="button" className="run-picker__trash"
               onClick={() => setScope("problem")}>{t("Back to the runs")}</button>}
           </div>}
         </div>
      </div>
    </header>
    {props.error && <div className="error">{props.error}</div>}
    {props.run && !props.run.problem && <p className="run-workspace__legacy">{t("This run has no saved problem snapshot")}. {t("Replay uses the currently loaded problem")}</p>}
    <div className="run-workspace__spread">
      <section className="run-workspace__process">
         <div className="section-heading"><h2>{t("Workflow")}</h2>
           {workflow && <button type="button" className="run-workspace__tools" onClick={() => setToolsOpen(true)}>
             {t("See the agent's tools")}</button>}</div>
         {props.run === null && <label className="run-workspace__workflow-picker">{t("Choose a workflow")}
           <select className="select" value={workflow?.id ?? ""} onChange={(e) => { setChosen(e.target.value); setDraft({}); }}>
             {props.workflows.map((item) => <option value={item.id} key={item.id}>{t(item.name)}</option>)}
           </select>
         </label>}
         {workflow && <p className="run-workspace__context">{t(workflow.description)}</p>}
         {workflow && <WorkflowGraph workflow={workflow} active={props.watching ? "turn" : node} onPick={setNode}
           onTools={() => setToolsOpen(true)} />}
         {workflow && toolsOpen && <ToolViewer workflow={workflow}
           objective={props.run?.problem?.objective.type ?? props.objective} onClose={() => setToolsOpen(false)} />}
         {props.run === null ? <div className="run-workspace__launch">
           <div className="section-heading"><h2>{t("Run limits")}</h2></div>
           <div className="run-workspace__budget">
             {parameters.filter((parameter) => parameter.type !== "flag").map((parameter) => {
               const field = (key: string, label?: string) => <input className="input" type="text" placeholder="—"
                 inputMode={parameter.type === "number" ? "decimal" : "numeric"} aria-label={label} value={fields[key] ?? "-"}
                 onChange={(event) => setDraft((current) => ({ ...current, [key]: event.target.value }))} />;
               return parameter.type === "duration"
                 ? <label key={parameter.name} className="run-workspace__duration" title={t(parameter.help)}>
                   <span>{t(parameter.label)}</span><span className="run-workspace__duration-fields">
                     {field(`${parameter.name}:min`, t("Minutes"))} {t("min")} {field(`${parameter.name}:sec`, t("Seconds"))} {t("sec")}
                   </span></label>
                 : <label key={parameter.name} title={t(parameter.help)}><span>{t(parameter.label)}</span>{field(parameter.name)}</label>;
             })}
             <label><span>{t("Maximum cost")} ($)</span><input className="input" type="text" inputMode="decimal" placeholder="—"
               aria-label={t("Maximum cost")} value={costLimit} disabled={!hasPrices}
               onChange={(event) => setCostLimit(event.target.value)} /></label>
             <label><span>{t("Maximum output tokens per reply")}</span><input className="input" type="text" inputMode="numeric" placeholder="—"
               aria-label={t("Maximum output tokens per reply")} value={tokenLimit}
               onChange={(event) => setTokenLimit(event.target.value)} /></label>
           </div>
           <p className="run-workspace__budget-note">{t("Enter - in any ceiling to leave it without limit. A very low output-token ceiling can cut a reply short.")}</p>
           {parameters.filter((parameter) => parameter.type === "flag").map((parameter) => <div key={parameter.name} className="run-workspace__flag">
             <label><input type="checkbox" checked={fields[parameter.name] === "1"}
               onChange={(event) => setDraft((current) => ({ ...current, [parameter.name]: event.target.checked ? "1" : "0" }))} /> {t(parameter.label)}</label>
             <small>{t(parameter.help)}</small>
           </div>)}
           {!hasPrices && <p className="run-workspace__budget-note">{t("Enter both token prices in Model settings to enable a cost ceiling.")} <button type="button" onClick={props.onOpenModels}>{t("Model…")}</button></p>}
          <div className="run-workspace__launch-action"><button className="button button--primary run-workspace__start" type="button"
            disabled={workflow === null || props.problemId === null || props.watching || props.starting || !(customName ?? generatedName).trim()}
            onClick={() => workflow && setLaunch({ workflow: workflow.id, budget, name: (customName ?? generatedName).trim(),
              maxTokens: outputTokens() })}>{props.starting ? t("Starting…") : <>{t("Run")} ↗</>}</button>
            <label>{t("Run name")}<input className="input" type="text" maxLength={100} value={customName ?? generatedName}
              onChange={(event) => setCustomName(event.target.value)} aria-label={t("Run name")} /></label></div>
        </div> : <div className="run-workspace__history">
           <div className="section-heading"><h2>{t("Timeline")}</h2></div>
           {laneTabs}
          <div className="run-workspace__stop" role="status"><span><strong>{t(props.run.status)}</strong> · {t(stopExplanation(props.run))}</span>
            {props.run.status === "failed" && <button type="button" className="button" onClick={props.onNew}>
              {t("Fix and run again")}</button>}
            {props.watching && <button type="button" className="button run-workspace__stop-button"
              onClick={() => { if (window.confirm(t("Stop this run? It ends once the model calls under way have answered, and can be resumed later from its last finished turn."))) props.onStop(); }}
              disabled={stopping}>{t(stopping ? "Stop requested…" : "Stop run")}</button>}</div>
          {props.watching && stopping && <p className="run-workspace__budget-note">
            {t("The run ends once the model calls under way have answered: a few seconds, sometimes a minute.")}</p>}
          <div className="run-workspace__spend">
            <span>{t("turns")} <strong>{against(props.run.round, props.run.budget.rounds)}</strong></span>
            <span>{t("replies")} <strong>{against(props.run.spend.llm_calls, props.run.budget.llm_calls)}</strong></span>
            <span>{t("tools")} <strong>{against(props.run.spend.tool_calls, props.run.budget.tool_calls)}</strong></span>
            {/* The share of the run spent waiting on the model; the rest is the lab's own work. */}
            <span>{t("duration")} <strong>{elapsed(props.run.seconds, t)}
              {props.run.spend.model_seconds != null && props.run.seconds > 0 && <small> ({Math.round(
                Math.min(1, props.run.spend.model_seconds / props.run.seconds) * 100)}% {t("calls")})</small>}</strong></span>
            <span>{t("cost")} <strong>{props.run.spend.cost == null
              ? t("Unknown price")
              : spentCost(props.run.spend.cost, props.run.budget.max_cost, number)}</strong></span>
           </div>
           <p className="run-workspace__turn-legend">{t(timelineMetricLabel(props.run))} · {t("Engine measurement; only valid adopted steps advance the retained solution.")}</p>
           <ol className="run-workspace__turns">
            {steps.map((item) => {
              const shown = openTurn === item.round;
              return <li key={item.round}>
                <button type="button" aria-expanded={shown}
                  className={shown ? "run-workspace__turn is-open" : "run-workspace__turn"}
                  onClick={() => {
                    setEventIndex(null);
                    if (shown) {
                      // Closing is about the list, not about the run: the canvas keeps what it has.
                      setOpenTurn(null);
                      return;
                    }
                    setOpenTurn(item.round);
                    if (item.candidate) props.onReplay(item);
                  }}>
                  <span className="run-workspace__turn-index">{String(item.round + 1).padStart(2, "0")}</span>
                  <span><strong>{t(item.accepted && item.valid ? adopted : item.outcome)} · {item.valid == null ? "—" : t(item.valid ? "valid" : "invalid")}</strong><small>{item.tools.length ? item.tools.slice(0, 3).join(" → ") + (item.tools.length > 3 ? ` +${item.tools.length - 3}` : "") : item.tool_calls > 0 ? `${item.tool_calls} ${t("tools")} · ${t("Trace unavailable")}` : t("No tools called")}</small></span>
                   <span className="run-workspace__turn-score">{timelineMetric(item, props.run!) == null ? "—" : number(timelineMetric(item, props.run!)!, 5)}</span>
                   <span className="run-workspace__turn-caret" aria-hidden="true">{shown ? "▾" : "▸"}</span>
                </button>
                {shown && <div className="run-workspace__turn-detail">
                  <TurnDetail step={item} steps={viewed?.steps ?? []} event={event} onEvent={(picked) => {
                    setEventIndex(picked.index);
                    if (picked.candidate) props.onReplayCandidate(picked.candidate);
                  }} />
                </div>}
              </li>;
            })}
          </ol>
        </div>}
      </section>
      <section className="run-workspace__solution">
         <div className="section-heading"><h2>{t("Current solution")}</h2></div>
        {laneTabs}
        <div className="run-workspace__canvas">{props.canvas}</div>
        {arrangements.length > 0 && <div className="run-workspace__drafts">
          <input type="range" min={0} max={arrangements.length - 1} step={1} value={index}
            aria-label={t("Browse the arrangements of each turn")}
            onChange={(changed) => {
              const next = Number(changed.target.value);
              setCursor(next);
              if (arrangements[next]) props.onReplayCandidate(arrangements[next].candidate);
            }} />
          {current !== null && <p className="run-workspace__drafts-line">
            <span><strong>{index + 1}/{arrangements.length}</strong> {t("turns")}</span>
            <span>{t("Reached at turn")} <strong>{current.round + 1}</strong></span>
            {current.value !== null && <span>{t("score")} <strong>{number(current.value, 5)}</strong>
              {current.label !== "" && <> · {t(current.label)}</>}</span>}
            {current.candidate.candidate_id === championId
              && <span className="run-workspace__drafts-record">{t(adopted)}</span>}
          </p>}
        </div>}
        {props.run && <div className="run-workspace__records">
          <RecordCard
            title={lane === null ? "Run record" : "Agent record"} value={recordValue === null ? "—" : number(recordValue, 5)}
            caption={t(timelineMetricLabel(props.run)) + (record !== null
              ? ` · ${t("Reached at turn")} ${record.round + 1}` : "")}
            picture={reminder} alt={t("The arrangement this run retained")}
            plate="no retained arrangement yet" published={false}
            onOpen={() => setViewing({ src: reminder, title: t(lane === null ? "Run record" : "Agent record"), caption: recordCaption })} />
          <RecordCard
            title="Problem reference"
            value={published === null || published.value === null ? "—"
              : `${number(published.value, 5)}${published.unit === "" ? "" : ` ${t(published.unit)}`}`}
            caption={publishedCaption} picture={published?.preview ?? ""}
            alt={t("Published reference figure")} plate="No published figure for this problem."
            published
            onOpen={() => published && setViewing({
              src: published.preview, title: t("Problem reference"), caption: publishedCaption,
            })} />
        </div>}
        <div className="run-workspace__verdict"><StatusPanel evaluation={props.evaluation} summary={props.summary} busy={props.busy} best={props.best}
          view={props.view} showOrientations={props.showOrientations} onToggleOrientations={props.onToggleOrientations} /></div>
        {props.run && <div className="run-workspace__compare">
           <div className="section-heading"><h2>{t("Comparison")}</h2></div>
          <RunsComparison key={props.run.run_id} current={props.run.run_id} runs={saved} workflows={props.workflows} />
        </div>}
      </section>
    </div>
    {viewing && createPortal(<div className="reference-viewer" role="dialog" aria-modal="true" aria-label={viewing.title}>
      <button type="button" className="reference-viewer__backdrop" aria-label={t("Close")} onClick={() => setViewing(null)} />
      <div className="reference-viewer__sheet">
        <div className="reference-viewer__heading"><h2>{viewing.title}</h2>
          <button type="button" aria-label={t("Close")} onClick={() => setViewing(null)}>×</button></div>
        <img src={viewing.src} alt={viewing.title} />
        {viewing.caption !== "" && <p>{viewing.caption}</p>}
      </div>
    </div>, document.body)}
    {launch && <LaunchConfirm launch={launch} workflow={props.workflows.find((item) => item.id === launch.workflow) ?? null}
      problem={launch.resume ? props.run?.problem?.name ?? "" : props.problemName ?? ""} starting={props.starting}
      onCancel={() => setLaunch(null)}
      onConfirm={() => { props.onStart(launch.workflow, launch.budget, launch.name, launch.maxTokens, launch.resume); setLaunch(null); }} />}
    {rerunOpen && props.run && createPortal(<div className="modal" onMouseDown={(event) => { if (event.target === event.currentTarget) setRerunOpen(false); }}>
      <form className="modal__panel run-workspace__name-dialog" role="dialog" aria-modal="true" aria-label={t("New run")}
        onSubmit={(event) => { event.preventDefault(); startFromRun(); }} onKeyDown={(event) => { if (event.key === "Escape") setRerunOpen(false); }}>
        <div className="modal__body"><h2>{t("New run")}</h2><p>{t("Same workflow and limits as the current run")}</p>
          <label>{t("Run name")}<input className="input" type="text" maxLength={100} required autoFocus value={rerunName}
            onChange={(event) => setRerunName(event.target.value)} /></label></div>
        <div className="modal__actions"><button className="button" type="button" onClick={() => setRerunOpen(false)}>{t("Cancel")}</button>
          <button className="button" type="button" onClick={configureFromRun}>{t("Adjust settings")}</button>
          <button className="button button--primary" type="submit" disabled={!rerunName.trim()}>{t("Run")} ↗</button></div>
      </form>
    </div>, document.body)}
  </main>;
}

/**
 * One of the two records, drawn once so the pair cannot drift apart.
 *
 * A record is a picture, a value and the line that says where it comes from; both sides use
 * the same type, the same sizes and the same viewer, and only the plate differs.
 */
function RecordCard(props: {
  title: string;
  value: string;
  caption: string;
  picture: string;
  alt: string;
  plate: string;
  published: boolean;
  onOpen: () => void;
}) {
  const { t } = useI18n();
  const openable = props.picture !== "";
  return <figure className={props.published ? "run-record run-record--published" : "run-record"}>
    <button type="button" className="run-record__picture" disabled={!openable}
      aria-label={t(openable ? "Enlarge this record" : props.plate)}
      title={t(openable ? "Enlarge this record" : props.plate)} onClick={props.onOpen}>
      {openable
        ? <img src={props.picture} alt={props.alt} />
        : <span className="run-record__plate">{t(props.plate)}</span>}
    </button>
    <figcaption>
      <span className="eyebrow">{t(props.title)}</span>
      <strong>{props.value}</strong>
      <small>{props.caption}</small>
    </figcaption>
  </figure>;
}

/**
 * A model's own text, which models often lay out in Markdown: shown formatted, a line break kept
 * as one. Raw HTML in it is never rendered, and links open apart from the lab.
 */
function Prose({ text }: { text: string }) {
  return <div className="run-workspace__prose"><Markdown remarkPlugins={[remarkGfm]} components={{
    a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
  }}>{text}</Markdown></div>;
}

/** The first line of a model's text, without the Markdown marks that would show as symbols. */
const firstLine = (text: string): string => (text.split("\n").find((line) => line.trim()) ?? "")
  .replace(/[#*_`>|]+/g, "").replace(/\s+/g, " ").trim().slice(0, 90);

/**
 * What a critic found in a team's arrangement, from its point of view, and what came of it: the
 * builder's answer and whether the engine found it better.
 */
function Critique({ lane }: { lane: AgentLaneDoc }) {
  const { t, number } = useI18n();
  const critique = lane.critique, revision = lane.revision;
  if (!critique) return null;
  const score = (value: number | null | undefined) => value == null ? "—" : number(value, 5);
  return <details className="run-workspace__trace-item run-workspace__critique" open><summary>
    <span className="run-workspace__trace-symbol">⚔</span><strong>{t("Critique")}</strong>
    <span>{agentName(lane.id, t)}</span>
    {revision && <small className={revision.paid ? "is-paid" : undefined}>{t(revision.paid ? "paid off" : "no gain")}</small>}
  </summary>
    <dl>
      <dt>{t("Weakest point")}</dt><dd>{critique.flaw}</dd>
      {critique.evidence && <><dt>{t("The engine's numbers")}</dt><dd>{critique.evidence}</dd></>}
      {critique.move && <><dt>{t("Move proposed")}</dt><dd>{critique.move}</dd></>}
      {revision && <><dt>{t("The builder's answer")}</dt><dd>{revision.answer ? <Prose text={revision.answer} /> : "—"}</dd>
        <dt>{t("Best score")}</dt><dd>{score(revision.before)} → <strong>{score(revision.after)}</strong></dd></>}
    </dl>
  </details>;
}

/** A tool call's input and result; a program is shown as code, and what it printed as text. */
function Exchange({ input, result }: { input: unknown; result: unknown }) {
  const { t } = useI18n();
  const code = typeof input === "object" && input !== null && typeof (input as { code?: unknown }).code === "string"
    ? (input as { code: string }).code : null;
  const printed = typeof result === "object" && result !== null && typeof (result as { printed?: unknown }).printed === "string"
    ? (result as { printed: string }).printed : null;
  const rest = printed === null ? result : Object.fromEntries(Object.entries(result as object).filter(([key]) => key !== "printed"));
  return <>
    <details open={code !== null}><summary>{t(code === null ? "Input" : "Program")}</summary>
      <pre className={code === null ? undefined : "run-workspace__code"}>{code ?? print(input)}</pre></details>
    {printed ? <details open><summary>{t("Printed output")}</summary><pre>{printed}</pre></details> : null}
    <details><summary>{t("Result")}</summary><pre>{print(rest)}</pre></details>
  </>;
}

function TurnDetail({ step, steps, event, onEvent }: {
  step: AgentRunStepDoc; steps: AgentRunStepDoc[]; event: AgentToolEventDoc | null; onEvent: (event: AgentToolEventDoc) => void;
}) {
  const { t, number } = useI18n();
  const [filter, setFilter] = useState<"all" | "tools" | "models">("all");
  type ModelMessage = NonNullable<AgentRunStepDoc["model_messages"]>[number];
  type TraceItem = { kind: "model"; order: number; value: ModelMessage } | { kind: "tool"; order: number; value: AgentToolEventDoc };
  const messages = step.model_messages ?? [];
  const tools = step.events ?? [];
  const hasOrder = [...messages, ...tools].every((item) => item.message_index !== undefined);
  // A turn writes one note at most: the ones written up to this turn, newest first.
  const notes = steps.flatMap((item) => item.round <= step.round && item.note ? [{ round: item.round, note: item.note }] : []).reverse();
  const trace: TraceItem[] = [
    ...messages.map((value) => ({ kind: "model" as const, order: value.message_index ?? value.index, value })),
    ...tools.map((value) => ({ kind: "tool" as const, order: value.message_index ?? messages.length + value.index, value })),
  ].sort((a, b) => a.order - b.order || (a.kind === "model" ? -1 : 1));
  const visible = trace.filter((item) => filter === "all" || (filter === "tools" ? item.kind === "tool" : item.kind === "model"));
  return <div className="run-workspace__detail">
    <h3>{t("Step")} {step.round + 1} <span className={step.valid ? "status status--valid" : "status status--invalid"}>{step.valid == null ? "—" : t(step.valid ? "valid" : "invalid")}</span></h3>
    {step.reason && <p className="run-workspace__reason"><small>{t("Agent's stated reason")}</small> “{step.reason}”</p>}
    {step.verdict && !step.valid && <div className="run-workspace__failures">{step.verdict.validation.results.filter((result) => !result.valid)
      .map((result) => <p key={result.constraint}>{t(result.constraint.replaceAll("_", " "))} · {result.violations.length} · {number(result.severity)}</p>)}</div>}
    {step.plan && <details className="run-workspace__trace-item" open><summary>
      <span className="run-workspace__trace-symbol">✳</span><strong>{t("Turn plan")}</strong></summary>
      <Prose text={step.plan} /></details>}
    {(step.lanes ?? []).map((lane) => lane.critique && <Critique key={lane.id} lane={lane} />)}
    {trace.length ? <>
      <div className="run-workspace__trace-heading"><strong>{t("Model and tool trace")}</strong><div role="group" aria-label={t("Trace filter")}>
        {(["all", "tools", "models"] as const).map((choice) => <button key={choice} type="button" aria-pressed={filter === choice}
          onClick={() => setFilter(choice)}>{t(choice === "all" ? "All" : choice === "tools" ? "Tool calls" : "Model replies")}</button>)}
      </div></div>
      {!hasOrder && <p className="run-workspace__trace-legacy">{t("Exact message order was not recorded for this older run.")}</p>}
      <ol className="run-workspace__trace">{visible.map((item) => <li key={`${item.kind}-${item.value.index}`}>
        {item.kind === "model" ? (() => {
          const message = item.value;
          const tokens = message.tokens_out ?? (message.content ? Math.ceil(message.content.length / 4) : null);
          return <details className="run-workspace__trace-item run-workspace__trace-item--model"><summary>
            <span className="run-workspace__trace-symbol">✳</span><strong>{t("Model reply")} {message.index + 1}</strong>
            {(message.branch_id || message.tool_calls) ? <span>{[
              message.branch_id && agentName(message.branch_id, t),
              message.tool_calls && `${message.tool_calls} ${t("tool requests")}`,
            ].filter(Boolean).join(" · ")}</span> : null}
            {tokens !== null && <small>{message.tokens_out == null ? "≈" : ""}{number(tokens, 0)} {t("output tokens")}</small>}
          </summary>
            {message.content ? <Prose text={message.content} /> : <p className="muted">{t("The model requested tools without a text message.")}</p>}
            {message.reasoning && <details><summary>{t("Provider-visible reasoning")}</summary><pre>{message.reasoning}</pre></details>}
          </details>;
        })() : <details className={`run-workspace__trace-item run-workspace__trace-item--tool${event?.index === item.value.index ? " is-active" : ""}`}
          onToggle={(e) => { if (e.currentTarget.open) onEvent(item.value as AgentToolEventDoc); }}><summary>
          <span className="run-workspace__trace-symbol">↳</span><strong><code>{item.value.tool}</code></strong>
          {item.value.branch_id && <span>{t("Agent")} {agentName(item.value.branch_id, t)}</span>}
          <small>{t(item.value.status)}</small>
        </summary>
          <Exchange input={item.value.input} result={item.value.result} />
        </details>}
      </li>)}</ol>
    </> : <p className="muted">{step.tools.join(" → ") || (step.tool_calls > 0 ? `${step.tool_calls} ${t("tools")} · ${t("Trace unavailable")}` : t("No tools called"))}</p>}
    {notes.length > 0 && <div className="run-workspace__memory"><strong>{t("the agent's notes")}</strong>
      {notes.map((item, index) => <details key={item.round} className="run-workspace__trace-item" open={index === 0}><summary>
        <span className="run-workspace__trace-symbol">✎</span><strong>{t("Written at turn")} {item.round + 1}</strong>
        <span>{firstLine(item.note)}</span>
      </summary><Prose text={item.note} /></details>)}
    </div>}
  </div>;
}
