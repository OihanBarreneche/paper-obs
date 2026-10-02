import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useI18n } from "../i18n";
import "./QuickStart.css";

type Step = { title: string; body: string; target: string; side: "left" | "right" | "below" | "inside" | "center"; includeTop?: string; cardWidth?: number; gap?: number; arrowOffsetY?: number };

const STEPS: readonly Step[] = [
  {
    title: "Start with two squares",
    body: "Each small square has side length 1. The challenge is to arrange them inside the smallest possible square. Two copies fit side by side in a square of side 2. Try moving one: the measurements on the right follow your arrangement.",
    target: ".canvas-sheet", side: "right",
  },
  {
    title: "A first try with five squares",
    body: "Four squares form a 2 × 2 block; the fifth sits above it. This valid but naive arrangement needs a surrounding square of side 3, hence area 9. Look at the empty space and try a better arrangement.",
    target: ".canvas-sheet", side: "right",
  },
  {
    title: "A better construction",
    body: "Tilting one square lets all five fit in a square of side about 2.707, with area about 7.33. This case is proved optimal. On other problems, the published construction may only be a record that can still improve.",
    target: ".canvas-sheet", side: "right",
  },
  {
    title: "Eleven squares: beyond the grid",
    body: "A simple grid wastes space for 11 squares. The published construction offsets and tilts some copies. It is a best-known construction, not a proved optimum.",
    target: ".canvas-sheet", side: "right",
  },
  {
    title: "Seventeen squares: a surprising layout",
    body: "Ten squares stay aligned while seven are tilted. This almost meme-like published layout shows how strange a strong packing can look. No proof of optimality is known here.",
    target: ".canvas-sheet", side: "right",
  },
  {
    title: "Organize your problem lists",
    body: "Create lists for your own explorations. A list can hold problems from different families; select one to load its editable arrangement.",
    target: ".profile-picker__popover", side: "below",
  },
  {
    title: "Browse the catalog families",
    body: "Add a problem opens the catalog. Choose a broad family on the left, then filter the illustrated subfamilies by shape and container.",
    target: ".profile-catalog__sheet", side: "inside",
  },
  {
    title: "Choose a published instance",
    body: "Open a subfamily to see its different counts and published arrangements. Each card has a reference figure and value; adding it loads an editable problem.",
    target: ".profile-catalog__sheet", side: "inside",
  },
  {
    title: "Read the measurements",
    body: "The right page reports validity, the score and the reference. A proved optimum differs from a best-known construction: check the source and its last update before comparing results.",
    target: ".panel", side: "left", arrowOffsetY: 32,
  },
  {
    title: "Build a custom shape",
    body: "Create combines simple shapes. Add parts or cut them away, then save the result as a shape you can place in a problem.",
    target: ".canvas-sheet", side: "right",
  },
  {
    title: "Design an arena",
    body: "Arena edits the region in problems with a configurable container, including custom problems. This tab is unavailable when the objective itself fixes or measures the container.",
    target: ".workspace-tabs__tab--arena", side: "below",
  },
  {
    title: "Explore agent workflows",
    body: "LLMs can search for solutions through agent workflows. This is an instructive way to inspect orchestration, but it uses many tokens and is not necessarily the most effective optimization method. Compare it with classical search.",
    target: ".run-workspace", side: "center", cardWidth: 320,
  },
  {
    title: "Set the model and safeguards",
    body: "Choose a provider and model, then enter a key if needed. Fill in both token prices, check your provider quota, and always set run limits before starting. The key is kept in this browser and never written into a run file.",
    target: ".modal__panel", side: "left", cardWidth: 290, gap: 12,
  },
  {
    title: "Watch the agents work",
    body: "Choose a workflow and its limits, then follow each step, model message, tool call and candidate solution. You can stop a run while it is active. The statistics page, behind the chart icon in the header, compares every run.",
    target: ".run-workspace__process", includeTop: ".run-workspace__intro h1", side: "right",
  },
  {
    title: "Explore search methods",
    body: "Search compares methods without an LLM on the same geometry engine. It also follows free research: open this project in an agent such as Claude Code or Codex, ask it for a free research, and watch its session live here.",
    target: ".search-workspace__methods", side: "right",
  },
];

export const QUICK_START_STEPS = STEPS.length;

type Geometry = { focus: DOMRect; card: { x: number; y: number; width: number; height: number } };

function position(step: Step, focus: DOMRect, cardHeight: number): Geometry["card"] {
  const gap = step.gap ?? 44;
  const width = Math.min(step.cardWidth ?? 380, window.innerWidth - 32);
  if (step.side === "inside") return {
    x: Math.max(12, focus.right - width - 24),
    // A sheet taller than the window keeps the card on screen.
    y: Math.max(12, Math.min(focus.bottom, window.innerHeight) - cardHeight - 24),
    width, height: cardHeight,
  };
  if (step.side === "center") return {
    x: Math.max(12, (window.innerWidth - width) / 2),
    y: Math.max(12, Math.min(window.innerHeight - cardHeight - 12,
      focus.top + (Math.min(focus.bottom, window.innerHeight) - focus.top - cardHeight) / 2)),
    width, height: cardHeight,
  };
  let side = step.side;
  if (side === "right" && focus.right + gap + width > window.innerWidth - 12) side = "left";
  if (side === "left" && focus.left - gap - width < 12) side = "below";
  if (side === "below" && focus.bottom + gap + cardHeight > window.innerHeight - 12) {
    side = focus.right + gap + width < window.innerWidth - 12 ? "right" : "left";
  }
  const x = side === "right" ? focus.right + gap
    : side === "left" ? focus.left - gap - width
      : focus.left + (focus.width - width) / 2;
  const y = side === "below" ? focus.bottom + gap : focus.top + Math.min(18, focus.height / 5);
  return {
    x: Math.max(12, Math.min(window.innerWidth - width - 12, x)),
    y: Math.max(12, Math.min(window.innerHeight - cardHeight - 12, y)),
    width,
    height: cardHeight,
  };
}

