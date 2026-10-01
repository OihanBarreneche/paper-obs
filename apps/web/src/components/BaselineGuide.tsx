/**
 * How each classical method works, in a few steps with a schema each.
 *
 * The methods are `search/baselines.py`; this window tells them in words, so a figure
 * quoted here (a shake of 30 %, 24 probes, 21 judgements a hop) follows the constant it
 * names there. A new baseline adds one entry to `GUIDES`, and with it one tab.
 */
import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { useI18n } from "../i18n";
import "./ToolViewer.css";
import "./BaselineGuide.css";

type Guide = {
  /** The engine's name of the baseline, as the method menu lists it. */
  name: string;
  role: string;
  intro: string;
  steps: { title: string; text: string; figure: ReactNode }[];
  cost: string;
  limit: string;
};

const GUIDES: Guide[] = [
  {
    name: "lattice",
    role: "The floor: what a plain construction reaches.",
    intro: "Lays the shapes on a regular lattice, then makes them as large as the engine still accepts. Nothing is drawn at random: two runs give the same arrangement.",
    steps: [
      { title: "Lay the shapes on a lattice", figure: <Lattices />,
        text: "The shapes go on a square grid. For discs, a staggered lattice is tried too, every other row shifted by half a spacing. The engine judges both, and the run keeps the one it ranks higher." },
      { title: "Grow them by halving", figure: <Halving />,
        text: "Between a scale known to fit and the largest possible one, the run tries the middle. Accepted, it becomes the new floor; refused, the new ceiling. Each probe halves the gap, and 24 probes pin the scale to a millionth." },
    ],
    cost: "One judgement per lattice, then one per probe: 26 at most.",
    limit: "The shapes never leave their lattice, so the run cannot find an irregular arrangement, which is often the best one.",
  },
  {
    name: "basin_hopping",
    role: "The reference: the agents' own tools, applied without reasoning.",
    intro: "Starts from the better lattice, then repeats one hop: shake, polish, keep if better. This is monotonic basin hopping, a classical search for packings, run with the polish tool the agents call.",
    steps: [
      { title: "Shake", figure: <Shake />,
        text: "Every shape of the best arrangement moves at random by up to 30 % of its size, and turns by up to 30° where rotation is free. The contacts break, and shapes often overlap." },
      { title: "Polish", figure: <Polish />,
        text: "The polish tool first pushes the overlapping shapes apart, then tries small moves and keeps each one the engine prefers. The arrangement settles at the bottom of the nearest basin." },
      { title: "Keep or drop", figure: <Hops />,
        text: "The engine judges the result, which replaces the best arrangement only if it ranks higher. The next hop starts from the best either way, and five hops in a row without progress stop the run." },
    ],
    cost: "21 judgements a hop: twenty polish steps and the verdict, until the budget runs out.",
    limit: "The hops are blind: on a large problem, most of them land in a worse basin.",
  },
];

export function BaselineGuide({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const [picked, setPicked] = useState(GUIDES[0]?.name);
  const guide = GUIDES.find((item) => item.name === picked) ?? GUIDES[0]!;
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [onClose]);
  return createPortal(<div className="tool-viewer__overlay" role="presentation"
    onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="tool-viewer baseline-guide" role="dialog" aria-modal="true" aria-label={t("How the classical methods work")}>
      <header className="tool-viewer__header">
        <div>
          <h2>{t("How the classical methods work")}</h2>
          <p>{t("Each method proposes arrangements, and the engine judges every one: a judgement is the unit of a method's budget.")}</p>
        </div>
        <button type="button" onClick={onClose} aria-label={t("Close")}>×</button>
      </header>
      <div className="tool-viewer__filters" role="tablist" aria-label={t("Classical methods")}>
        {GUIDES.map((item) => <button type="button" role="tab" key={item.name} aria-selected={item === guide}
          onClick={() => setPicked(item.name)}>{t(item.name.replaceAll("_", " "))}</button>)}
      </div>
      <article className="baseline-guide__body" role="tabpanel">
        <p className="baseline-guide__role">{t(guide.role)}</p>
        <p>{t(guide.intro)}</p>
        <ol className="baseline-guide__steps">{guide.steps.map((step) => <li key={step.title}>
          <div><h3>{t(step.title)}</h3><p>{t(step.text)}</p></div>
          <figure>{step.figure}</figure>
        </li>)}</ol>
        <dl className="tool-viewer__facts">
          <dt>{t("Cost")}</dt><dd>{t(guide.cost)}</dd>
          <dt>{t("Limit")}</dt><dd>{t(guide.limit)}</dd>
        </dl>
      </article>
    </section>
  </div>, document.body);
}

