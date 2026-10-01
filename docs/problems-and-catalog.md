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

The bundled catalog at `apps/web/public/catalog/packing_equal_copies.json` was generated on 2026-09-27 from [Erich Friedman's packing collection](https://erich-friedman.github.io/packing/index.html) and linked problem pages. It currently contains **107 families and 2,847 entries**:

| Section | Families | Entries | Supported families |
| --- | ---: | ---: | ---: |
| Packing equal copies | 80 | 2,235 | 79 |
| Maximum total perimeter | 16 | 415 | 16 |
| Covering | 9 | 139 | 9 |
| Other, currently unsupported | 2 | 58 | 0 |

“Supported” means the current engine can construct and judge that family's problem. It does **not** promise a useful initializer, a baseline, a verified optimum or a complete candidate. Total-perimeter search currently has a varied initializer but no dedicated classical baseline. Four catalog families carry explicit caveats (`cirinel`, `cirRell`, `cirRrec`, `squcosqu`): published and engine quantities or container assumptions are not directly interchangeable.

The catalog stores source links, attributions, stated proof status and a last-check date. A published construction must not be labeled a proved optimum unless its source says so. These are snapshot records, not live queries; a record can be superseded. Some previews link to source-hosted images, so they may be unavailable offline. Candidate coordinate files under `apps/web/public/catalog/candidates/` are separate from reference values and must be judged by the engine after import.

Reference units matter: squares in a smallest triangle are solved by enlarging copies inside a unit triangle; the engine also reports the equivalent triangle side for unit copies. The three-square covering source publishes **area**, while the covering objective searches over target side; the UI leads with the engine's target area for that reference. Two triangles maximizing total side in a square have a continuum of optimal placements, including the bundled equal-size pair.

## First visit

The browser starts with three editable categories. **Start here · squares** visits 2, 5, 10, 11, 17 and 29 equal squares in that order. **Explore packing** samples five shape and container combinations. **Other objectives** has three total-perimeter and three covering examples. All 17 starters ship editable candidate coordinates that are judged by the engine when loaded. Most reproduce an elementary construction from the source; the three-pentagon and three-square covering layouts are close reconstructions of published figures, explicitly marked approximate in the UI. The maintainers' starter builder regenerates and validates the eleven non-square candidates. These are small entry points into the full catalog, not a claim that every published construction is bundled. The compact snapshot in `apps/web/src/starterCatalog.json` is drawn from the main catalog and supplies the same problem templates and references to these examples. The library is saved in the browser, so edits and additional categories persist. Existing Demo and Squares folders are folded into the new categories on migration without discarding added profiles.

The catalog is built by the maintainers' own tools, kept outside the repository; the checked-in asset is what the app reads. Check upstream attribution and redistribution terms before publishing generated images or imported coordinates. Keep a reference's original units, status and verification date when adding a source.

## Current limits

The app can represent more families than it can search effectively. It cannot yet express 3D packing, arbitrary per-placement shape families, or every free-aspect-ratio container and custom constraint appearing in external collections. A custom problem can define available shapes, arenas and constraints, but it is not a full symbolic geometry language. Add new families through explicit domain and geometry contracts, not by guessing scores from their pictures.
