import { useId, useState } from "react";

import { useI18n } from "../i18n";
import type { AgentRunSummaryDoc, WorkflowManifestDoc } from "../types";
import { elapsed } from "./RunWorkspace";
import { useWidth } from "./useWidth";

/** One colour per compared run, the open one first. */
const COLOURS = ["#7c5aa6", "#c9748f", "#3f8a9e", "#c29a4a", "#5f9468", "#9a6f55", "#5b6fb3", "#b35b5b"];

type Run = AgentRunSummaryDoc;

/**
 * The open run beside any others of its problem: how each one's best progressed turn by turn,
 * and what each spent. Everything comes from the run listing, so comparing many runs reads no
 * run document.
 */
export function RunsComparison({ current, runs, workflows }: {
  current: string;
  runs: Run[];
  workflows: WorkflowManifestDoc[];
}) {
  const { t, number } = useI18n();
  const [chosen, setChosen] = useState<string[]>([]);
  const self = runs.find((run) => run.run_id === current);
  if (self === undefined) return null;
  const others = runs.filter((run) => run.problem_id === self.problem_id && run.run_id !== current);
  const shown = [self, ...others.filter((run) => chosen.includes(run.run_id))];
  const colour = (run: Run) => COLOURS[shown.indexOf(run) % COLOURS.length] ?? "#888";
  const all = others.length > 0 && others.every((run) => chosen.includes(run.run_id));
  const workflowName = (run: Run) => t(workflows.find((item) => item.id === run.workflow)?.name ?? run.workflow);
  const name = (run: Run) => run.name ?? workflowName(run);
  // A gap to the record reads the same on every run of the problem; the engine's score is the
  // fallback where the problem has no comparable record.
  const byGap = shown.every((run) => run.track.every((point) => point[2] != null));
  const best = (run: Run) => {
    const last = run.track[run.track.length - 1];
    if (last === undefined) return "—";
    return byGap && last[2] != null ? gap(last[2], number) : number(last[1] ?? 0, 6);
  };
  return <div className="run-compare">
    {others.length === 0 ? <p className="muted">{t("No other run on this problem yet.")}</p> : <>
      <div className="run-compare__choices">
        <button type="button" className="run-compare__all" aria-pressed={all}
          onClick={() => setChosen(all ? [] : others.map((run) => run.run_id))}>{t("All runs of this problem")}</button>
        {others.map((run) => {
          const on = chosen.includes(run.run_id);
          return <button key={run.run_id} type="button" aria-pressed={on}
            onClick={() => setChosen(on ? chosen.filter((id) => id !== run.run_id) : [...chosen, run.run_id])}>
            <i style={on ? { background: colour(run), borderColor: colour(run) } : undefined} />
            {name(run)} <small>{best(run)}</small></button>;
        })}
      </div>
      {shown.length > 1 && <>
        <Progress runs={shown} byGap={byGap} colour={colour} name={name} />
        <div className="run-compare__table"><table>
          <thead><tr><th>{t("Compared run")}</th><th>{t(byGap ? "Gap to the record" : "Best score")}</th>
            <th>{t("turns")}</th><th>{t("duration")}</th><th>{t("cost")}</th></tr></thead>
          <tbody>{shown.map((run) => <tr key={run.run_id} className={run === self ? "is-current" : undefined}>
            <td title={name(run)}><i style={{ background: colour(run) }} /><b>{workflowName(run).split(" · ")[0]}</b> {name(run)}</td>
            <td><strong>{best(run)}</strong></td>
            <td>{run.round}</td><td>{elapsed(run.seconds, t)}</td>
            <td>{run.spend.cost == null ? "—" : `${number(run.spend.cost, 3)} $`}</td>
          </tr>)}</tbody>
        </table></div>
      </>}
    </>}
  </div>;
}

const gap = (value: number, number: (value: number, digits?: number) => string, digits = 3) =>
  `${value > 0 ? "+" : value < 0 ? "−" : ""}${number(Math.abs(value) * 100, digits)} %`;

