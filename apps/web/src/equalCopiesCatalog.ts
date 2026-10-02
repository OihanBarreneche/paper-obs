/**
 * The generated Packing Center catalogue, fetched as a static asset.
 *
 * The collection publishes four sections — the equal-copies matrix, the copies
 * that maximise the total perimeter, covering, and the other packing problems
 * whose pages read the same way — about 2500 records and half a megabyte no
 * screen needs at start-up. The navigator asks for this file the first time its
 * catalogue panel opens, and never before, so it stays an asset the browser
 * downloads on demand instead of a bundle it always carries.
 *
 * What this module holds is exactly what the asset publishes: a section, a size,
 * a status, an attribution and, for a family the domain can express, a ready-made
 * `problem_template`. Nothing here is recomputed. A subfamily the lab cannot judge
 * yet is still readable — marked unsupported and unaddable — while a supported one
 * becomes a problem document: the asset's own template when it carries one, and
 * the squares' `minimize_container` convention otherwise.
 */

import { api } from "./api";
import { withinVisibleCount } from "./catalog";
import { loadedVerification, verificationOf } from "./verification";
import type { ProblemReference } from "./catalog";
import type { ObjectiveDoc, ProblemDoc, ShapeDoc, ShapeFamilyDoc } from "./types";

export type CopyStatus = "proved" | "best_known" | "none";

/** One published record: the figure it belongs to, its size, and who found it. */
export type CopyInstance = {
  /** Every count the figure stands for; a printed range arrives already expanded. */
  counts: number[];
  /**
   * The published container size, in the unit `symbol` names, or null when the
   * source printed it in a form we cannot read exactly — the truncated areas of the
   * ellipse page. A null record keeps its card and shows its formula only.
   */
  value: number | null;
  formula: string;
  /** `s` for a square's side, `r` for a circle's radius. */
  symbol: string;
  status: CopyStatus;
  /** The source's own sentence: "Found by … in …", "Proved by …", "Trivial". */
  attribution: string;
  figure: string;
};

export type CopyFamily = {
  slug: string;
  page: string;
  title: string;
  shape: string;
  container: string;
  /** The collection's own section heading this subfamily belongs to. */
  section: string;
  /** The asset's own claim: can the lab judge this subfamily today? */
  supported: boolean;
  /**
   * The ready-made problem a supported family launches from, built by the catalogue
   * script with the domain's own helpers. It carries the trivial count of one; the
   * card's own count replaces it. Absent on a family the domain cannot express.
   */
  problem_template?: ProblemDoc;
  /**
   * Why a launchable family's published number cannot be read back from its
   * template, or "" when it can. The card shows it as a badge, so a launcher never
   * hides a mismatch between what the source measured and what the engine scores.
   */
  caveat: string;
  intro: string;
  instances: CopyInstance[];
  warnings: string[];
};

export type CopyCatalog = {
  source: string;
  base: string;
  /** Date of the snapshot every reference records as its last check. */
  generated: string;
  families: CopyFamily[];
  warnings: string[];
};

const CATALOG_URL = "/catalog/packing_equal_copies.json";

/** The collection's own heading for the section that maximises total perimeter. */
const PERIMETER_SECTION = "Packing Copies to Maximize Total Perimeter";

/** The side a unit regular polygon has, per the collection's own naming. */
const REGULAR_SIDES: Record<string, number> = {
  triangle: 3,
  square: 4,
  pentagon: 5,
  hexagon: 6,
  octagon: 8,
};

/** The engine palette entry a catalogue shape is read from, when it is not a unit polygon. */
const PALETTE_LABELS: Record<string, string> = {
  tan: "right triangle",
  domino: "domino",
  l: "L-tromino",
};

/**
 * The unit copy a supported subfamily packs, or null when none can be built.
 *
 * The collection measures unit copies, so the shape is taken at the source's own
 * size: side 1 for a regular polygon and radius 1 for a circle — its one-circle
 * square has side 2, which is that radius, not the engine's natural half-unit
 * disc. That is what makes the published size and the engine's own measurement
 * comparable. The tan, the domino and the L have no unit written here at all:
 * their outline is the engine's to define, so it is read from the palette the
 * API sends, and a shape the palette does not carry is not built.
 */