/** A small, dismissible tour. It points to real controls and never runs a solver. */
export function QuickStart({ stepIndex, onStep, onClose }: {
  stepIndex: number;
  onStep: (index: number) => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const card = useRef<HTMLElement | null>(null);
  const [geometry, setGeometry] = useState<Geometry | null>(null);
  const [practice, setPractice] = useState(false);
  const step = STEPS[stepIndex] ?? STEPS[0]!;

  useEffect(() => setPractice(false), [stepIndex]);

  useLayoutEffect(() => {
    let frame = 0;
    let attempts = 0;
    setGeometry(null);
    const update = () => {
      const element = document.querySelector(step.target);
      const raw = element?.getBoundingClientRect();
      const heading = step.includeTop ? document.querySelector(step.includeTop)?.getBoundingClientRect() : null;
      const focus = raw && heading ? new DOMRect(raw.left, Math.min(raw.top, heading.top), raw.width,
        raw.bottom - Math.min(raw.top, heading.top)) : raw;
      if (!focus || focus.width === 0 || focus.height === 0) {
        if (attempts++ < 120) frame = requestAnimationFrame(update);
        return;
      }
      setGeometry({ focus, card: position(step, focus, card.current?.offsetHeight ?? 220) });
    };
    frame = requestAnimationFrame(update);
    const observer = new ResizeObserver(update);
    if (card.current) observer.observe(card.current);
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [step]);

  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); onClose(); }
    };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [onClose]);

  const focus = geometry?.focus;
  const box = geometry?.card;
  const targetX = focus ? box && box.x > focus.right
    ? focus.right - Math.min(65, focus.width / 5)
    : focus.left + Math.min(65, focus.width / 5) : 0;
  const targetY = focus ? focus.top + Math.min(focus.height / 2, step.arrowOffsetY ?? 90) : 0;
  const sourceX = box ? (box.x > targetX ? box.x : box.x + box.width) : 0;
  const sourceY = box ? box.y + Math.min(75, box.height / 2) : 0;

  return createPortal(<div className={`quick-start${practice ? " quick-start--practice" : ""}`} role="dialog" aria-modal={practice ? undefined : true} aria-label={t("Quick start")}>
    {!practice && <div className="quick-start__shade" />}
    {!practice && focus && <div className="quick-start__spotlight" style={{
      left: Math.max(5, focus.left - 7), top: Math.max(5, focus.top - 7),
      width: focus.width + 14, height: focus.height + 14,
    }} />}
    {!practice && focus && box && step.side !== "inside" && step.side !== "center" && <svg className="quick-start__arrow" viewBox={`0 0 ${window.innerWidth} ${window.innerHeight}`} aria-hidden="true">
      <defs><marker id="quick-start-arrowhead" markerUnits="userSpaceOnUse" markerWidth="14" markerHeight="14" refX="12" refY="7" orient="auto"><path d="M0 0 14 7 0 14" /></marker></defs>
      <path d={`M ${sourceX} ${sourceY} Q ${(sourceX + targetX) / 2} ${sourceY - 22} ${targetX} ${targetY}`} markerEnd="url(#quick-start-arrowhead)" />
    </svg>}
    <section ref={card} className="quick-start__card" style={practice
      ? { left: "auto", top: "auto", right: 20, bottom: 20, width: Math.min(320, window.innerWidth - 40) }
      : box ? { left: box.x, top: box.y, width: box.width } : { visibility: "hidden" }}>
      <div className="quick-start__meta"><span>{t("Quick start")}</span><span>{stepIndex + 1} / {STEPS.length}</span></div>
      <h2>{t(step.title)}</h2>
      <p>{t(practice ? "Experiment freely, then continue when ready." : step.body)}</p>
      <div className="quick-start__actions">
        {stepIndex > 0 ? <button type="button" className="quick-start__previous" onClick={() => onStep(stepIndex - 1)}>{t("Previous")}</button> : <span />}
        <button type="button" className="quick-start__skip" onClick={onClose}>{t("Skip guide")}</button>
        <button type="button" className="quick-start__next" onClick={() => stepIndex + 1 === STEPS.length ? onClose() : onStep(stepIndex + 1)}>
          {t(stepIndex + 1 === STEPS.length ? "Finish" : "Next")}
        </button>
        {!practice && <button type="button" className="quick-start__try" onClick={() => setPractice(true)}>{t("Try it")}</button>}
      </div>
    </section>
  </div>, document.body);
}
