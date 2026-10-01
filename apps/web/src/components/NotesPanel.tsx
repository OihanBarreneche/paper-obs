import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useI18n } from "../i18n";
import "./NotesPanel.css";

function noteKey(problemId: string) { return `paper-obs-notes:${problemId}`; }

function boldParts(line: string): ReactNode[] {
  return line.split(/(\*\*[^*]+\*\*)/g).map((part, index) =>
    part.startsWith("**") && part.endsWith("**")
      ? <strong key={index}>{part.slice(2, -2)}</strong> : part);
}

function preview(text: string): ReactNode[] {
  return text.split("\n").map((line, index) => {
    if (line.startsWith("## ")) return <h4 key={index}>{boldParts(line.slice(3))}</h4>;
    if (line.startsWith("# ")) return <h3 key={index}>{boldParts(line.slice(2))}</h3>;
    return <p key={index}>{line ? boldParts(line) : "\u00a0"}</p>;
  });
}

export function NotesPanel({ problemId }: { problemId: string | null }) {
  const { t } = useI18n();
  const [text, setText] = useState(() => {
    try { return problemId ? window.localStorage.getItem(noteKey(problemId)) ?? "" : ""; }
    catch { return ""; }
  });
  const [showPreview, setShowPreview] = useState(true);
  const editor = useRef<HTMLTextAreaElement | null>(null);
  useEffect(() => { if (problemId) {
    try { window.localStorage.setItem(noteKey(problemId), text); } catch { /* Notes remain usable in memory. */ }
  } }, [problemId, text]);

  const insert = (prefix: string, suffix = "") => {
    const area = editor.current;
    if (!area) return;
    const start = area.selectionStart;
    const end = area.selectionEnd;
    const selected = text.slice(start, end);
    const content = selected || (prefix === "**" ? t("text") : "");
    setText(text.slice(0, start) + prefix + content + suffix + text.slice(end));
    requestAnimationFrame(() => { area.focus(); area.setSelectionRange(start + prefix.length, start + prefix.length + content.length); });
  };

  const heading = (prefix: string) => {
    const area = editor.current;
    if (!area) return;
    const start = area.selectionStart;
    const lineStart = text.lastIndexOf("\n", start - 1) + 1;
    const existing = /^(?:#{1,2} )?/.exec(text.slice(lineStart))?.[0] ?? "";
    const next = text.slice(0, lineStart) + prefix + text.slice(lineStart + existing.length);
    setText(next);
    requestAnimationFrame(() => {
      const cursor = Math.max(lineStart + prefix.length, start + prefix.length - existing.length);
      area.focus(); area.setSelectionRange(cursor, cursor);
    });
  };

  return <section className="panel__section notes-panel">
    <div className="notes-panel__heading"><h2 className="panel__title">{t("Research notes")}</h2>
      <button type="button" onClick={() => setShowPreview((value) => !value)} disabled={!problemId}>{t(showPreview ? "Edit notes" : "Preview")}</button></div>
    {!problemId ? <p className="muted">{t("Load a problem to keep notes.")}</p> : <>
      {!showPreview && <><div className="notes-panel__tools">
        <button type="button" onClick={() => heading("# ")}>{t("Title")}</button>
        <button type="button" onClick={() => heading("## ")}>{t("Subtitle")}</button>
        <button type="button" onClick={() => insert("**", "**")}><strong>B</strong></button>
      </div><textarea ref={editor} value={text} rows={5} placeholder={t("Write a hypothesis, observation, or source to revisit…")}
        onChange={(event) => setText(event.target.value)} /></>}
      {showPreview && <div className="notes-panel__preview">{text ? preview(text) : <p className="muted">{t("No notes yet.")}</p>}</div>}
      <small>{t("Saved in this browser for this problem.")}</small>
    </>}
  </section>;
}