export function copyShape(family: CopyFamily, palette: ShapeFamilyDoc[]): ShapeDoc | null {
  if (family.shape === "circle") return { type: "circle", radius: 1 };
  const sides = REGULAR_SIDES[family.shape];
  if (sides !== undefined) return { type: "regular_polygon", sides, side: 1 };
  const label = PALETTE_LABELS[family.shape];
  if (label === undefined) return null;
  return palette.find((entry) => entry.label === label)?.shape ?? null;
}

/** Whether a card may be added: the asset calls it supported and a problem can be built. */
export function copyable(family: CopyFamily, palette: ShapeFamilyDoc[]): boolean {
  return family.supported && (family.problem_template !== undefined || copyShape(family, palette) !== null);
}

/** Singular and plural of a shape's name: a title to generate, and a key to translate. */
const COPY_NOUNS: Record<string, [string, string]> = {
  circle: ["circle", "circles"],
  triangle: ["triangle", "triangles"],
  square: ["square", "squares"],
  pentagon: ["pentagon", "pentagons"],
  hexagon: ["hexagon", "hexagons"],
  octagon: ["octagon", "octagons"],
  tan: ["tan", "tans"],
  domino: ["domino", "dominoes"],
  l: ["L", "L's"],
};

/** The English noun a card title is built from, so the translator can render it. */
export function copyNoun(shape: string, count: number): string {
  const nouns = COPY_NOUNS[shape];
  if (nouns === undefined) return shape;
  return (count === 1 ? nouns[0] : nouns[1]) ?? shape;
}

/**
 * The noun the container filter shows for a catalogue container.
 *
 * A container is not the packed shape's plural: "circles in squares" packs
 * circles into a *square*, and the two words translate differently in French
 * ("disques" against "carré"). The mapped keys are therefore distinct from the
 * shape nouns, and an unknown container keeps its asset word.
 */
const CONTAINER_NOUNS: Record<string, string> = {
  circle: "container circle", square: "container square", triangle: "container triangle",
  pentagon: "container pentagon", hexagon: "container hexagon", octagon: "container octagon",
  rectangle: "container rectangle", ellipse: "container ellipse",
  tan: "container tan", domino: "container domino", l: "container l",
};

/** The English noun a container filter shows, so the translator can render it. */
export function containerNoun(container: string): string {
  return CONTAINER_NOUNS[container] ?? container;
}

/** The collection's own heading for the section that covers a target region. */
const COVERING_SECTION = "Covering";

/**
 * The identifier namespace of each section, so no two families can collide.
 *
 * A generated document's identifier is its shape's plural noun, the card's count,
 * the section's namespace and the container. The namespace is what keeps two
 * families apart when they put the same shape into the same container from
 * different sections: the matrix packs into the smallest container, the covering
 * section covers the largest target, and the total-perimeter section maximises a
 * sum. The matrix keeps the historical `in-smallest` prefix, so identifiers already
 * stored in a profile library keep pointing at the same problem.
 */
const SECTION_NAMESPACES: Record<string, string> = {
  "Packing Equal Copies": "in-smallest",
  [PERIMETER_SECTION]: "total-perimeter-in",
  [COVERING_SECTION]: "covering",
};

/**
 * The identifier a generated document is filed under, namespaced by its section.
 *
 * The source may print one count beside two different figures: the dominoes-in-squares
 * page prints "3." for figure 5.png as well as for its real n = 3 record. Such a count
 * is ambiguous, so the card also carries its figure's stem and the two cards coexist in
 * a category instead of overwriting one another. The printed number is never changed;
 * only the identifier gains the figure. Every other count keeps the historical shape.
 */
export function copyProblemId(family: CopyFamily, count: number, figure = ""): string {
  const namespace = SECTION_NAMESPACES[family.section] ?? "family";
  const identity = `${copyNoun(family.shape, 2)}-${count}-${namespace}-${family.container}`;
  const stem = figureStem(figure);
  const printed = copyConfigurations(family).filter((card) => card.count === count);
  return printed.length > 1 && stem !== "" ? `${identity}-figure-${stem}` : identity;
}

/** A container as a sentence prints it: the collection's "l" is the letter L. */
function containerWord(container: string): string {
  return container === "l" ? "L" : container;
}

