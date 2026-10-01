/**
 * The control strip at the top of the window.
 *
 * It renders the current choices and reports what the user asked for, so the
 * application remains the only place where a request is built and sent. The state
 * it keeps is its own display state and nothing else: the busy label's delay and
 * the scale field's draft.
 *
 * Two details here exist because of a real complaint about flicker. The busy
 * label keeps its place in the layout whether or not it is showing, and it only
 * appears if the work lasts long enough to be worth mentioning — a verdict
 * usually comes back in a few milliseconds, and a label that blinks on and off
 * twenty times while a slider is dragged is worse than no label at all. For the
 * same reason the controls are *not* disabled while a request is in flight: a
 * disabled control loses focus and stops responding to the hand that is using
 * it, and the application's throttle already guarantees one request at a time.
 */

import { useEffect, useRef, useState } from "react";
import { useI18n } from "../i18n";
import type { ProfileCategory } from "../profileLibrary";
import type { ProblemDoc } from "../types";
import { ProfileNavigator } from "./ProfileNavigator";

import type {
  ExampleSummaryDoc,
  InitStrategy,
  ScaleBoundsDoc,
  WorkspaceMode,
} from "../types";

export type ToolbarProps = {
  /** Every example problem the backend found, in identifier order. */
  examples: ExampleSummaryDoc[];
  categories: ProfileCategory[];
  categoryId: string;
  localProblems: Record<string, ProblemDoc>;
  onCategory: (id: string) => void;
  onCreateCategory: (name: string) => void;
  onRenameCategory: (id: string, name: string) => void;
  onDeleteCategory: (id: string) => void;
  onRemoveProblem: (id: string) => void;
  onEditProblem: (id: string) => void;
  onAddSquare: (count: number) => void;
  /** Add a generated catalogue problem to the active category, then open it. */
  onAddProblem: (problem: ProblemDoc) => void;
  onNewCustom: () => void;
  onImportProblem: (problem: unknown) => Promise<void>;
  /** Identifier of the problem currently loaded, or null before the first load. */
  problemId: string | null;
  onProblemChange: (problemId: string) => void;
  /** Selecting an arrangement immediately initializes the current problem. */
  strategy: InitStrategy;
  /**
   * The initialisers the loaded problem's family offers, in the order they are shown.
   * A staggered lattice is defined for discs only, so it is absent here on every other
   * family — and `strategy` above is always one of these.
   */
  strategies: InitStrategy[];
  onStrategyChange: (strategy: InitStrategy) => void;
  onOpenModels: () => void;
  /** Download the current candidate as an SVG document. */
  onExportSvg: () => void;
  /** Open the dialog that imports a pasted solution as the candidate. */
  onOpenImport: () => void;
  /** Download the problem document, in the format the command line reads with `-p`. */
  onExportProblem: () => void;
  /** Download the candidate document, in the format the command line reads with `-c`. */
  onExportCandidate: () => void;
  /** Common scale currently being edited, or null before a candidate exists. */
  scale: number | null;
  /** Radius already measured by the engine's view, when the shapes are discs. */
  effectiveRadius: number | null;
  /** Interval the engine considers worth exploring, for the slider bounds. */
  scaleBounds: ScaleBoundsDoc | null;
  /** Called on every slider move; the application throttles the round trips. */
  onScaleChange: (scale: number) => void;
  /** Called when the slider is released, for a final verdict and one undo step. */
  onScaleCommit: () => void;
  /** True while a request is in flight. */
  busy: boolean;
  /** What the left half shows: the shapes, the arena, or a workflow's run. */
  mode: WorkspaceMode;
  /** Start over: every placed shape, or the arena's stack, depending on the mode. */
  onClear: () => void;
  /** Whether there is anything to clear in the current workspace. */
  canClear: boolean;
  canUndo: boolean;
  onUndo: () => void;
  canRedo: boolean;
  onRedo: () => void;
  onOpenGuide: () => void;
  onOpenStatistics: () => void;
  guideReveal: "picker" | "catalog-list" | "catalog-family" | null;
};