/* The schemas: drawn by hand, in the units of a 260 × 130 box. */

const INK = "#644776", SHAPE = "#d9c2e0", GOOD = "#2f8a57", BAD = "#b9483f";

function Figure({ label, children }: { label: string; children: ReactNode }) {
  return <svg viewBox="0 0 260 130" role="img" aria-label={label}>{children}</svg>;
}

function Disc({ x, y, r, dashed = false }: { x: number; y: number; r: number; dashed?: boolean }) {
  return <circle cx={x} cy={y} r={r} fill={dashed ? "none" : SHAPE} fillOpacity={0.75} stroke={INK}
    strokeWidth={dashed ? 1 : 1.5} strokeDasharray={dashed ? "3 3" : undefined} />;
}

/** The arrow head the schemas draw, defined in each figure that points with one. */
const ARROW = <defs><marker id="baseline-guide-arrow" viewBox="0 0 8 8" refX={7} refY={4} markerWidth={7} markerHeight={7} orient="auto">
  <path d="M0 0L8 4L0 8z" fill={INK} /></marker></defs>;

function Box({ left, children }: { left: number; children: ReactNode }) {
  return <g transform={`translate(${left} 6)`}>
    <rect width={100} height={100} fill="none" stroke="#3d2d48" strokeWidth={1.5} />{children}
  </g>;
}

function Lattices() {
  const { t } = useI18n();
  const panels = [
    { left: 10, name: "grid", centres: [18, 50, 82].flatMap((y) => [18, 50, 82].map((x) => [x, y] as const)) },
    { left: 150, name: "staggered", centres: [18, 46, 74].flatMap((y, row) => (row % 2 ? [34, 66] : [18, 50, 82]).map((x) => [x, y] as const)) },
  ];
  return <Figure label={t("A grid and a staggered lattice")}>
    {panels.map((panel) => <Box key={panel.name} left={panel.left}>
      {panel.centres.map(([x, y]) => <Disc key={`${x} ${y}`} x={x} y={y} r={15} />)}
      <text x={50} y={120} textAnchor="middle">{t(panel.name)}</text>
    </Box>)}
  </Figure>;
}

function Halving() {
  const { t } = useI18n();
  // Each bracket is the gap still open, and its middle the probe the engine judges.
  const brackets = [[20, 240, true], [130, 240, false], [130, 185, true]] as const;
  return <Figure label={t("The scale found by halving")}>
    {ARROW}
    {brackets.map(([low, high, accepted], index) => {
      const y = 22 + index * 26, middle = (low + high) / 2, colour = accepted ? GOOD : BAD;
      return <g key={index}>
        <path d={`M${low} ${y - 4}v8M${low} ${y}H${high}M${high} ${y - 4}v8`} stroke="#b7a3bf" strokeWidth={1.5} fill="none" />
        <circle cx={middle} cy={y} r={4.5} fill={colour} />
        <text x={middle + 8} y={y - 5} style={{ fill: colour }}>{accepted ? "✓" : "✗"}</text>
      </g>;
    })}
    <path d="M20 104H240" stroke={INK} strokeWidth={1.5} markerEnd="url(#baseline-guide-arrow)" />
    <text x={20} y={122}>{t("fits")}</text>
    <text x={130} y={122} textAnchor="middle">{t("scale")}</text>
    <text x={240} y={122} textAnchor="end">{t("too large")}</text>
  </Figure>;
}