/** A figure file name without its extension, for an identifier that must stay unique. */
function figureStem(figure: string): string {
  return figure.replace(/\.[^./]*$/, "");
}

/** Whether a family asks for the largest sum of the copies' sizes. */
function isPerimeter(family: CopyFamily): boolean {
  return family.section === PERIMETER_SECTION;
}

/** The sum the source prints for a family: radii for circles, sides otherwise. */
function copySum(family: CopyFamily, plural: boolean): string {
  if (family.shape === "circle") return plural ? "radii" : "radius";
  return plural ? "sides" : "side";
}

/**
 * The source page's own URL for a record's figure.
 *
 * The collection publishes one picture per record and we hotlink it instead of
 * copying it: there are about two thousand figures across the catalogue, tens of
 * megabytes of bitmaps, for a panel that shows a handful at a time. The asset
 * already carries the page and the file name, so the URL is those two read
 * together — and an empty answer means the asset has no figure to point at.
 */
export function copyFigureUrl(family: CopyFamily, instance: CopyInstance): string {
  if (family.page === "" || instance.figure === "") return "";
  return family.page + instance.figure;
}

/**
 * One entry per listed count a published figure stands for, so one card is one problem.
 *
 * A count above `MAX_VISIBLE_COUNT` is kept in the asset and expanded nowhere: the
 * interface stops being smooth past about a hundred shapes, so `withinVisibleCount`
 * — the one shared display rule — decides what the navigator may list.
 */
export function copyConfigurations(family: CopyFamily): { count: number; instance: CopyInstance }[] {
  return family.instances
    .flatMap((instance) => instance.counts.map((count) => ({ count, instance })))
    .filter(({ count }) => withinVisibleCount(count));
}

/**
 * A target the derived covering reading measures: the largest shape of this
 * family contained in the union of the unit copies. The names are the engine's
 * own (`maximize_covered_size.target`).
 */
export type CoverTarget = "circle" | "square" | "triangle";

/** Every target name the domain defines, in the order the editor offers them. */
export const COVER_TARGETS: readonly CoverTarget[] = ["circle", "square", "triangle"];

/**
 * The targets the engine is known to measure, as the editor's fallback list.
 *
 * The application still asks the engine at start-up which targets it honours
 * (`measureCoverTargets`), because that answer decides what the editor may offer;
 * this list is only the answer used while that probe is in flight. The catalogue
 * itself no longer consults it: every covering family derives the target its own
 * container names.
 */
export const MEASURED_COVER_TARGETS: readonly CoverTarget[] = ["circle", "square"];

/** The target a covering family's container names, or null for any other container. */
export function coverTargetFor(family: CopyFamily): CoverTarget | null {
  return (COVER_TARGETS as readonly string[]).includes(family.container)
    ? (family.container as CoverTarget)
    : null;
}

/**
 * The document a supported catalogue card adds to the active category.
 *
 * A covering card always builds the one covering model the product exposes: the
 * copies stay at their unit size and `maximize_covered_size` derives the target
 * from the union of their footprints. The target is the family's own container
 * shape, read through `coverTargetFor`; the template's fixed arena and its
 * `cover_region` objective are dropped, while the unit shape, the rotation policy
 * and the metadata carry over. Every other section keeps its template objective.
 * A family without a template — an older asset — falls back on the squares'
 * convention: the unit shape, `minimize_container`, and a free rotation. There is
 * no candidate preview in this collection, so `catalog_candidate_url` is
 * deliberately absent and the engine initializes an arrangement to judge.
 */
