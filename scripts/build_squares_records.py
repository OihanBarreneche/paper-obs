"""Read the published squares-in-squares table and check the curated records.

David Ellsworth's *Squares in Squares* page lists one box per published record:
the count it covers, its container side, who found or proved it, and its own SVG
figure. The curated rows in `apps/web/src/catalog.ts` must mirror that list
exactly — every count the page publishes, no count it leaves out, and no side
invented for a straight grid the page does not picture.

This script is the reading that keeps them honest. It parses the page's visible
boxes (the commented-out ones do not count), and compares the result with the
rows in `catalog.ts`: the count sets must be equal, every side must match, and
an SVG figure must match wherever the page draws one. It can be run at any time;
the page is cached under ignored `scripts/out/squares-cache/` so a re-run costs no request.

    .venv/bin/python scripts/build_squares_records.py [--refresh]

It changes nothing: the catalogue rows are curated, and a page that moved or a
record that drifted is reported as a failure for a human to fold in.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE_URL = "https://kingbird.myphotos.cc/packing/squares_in_squares.html"
CACHE = ROOT / "scripts/out/squares-cache"
CATALOG = ROOT / "apps/web/src/catalog.ts"
CANDIDATES = ROOT / "apps/web/public/catalog/candidates"

#: Absolute tolerance on a published side. The page prints ten significant
#: digits; `1e-9` is the lab's own validity tolerance.
TOLERANCE = 1e-9

#: The counts the page publishes, read from its visible boxes on 2026-09-26.
#: The gaps are the page's own: 12, 16, 20, 21, 25 and every straight-grid count
#: after them (30-32, 36, 42-45, 49, ...) are simply not listed, and neither is
#: anything between two published figures. The five large counts at the end are
#: the page's demonstrations, not a run of every n.
PUBLISHED_COUNTS = (
    1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14, 15, 17, 18, 19, 22, 23, 24, 26,
    27, 28, 29, 33, 34, 35, 37, 38, 39, 40, 41, 46, 47, 48, 50, 51, 52, 53, 54,
    55, 62, 63, 65, 66, 67, 68, 69, 70, 71, 79, 80, 82, 83, 84, 85, 86, 87, 88,
    89, 98, 99, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 119, 120, 122,
    123, 124, 125, 126, 127, 128, 129, 130, 131, 132, 142, 143, 145, 146, 147,
    148, 149, 150, 151, 152, 153, 154, 155, 156, 167, 168, 170, 171, 172, 173,
    174, 175, 176, 177, 178, 179, 180, 181, 182, 194, 195, 197, 198, 199, 200,
    201, 202, 203, 204, 205, 206, 207, 208, 209, 210, 223, 224, 226, 227, 228,
    229, 230, 231, 232, 233, 234, 235, 236, 237, 238, 239, 240, 241, 254, 255,
    257, 258, 259, 260, 261, 262, 263, 264, 265, 266, 267, 268, 269, 270, 271,
    272, 273, 287, 288, 290, 291, 292, 293, 294, 295, 296, 297, 298, 299, 300,
    301, 302, 303, 304, 305, 306, 307, 322, 323, 626, 1453, 1765, 1850, 2043,
)

#: The rows of `catalog.ts` are a JavaScript array of JSON-compatible tuples.
ROW_BLOCK = re.compile(r"const (?P<name>ROWS|EXTRA_ROWS): Row\[\] = \[(?P<body>.*?)\n\];", re.S)

#: The page's own markup, as the boxes are written by the generator.
COMMENT = re.compile(r"<!--.*?-->", re.S)
BOX = re.compile(r'<div class="box">')
HEADING = re.compile(r'<font size="\+3">\s*([^<]*)<br>')
EMBED = re.compile(r'<embed[^>]*src="(square-[^"]+?)"')
DESCRIPTION = re.compile(r'<div align="center">(.*?)</div>', re.S)
TAG = re.compile(r"<[^>]+>")
NUMBER_MACRO = re.compile(r"\\Nn\{([0-9.]+)\}")
SIMPLE_VALUE = re.compile(r"\$s\s*=\s*([0-9.]+)\s*\$")

#: A side above this count ships as a local candidate instead of a page figure.
LOCAL_CANDIDATE_MAX = 29


def fetch(refresh: bool = False) -> str:
    """Return the page's HTML, cached on disk: a re-run costs no request."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / "squares_in_squares.html"
    if path.is_file() and not refresh:
        return path.read_text(encoding="utf-8", errors="replace")
    request = urllib.request.Request(PAGE_URL, headers={"User-Agent": "paper-obs squares reader"})
    with urllib.request.urlopen(request, timeout=60) as answer:
        text = answer.read().decode("utf-8", errors="replace")
    path.write_text(text, encoding="utf-8")
    return text


