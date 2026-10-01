/**
 * What the engine has checked of the catalogue, as the verification asset reports it.
 *
 * `apps/web/public/catalog/verification.json` is written by
 * `paper_obs.catalog_verification`; this module reads it once and hands the answer to
 * whoever needs it. It decides nothing geometric: a card's level, its gap and the
 * candidate file that holds the arrangement are the engine's own findings.
 *
 * The asset is read at run time rather than bundled, so a maintainer can refresh it
 * without rebuilding the interface, and a missing asset simply means nothing has been
 * checked — never that everything has.
 */

export type VerificationEntry = {
  /** What the engine read of the arrangement against the published number. */
  status: string;
  /** How close what we hold is to the record: exact, near, approx, far or beaten. */
  level: "exact" | "near" | "approx" | "far" | "beaten" | "none";
  /** Whether the page printed enough decimals for the comparison to settle a record. */
  precise: boolean;
  /** Whether the arrangement held is the source's own rather than the lab's. */
  published: boolean;
  /** Whether this card's record may be treated as verified. */
  promoted: boolean;
  value: number | null;
  unit: string;
  measured: number | null;
  gap: number | null;
  source_kind: string;
  files: string[];
  /** The candidate file the interface may open, or null when none is offered. */
  candidate: string | null;
  checked_on: string;
};

export type FamilyVerification = {
  title: string;
  section: string;
  shape: string;
  container: string;
  /** The date the engine last judged a card of this family. */
  checked_on: string;
  source: { kind: string; label: string; url: string };
  entries: Record<string, VerificationEntry>;
};

export type CatalogVerification = {
  generated: string;
  /** The catalogue build this summary was taken against. */
  catalog_generated: string;
  required_decimals: number;
  near_gap: number;
  approx_gap: number;
  families: Record<string, FamilyVerification>;
};

const VERIFICATION_URL = "/catalog/verification.json";

let cache: CatalogVerification | null = null;

function empty(): CatalogVerification {
  return { generated: "", catalog_generated: "", required_decimals: 5, near_gap: 1e-4, approx_gap: 1e-3, families: {} };
}

/** Read the verification asset, once per session. A missing asset is an empty one. */
export async function loadVerification(): Promise<CatalogVerification> {
  if (cache !== null) return cache;
  try {
    const response = await fetch(VERIFICATION_URL);
    cache = response.ok ? await response.json() as CatalogVerification : empty();
  } catch {
    cache = empty();
  }
  return cache;
}

/** What has been read so far, or null before the asset is loaded. */
export function loadedVerification(): CatalogVerification | null {
  return cache;
}

/** What the engine established about one card, or null when nothing was checked. */
export function verificationOf(
  verification: CatalogVerification | null, family: string, count: number,
): VerificationEntry | null {
  return verification?.families[family]?.entries[String(count)] ?? null;
}

/** A gap as a readable percentage of the record. */
export function gapPercent(gap: number): string {
  return `${(gap * 100).toPrecision(2)} %`;
}