export function copyProblem(
  catalog: CopyCatalog,
  family: CopyFamily,
  instance: CopyInstance,
  count: number,
  palette: ShapeFamilyDoc[],
): ProblemDoc {
  if (!family.supported) {
    throw new Error(`the catalogue cannot build a problem for ${family.slug}`);
  }
  const measure = instance.symbol === "r" ? "radius" : instance.symbol === "a" ? "area" : "side";
  const proved = instance.status === "proved";
  // A covering asks the other question: the copies cover the largest target, they
  // are not packed inside the smallest one. A total-perimeter family keeps the
  // container and asks for the largest sum of the copies' sizes instead. The
  // template's objective already says so; only the card's own sentence has to
  // follow the section.
  const covering = family.section === "Covering";
  const perimeter = isPerimeter(family);
  // The one covering model the product exposes derives its target from the
  // family's own container shape. A covering family whose container names no
  // target is refused rather than silently handed the legacy fixed reading.
  const target = covering ? coverTargetFor(family) : null;
  if (covering && target === null) {
    throw new Error(`the covering family ${family.slug} names no derived target`);
  }
  const name = covering
    ? `${count} ${copyNoun(family.shape, count)} covering the largest ${family.container}`
    : perimeter
      ? `${count} ${copyNoun(family.shape, count)} in ${family.container === "ellipse" ? "an" : "a"} ${family.container} with the largest total ${copySum(family, false)}`
      : `${count} ${copyNoun(family.shape, count)} in the smallest ${containerWord(family.container)}`;
  // A record the source printed without a readable number describes its formula
  // instead: the problem is still built, and nothing claims a value we do not have.
  const reference = instance.value === null
    ? `The source prints ${instance.formula === "" ? (perimeter ? "the total" : "the container size") : instance.formula} as a formula the lab cannot read back.`
    : perimeter
      ? `The reference total ${instance.value} is ${proved ? "proved optimal" : "the best published construction, not a proved optimum"}.`
      : `The reference ${measure} ${instance.value} is ${proved ? "proved optimal" : covering
        ? "the largest published construction, not a proved optimum"
        : "the smallest published construction, not a proved optimum"}.`;
  const description = target !== null
    ? `Measure the largest ${family.container} contained in the union of ${count} unit ${copyNoun(family.shape, 2)}. ${reference}`
    : perimeter
      ? `Pack ${count} ${copyNoun(family.shape, 2)} inside a ${family.container}, maximising the sum of their ${copySum(family, true)}. ${reference}`
      : `Pack ${count} unit ${copyNoun(family.shape, 2)} inside the smallest possible ${containerWord(family.container)}. ${reference}`;
  const template = family.problem_template;
  // The engine's own finding about this card, when the verification asset has one: an
  // arrangement it confirmed is offered to the run, and nothing else is.
  const checked = verificationOf(loadedVerification(), family.slug, count);
  const candidate = checked?.candidate ? { catalog_candidate_url: checked.candidate } : {};
  if (template !== undefined) {
    if (target !== null) {
      // The template's arena belongs to the fixed reading the product no longer
      // exposes; the derived objective declares no arena, so the field is dropped.
      const derived: ProblemDoc = {
        ...template,
        problem_id: copyProblemId(family, count, instance.figure),
        name,
        description,
        seed: count,
        objective: { type: "maximize_covered_size", count, target },
        metadata: { ...template.metadata, reference: copyReference(catalog, family, instance, count), ...candidate },
      };
      delete derived.arena;
      return derived;
    }
    return {
      ...template,
      problem_id: copyProblemId(family, count, instance.figure),
      name,
      description,
      seed: count,
      objective: withCount(template.objective, count),
      metadata: { ...template.metadata, reference: copyReference(catalog, family, instance, count), ...candidate },
    };
  }
  const shape = copyShape(family, palette);
  if (shape === null) {
    throw new Error(`the catalogue cannot build a problem for ${family.slug}`);
  }
  if (target !== null) {
    return {
      problem_id: copyProblemId(family, count, instance.figure),
      name,
      description,
      seed: count,
      shape,
      objective: { type: "maximize_covered_size", count, target },
      rotation: { type: "rotation_policy", mode: "free", angles: [0] },
      constraints: [],
      metadata: { reference: copyReference(catalog, family, instance, count), ...candidate },
    };
  }
  return {
    problem_id: copyProblemId(family, count, instance.figure),
    name,
    description,
    seed: count,
    shape,
    objective: { type: "minimize_container", count, container: family.container },
    rotation: { type: "rotation_policy", mode: "free", angles: [0] },
    constraints: [],
    metadata: { reference: copyReference(catalog, family, instance, count), ...candidate },
  };
}

/** The template's objective, its trivial count replaced by the card's own n. */
function withCount(objective: ObjectiveDoc, count: number): ObjectiveDoc {
  // Every family whose instances differ by n carries that n as a count field;
  // reading the field rather than naming the types lets a new objective's
  // template launch without a branch here. maximize_count has no count to fix.
  return "count" in objective ? { ...objective, count } : objective;
}

