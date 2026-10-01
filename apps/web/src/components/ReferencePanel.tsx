import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { sourceFigure } from "../catalog";
import type { ProblemReference } from "../catalog";
import { useI18n } from "../i18n";
import "./ReferencePanel.css";

type Props = { problemId: string | null; reference: ProblemReference | null; candidateOrigin: string | null; onChange: (value: ProblemReference) => void };

const EMPTY: ProblemReference = {
  status: "none", value: null, unit: "", author: "", date: "", proved_by: "",
  proof_date: "", verified_on: "", note: "", preview: "", sources: [],
};

function externalUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch { return null; }
}

export function ReferencePanel({ problemId, reference, candidateOrigin, onChange }: Props) {
  const { t, number } = useI18n();
  const [editing, setEditing] = useState(false);
  const [viewing, setViewing] = useState(false);
  useEffect(() => { setEditing(false); setViewing(false); }, [problemId]);
  useEffect(() => {
    if (!viewing) return;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") setViewing(false); };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [viewing]);
  const value = reference ?? EMPTY;
  // One tint for every plate the app shows, and never for a total-perimeter figure.
  const tinted = value.figure_tint !== false && sourceFigure(value.preview);
  const hasData = value.status !== "none" || value.value !== null || Boolean(value.author || value.proved_by || value.note || value.sources.length);
  const update = (patch: Partial<ProblemReference>) => onChange({ ...value, ...patch });
  return <section className="panel__section reference-panel">
    <div className="reference-panel__heading"><h2 className="panel__title">{t("Problem reference")}</h2>
      <button className="reference-panel__edit" type="button" onClick={() => setEditing((open) => !open)}>{t(editing ? "Done" : "Edit")}</button></div>
    {!hasData && !editing ? <p className="reference-panel__empty">{t("No reference data for this problem yet.")}</p> : null}
    {!editing && hasData && <div className="reference-panel__body">
      {value.preview && <button type="button" className="reference-panel__preview-button"
        aria-label={t("Enlarge reference image")} onClick={() => setViewing(true)}>
        <img className={tinted ? "reference-panel__preview packing-figure--source" : "reference-panel__preview"}
          src={value.preview} alt={t("Published packing preview")} />
      </button>}
      <div className="reference-panel__facts">
        {value.status !== "none" && <span className="reference-panel__status">{t(value.status === "proved" ? "Proved optimum" : "Best known")}</span>}
        {value.value !== null && <strong>{number(value.value, 8)} <small>{t(value.unit)}</small></strong>}
        <span className="reference-panel__checked">{value.verified_on ? `${t("Last checked")}: ${value.verified_on}` : t("Verification date unknown")}</span>
        {value.author && <span>{t("Construction")}: {value.author}{value.date ? ` · ${value.date}` : ""}</span>}
        {value.proved_by && <span>{t("Proof")}: {value.proved_by}{value.proof_date ? ` · ${value.proof_date}` : ""}</span>}
      </div>
      {value.note && <p className="reference-panel__note">{t(value.note)}</p>}
      {candidateOrigin === "source-derived-approximation" && <p className="reference-panel__approximation">{t("Loaded arrangement approximates the published figure; compare its measurements with the reference.")}</p>}
      {candidateOrigin === "beaten-record" && <p className="reference-panel__record">{t("The loaded arrangement beats this published record: the figure and value above are the previous record, the verdict is the engine's measurement of the new one.")}</p>}
      {value.sources.length > 0 && <ul className="reference-panel__sources">{value.sources.map((source, index) => {
        const href = externalUrl(source.url);
        return href && <li key={index}><a href={href} target="_blank" rel="noopener noreferrer">{source.label} ↗</a></li>;
      })}</ul>}
    </div>}
    {editing && <div className="reference-panel__form">
      <label>{t("Reference status")}<select value={value.status} onChange={(event) => update({ status: event.target.value as ProblemReference["status"] })}>
        <option value="none">{t("No reference")}</option><option value="best_known">{t("Best known")}</option><option value="proved">{t("Proved optimum")}</option>
      </select></label>
      <div className="reference-panel__pair">
        <label>{t("Reference value")}<input type="number" step="any" value={value.value ?? ""} onChange={(event) => update({ value: event.target.value === "" ? null : Number(event.target.value) })} /></label>
        <label>{t("Unit / metric")}<input value={value.unit} onChange={(event) => update({ unit: event.target.value })} /></label>
      </div>
      <div className="reference-panel__pair">
        <label>{t("Construction author")}<input value={value.author} onChange={(event) => update({ author: event.target.value })} /></label>
        <label>{t("Construction date")}<input value={value.date} onChange={(event) => update({ date: event.target.value })} /></label>
      </div>
      <div className="reference-panel__pair">
        <label>{t("Proof author")}<input value={value.proved_by} onChange={(event) => update({ proved_by: event.target.value })} /></label>
        <label>{t("Proof date")}<input value={value.proof_date} onChange={(event) => update({ proof_date: event.target.value })} /></label>
      </div>
      <label>{t("Last checked")}<input type="date" value={value.verified_on} onChange={(event) => update({ verified_on: event.target.value })} /></label>
      <label>{t("Context")}<textarea rows={2} value={value.note} onChange={(event) => update({ note: event.target.value })} /></label>
      <div className="reference-panel__source-edit"><strong>{t("Sources")}</strong>
        {value.sources.map((source, index) => <div key={index}>
          <input aria-label={`${t("Source name")} ${index + 1}`} placeholder={t("Source name")} value={source.label}
            onChange={(event) => update({ sources: value.sources.map((item, position) => position === index ? { ...item, label: event.target.value } : item) })} />
          <input aria-label={`${t("Source URL")} ${index + 1}`} placeholder="https://…" value={source.url}
            onChange={(event) => update({ sources: value.sources.map((item, position) => position === index ? { ...item, url: event.target.value } : item) })} />
          <button type="button" aria-label={t("Remove source")} onClick={() => update({ sources: value.sources.filter((_, position) => position !== index) })}>×</button>
        </div>)}
        <button type="button" onClick={() => update({ sources: [...value.sources, { label: "", url: "" }] })}>＋ {t("Add source")}</button>
      </div>
    </div>}
    {viewing && value.preview && createPortal(<div className="reference-viewer" role="dialog" aria-modal="true" aria-label={t("Reference image")}>
      <button type="button" className="reference-viewer__backdrop" aria-label={t("Close")} onClick={() => setViewing(false)} />
      <div className="reference-viewer__sheet">
        <div className="reference-viewer__heading"><h2>{t("Reference image")}</h2>
          <button type="button" onClick={() => setViewing(false)} aria-label={t("Close")}>×</button></div>
        <img src={value.preview} alt={t("Published packing preview")}
          className={tinted ? "packing-figure--source" : undefined} />
        <p>{t("Published construction")}{value.status !== "none" ? ` · ${t(value.status === "proved" ? "Proved optimum" : "Best known")}` : ""}</p>
      </div>
    </div>, document.body)}
  </section>;
}
