import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { ReactFlow, Background, Handle, MarkerType, Position, useNodesInitialized, useReactFlow, useStore } from "@xyflow/react";
import type { Edge, Node, NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { useI18n } from "../i18n";
import type { WorkflowManifestDoc } from "../types";

type DiagramData = { label: string; kind: string; active: boolean; subtitle: string };

type Point = { x: number; y: number };

/** A step that runs as several agents at once is drawn as its first copy, a "⋯" and its last. */
const COPIES = ["1", "more", "n"];

/**
 * Place every step from the arrows alone: a step sits one row below the lowest step leading to
 * it, steps on the same row sit side by side, and the end sits beside the step that ends the run.
 * An arrow back to a step already on the way down closes a loop and is drawn up the left side.
 */
function layout(links: { from: string; to: string }[]): { at: Record<string, Point>; loops: Set<string>; row: Record<string, number> } {
  const loops = new Set<string>();
  const open = new Set<string>();
  const seen = new Set<string>();
  const walk = (id: string) => {
    open.add(id); seen.add(id);
    for (const { to } of links.filter((link) => link.from === id)) {
      if (open.has(to)) loops.add(`${id}>${to}`); else if (!seen.has(to)) walk(to);
    }
    open.delete(id);
  };
  walk("start");
  const forward = links.filter((link) => !loops.has(`${link.from}>${link.to}`));
  const row: Record<string, number> = { start: 0 };
  for (let pass = 0; pass < links.length; pass++) {
    for (const { from, to } of forward) {
      const above = row[from];
      if (above !== undefined) row[to] = Math.max(row[to] ?? 0, to === "end" ? above : above + 1);
    }
  }
  const at: Record<string, Point> = {};
  const rows: string[][] = [];
  for (const id of [...seen].filter((id) => id !== "end")) (rows[row[id] ?? 0] ??= []).push(id);
  // Every row is centred on one axis, so a step that fans out sits above the middle of its copies.
  rows.forEach((ids, index) => ids.forEach((id, column) => {
    at[id] = { x: (column - (ids.length - 1) / 2) * 280, y: 20 + index * 120 };
  }));
  const beside = rows[row.end ?? 0] ?? [];
  at.end = { x: (beside.length + 1) / 2 * 280, y: 28 + (row.end ?? 0) * 120 };
  return { at, loops, row };
}

/** What enters and what leaves any workflow; each step's own details come from its manifest. */
const ENDS: Record<string, string[]> = {
  start: ["The problem and the run's limits enter the run."],
  end: ["The run keeps the best valid arrangement and the full trace of every turn."],
};

function WorkflowBlock({ data }: NodeProps<Node<DiagramData>>) {
  if (data.kind === "more") return <div className="flow-more" aria-hidden="true">⋯</div>;
  return (
    <div className={`flow-block flow-block--${data.kind}${data.active ? " flow-block--active" : ""}`}>
      <Handle id="top" type="target" position={Position.Top} />
      <Handle id="left" type="target" position={Position.Left} />
      <span className="flow-block__symbol" aria-hidden="true">{data.kind === "agent" ? "✳" : data.kind === "route" ? "◇" : data.kind === "end" ? "■" : "○"}</span>
      <span className="flow-block__body"><strong>{data.label}</strong><small>{data.subtitle}</small></span>
      <span className="flow-block__open" aria-hidden="true">↗</span>
      <Handle id="bottom" type="source" position={Position.Bottom} />
      <Handle id="right" type="source" position={Position.Right} />
      <Handle id="back" type="source" position={Position.Left} />
    </div>
  );
}

const nodeTypes = { block: WorkflowBlock };

/** How the view frames the nodes: wider on the left, where a loop's label hangs outside them. */
const FIT = { padding: { top: .12, right: .12, bottom: .12, left: "84px" } } as const;

/**
 * Frame the whole workflow again when its box changes size: a diagram first drawn in a hidden
 * tab would otherwise keep the scale it opened at. Another workflow remounts the diagram.
 */
function Refit() {
  const { fitView } = useReactFlow();
  const ready = useNodesInitialized();
  const width = useStore((state) => state.width);
  const height = useStore((state) => state.height);
  useEffect(() => {
    if (ready && width > 0 && height > 0) void fitView(FIT);
  }, [ready, width, height, fitView]);
  return null;
}

function GraphButtons({ expanded, onExpand }: { expanded: boolean; onExpand: () => void }) {
  const { fitView, zoomIn, zoomOut } = useReactFlow();
  const { t } = useI18n();
  return <div className="workflow-graph__controls" onPointerDown={(event) => event.stopPropagation()}>
    <button type="button" aria-label={t("Zoom in")} onClick={() => void zoomIn({ duration: 180 })}>+</button>
    <button type="button" aria-label={t("Zoom out")} onClick={() => void zoomOut({ duration: 180 })}>−</button>
    <button type="button" aria-label={t("Reset workflow view")} onClick={() => void fitView({ ...FIT, duration: 240 })}>↻</button>
    <button type="button" aria-label={t(expanded ? "Close large workflow view" : "Open large workflow view")}
      onClick={onExpand}>{expanded ? "×" : "⛶"}</button>
  </div>;
}

export function WorkflowGraph({ workflow, active, onPick, onTools }: {
  workflow: WorkflowManifestDoc;
  active: string | null;
  onPick: (id: string) => void;
  /** Open the tool viewer, offered from an agent step. */
  onTools?: () => void;
}) {
  const { t } = useI18n();
  const [selected, setSelected] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    if (!expanded) return;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") setExpanded(false); };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [expanded]);
  // A parallel step becomes its copies, and every arrow to or from it fans out to each of them.
  const drawn = useMemo(() => {
    const parallel = new Set(workflow.nodes.filter((node) => node.parallel).map((node) => node.id));
    return (id: string) => parallel.has(id) ? COPIES.map((copy) => `${id}#${copy}`) : [id];
  }, [workflow]);
  const links = useMemo(() => [{ from: "start", to: workflow.nodes[0]?.id ?? "end", label: "" }, ...workflow.edges]
    .flatMap((edge) => {
      const froms = drawn(edge.from), tos = drawn(edge.to);
      // Two parallel steps are joined copy to copy: each team goes on in its own lane.
      if (froms.length > 1 && tos.length > 1) return froms.map((from, index) => ({ ...edge, from, to: tos[index] ?? from }));
      return froms.flatMap((from) => tos.map((to) => ({ ...edge, from, to })));
    }),
  [workflow, drawn]);
  const { at, loops, row } = useMemo(() => layout(links), [links]);
  const nodes = useMemo<Node<DiagramData>[]>(() => [
    { id: "start", label: "Input", kind: "start", help: "problem" },
    ...workflow.nodes,
    { id: "end", label: "End", kind: "end", help: "Result" },
  ].flatMap((node) => drawn(node.id).map((id) => {
    const copy = id.split("#")[1];
    return {
      id, type: "block", draggable: false,
      position: (copy === undefined && "position" in node ? node.position : undefined) ?? at[id] ?? { x: 0, y: 20 },
      data: {
        label: copy === undefined ? t(node.label) : `${t(node.label)} ${copy}`,
        kind: copy === "more" ? "more" : node.kind, active: node.id === active,
        subtitle: node.kind === "agent" ? t("Agent proposal") : node.kind === "route" ? t("Decision") : t(node.help),
      },
    };
  })), [workflow, drawn, at, active, t]);
  // The "⋯" between copies stands for the others: it is placed like them, but drawn without arrows.
  const edges = useMemo<Edge[]>(() => links.filter((edge) => !`${edge.from} ${edge.to}`.includes("#more")).map((edge) => {
    const loop = loops.has(`${edge.from}>${edge.to}`);
    const aside = edge.to === "end" && row[edge.from] === row.end;
    // A loop goes up the left of every row it passes: blocks are 180 to 260 wide, so its lane is
    // set from the leftmost centre of those rows, and from the least room its own ends can have.
    const passed = Object.keys(at).filter((id) => id !== "end"
      && (row[id] ?? 0) >= (row[edge.to] ?? 0) && (row[id] ?? 0) <= (row[edge.from] ?? 0));
    const left = Math.min(...passed.map((id) => at[id]?.x ?? 0));
    const ends = Math.min(at[edge.from]?.x ?? 0, at[edge.to]?.x ?? 0);
    return {
      id: `${edge.from}-${edge.to}`, source: edge.from, target: edge.to, type: "smoothstep",
      pathOptions: loop ? { offset: Math.max(20, ends - 90 - (left - 160)) } : undefined,
      sourceHandle: loop ? "back" : aside ? "right" : "bottom",
      targetHandle: loop || aside ? "left" : "top",
      // A router's answers are keys the graph reads; "again" and "done" have a word of their own.
      label: edge.label === "again" ? t("Repeat") : edge.label === "done" ? t("stop") : edge.label ? t(edge.label) : undefined,
      style: { stroke: loop ? "#a474b4" : "#9b82ab", strokeWidth: 2 },
      markerEnd: { type: MarkerType.ArrowClosed, color: "#9b82ab" },
    };
  }), [links, loops, row, at, t]);
  const picked = selected === "start" ? { label: "Input", help: "problem", kind: "start", details: ENDS.start }
    : selected === "end" ? { label: "End", help: "Result", kind: "end", details: ENDS.end }
    : workflow.nodes.find((node) => node.id === selected);
  const diagram = (large: boolean) => <div className={`workflow-graph${large ? " workflow-graph--large" : ""}`}>
      {/* A middle-button press would start the browser's autoscroll; here it pans, as the left one does. */}
      {/* A taller workflow gets a taller box, so that framed whole it stays readable. */}
      <div className="workflow-graph__canvas" onMouseDownCapture={(event) => { if (event.button === 1) event.preventDefault(); }}
        style={large ? undefined : { height: `clamp(285px, ${(Math.max(0, ...Object.values(row)) + 1) * 52}px, 480px)` }}>
        <ReactFlow key={workflow.name} nodes={nodes} edges={edges} nodeTypes={nodeTypes} nodeOrigin={[0.5, 0]} fitView fitViewOptions={FIT}
          minZoom={0.2} maxZoom={large ? 3 : 1.5}
          nodesDraggable={false} nodesConnectable={false} elementsSelectable panOnDrag={[0, 1]} zoomOnScroll
          proOptions={{ hideAttribution: true }}
          onNodeClick={(_, node) => { const id = node.id.split("#")[0] ?? node.id; setSelected(id); onPick(id); }}>
          <Background color="#d9cbdd" gap={24} size={1} />
          <Refit />
          <GraphButtons expanded={large} onExpand={() => setExpanded(!large)} />
        </ReactFlow>
      </div>
      {picked && <div className="workflow-graph__detail"><strong>{t(picked.label)}</strong><span>{t(picked.help)}</span>
        {(picked.details ?? []).length > 0 && <ul>
          {(picked.details ?? []).map((line) => <li key={line}>{t(line)}</li>)}
        </ul>}
        {picked.kind === "agent" && (picked as { tools?: boolean }).tools !== false && onTools && <button type="button" className="workflow-graph__tools" onClick={onTools}>
          {t("See the agent's tools")}</button>}
      </div>}
    </div>;
  return <>{diagram(false)}{expanded && createPortal(<div className="workflow-graph__overlay" role="presentation"
    onMouseDown={(event) => { if (event.target === event.currentTarget) setExpanded(false); }}>
    <section className="workflow-graph__dialog" role="dialog" aria-modal="true" aria-label={t("Workflow detail")}>
      <header><h2>{t(workflow.name)}</h2><button type="button" onClick={() => setExpanded(false)} aria-label={t("Close")}>×</button></header>
      {diagram(true)}
    </section>
  </div>, document.body)}</>;
}
