import type { ProblemDoc } from "./types";
import { SQUARE_RECORDS, squareProblem } from "./catalog";
import { copyProblem } from "./equalCopiesCatalog";
import type { CopyCatalog } from "./equalCopiesCatalog";
import starterCatalog from "./starterCatalog.json";
import workflowDemoCatalog from "./workflowDemoCatalog.json";
import beatenRecordsCatalog from "./beatenRecordsCatalog.json";

export type ProfileCategory = { id: string; name: string; problemIds: string[] };
export type ProfileLibrary = { categories: ProfileCategory[]; problems: Record<string, ProblemDoc> };

const STORAGE_KEY = "paper-obs-profile-library-v1";
export const STARTER_CATEGORY_ID = "square-intro";
const RECORDS_CATEGORY_ID = "beaten-records";

/** Built-in categories a saved library has already been offered, oldest first. A library
 * saved before the list existed has seen the first four; a later built-in joins it once,
 * and stays away if the user deletes it. */
const BUILT_IN_IDS = [STARTER_CATEGORY_ID, "packing-variety", "other-objectives", "workflow-demo", RECORDS_CATEGORY_ID];
const FIRST_BUILT_INS = 4;

const SQUARE_COUNTS = [2, 5, 10, 11, 17, 29];
const VARIETY = [["cirincir", 3], ["triinsqu", 2], ["penincir", 3], ["hexinsqu", 4], ["squintri", 2]] as const;
const OTHER = [["cirRcir", 2], ["cirRsqu", 2], ["triRsqu", 2], ["circovcir", 3], ["circovsqu", 2], ["squcosqu", 3]] as const;
const WORKFLOW_DEMO = [["peninsqu", 5], ["peninsqu", 8], ["peninsqu", 12],
  ["cirRcir", 5], ["sqcovcir", 7]] as const;

/** Curated entry points use the same catalog builder as Add a problem. */
function starterProblems(): { squares: ProblemDoc[]; variety: ProblemDoc[]; other: ProblemDoc[]; workflowDemo: ProblemDoc[]; records: ProblemDoc[] } {
  const catalog = starterCatalog as unknown as CopyCatalog;
  const demoCatalog = workflowDemoCatalog as unknown as CopyCatalog;
  const recordsCatalog = beatenRecordsCatalog as unknown as CopyCatalog;
  const fromCatalog = ([slug, count]: readonly [string, number]): ProblemDoc => {
    const family = catalog.families.find((entry) => entry.slug === slug);
    const instance = family?.instances.find((entry) => entry.counts.includes(count));
    if (!family || !instance) throw new Error(`Missing starter catalog entry: ${slug}/${count}`);
    const problem = copyProblem(catalog, family, instance, count, []);
    return { ...problem, metadata: { ...problem.metadata,
      catalog_candidate_url: `/catalog/candidates/starter-${slug}-${count}.json`,
    } };
  };
  const fromDemo = ([slug, count]: readonly [string, number]): ProblemDoc => {
    const family = demoCatalog.families.find((entry) => entry.slug === slug);
    const instance = family?.instances.find((entry) => entry.counts.includes(count));
    if (!family || !instance) throw new Error(`Missing workflow demo entry: ${slug}/${count}`);
    return copyProblem(demoCatalog, family, instance, count, []);
  };
  return {
    squares: SQUARE_COUNTS.map((count) => {
      const record = SQUARE_RECORDS.find((entry) => entry.count === count);
      if (!record) throw new Error(`Missing square record: ${count}`);
      return squareProblem(record);
    }),
    variety: VARIETY.map(fromCatalog),
    other: OTHER.map(fromCatalog),
    workflowDemo: WORKFLOW_DEMO.map(fromDemo),
    // Each card keeps the published record as its reference (figure, value, author)
    // and opens on the arrangement that beat it.
    records: recordsCatalog.families.flatMap((family) => family.instances.flatMap((instance) =>
      instance.counts.map((count) => {
        const problem = copyProblem(recordsCatalog, family, instance, count, []);
        return { ...problem, metadata: { ...problem.metadata,
          catalog_candidate_url: `/catalog/candidates/record-${family.slug}-${count}.json` } };
      }))),
  };
}

