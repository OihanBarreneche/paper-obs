/**
 * The tools a workflow's agents may call, browsable without opening the code.
 *
 * Everything shown comes from the backend's catalogue, which reads the tools themselves:
 * the names, the docstrings and the argument schemas are what a model is sent, and the
 * objectives are those the workflow's menu offers each tool on. Only the French is added,
 * by looking each sentence up like any other string of the interface.
 */
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { api } from "../api";
import { useI18n } from "../i18n";
import type { AgentToolDoc, JsonSchemaDoc, WorkflowManifestDoc, WorkflowToolsDoc } from "../types";
import "./ToolViewer.css";

const OBJECTIVE_LABELS: Record<string, string> = {
  minimize_container: "minimise the container",
  maximize_scale: "maximise the scale",
  maximize_count: "maximise the count",
  cover_region: "cover the target at the smallest scale",
  maximize_covered_size: "maximise the covered target",
  maximize_total_perimeter: "maximise the total perimeter",
};

type Row = { name: string; type: string; required: boolean; fallback: string | null; description: string | null; depth: number };

/** A schema's type as JSON Schema names it, with a list written `type[]` and a choice `a | b`. */
function typeName(schema: JsonSchemaDoc): string {
  if (schema.anyOf) return schema.anyOf.filter((item) => item.type !== "null").map(typeName).join(" | ") || "null";
  if (schema.enum) return schema.enum.map((value) => JSON.stringify(value)).join(" | ");
  if (schema.type === "array") return `${schema.items ? typeName(schema.items) : "any"}[]`;
  if (schema.type === "object") return schema.title ?? "object";
  return schema.type ?? "any";
}

/** The object a list of objects holds, where a field is one (possibly optional). */
function listedObject(schema: JsonSchemaDoc): JsonSchemaDoc | null {
  const present = schema.anyOf?.find((item) => item.type !== "null") ?? schema;
  return present.type === "array" && present.items?.type === "object" ? present.items : null;
}

/** One row per argument, and one per field of a list of objects, indented under it. */
function rows(schema: JsonSchemaDoc, prefix = "", depth = 0): Row[] {
  const required = new Set(schema.required ?? []);
  return Object.entries(schema.properties ?? {}).flatMap(([name, field]) => {
    const nested = listedObject(field);
    return [{
      name: prefix + name, type: typeName(field), required: required.has(name), depth,
      fallback: "default" in field ? JSON.stringify(field.default) : null,
      description: field.description ?? nested?.description ?? null,
    }, ...(nested ? rows(nested, `${prefix}${name}[].`, depth + 1) : [])];
  });
}

/** A tool's reply laid out: JSON indented, a sentence as it came. */
function pretty(reply: string): string {
  try {
    return JSON.stringify(JSON.parse(reply), null, 2);
  } catch {
    return reply;
  }
}

/** A docstring sentence, with its `quoted` names set as code. */
function Prose({ text }: { text: string }) {
  return <>{text.split("`").map((part, index) => index % 2 === 1 ? <code key={index}>{part}</code> : part)}</>;
}

