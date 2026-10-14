"""Refresh hosted reference records, their compact copies and source dates.

Run from the checkout with its Python environment. Default: live refresh and
apply after every source succeeds. --check previews; --offline --check replays
cached HTML without claiming a new source check. No images or coordinates are
downloaded. Changed external squares and index membership require review.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import build_packing_catalog as packing
import build_squares_records as squares

ROOT = Path(__file__).resolve().parents[1]
ASSET = ROOT / "apps/web/public/catalog/packing_equal_copies.json"
CACHE = ROOT / "scripts/out/catalog-update"
REPORT = ROOT / ".private/catalog-update/latest.json"
SOURCE_FIELDS = ("value", "formula", "symbol", "status", "attribution", "figure",
                 "value_upper_bound", "source_ambiguous", "source_values")
MAXIMIZED = {"Covering", "Packing Copies to Maximize Total Perimeter"}
COMPACT = ("starterCatalog.json", "beatenRecordsCatalog.json", "workflowDemoCatalog.json")


def encoded(value: dict) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".writing")
    temporary.write_text(encoded(value), encoding="utf-8")
    temporary.replace(path)


def fetch(url: str, name: str, *, offline: bool) -> str:
    """Use HTTP validators on live checks; a 304 is a fresh source check too."""
    path, metadata = CACHE / f"{name}.html", CACHE / f"{name}.json"
    if offline:
        return path.read_text(encoding="utf-8")
    headers = {"User-Agent": "paper-obs owner-requested catalog refresh"}
    if path.exists() and metadata.exists():
        stored = json.loads(metadata.read_text(encoding="utf-8"))
        if stored.get("url") == url:
            headers.update({key: stored[value] for key, value in (
                ("If-None-Match", "etag"), ("If-Modified-Since", "last_modified")
            ) if stored.get(value)})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
            text = response.read().decode("utf-8", errors="replace")
            validators = {"url": url, "etag": response.headers.get("ETag"),
                          "last_modified": response.headers.get("Last-Modified")}
    except urllib.error.HTTPError as error:
        if error.code == 304 and path.exists():
            return path.read_text(encoding="utf-8")
        raise
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    write(metadata, validators)
    return text


def index_membership(html: str) -> set[str]:
    """Use the existing index reader, without fetching a stale index twice."""
    original = packing.fetch
    try:
        packing.fetch = lambda *args, **kwargs: html
        hosted, _ = packing.equal_copies_index()
    finally:
        packing.fetch = original
    result = {slug for slug, _ in hosted}
    for section, slugs, _ in packing.index_sections(html):
        if section in packing.SECTIONS and section != "Packing Equal Copies":
            result.update(slug for slug in slugs if slug not in packing.UNPUBLISHED)
    return result


def refresh_family(family: dict, html: str, checked_on: str) -> dict:
    """Replace source fields only, preserving templates and engine-owned data."""
    current = copy.deepcopy(family)
    warnings: list[str] = []
    records = packing.instances(html, family["slug"], warnings)
    if not records or any(": skipped " in item for item in warnings):
        raise ValueError(f"unreadable records: {warnings}")
    previous = {n: row for row in family["instances"] for n in row["counts"]}
    seen: dict[int, dict] = {}
    for row in records:
        if family["section"] not in MAXIMIZED:
            row.pop("value_upper_bound", None)
        elif row["value"] is not None:
            row.setdefault("value_upper_bound", row["value"])
        for count in row["counts"]:
            previous_row = seen.get(count)
            if previous_row is None:
                seen[count] = row
            elif row["value"] is None or previous_row["value"] is None:
                raise ValueError(f"ambiguous overlapping source count: {count}")
            else:
                warnings.append(f"{family['slug']}: overlapping count {count}; retained best printed value")
                higher = family["section"] in MAXIMIZED
                better = row["value"] > previous_row["value"] if higher else row["value"] < previous_row["value"]
                if better:
                    seen[count] = row
        old = previous.get(row["counts"][-1], {})
        for key in old.keys() - row.keys() - set(SOURCE_FIELDS) - {"counts"}:
            row[key] = copy.deepcopy(old[key])
    for row in records:
        row["counts"] = [n for n in row["counts"] if seen[n] is row]
    records = [row for row in records if row["counts"]]
    current.update(instances=records, warnings=warnings, intro=packing.intro(html),
                   source_checked_on=checked_on)
    return current


def changes_of(before: dict, after: dict) -> list[dict]:
    changes = []
    for old, new in zip(before["families"], after["families"], strict=True):
        a = {n: row for row in old["instances"] for n in row["counts"]}
        b = {n: row for row in new["instances"] for n in row["counts"]}
        for count in sorted(a.keys() | b.keys()):
            left = {k: a[count].get(k) for k in SOURCE_FIELDS} if count in a else None
            right = {k: b[count].get(k) for k in SOURCE_FIELDS} if count in b else None
            if left == right:
                continue
            kind = "added" if left is None else "removed" if right is None else "metadata"
            if left and right and left["value"] is not None and right["value"] is not None and left["value"] != right["value"]:
                kind = "improved" if (right["value"] > left["value"]) == (new["section"] in MAXIMIZED) else "worsened"
                if left["formula"] == right["formula"] and left["attribution"] == right["attribution"]:
                    kind = "numeric_correction"
            if right and right.get("source_ambiguous"):
                kind = "ambiguous_source"
            changes.append({"family": new["slug"], "count": count, "page": new["page"],
                            "change": kind, "before": left, "after": right})
    return changes


def compact_copy(document: dict, families: dict, checked_on: str) -> dict:
    """Refresh selected source rows; keep candidate links and historic values."""
    current = copy.deepcopy(document)
    current["generated"] = checked_on
    for family in current["families"]:
        source = families[family["slug"]]
        family.update(source_checked_on=checked_on, warnings=source["warnings"], intro=source["intro"])
        rows = {n: row for row in source["instances"] for n in row["counts"]}
        for row in family["instances"]:
            matched = [rows.get(n) for n in row["counts"]]
            if any(item is None for item in matched) or any(
                any(item.get(k) != matched[0].get(k) for k in SOURCE_FIELDS) for item in matched[1:]
            ):
                raise ValueError(f"compact selection needs review: {family['slug']} {row['counts']}")
            reference = matched[0]
            if row["value"] != reference["value"]:
                row.setdefault("historical_reference", {k: row.get(k) for k in SOURCE_FIELDS[:6]})
            for key in SOURCE_FIELDS:
                if key in reference:
                    row[key] = copy.deepcopy(reference[key])
                else:
                    row.pop(key, None)
    return current


def audit_of(report: dict, prior: dict) -> dict:
    """Keep earlier source changes inspectable when the latest audit replaces them."""
    current = {k: v for k, v in report.items() if k != "offline"}
    history = copy.deepcopy(prior.get("history", []))
    if prior.get("changes"):
        history.append({k: copy.deepcopy(v) for k, v in prior.items() if k != "history"})
    if history:
        current["history"] = history
    return current


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="report without changing published assets")
    parser.add_argument("--offline", action="store_true", help="replay cache; requires --check, retains source dates")
    args = parser.parse_args(argv)
    if args.offline and not args.check:
        parser.error("--offline requires --check")
    started = time.perf_counter()
    old = json.loads(ASSET.read_text(encoding="utf-8"))
    checked_on = old["generated"] if args.offline else date.today().isoformat()
    report = {"checked_on": checked_on, "offline": args.offline, "failures": [], "changes": []}
    try:
        index = fetch(old["source"], "index", offline=args.offline)
        members = index_membership(index)
        known = {f["slug"] for f in old["families"]}
        if members != known:
            raise ValueError(f"index membership needs review: added={sorted(members-known)}, removed={sorted(known-members)}")
        updated: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=4) as pool:
            tasks = {pool.submit(fetch, f["page"], f["slug"], offline=args.offline): f for f in old["families"]}
            for task in as_completed(tasks):
                family = tasks[task]
                try:
                    updated[family["slug"]] = refresh_family(family, task.result(), checked_on)
                except Exception as error:
                    report["failures"].append({"family": family["slug"], "error": str(error)})
                done = len(updated) + len(report["failures"])
                if done % 10 == 0 or done == len(tasks):
                    print(f"Sources: {done}/{len(tasks)} ({time.perf_counter()-started:.1f}s)", flush=True)
        external = squares.parse_page(fetch(squares.PAGE_URL, "squares", offline=args.offline))
        differences = squares.check(external, squares.catalog_rows())
        if differences:
            report["failures"].append({"family": "external-squares", "error": differences})
        if report["failures"]:
            raise ValueError("source checks failed; published assets were not changed")
        new = copy.deepcopy(old)
        new.update(generated=checked_on, families=[updated[f["slug"]] for f in old["families"]])
        new["warnings"] = [w for f in new["families"] for w in f["warnings"]]
        report["changes"] = changes_of(old, new)
        report["totals"] = dict(Counter(c["change"] for c in report["changes"]))
        outputs = {ASSET: new}
        for name in COMPACT:
            path = ROOT / "apps/web/src" / name
            outputs[path] = compact_copy(json.loads(path.read_text(encoding="utf-8")), updated, checked_on)
        catalog_ts = ROOT / "apps/web/src/catalog.ts"
        ts = re.sub(r'const VERIFIED_ON = "[0-9-]+";', f'const VERIFIED_ON = "{checked_on}";', catalog_ts.read_text(encoding="utf-8"))
        report["families"] = [{"slug": f["slug"], "page": f["page"], "checked_on": checked_on,
                               "entries": len(f["instances"]), "changes": dict(Counter(
                                   c["change"] for c in report["changes"] if c["family"] == f["slug"]))}
                              for f in new["families"]]
        report["scope"] = "All hosted catalog families; linked external squares checked separately. Source readings, not proofs."
        if not args.check:
            # Only changed references need a fresh engine comparison. build() is
            # read-only; do not overwrite locally edited published candidates.
            verification = ASSET.parent / "verification.json"
            if report["changes"]:
                from paper_obs.catalog_verification import build
                staged = ASSET.with_name(ASSET.name + ".writing")
                staged.write_text(encoded(new), encoding="utf-8")
                try:
                    summary, _ = build(staged, checked_on)
                finally:
                    staged.unlink(missing_ok=True)
                summary["asset"] = ASSET.name
            else:
                summary = json.loads(verification.read_text(encoding="utf-8"))
                summary["catalog_generated"] = checked_on
            outputs[verification] = summary
            audit = ASSET.parent / "source_audit.json"
            prior = json.loads(audit.read_text(encoding="utf-8")) if audit.exists() else {}
            if report["changes"] or prior.get("checked_on") != checked_on:
                outputs[audit] = audit_of(report, prior)
            # Every input and derived output is checked before the first write.
            for path, value in outputs.items():
                if not path.exists() or path.read_text(encoding="utf-8") != encoded(value):
                    write(path, value)
            if catalog_ts.read_text(encoding="utf-8") != ts:
                temporary = catalog_ts.with_name(catalog_ts.name + ".writing")
                temporary.write_text(ts, encoding="utf-8")
                temporary.replace(catalog_ts)
    except Exception as error:
        report["failures"].append({"error": str(error)})
    report["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    write(REPORT, report)
    print(f"Changes: {report.get('totals', {})}; failures: {len(report['failures'])}; elapsed: {report['elapsed_seconds']}s", flush=True)
    print(f"Report: {REPORT}", flush=True)
    for failure in report["failures"]:
        print(failure, flush=True)
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