/** The part of the chart on screen: a range of turns, and a range of values or null to fit them. */
type Window = { x0: number; x1: number; y0: number | null; y1: number | null };
/** A rectangle being dragged, in the chart's own pixels. */
type Drag = { x: number; y: number; x2: number; y2: number };

/**
 * Each run's best so far, turn by turn: a step at every new best, held to the run's last turn.
 *
 * Dragging a rectangle zooms on it; a flat one zooms on those turns only and fits the values
 * they show, which is how runs a hundredth of a percent apart become readable.
 */
function Progress({ runs, byGap, colour, name }: {
  runs: Run[];
  byGap: boolean;
  colour: (run: Run) => string;
  name: (run: Run) => string;
}) {
  const { t, number } = useI18n();
  const [ref, width] = useWidth();
  const clip = useId();
  const [zoom, setZoom] = useState<Window | null>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const value = (point: Run["track"][number]) => (byGap ? point[2] : point[1]) ?? 0;
  const series = runs.map((run) => ({
    run,
    points: run.track.map((point) => ({ turn: point[0] + 1, level: value(point) })),
    end: Math.max(run.round, (run.track[run.track.length - 1]?.[0] ?? 0) + 1),
  }));
  const turns = Math.max(2, ...series.map((item) => item.end));
  const x0 = zoom?.x0 ?? 1, x1 = zoom?.x1 ?? turns;
  // The values to fit: every step inside the turns shown, or, for a run with none there, the level
  // it holds across them. A level a run leaves inside the window is not fitted: it would squash
  // the closing gaps the zoom is for.
  const seen = series.flatMap(({ points, end }) => {
    const inside = points.filter((item) => item.turn > x0 && item.turn <= x1).map((item) => item.level);
    const held = points.filter((item) => item.turn <= x0).pop();
    return inside.length > 0 ? inside : held && end >= x0 ? [held.level] : [];
  });
  let lo = zoom?.y0 ?? Math.min(...seen), hi = zoom?.y1 ?? Math.max(...seen);
  if (zoom === null && byGap) hi = Math.max(0, hi);
  if (!(hi > lo)) { const half = Math.abs(hi) * 0.01 || 0.001; lo -= half; hi += half; }
  const pad = zoom?.y0 != null ? 0 : (hi - lo) * 0.08;
  const low = lo - pad, high = hi + pad;
  const height = 240, left = 70, right = 14, top = 12, bottom = 30;
  const plotRight = width - right, plotBottom = height - bottom;
  const px = (turn: number) => left + ((turn - x0) / (x1 - x0)) * (plotRight - left);
  const py = (level: number) => top + ((high - level) / (high - low)) * (plotBottom - top);
  const turnAt = (x: number) => x0 + ((x - left) / (plotRight - left)) * (x1 - x0);
  const levelAt = (y: number) => high - ((y - top) / (plotBottom - top)) * (high - low);
  // Enough digits that the ticks of a narrow window still read apart.
  const span = (hi - lo) * (byGap ? 100 : 1);
  const digits = Math.min(6, Math.max(byGap ? 2 : 3, Math.ceil(-Math.log10(span / 3)) + 1));
  const label = (level: number) => byGap ? gap(level, number, digits) : number(level, digits);
  const ticks = [0, 1 / 3, 2 / 3, 1].map((share) => lo + share * (hi - lo));
  const every = Math.max(1, Math.ceil((Math.floor(x1) - Math.ceil(x0) + 1) / 6));
  const turnTicks: number[] = [];
  for (let turn = Math.ceil(x0); turn <= x1; turn += every) turnTicks.push(turn);

  const at = (event: React.PointerEvent<SVGRectElement>) => {
    const box = event.currentTarget.ownerSVGElement?.getBoundingClientRect();
    const x = event.clientX - (box?.left ?? 0), y = event.clientY - (box?.top ?? 0);
    return { x: Math.min(plotRight, Math.max(left, x)), y: Math.min(plotBottom, Math.max(top, y)) };
  };
  const finish = () => {
    if (drag === null) return;
    setDrag(null);
    const a = Math.min(drag.x, drag.x2), b = Math.max(drag.x, drag.x2);
    if (b - a < 6) return;
    const flat = Math.abs(drag.y2 - drag.y) < 10;
    setZoom({ x0: turnAt(a), x1: turnAt(b),
      y0: flat ? null : levelAt(Math.max(drag.y, drag.y2)), y1: flat ? null : levelAt(Math.min(drag.y, drag.y2)) });
  };

  return <div ref={ref} className="run-compare__chart">
    {seen.length === 0 ? <p className="muted">{t("No valid score to plot")}</p>
      : width > 0 && <svg width={width} height={height} role="img" aria-label={t("Best so far, turn by turn")}>
        <defs><clipPath id={clip}><rect x={left} y={top} width={plotRight - left} height={plotBottom - top} /></clipPath></defs>
        {ticks.map((level) => <g key={level}>
          <line x1={left} x2={plotRight} y1={py(level)} y2={py(level)} className="run-compare__grid" />
          <text x={left - 8} y={py(level) + 4} textAnchor="end">{label(level)}</text></g>)}
        {byGap && low <= 0 && 0 <= high && <>
          <line x1={left} x2={plotRight} y1={py(0)} y2={py(0)} className="run-compare__record" />
          <text x={plotRight} y={py(0) - 5} textAnchor="end" className="run-compare__strong">{t("record")}</text>
        </>}
        <line x1={left} x2={plotRight} y1={plotBottom} y2={plotBottom} className="run-compare__axis" />
        {turnTicks.map((turn, index) => <text key={turn} x={px(turn)} y={height - 10}
          textAnchor={index === 0 ? "start" : "middle"}>{index === 0 ? `${t("turn")} ${turn}` : turn}</text>)}
        <g clipPath={`url(#${clip})`}>{series.map(({ run, points, end }) => {
          const first = points[0];
          if (first === undefined) return null;
          const path = points.slice(1).reduce((line, item) => `${line} H ${px(item.turn)} V ${py(item.level)}`,
            `M ${px(first.turn)} ${py(first.level)}`) + ` H ${px(end)}`;
          return <g key={run.run_id} stroke={colour(run)} fill="none">
            <path d={path} strokeWidth={2.5} />
            {points.map((item) => <circle key={item.turn} cx={px(item.turn)} cy={py(item.level)} r={3.5} fill="#fffdfb" strokeWidth={2}>
              <title>{`${name(run)} · ${t("turn")} ${item.turn} · ${byGap ? gap(item.level, number, 4) : number(item.level, 6)}`}</title>
            </circle>)}
          </g>;
        })}</g>
        {drag && <rect className="run-compare__brush" x={Math.min(drag.x, drag.x2)} y={Math.min(drag.y, drag.y2)}
          width={Math.abs(drag.x2 - drag.x)} height={Math.abs(drag.y2 - drag.y)} />}
        <rect className="run-compare__surface" x={left} y={top} width={plotRight - left} height={plotBottom - top}
          onPointerDown={(event) => {
            event.currentTarget.setPointerCapture(event.pointerId);
            const point = at(event);
            setDrag({ ...point, x2: point.x, y2: point.y });
          }}
          onPointerMove={(event) => { if (drag) { const point = at(event); setDrag({ ...drag, x2: point.x, y2: point.y }); } }}
          onPointerUp={finish} onPointerCancel={() => setDrag(null)} />
      </svg>}
    <p className="run-compare__hint">{zoom
      ? <button type="button" onClick={() => setZoom(null)}>{t("Show every turn")}</button>
      : t("Drag across the chart to zoom: a flat stroke picks turns, a rectangle picks values too.")}</p>
  </div>;
}