export function defaultLibrary(): ProfileLibrary {
  const starters = starterProblems();
  return {
    categories: [
      { id: STARTER_CATEGORY_ID, name: "Start here · squares", problemIds: starters.squares.map((problem) => problem.problem_id) },
      { id: "packing-variety", name: "Explore packing", problemIds: starters.variety.map((problem) => problem.problem_id) },
      { id: "other-objectives", name: "Other objectives", problemIds: starters.other.map((problem) => problem.problem_id) },
      { id: "workflow-demo", name: "Demo Workflow", problemIds: starters.workflowDemo.map((problem) => problem.problem_id) },
      { id: RECORDS_CATEGORY_ID, name: "Records beaten by Claude", problemIds: starters.records.map((problem) => problem.problem_id) },
    ],
    problems: Object.fromEntries([...starters.squares, ...starters.variety, ...starters.other, ...starters.workflowDemo,
      ...starters.records].map((problem) => [problem.problem_id, problem])),
  };
}

export function readLibrary(): ProfileLibrary {
  try {
    const saved = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "null") as
      (Partial<ProfileLibrary> & { builtIns?: unknown; offeredRecords?: unknown }) | null;
    if (!saved || !Array.isArray(saved.categories) || !saved.problems || typeof saved.problems !== "object") {
      return defaultLibrary();
    }
    const categories = saved.categories.filter((item): item is ProfileCategory =>
      item !== null && typeof item.id === "string" && typeof item.name === "string" && Array.isArray(item.problemIds))
      .map((item) => ({ ...item, problemIds: item.problemIds.filter((id) => typeof id === "string") }));
    if (!categories.length) return defaultLibrary();
    const defaults = defaultLibrary();
    const seen = Array.isArray(saved.builtIns) ? saved.builtIns : BUILT_IN_IDS.slice(0, FIRST_BUILT_INS);
    const added = defaults.categories.filter((category) => !seen.includes(category.id)
      && !categories.some((item) => item.id === category.id));
    // A record beaten after the library was saved joins its category once, like a new
    // built-in category; one the user removed stays away.
    const offered = Array.isArray(saved.offeredRecords) ? saved.offeredRecords : [];
    const records = defaults.categories.find((category) => category.id === RECORDS_CATEGORY_ID)?.problemIds ?? [];
    const fresh = records.filter((id) => !offered.includes(id));
    const merged = categories.map((category) => category.id !== RECORDS_CATEGORY_ID ? category
      : { ...category, problemIds: [...category.problemIds, ...fresh.filter((id) => !category.problemIds.includes(id))] });
    // A record's document is generated, not curated: the shipped one (its reference
    // re-read on the page) replaces whatever copy the browser saved.
    const shipped = Object.fromEntries(records.flatMap((id) => {
      const problem = defaults.problems[id];
      return problem === undefined ? [] : [[id, problem] as const];
    }));
    return { categories: [...merged, ...added],
      problems: { ...defaults.problems, ...saved.problems as Record<string, ProblemDoc>, ...shipped } };
  } catch {
    return defaultLibrary();
  }
}

export function saveLibrary(library: ProfileLibrary): void {
  // Whatever is saved has been offered every current built-in category and record.
  const records = defaultLibrary().categories.find((category) => category.id === RECORDS_CATEGORY_ID)?.problemIds ?? [];
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...library, builtIns: BUILT_IN_IDS, offeredRecords: records }));
}

export function includeProfile(library: ProfileLibrary, categoryId: string, problem: ProblemDoc | string): ProfileLibrary {
  const id = typeof problem === "string" ? problem : problem.problem_id;
  return {
    categories: library.categories.map((category) => category.id !== categoryId || category.problemIds.includes(id)
      ? category : { ...category, problemIds: [...category.problemIds, id] }),
    problems: typeof problem === "string" ? library.problems : { ...library.problems, [id]: problem },
  };
}

export function removeProfile(library: ProfileLibrary, categoryId: string, problemId: string): ProfileLibrary {
  return {
    ...library,
    categories: library.categories.map((category) => category.id === categoryId
      ? { ...category, problemIds: category.problemIds.filter((id) => id !== problemId) } : category),
  };
}

export function removeCategory(library: ProfileLibrary, categoryId: string): ProfileLibrary {
  return { ...library, categories: library.categories.filter((category) => category.id !== categoryId) };
}

export function replaceProfile(library: ProfileLibrary, categoryId: string, oldId: string, problem: ProblemDoc): ProfileLibrary {
  return {
    categories: library.categories.map((category) => category.id === categoryId
      ? { ...category, problemIds: category.problemIds.includes(oldId)
        ? category.problemIds.map((id) => id === oldId ? problem.problem_id : id)
        : [...category.problemIds, problem.problem_id] }
      : category),
    problems: { ...library.problems, [problem.problem_id]: problem },
  };
}