/**
 * What the published number measures: the container's size for a packing, the
 * covered target's size for a covering.
 */
function measureUnit(family: CopyFamily, symbol: string): string {
  // The perimeter pages print a sum, not a length of the container; its name says
  // radii for circles and sides for every other family, whatever letter the parser
  // read beside the number.
  if (isPerimeter(family)) return `sum of ${copySum(family, true)}`;
  const target = family.section === "Covering" ? "covered" : "container";
  const size = symbol === "r" ? "radius" : symbol === "a" ? "area" : "side";
  return `${target} ${size}`;
}

/** The source sentence read as a reference: construction, proof and last check. */
function copyReference(catalog: CopyCatalog, family: CopyFamily, instance: CopyInstance, count: number): ProblemReference {
  const checked = verificationOf(loadedVerification(), family.slug, count);
  const found = /Found by (.+?) in (.+?)(?:\.|$)/.exec(instance.attribution);
  const proved = /Proved by (.+?) in (.+?)(?:\.|$)/.exec(instance.attribution);
  return {
    status: instance.status,
    value: instance.value,
    unit: measureUnit(family, instance.symbol),
    author: found?.[1] ?? "",
    date: found?.[2] ?? "",
    proved_by: proved?.[1] ?? "",
    proof_date: proved?.[2] ?? "",
    // A date a check happened on, when one did: the entry's own, otherwise the date the
    // catalogue's values were last read from the source pages.
    verified_on: checked?.checked_on ?? catalog.generated,
    note: instance.formula === "" ? instance.attribution : `${instance.attribution} · ${instance.formula}`,
    // Hotlinked, never copied: the reference panel shows the source's own figure. A
    // total-perimeter page colours its copies by size, so its figure keeps its colours.
    preview: copyFigureUrl(family, instance),
    sources: [{ label: `${family.title} · Erich Friedman's Packing Center`, url: family.page }],
  };
}

/** One subfamily's picture: the arrangement the navigator shows, or its reason. */
export type FamilyPreview = {
  /** `rendered` is an engine drawing, `figure` the source's own picture. */
  kind: "rendered" | "figure" | "schematic";
  /** Copies the picture shows, within the builder's 5-15 window. */
  count: number;
  /** The picture itself: a local tile path or the source page's figure URL. */
  url: string;
  /** Why a schematic was drawn, present only for that kind. */
  reason?: string;
};

export type FamilyPreviews = {
  generated: string;
  families: Record<string, FamilyPreview>;
};

const PREVIEWS_URL = "/catalog/family_previews.json";

/**
 * The preview manifest: one real picture per subfamily, chosen by the builder.
 *
 * The maintainers' preview builder decides, for every family, whether the
 * tile is the exact published packing the lab ships, the source's own figure, or
 * — only when the source publishes none — an engine-drawn schematic. The
 * navigator displays that choice and never decides a count of its own, exactly as
 * it displays the catalogue's records without recomputing them.
 */
export async function loadFamilyPreviews(): Promise<FamilyPreviews> {
  const response = await fetch(PREVIEWS_URL);
  if (!response.ok) throw new Error(`Family previews: HTTP ${response.status}`);
  const document: unknown = await response.json();
  if (!isRecord(document) || !isRecord(document.families)) {
    throw new Error("Family previews: unexpected document");
  }
  const families: Record<string, FamilyPreview> = {};
  for (const [slug, value] of Object.entries(document.families)) {
    const entry = readPreview(value);
    if (entry !== null) families[slug] = entry;
  }
  return { generated: text(document.generated), families };
}

function readPreview(value: unknown): FamilyPreview | null {
  if (!isRecord(value)) return null;
  const kind = value.kind;
  if (kind !== "rendered" && kind !== "figure" && kind !== "schematic") return null;
  const count = typeof value.count === "number" && Number.isFinite(value.count) ? value.count : 0;
  const reason = text(value.reason);
  return { kind, count, url: text(value.url), ...(reason === "" ? {} : { reason }) };
}