const STRATEGIES: readonly { value: InitStrategy; label: string }[] = [
  { value: "grid", label: "grid" },
  { value: "staggered", label: "staggered" },
  { value: "random", label: "random" },
  { value: "varied", label: "varied" },
  { value: "cover", label: "cover" },
];

/** How long a request must last before the interface admits it is working. */
const BUSY_DELAY_MS = 250;

const ChartIcon = () => <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
  strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><path d="M4 20h16M7 16v-4M12 16V7M17 16v-7" /></svg>;

/** Feather's "settings" gear (MIT licence). */
const GearIcon = () => <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
  strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3" />
  <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>;

export function Toolbar(props: ToolbarProps) {
  const { t, number, language, setLanguage } = useI18n();
  // The settings popover closes on a click outside it, or on Escape.
  // It is placed on the page, not in the toolbar, which scrolls sideways on a narrow screen.
  const [settingsOpen, setSettingsOpen] = useState<{ top: number; right: number } | null>(null);
  const settings = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!settingsOpen) return;
    const outside = (event: PointerEvent) => { if (!settings.current?.contains(event.target as Node)) setSettingsOpen(null); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setSettingsOpen(null); };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [settingsOpen]);
  const {
    examples,
    problemId,
    onProblemChange,
    strategy,
    strategies,
    onStrategyChange,
    onOpenModels,
    onExportSvg,
    onOpenImport,
    onExportProblem,
    onExportCandidate,
    scale,
    effectiveRadius,
    scaleBounds,
    onScaleChange,
    onScaleCommit,
    busy,
    mode,
    onClear,
    canClear,
    canUndo,
    onUndo,
    canRedo,
    onRedo,
  } = props;

  const [showBusy, setShowBusy] = useState(false);
  const timer = useRef<number | null>(null);
  const filesRef = useRef<HTMLDetailsElement | null>(null);
  useEffect(() => {
    const closeOutside = (event: PointerEvent) => {
      if (filesRef.current && !filesRef.current.contains(event.target as Node)) filesRef.current.open = false;
    };
    const closeEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && filesRef.current) filesRef.current.open = false;
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeEscape);
    };
  }, []);
  useEffect(() => {
    if (!busy) {
      if (timer.current !== null) {
        window.clearTimeout(timer.current);
        timer.current = null;
      }
      setShowBusy(false);
      return;
    }
    if (timer.current === null && !showBusy) {
      timer.current = window.setTimeout(() => {
        timer.current = null;
        setShowBusy(true);
      }, BUSY_DELAY_MS);
    }
  }, [busy, showBusy]);

  // The slider fires `change` continuously while it is dragged, and `pointerup`
  // even when nothing moved: committing only after a move keeps a click on the
  // thumb from costing a round trip and an undo step.
  const moved = useRef(false);
  // What is being typed in the scale field, or null when the engine's value is
  // what the field shows. Kept apart from the engine's scale so a half-typed
  // number survives the round trip.
  const [draft, setDraft] = useState<string | null>(null);

  const commitScale = () => {
    if (moved.current) {
      moved.current = false;
      onScaleCommit();
    }
  };

  // A scale the objective fixes is not a variable a slider may drive: the engine
  // reports it beside the interval, and the control shows that one value instead of
  // a handle whose every move would produce a candidate the engine refuses. A
  // total-perimeter family reports both a real interval over a copy's local size
  // and the common scale fixed at 1, which is exactly why the fixed value is what
  // is shown and the interval is not turned into a slider.
  const fixedScale = scaleBounds !== null && scaleBounds.fixed != null;
  return (
    <header className="toolbar">
      <div className="toolbar__brand">
        <span className="toolbar__title">Paper <em>Obs</em></span>
        <span className="toolbar__acronym" aria-label="Placement Analysis Platform for Experiments and Research">
          <span><b>P</b>lacement</span><span><b>A</b>nalysis</span><span><b>P</b>latform</span>
          <span>for</span><span><b>E</b>xperiments</span><span>and</span><span><b>R</b>esearch</span>
        </span>
      </div>
      <div className="toolbar__utility">
        <button type="button" className="toolbar__icon" onClick={props.onOpenStatistics}
          title={t("Statistics")} aria-label={t("Statistics")}><ChartIcon /></button>
        <div className="toolbar__settings" ref={settings}>
          <button type="button" className="toolbar__icon" aria-expanded={settingsOpen !== null} onClick={(event) => {
            const at = event.currentTarget.getBoundingClientRect();
            setSettingsOpen(settingsOpen ? null : { top: at.bottom + 8, right: window.innerWidth - at.right });
          }}
            title={t("Settings")} aria-label={t("Settings")}><GearIcon /></button>
          {settingsOpen && <div className="toolbar__settings-panel" role="dialog" aria-label={t("Settings")} style={settingsOpen}>
            <div className="toolbar__setting">
              <span>{t("Language")}</span>
              <div className="toolbar__language" role="group" aria-label="Langue / Language">
                <button type="button" aria-pressed={language === "fr"} onClick={() => setLanguage("fr")}>Français</button>
                <button type="button" aria-pressed={language === "en"} onClick={() => setLanguage("en")}>English</button>
              </div>
            </div>
            <button type="button" className="toolbar__setting toolbar__setting--action"
              onClick={() => { setSettingsOpen(null); props.onOpenGuide(); }}>
              <span>{t("Quick start")}</span><small>{t("Replay the guided tour of the interface")}</small>
            </button>
          </div>}
        </div>
      </div>
      <div className="toolbar__inner">

      <div className="toolbar__group toolbar__problem">
        <ProfileNavigator categories={props.categories} categoryId={props.categoryId}
          examples={examples} localProblems={props.localProblems} problemId={problemId}
          onCategory={props.onCategory} onProblem={onProblemChange}
          onCreateCategory={props.onCreateCategory} onRenameCategory={props.onRenameCategory} onDeleteCategory={props.onDeleteCategory}
          onRemoveProblem={props.onRemoveProblem} onEditProblem={props.onEditProblem}
          onAddSquare={props.onAddSquare} onAddProblem={props.onAddProblem}
          onNewCustom={props.onNewCustom} onImportProblem={props.onImportProblem}
          guideReveal={props.guideReveal} />
      </div>

      <div className="toolbar__right">
        {/* The book's left edge anchors the problem selector. Editing and file
            controls stay together at its right edge, whatever the page count. */}
        {(mode === "shapes" || mode === "arena" || mode === "compose") && (
          <div className="toolbar__group toolbar__history">
            <button
              type="button"
              className="button"
              disabled={!canUndo}
              onClick={onUndo}
              aria-label={`${t("Undo")} (Ctrl+Z)`}
            >
              <span aria-hidden="true">↶</span><span className="sr-only">{t("Undo")}</span>
            </button>
            <button
              type="button"
              className="button"
              disabled={!canRedo}
              onClick={onRedo}
              aria-label={`${t("Redo")} (Ctrl+Shift+Z)`}
            >
              <span aria-hidden="true">↷</span><span className="sr-only">{t("Redo")}</span>
            </button>
            {(mode === "shapes" || mode === "arena") && (
              <button
                type="button"
                className="button"
                disabled={!canClear}
                aria-label={
                  mode === "arena"
                    ? t("start the arena over with a single rectangle")
                    : t("remove every placed shape")
                }
                onClick={onClear}
              >
                <span aria-hidden="true">×</span><span className="sr-only">{t("Clear")}</span>
              </button>
            )}
          </div>
        )}
      <div className="toolbar__actions">
      {mode === "run" && <button type="button" className="button" onClick={onOpenModels}>{t("Model…")}</button>}

      {mode === "shapes" && (
        // Text alone, without the slider, sits on one baseline with the × before it.
        <div className={scaleBounds === null || fixedScale ? "toolbar__scale toolbar__scale--text" : "toolbar__scale"}>
          <label className="field__label toolbar__scale-symbol" htmlFor="toolbar-scale" aria-label={t("scale factor")}>×</label>
          {scaleBounds === null ? (
            <span className="muted">{t("no candidate yet")}</span>
          ) : fixedScale ? (
            <>
              <span className="toolbar__radius">{number(scaleBounds.fixed ?? 0, 3)}</span>
              <span className="muted">{t("fixed by the objective")}</span>
            </>
          ) : (
            <>
              <input
                id="toolbar-scale"
                className="input"
                type="range"
                min={scaleBounds.low}
                max={scaleBounds.high}
                step="any"
                value={scale ?? scaleBounds.low}
                // Not disabled while a verdict is in flight: the browser blurs a
                // disabled input, so the slider would lose focus under the hand
                // of whoever is dragging it.
                disabled={scale === null || fixedScale}
                onChange={(event) => {
                  moved.current = true;
                  onScaleChange(Number(event.target.value));
                }}
                onPointerUp={commitScale}
                onKeyUp={commitScale}
              />
              <input
                id="toolbar-scale-value"
                className="input input--narrow"
                type="number"
                inputMode="decimal"
                step="0.001"
                aria-label={t("scale value")}
                value={draft ?? (scale === null ? "" : String(Number(scale.toFixed(3))))}
                disabled={scale === null || fixedScale}
                onFocus={() => setDraft(scale === null ? "" : String(Number(scale.toFixed(3))))}
                onChange={(event) => {
                  // A half-typed number is kept as text: "2." is not a value yet,
                  // and replacing the field's contents while it is being typed is
                  // how a number input becomes impossible to use.
                  const typed = event.target.value;
                  setDraft(typed);
                  const parsed = Number(typed);
                  if (typed !== "" && Number.isFinite(parsed) && parsed > 0) {
                    moved.current = true;
                    onScaleChange(parsed);
                  }
                }}
                onBlur={() => {
                  setDraft(null);
                  commitScale();
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    setDraft(null);
                    commitScale();
                    event.currentTarget.blur();
                  } else if (event.key === "Escape") {
                    setDraft(null);
                  }
                }}
              />
              {effectiveRadius !== null && <span className="toolbar__radius">R = {number(effectiveRadius, 3)}</span>}
            </>
          )}
        </div>
      )}

      {/* No initialiser the engine can run — an unknown objective, or no problem
          loaded: the control is absent rather than shown failing. */}
      {(mode === "shapes" || mode === "arena") && strategies.length > 0 && <div className="toolbar__group toolbar__init">
        <select
          className="select"
          value={strategy}
          aria-label={t("Arrangement")}
          onChange={(event) => onStrategyChange(event.target.value as InitStrategy)}
        >
          {/* Only the initialisers this family is defined for: a staggered lattice is
              an arrangement of discs, and the engine refuses it for anything else. */}
          {STRATEGIES.filter((option) => strategies.includes(option.value)).map((option) => (
            <option key={option.value} value={option.value}>
              {t(option.label)}
            </option>
          ))}
        </select>
        <span className={`busy${showBusy ? "" : " busy--hidden"}`} aria-live="polite">
          {t("working…")}
        </span>
      </div>}

      </div>

      <div className="toolbar__group toolbar__files-group">
        <button
          type="button"
          className="button button--ghost"
          onClick={onOpenImport}
        >
          {t("Import")}
        </button>
        <details className="toolbar__files" ref={filesRef}><summary>{t("Export")} ▾</summary><div>
          <button type="button" className="button button--ghost" onClick={() => { onExportSvg(); if (filesRef.current) filesRef.current.open = false; }}>SVG</button>
          <button type="button" className="button button--ghost" onClick={() => { onExportProblem(); if (filesRef.current) filesRef.current.open = false; }}>{t("Save problem")}</button>
          <button type="button" className="button button--ghost" onClick={() => { onExportCandidate(); if (filesRef.current) filesRef.current.open = false; }}>{t("Save candidate")}</button>
        </div></details>
      </div>
      </div>
      </div>
    </header>
  );
}
