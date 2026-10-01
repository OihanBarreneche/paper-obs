/**
 * The elementary shapes, defined once for every creation menu.
 *
 * A shape is created by a gesture — a right-click on a canvas — and each workspace
 * creates it out of a different vocabulary: the shapes workspace places a packable
 * family the engine publishes, while the arena and the composer add a *primitive*
 * the engine compiles into a region or an outline. Both vocabularies live here,
 * under one entry per elementary shape, so the three menus cannot drift apart:
 * one order, one label per entry, one place that says which entries exist. Adding
 * or renaming a shape is a single edit.
 *
 * A menu item carries only the size a creation starts from; the panel then edits
 * it and the engine judges it, so no coordinate, radius or area is decided here.
 * The one exception is the shapes workspace, which names an engine palette entry
 * rather than a primitive — the engine still owns what that family is.
 */

import type { ArenaPartParams } from "./types";

/** One workspace whose right-click menu creates an elementary shape. */
export type CreateWorkspace = "shapes" | "compose" | "arena";

/** One elementary shape, as every creation menu sees it. */
export type ElementaryShape = {
  /** Stable identity, and the name a menu item is built from. */
  id: string;
  /** The one label every workspace shows, through the translator. */
  label: string;
  /**
   * The engine palette entry the shapes workspace stores, or null where the
   * domain publishes no such family. The entry then carries no shape document:
   * that stays the engine's own decision, and the reason names it below.
   */
  paletteId: string | null;
  /**
   * The primitive the arena and the composer add, or null for the one shape that
   * is drawn rather than added.
   */
  primitive: ArenaPartParams | null;
  /** True for the outline the canvas draws, rather than a primitive to add. */
  drawn?: boolean;
  /** The side count a regular polygon's field starts from. */
  sides?: number;
  /** The two semi-axes an ellipse's fields start from. */
  axes?: [number, number];
  /** The workspaces whose menu offers this shape. */
  workspaces: readonly CreateWorkspace[];
};

/**
 * Every elementary shape, in the order the three menus show it.
 *
 * The order, the labels and the capitalisation are the same everywhere. An entry
 * a workspace cannot offer is spelled out here, beside the entry it concerns,
 * rather than left as an omission a reader has to guess at:
 *
 * - `rectangle` has no palette family: the engine publishes a square, and a
 *   non-square rectangle is an outline drawn in the composer, reached from the
 *   shapes workspace through "your own shapes".
 * - `ellipse` is an arena primitive only: the domain's packable shapes are a
 *   disc, a regular polygon and a hand-drawn outline, with no ellipse family.
 * - `drawn_polygon` has no place in the shapes workspace: the packing canvas has
 *   no drawing gesture, so the outline is drawn in the composer and placed from
 *   the library.
 */