function Shake() {
  const { t } = useI18n();
  const before = [[27, 27], [73, 27], [27, 73], [73, 73]] as const;
  const moves = [[8, -5], [-9, 6], [6, 4], [-5, -8]] as const;
  return <Figure label={t("A shaken arrangement")}>
    {ARROW}
    <Box left={10}>{before.map(([x, y]) => <Disc key={`${x} ${y}`} x={x} y={y} r={22} />)}</Box>
    <path d="M118 56h22" stroke={INK} strokeWidth={1.5} markerEnd="url(#baseline-guide-arrow)" />
    <Box left={150}>
      {before.map(([x, y]) => <Disc key={`${x} ${y}`} x={x} y={y} r={22} dashed />)}
      {before.map(([x, y], index) => <Disc key={index} x={x + (moves[index]?.[0] ?? 0)} y={y + (moves[index]?.[1] ?? 0)} r={22} />)}
    </Box>
  </Figure>;
}

/** A landscape as a path: its height at each x, lower on the page being better. */
function landscape(height: (x: number) => number): string {
  return Array.from({ length: 49 }, (_, index) => 10 + index * 5)
    .map((x, index) => `${index ? "L" : "M"}${x} ${height(x).toFixed(1)}`).join("");
}

const valley = (x: number, at: number, depth: number, width: number) => depth * Math.exp(-(((x - at) / width) ** 2));

function Polish() {
  const { t } = useI18n();
  const ball = (x: number) => 15 + valley(x, 140, 80, 55);
  return <Figure label={t("A shaken arrangement settling into its basin")}>
    <path d={landscape((x) => ball(x) + 7)} stroke={INK} strokeWidth={1.5} fill="none" />
    {[76, 92, 108, 124].map((x) => <circle key={x} cx={x} cy={ball(x)} r={2} fill="#b7a3bf" />)}
    <circle cx={60} cy={ball(60)} r={6} fill="none" stroke={INK} strokeWidth={1.5} strokeDasharray="2 2" />
    <circle cx={140} cy={ball(140)} r={6} fill={INK} />
    <text x={60} y={ball(60) - 11} textAnchor="middle">{t("shaken")}</text>
    <text x={140} y={124} textAnchor="middle">{t("settled")}</text>
  </Figure>;
}

function Hops() {
  const { t } = useI18n();
  const ball = (x: number) => 13 + valley(x, 55, 48, 22) + valley(x, 135, 80, 22) + valley(x, 212, 38, 20);
  const hop = (from: number, to: number) =>
    `M${from} ${ball(from) - 7}Q${(from + to) / 2} ${Math.min(ball(from), ball(to)) - 90} ${to} ${ball(to) - 9}`;
  return <Figure label={t("Hops between basins, kept only when better")}>
    <text x={10} y={10}>{t("lower is better")}</text>
    <path d={landscape((x) => ball(x) + 7)} stroke={INK} strokeWidth={1.5} fill="none" />
    <path d={hop(55, 135)} stroke={GOOD} strokeWidth={1.5} strokeDasharray="4 3" fill="none" />
    <path d={hop(135, 212)} stroke={BAD} strokeWidth={1.5} strokeDasharray="4 3" fill="none" />
    <circle cx={55} cy={ball(55)} r={6} fill="none" stroke={INK} strokeWidth={1.5} />
    <circle cx={135} cy={ball(135)} r={6} fill={INK} />
    <circle cx={212} cy={ball(212)} r={6} fill="none" stroke={BAD} strokeWidth={1.5} strokeDasharray="2 2" />
    <text x={135} y={124} textAnchor="middle" style={{ fill: GOOD }}>✓ {t("kept")}</text>
    <text x={212} y={ball(212) + 26} textAnchor="middle" style={{ fill: BAD }}>✗ {t("dropped")}</text>
  </Figure>;
}
