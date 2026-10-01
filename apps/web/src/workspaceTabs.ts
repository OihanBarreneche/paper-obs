/**
 * The workspace tabs, and the page edges the book effect derives from them.
 *
 * The list below is the only place the number of tabs is written. The stacked
 * page edges behind the sheet follow one rule, which holds whatever the count:
 * for the active tab at index `i` of `n`, `i` pages stand to its left and
 * `n - 1 - i` to its right. The first tab therefore has none on its left, the
 * last none on its right, and adding or removing a tab needs no other change.
 *
 * Kept apart from the component so the rule can be read — and checked — without
 * a browser.
 */

import type { WorkspaceMode } from "./types";

export const WORKSPACE_TABS: readonly { mode: WorkspaceMode; label: string }[] = [
  { mode: "shapes", label: "Shapes" },
  // The shape composer comes before the arena: building a shape needs no arena,
  // and the palette's "create your own shape" reaches it as much as this tab.
  { mode: "compose", label: "Create" },
  { mode: "arena", label: "Arena" },
  { mode: "run", label: "Agents" },
  { mode: "search", label: "Search" },
];

/**
 * How many page edges the active tab leaves on each side, for one list of tabs.
 *
 * The list is a parameter so the rule can be checked on any count of tabs, which
 * is exactly the property that has to hold when a tab is added or removed. An
 * unknown mode falls back to the first tab, which is also where the application
 * lands when a problem rules another workspace out.
 */
export function pageEdges(
  mode: WorkspaceMode,
  tabs: readonly { mode: WorkspaceMode }[] = WORKSPACE_TABS,
): { left: number; right: number } {
  const found = tabs.findIndex((tab) => tab.mode === mode);
  const active = found < 0 ? 0 : found;
  return { left: active, right: tabs.length - 1 - active };
}

/** The thickness one stacked page edge adds to the block, in pixels. */
export const PAGE_EDGE_WIDTH = 12;