/** Read the asset, keeping only the records that carry everything a card shows. */
export async function loadCopyCatalog(): Promise<CopyCatalog> {
  const response = await fetch(CATALOG_URL);
  if (!response.ok) throw new Error(`Packing catalogue: HTTP ${response.status}`);
  const document: unknown = await response.json();
  if (!isRecord(document) || !Array.isArray(document.families)) {
    throw new Error("Packing catalogue: unexpected document");
  }
  return {
    source: text(document.source),
    base: text(document.base),
    generated: text(document.generated),
    families: document.families.map(readFamily).filter((family): family is CopyFamily => family !== null),
    warnings: strings(document.warnings),
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function readInstance(value: unknown): CopyInstance | null {
  if (!isRecord(value)) return null;
  const amount = value.value;
  const status = value.status;
  const counts = Array.isArray(value.counts)
    ? value.counts.filter((count): count is number => typeof count === "number" && Number.isInteger(count) && count > 0)
    : [];
  if (counts.length === 0) return null;
  if (status !== "proved" && status !== "best_known" && status !== "none") return null;
  const formula = text(value.formula);
  // The annotation keeps the guarded status a `CopyStatus`; an object literal would
  // widen the three literals back to `string` and the record would stop type-checking.
  const common: Omit<CopyInstance, "value"> = {
    counts,
    formula,
    symbol: text(value.symbol),
    status,
    attribution: text(value.attribution),
    figure: text(value.figure),
  };
  if (typeof amount === "number" && Number.isFinite(amount)) return { ...common, value: amount };
  // A record the source printed in a form we cannot read — a truncated ellipse
  // area — carries no number and is kept only when it has a formula to show.
  if (amount !== null || formula === "") return null;
  return { ...common, value: null };
}

function readFamily(value: unknown): CopyFamily | null {
  if (!isRecord(value)) return null;
  const instances = Array.isArray(value.instances)
    ? value.instances.map(readInstance).filter((instance): instance is CopyInstance => instance !== null)
    : [];
  if (typeof value.slug !== "string" || typeof value.title !== "string" || instances.length === 0) return null;
  return {
    slug: value.slug,
    page: text(value.page),
    title: value.title,
    shape: text(value.shape),
    container: text(value.container),
    section: text(value.section),
    supported: value.supported === true,
    problem_template: readProblemTemplate(value.problem_template),
    caveat: text(value.caveat),
    intro: text(value.intro),
    instances,
    warnings: strings(value.warnings),
  };
}

/**
 * The asset's ready-made problem, or undefined when it is absent or malformed.
 *
 * Only the three fields a launch cannot work without are checked here: the shape,
 * the objective and the rotation. The engine validates the whole document when it
 * is sent, so the browser keeps its one job — carrying what the engine wrote.
 */
function readProblemTemplate(value: unknown): ProblemDoc | undefined {
  if (!isRecord(value) || !isRecord(value.shape) || !isRecord(value.objective) || !isRecord(value.rotation)) {
    return undefined;
  }
  return value as unknown as ProblemDoc;
}

/**
 * Ask the engine which cover targets it measures, by asking it to build one.
 *
 * The engine publishes no list of targets: it accepts a name and answers whether
 * it can measure it, either with a judged candidate or with its own refusal. A
 * minimal derived problem at count 1 and the engine's own grid initialiser is
 * enough to tell the two apart. The answer decides which targets the editor may
 * offer; the catalogue no longer consults it, because every covering family
 * derives the target its own container names.
 */
export async function measureCoverTargets(): Promise<CoverTarget[]> {
  const unit: ShapeDoc = { type: "circle", radius: 1 };
  const measured = await Promise.all(
    COVER_TARGETS.map(async (target): Promise<CoverTarget | null> => {
      const problem: ProblemDoc = {
        problem_id: `cover-target-${target}`,
        name: "",
        description: "",
        seed: null,
        shape: unit,
        objective: { type: "maximize_covered_size", count: 1, target },
        rotation: { type: "rotation_policy", mode: "fixed", angles: [0] },
        constraints: [],
        metadata: {},
      };
      try {
        await api.init({ problem, strategy: "grid" });
        return target;
      } catch {
        return null;
      }
    }),
  );
  return measured.filter((target): target is CoverTarget => target !== null);
}
