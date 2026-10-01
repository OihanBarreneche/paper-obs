# Problems and catalog

A problem declares one shape family, an objective, rotation policy, seed and optional constraints. Most problems also declare an arena. Container minimization and some covering objectives derive the relevant region from the candidate instead. A candidate holds placements and a common scale; maximum-total-perimeter placements additionally use local scales. The domain JSON format is explicit and intended to remain readable across versions.

| Objective | Question | Main validity rule |
| --- | --- | --- |
| `maximize_scale` | How large can a fixed number of equal copies be? | Copies fit and do not overlap |
| `maximize_count` | How many fixed-size copies fit? | Copies fit and do not overlap |
| `minimize_container` | How small a surrounding container holds a fixed set? | No overlaps; region is measured from placements |
| `cover_region` / `maximize_covered_size` | What target can copies cover? | Target is covered; copies may overlap and protrude |
| `maximize_total_perimeter` | How large can the sum of copy perimeters be? | Independent sizes; copies fit and do not overlap |

The primary score is oriented so larger means better. The UI may promote another, more readable measurement, such as container side or sum of radii. For total perimeter of unit-circle copies, the sum of local radius scales is proportional to total perimeter; for unit regular polygons, the sum of side scales is proportional. Compare candidates only within the same exact problem and units.

Shapes include discs, regular polygons and connected custom polygons. The editor can compose primitives into a custom shape; holes and disconnected results are currently rejected. Composite arenas can have unions, cuts and intersections. This is 2D only.

## Reference catalog snapshot

The bundled catalog at `apps/web/public/catalog/packing_equal_copies.json` was generated on 2026-10-02 from [Erich Friedman's packing collection](https://erich-friedman.github.io/packing/index.html) and linked problem pages. It currently contains **107 families and 3,996 entries**:

| Section | Families | Entries | Supported families |
| --- | ---: | ---: | ---: |
| Packing equal copies | 80 | 3,098 | 79 |
| Maximum total perimeter | 16 | 701 | 16 |
| Covering | 9 | 139 | 9 |
| Other, currently unsupported | 2 | 58 | 0 |

“Supported” means the current engine can construct and judge that family's problem. It does **not** promise a useful initializer, a baseline, a verified optimum or a complete candidate. Total-perimeter search currently has a varied initializer but no dedicated classical baseline. Four catalog families carry explicit caveats (`cirinel`, `cirRell`, `cirRrec`, `squcosqu`): published and engine quantities or container assumptions are not directly interchangeable.

The catalog stores source links, attributions, stated proof status and a last-check date; `generated` is when its values were last read from the sources, and a card whose arrangement the engine has judged carries the date of that check instead. A published construction must not be labeled a proved optimum unless its source says so. These are snapshot records, not live queries; a record can be superseded. Some previews link to source-hosted images, so they may be unavailable offline. Candidate coordinate files under `apps/web/public/catalog/candidates/` are separate from reference values and must be judged by the engine after import.

Reference units matter: squares in a smallest triangle are solved by enlarging copies inside a unit triangle; the engine also reports the equivalent triangle side for unit copies. Every fixed catalog container is normalised so that the length its page prints is 1: a regular polygon's side, a tan's leg, a domino's short side, and an L's short side, except on the circle and square pages, which print the L's long side. A non-regular arena declares that length as `reference_length`, so the engine reports `equivalent_container_side` for it too. The three-square covering source publishes **area**, while the covering objective searches over target side; the UI leads with the engine's target area for that reference. Two triangles maximizing total side in a square have a continuum of optimal placements, including the bundled equal-size pair.

## What the engine has checked

A catalog value is what a source page printed; `verification.json`, written by `scripts/verify_catalog_records.py`, is what the engine reads back. The script builds the problem the interface builds for a card — the family's template at that count, the section's objective, a covering's derived target — finds every candidate file that could describe it, hands each to the engine, and reads the source's own unit out of the verdict: a container side for a packing, a sum of radii or sides for a total-perimeter family, the covered size for a covering. `--check` fails when the file no longer matches the catalog or the candidates it settles.

What it can find coordinates for is limited. Packomania publishes a coordinate archive per family, but only four of its nineteen containers name a family this collection also lists (`cirinsqu`, `cirincir`, `cirinhex`, `cirinpen`); the rest — a semicircle, a quadrant, a heptagon, an octagon, a nonagon, a decagon, rectangles and a right isosceles triangle — have no page here. Every other page carries a picture and a "Found by …" line, and nothing else. The run of 2026-10-02 judged the 104 cards that had an arrangement to judge: 98 reproduced the printed number, 3 differed from it, 1 beat it, 1 read worse and 1 printed a quantity the engine does not measure. Eleven of those cards are the lab's own starting configurations, every one of them within 0.13 % of its record and most within 0.01 %.

A card whose arrangement reproduces its printed number is written out as `published-<family>-<n>.json`, re-expressed in the catalog's own frame so a run can open the record itself; the entry names it as `candidate`. A frame is not a detail: Packomania normalises a regular polygon on its circumradius and prints an even-sided one edge-up, while the catalog normalises on the polygon's side and puts a vertex up, so a published arrangement is scaled — and, for an even-sided container, turned — before it is judged. An entry that does not reproduce its number reports its gap and offers no candidate.

The precision of a printed number bounds every claim. `10.304` cannot be told apart from anything within its last printed digit, so an improvement smaller than that is not claimed as one, and a card is only **confirmed** when the page printed at least five decimals and the engine reads that number back. With fewer, the card is an approach however good it looks: a margin far smaller than the rounding decides whether a record was reached. A construction the lab holds — the record sessions among them — is measured and reported under `source_kind: record` but never promoted: its entry keeps `promoted: false`, offers no candidate, and the interface keeps showing the published value.

## First visit

The browser starts with five editable categories. **Start here · squares** visits 2, 5, 10, 11, 17 and 29 equal squares in that order. **Explore packing** samples five shape and container combinations. **Other objectives** has three total-perimeter and three covering examples. All 17 starters ship editable candidate coordinates that are judged by the engine when loaded. Most reproduce an elementary construction from the source; the three-pentagon and three-square covering layouts are close reconstructions of published figures, explicitly marked approximate in the UI. The maintainers' starter builder regenerates and validates the eleven non-square candidates. These are small entry points into the full catalog, not a claim that every published construction is bundled. The compact snapshot in `apps/web/src/starterCatalog.json` is drawn from the main catalog and supplies the same problem templates and references to these examples. **Demo Workflow** holds the problems the agent workflows are compared on. **Records beaten by Claude** opens each card on an arrangement that beats the published record: the reference panel keeps the previous record (value, author, source figure) and the verdict measures the new one, from `record-<family>-<n>.json` candidates and the compact `apps/web/src/beatenRecordsCatalog.json`. The library is saved in the browser, so edits and additional categories persist; a built-in category added later joins a saved library once and stays deleted if the user removes it.

The catalog is built by the maintainers' own tools, kept outside the repository; the checked-in asset is what the app reads. Check upstream attribution and redistribution terms before publishing generated images or imported coordinates. Keep a reference's original units, status and verification date when adding a source.

## Current limits

The app can represent more families than it can search effectively. It cannot yet express 3D packing, arbitrary per-placement shape families, or every free-aspect-ratio container and custom constraint appearing in external collections. A custom problem can define available shapes, arenas and constraints, but it is not a full symbolic geometry language. Add new families through explicit domain and geometry contracts, not by guessing scores from their pictures.