export function ToolViewer({ workflow, objective, onClose }: {
  workflow: WorkflowManifestDoc;
  /** The objective of the problem at hand, chosen first; null shows every tool alike. */
  objective: string | null;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const [catalog, setCatalog] = useState<WorkflowToolsDoc | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<string | null>(objective);
  const [picked, setPicked] = useState<string | null>(null);
  const list = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let current = true;
    api.workflowTools(workflow.id)
      .then((body) => { if (current) setCatalog(body); })
      .catch((reason: unknown) => { if (current) setError(reason instanceof Error ? reason.message : String(reason)); });
    return () => { current = false; };
  }, [workflow.id]);
  useEffect(() => {
    // Caught before the large diagram's own handler, so Escape closes this window alone.
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.stopPropagation(); onClose(); }
    };
    document.addEventListener("keydown", close, true);
    return () => document.removeEventListener("keydown", close, true);
  }, [onClose]);

  const tools = catalog?.tools ?? [];
  const offered = (tool: AgentToolDoc) => filter === null || tool.objectives.includes(filter);
  // Offered tools first, in the engine's own order, so the arrow keys walk what the agent sees.
  const ordered = [...tools.filter(offered), ...tools.filter((item) => !offered(item))];
  const tool = ordered.find((item) => item.name === picked) ?? ordered[0] ?? null;
  const count = tools.filter(offered).length;

  const step = (by: number) => {
    if (tool === null) return;
    const next = ordered[(ordered.indexOf(tool) + by + ordered.length) % ordered.length];
    if (next) setPicked(next.name);
  };
  // The picked tool takes the focus, so the arrow keys carry it along the list.
  useEffect(() => {
    if (picked !== null) list.current?.querySelector<HTMLElement>("[aria-selected=true]")?.focus();
  }, [picked]);
  const label = (name: string) => {
    const spaced = name.replaceAll("_", " ");
    return t(spaced) === spaced ? null : t(spaced);
  };
  const everywhere = tool !== null && catalog !== null && tool.objectives.length === catalog.objectives.length;

  return createPortal(<div className="tool-viewer__overlay" role="presentation"
    onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="tool-viewer" role="dialog" aria-modal="true" aria-label={t("Agent tools")}>
      <header className="tool-viewer__header">
        <div>
          <h2>{t("Agent tools")}</h2>
          <p>{t(workflow.name)} · {t("read from the code: each description is the tool's own docstring, as the model receives it")}</p>
        </div>
        <button type="button" onClick={onClose} aria-label={t("Close")}>×</button>
      </header>
      {catalog && <div className="tool-viewer__filters" role="tablist" aria-label={t("Objective")}>
        <button type="button" role="tab" aria-selected={filter === null} onClick={() => setFilter(null)}>
          {t("every objective")}
        </button>
        {catalog.objectives.map((kind) => <button type="button" role="tab" key={kind} aria-selected={filter === kind}
          onClick={() => setFilter(kind)}>
          {t(OBJECTIVE_LABELS[kind] ?? kind)}{kind === objective && <small> · {t("this problem")}</small>}
        </button>)}
      </div>}
      {error && <p className="error">{t("The tools could not be listed")}: {error}</p>}
      {!catalog && !error && <p className="tool-viewer__empty">{t("working…")}</p>}
      {catalog && <div className="tool-viewer__body">
        <div className="tool-viewer__list" role="listbox" ref={list} aria-label={t("Agent tools")}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") { event.preventDefault(); step(1); }
            if (event.key === "ArrowUp") { event.preventDefault(); step(-1); }
          }}>
          <p className="tool-viewer__count">{count} / {tools.length} {t("tools offered")}</p>
          {ordered.map((item) => <button type="button" role="option" key={item.name}
            aria-selected={item.name === tool?.name} tabIndex={item.name === tool?.name ? 0 : -1}
            className={offered(item) ? "" : "tool-viewer__absent"} onClick={() => setPicked(item.name)}>
            <code>{item.name}</code>{label(item.name) && <small>{label(item.name)}</small>}
          </button>)}
        </div>
        {tool && <article className="tool-viewer__detail">
          <h3><code>{tool.name}</code>{label(tool.name) && <span>{label(tool.name)}</span>}</h3>
          {!offered(tool) && <p className="tool-viewer__warning">{t("not offered on this objective")}</p>}
          {tool.description.map((paragraph) => <p key={paragraph}><Prose text={t(paragraph)} /></p>)}
          <dl className="tool-viewer__facts">
            <dt>{t("Offered on")}</dt>
            <dd>{everywhere ? t("every objective") : tool.objectives.map((kind) => t(OBJECTIVE_LABELS[kind] ?? kind)).join(", ")}</dd>
          </dl>
          <h4>{t("Arguments")}</h4>
          {rows(tool.parameters).length === 0 ? <p className="tool-viewer__empty">{t("no argument")}</p>
            : <table className="tool-viewer__arguments"><tbody>
              {rows(tool.parameters).map((row) => <tr key={row.name}>
                <th style={{ paddingLeft: 8 + row.depth * 16 }}><code>{row.name}</code></th>
                <td><code>{row.type}</code></td>
                <td>{row.required ? t("required") : row.fallback !== null ? <>{t("default")} <code>{row.fallback}</code></> : t("optional")}</td>
                <td>{row.description ? <Prose text={t(row.description)} /> : ""}</td>
              </tr>)}
            </tbody></table>}
          {/* Left uncontrolled, so an example opened once stays open from tool to tool. */}
          {tool.example && <details className="tool-viewer__example">
            <summary>{t("Example")}</summary>
            <p><Prose text={t(tool.example.caption)} /></p>
            <h5>{t("The call the model sends")}</h5>
            <pre>{tool.name}({Object.keys(tool.example.arguments).length > 0
              ? JSON.stringify(tool.example.arguments, null, 2) : ""})</pre>
            <h5>{t("What the tool answers")}</h5>
            <pre>{pretty(tool.example.reply)}</pre>
          </details>}
          <details className="tool-viewer__schema">
            <summary>{t("Arguments as the model receives them (JSON Schema)")}</summary>
            <pre>{JSON.stringify(tool.parameters, null, 2)}</pre>
          </details>
        </article>}
      </div>}
    </section>
  </div>, document.body);
}
