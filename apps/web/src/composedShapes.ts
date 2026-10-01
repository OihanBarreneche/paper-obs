/**
 * The composed shapes kept in this browser.
 *
 * A composed shape is a ShapeDoc the engine compiled, plus what the library needs to
 * list and re-edit it: a name, the stack that produced it, and the outline the engine
 * drew so a tile can be shown without asking again. It lives in localStorage, like the
 * profile library: the browser owns its own shapes, and the engine remembers nothing
 * between requests.
 */

import type { ComposedShapeDoc, ShapeDoc } from "./types";

const STORAGE_KEY = "paper-obs-composed-shapes-v1";

/** Whether a value read from storage is a shape this library can draw and edit. */
function isShape(value: unknown): value is ShapeDoc {
  if (typeof value !== "object" || value === null) return false;
  const type = (value as { type?: unknown }).type;
  return type === "circle" || type === "regular_polygon" || type === "custom_polygon";
}

function isComposedShape(value: unknown): value is ComposedShapeDoc {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Partial<ComposedShapeDoc>;
  return (
    typeof item.id === "string" &&
    typeof item.name === "string" &&
    typeof item.path === "string" &&
    typeof item.area === "number" &&
    Array.isArray(item.bounds) &&
    Array.isArray(item.parts) &&
    isShape(item.shape)
  );
}

/**
 * Read the library, dropping anything a malformed stored document left behind.
 *
 * A record that no longer has the shape of a composed shape is skipped rather than
 * crashing the page on open: localStorage is shared with every earlier build.
 */
export function readComposedShapes(): ComposedShapeDoc[] {
  try {
    const saved = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "[]") as unknown;
    return Array.isArray(saved) ? saved.filter(isComposedShape) : [];
  } catch {
    return [];
  }
}

export function saveComposedShapes(shapes: ComposedShapeDoc[]): void {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(shapes));
}

/** Add or replace one shape, keeping the library's order stable on an edit. */
export function upsertComposedShape(
  shapes: ComposedShapeDoc[],
  shape: ComposedShapeDoc,
): ComposedShapeDoc[] {
  return shapes.some((item) => item.id === shape.id)
    ? shapes.map((item) => (item.id === shape.id ? shape : item))
    : [...shapes, shape];
}

export function removeComposedShape(shapes: ComposedShapeDoc[], id: string): ComposedShapeDoc[] {
  return shapes.filter((item) => item.id !== id);
}

/** A fresh library identifier. The engine never sees it: a problem carries the shape. */
export function newComposedShapeId(): string {
  return `composed-${crypto.randomUUID()}`;
}