export const ELEMENTARY_SHAPES: readonly ElementaryShape[] = [
  {
    id: "disc",
    label: "Disc",
    paletteId: "disc",
    primitive: { kind: "disk", radius: 1 },
    workspaces: ["shapes", "compose", "arena"],
  },
  {
    id: "square",
    label: "Square",
    paletteId: "square",
    primitive: { kind: "rect", width: 2, height: 2 },
    workspaces: ["shapes", "compose", "arena"],
  },
  {
    id: "triangle",
    label: "Equilateral triangle",
    paletteId: "triangle",
    // A unit-ish equilateral triangle: the regular polygon of three sides.
    primitive: { kind: "regular_ngon", sides: 3, circumradius: 1.2 },
    workspaces: ["shapes", "compose", "arena"],
  },
  {
    id: "right_triangle",
    label: "Right triangle",
    paletteId: "right_triangle",
    // A unit right isosceles triangle: legs 1, centred on its own box.
    primitive: {
      kind: "polygon",
      points: [
        [-0.5, -0.5],
        [0.5, -0.5],
        [-0.5, 0.5],
      ],
    },
    workspaces: ["shapes", "compose", "arena"],
  },
  {
    id: "regular_polygon",
    label: "Regular polygon",
    paletteId: "polygon",
    primitive: { kind: "regular_ngon", sides: 5, circumradius: 1.2 },
    // The one primitive whose side count the menu offers: a pentagon is one
    // field away, and a named hexagon preset would be the same shape twice.
    sides: 5,
    workspaces: ["shapes", "compose", "arena"],
  },
  {
    id: "rectangle",
    label: "Rectangle",
    paletteId: null,
    primitive: { kind: "rect", width: 3, height: 2 },
    workspaces: ["compose", "arena"],
  },
  {
    id: "domino",
    label: "Domino",
    paletteId: "domino",
    // Two unit squares side by side, centred on their shared middle.
    primitive: {
      kind: "polygon",
      points: [
        [-1, -0.5],
        [1, -0.5],
        [1, 0.5],
        [-1, 0.5],
      ],
    },
    workspaces: ["shapes", "compose", "arena"],
  },
  {
    id: "l_tromino",
    label: "L-tromino",
    paletteId: "l_tromino",
    // Three unit squares in an L, centred on the box's own middle.
    primitive: {
      kind: "polygon",
      points: [
        [-1, -1],
        [1, -1],
        [1, 0],
        [0, 0],
        [0, 1],
        [-1, 1],
      ],
    },
    workspaces: ["shapes", "compose", "arena"],
  },
  {
    id: "ellipse",
    label: "Ellipse",
    paletteId: null,
    // The two semi-axes the collection names a and b, at a size big enough to be
    // seen and grabbed once the engine has compiled the outline.
    primitive: { kind: "ellipse", a: 3, b: 2 },
    axes: [3, 2],
    workspaces: ["compose", "arena"],
  },
  {
    id: "drawn_polygon",
    label: "Drawn polygon",
    paletteId: null,
    // A polygon is drawn rather than added: the canvas reports its vertices and
    // the engine refuses fewer than three in its own words.
    primitive: null,
    drawn: true,
    workspaces: ["compose", "arena"],
  },
];

/** The fresh arena: the rectangle "start over" leaves, before any part is added. */
export const ARENA_BASE: ArenaPartParams = { kind: "rect", width: 6, height: 6 };

/** The elementary shape a menu named, or undefined for an identifier that is not one. */
export function elementaryShape(id: string): ElementaryShape | undefined {
  return ELEMENTARY_SHAPES.find((entry) => entry.id === id);
}

/**
 * The primitive one entry creates, with the numbers the menu's fields reported.
 *
 * A regular polygon is the one primitive with a choosable side count and an ellipse
 * the one with two semi-axes. A field that reads as no number yet falls back on the
 * size the entry starts from; a number the engine cannot use is passed through, and
 * the engine refuses it in its own words.
 */
export function primitiveFromMenu(
  entry: ElementaryShape,
  sides?: number,
  axes?: [number, number],
): ArenaPartParams | null {
  const base = entry.primitive;
  if (base === null) {
    return null;
  }
  if (base.kind === "regular_ngon" && entry.sides !== undefined && sides !== undefined && Number.isFinite(sides)) {
    return { ...base, sides: Math.round(sides) };
  }
  if (base.kind === "ellipse" && axes !== undefined) {
    return {
      kind: "ellipse",
      a: Number.isFinite(axes[0]) ? axes[0] : base.a,
      b: Number.isFinite(axes[1]) ? axes[1] : base.b,
    };
  }
  return base;
}

/**
 * The domain's own description of a primitive's numbers.
 *
 * A card shows this until the engine's answer replaces it, so a part added by a
 * gesture reads like the ones the engine compiled beside it — in the interface's
 * language, which is why the words come through the translator the caller holds.
 */
export function describePrimitive(params: ArenaPartParams, t: (english: string) => string): string {
  switch (params.kind) {
    case "rect":
      return `${t("rectangle")} ${params.width} × ${params.height}`;
    case "disk":
      return `${t("disc")} · ${t("radius")} ${params.radius}`;
    case "ellipse":
      return `${t("Ellipse")} · ${t("semi-axis a")} ${params.a} · ${t("semi-axis b")} ${params.b}`;
    case "regular_ngon":
      return `${t("regular polygon")} · ${t("sides")} ${params.sides} · ${t("circumradius")} ${params.circumradius}`;
    case "polygon":
      return `${t("Polygon")} · ${t("vertices")} ${params.points.length}`;
  }
}