def visible(fragment: str) -> str:
    """Return one HTML fragment's readable text, its whitespace collapsed."""
    return re.sub(r"\s+", " ", unescape(TAG.sub(" ", fragment))).strip()


def parse_page(html: str) -> dict[int, dict]:
    """Return one record per count the page publishes, keyed by that count.

    The boxes hidden in HTML comments are skipped: the page keeps a superseded box
    that way, and it is not a published record. Every count of a grouped heading
    ("47, 48") shares the box's value, status and figure, exactly as the page
    draws them.
    """
    body = COMMENT.sub("", html)
    starts = [match.start() for match in BOX.finditer(body)]
    records: dict[int, dict] = {}
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(body)
        chunk = body[start:end]
        heading = HEADING.search(chunk)
        if heading is None:
            continue
        counts = [int(value) for value in re.findall(r"\d+", heading.group(1))]
        description = DESCRIPTION.search(chunk)
        text = visible(description.group(1)) if description else ""
        macro = NUMBER_MACRO.search(text)
        simple = SIMPLE_VALUE.search(text)
        value = float(macro.group(1)) if macro else (float(simple.group(1)) if simple else None)
        figure = EMBED.search(chunk)
        status = "proved" if ("Proved by" in text or "Trivial" in text) else "best_known"
        for count in counts:
            records[count] = {
                "value": value,
                "status": status,
                "figure": figure.group(1) if figure else "",
                "description": text,
            }
    return records


def catalog_rows(path: Path = CATALOG) -> dict[int, list]:
    """Return the curated rows of `catalog.ts`, keyed by count."""
    text = path.read_text(encoding="utf-8")
    rows: dict[int, list] = {}
    for block in ROW_BLOCK.finditer(text):
        for line in block.group("body").splitlines():
            line = line.strip().rstrip(",")
            if not line.startswith("["):
                continue
            row = json.loads(line)
            rows[int(row[0])] = row
    return rows


def check(page: dict[int, dict], rows: dict[int, list]) -> list[str]:
    """Return the disagreements between the page and the curated records."""
    problems: list[str] = []
    published = set(PUBLISHED_COUNTS)
    if set(page) != published:
        problems.append(f"the constant and the page disagree: {sorted(set(page) ^ published)}")
    if set(rows) != published:
        missing = sorted(published - set(rows))
        extra = sorted(set(rows) - published)
        problems.append(f"catalog.ts has {len(extra)} counts the page leaves out: {extra}")
        problems.append(f"catalog.ts is missing {len(missing)} counts the page lists: {missing}")
    for count in sorted(published & set(rows) & set(page)):
        row, record = rows[count], page[count]
        if len(row) < 2 or abs(float(row[1]) - record["value"]) > TOLERANCE:
            problems.append(f"n={count}: catalog side {row[1:2]} against the page's {record['value']}")
        figure = row[6] if len(row) > 6 else ""
        if count > LOCAL_CANDIDATE_MAX and figure != record["figure"]:
            problems.append(f"n={count}: catalog figure {figure!r} against the page's {record['figure']!r}")
        if count <= LOCAL_CANDIDATE_MAX:
            if figure != "":
                problems.append(f"n={count}: expected the local candidate, found figure {figure!r}")
            if not (CANDIDATES / f"squares-{count}.json").is_file():
                problems.append(f"n={count}: no local candidate ships for the record")
    return problems


def main(argv: list[str] | None = None) -> int:
    """Read the page, compare it with the curated records, and report."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="re-download even the cached page")
    arguments = parser.parse_args(argv)

    page = parse_page(fetch(arguments.refresh))
    rows = catalog_rows()
    problems = check(page, rows)
    print(f"page: {len(page)} published counts, catalog: {len(rows)} curated rows")
    print(f"gaps around 41-46: 41={41 in page}, 42-45={sorted(c for c in (42, 43, 44, 45) if c in page)}, 46={46 in page}")
    if problems:
        print(f"\n{len(problems)} disagreement(s):")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print("the catalogue mirrors the page exactly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
