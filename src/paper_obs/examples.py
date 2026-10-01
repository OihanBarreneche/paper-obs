"""Example runs and research sessions shipped with the lab, so that a first visitor can read
agent traces without paying for a run.

The examples live in ``examples/`` at the root of a source checkout: ``runs/`` holds run
documents, ``research/`` session folders. :func:`seed` copies each one into the runs folder
the first time the lab starts, and records it in ``examples.json`` there, so an example the
owner deletes is never copied back. A copied document says ``"example": true``: the listings
pass it on, and the statistics leave it out.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from paper_obs.storage.files import runs_directory

#: The shipped examples, in a source checkout.
EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
#: The file, in the runs folder, that lists the examples already copied there.
MARKER = "examples.json"


def seed(directory: Path | None = None, source: Path | None = None) -> list[str]:
    """Copy each shipped example not copied before into the runs folder; return their names."""
    folder = runs_directory() if directory is None else directory
    shipped = EXAMPLES if source is None else source
    marker = folder / MARKER
    try:
        seeded = set(json.loads(marker.read_text(encoding="utf-8"))["seeded"])
    except (OSError, ValueError, KeyError, TypeError):
        seeded = set()
    copied = []
    pairs = [(path, folder / path.name) for path in sorted((shipped / "runs").glob("*.json"))]
    pairs += [(path.parent, folder / "research" / path.parent.name)
              for path in sorted((shipped / "research").glob("*/session.json"))]
    for origin, target in pairs:
        name = f"{origin.parent.name}/{origin.name}"
        if name in seeded or target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if origin.is_dir():
            shutil.copytree(origin, target)
            (target / "work").mkdir(exist_ok=True)
        else:
            shutil.copyfile(origin, target)
        seeded.add(name)
        copied.append(name)
    if copied:
        marker.write_text(json.dumps({"seeded": sorted(seeded)}, indent=2), encoding="utf-8")
    return copied


__all__ = ["EXAMPLES", "MARKER", "seed"]
