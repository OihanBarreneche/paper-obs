# Precision and performance

An engine verdict and a displayed measurement do not always have the same numerical guarantee. Tangency is valid. For straight-edged convex copies, the engine uses separation tests and reports penetration depth; disc-only cases can use closed-form circle predicates. Geometry involving curved boundaries mixed with boolean arena operations passes through a polygonal representation.

## Curves and tolerances

Discs and ellipses are compiled to **circumscribed** polygons for general Shapely operations and drawing. With 256 chords, a vertex can exceed the true radius by about `7.53e-5` relative, and polygon area exceeds the true disc area by about `5.02e-5` relative. The circumscribed direction preserves ideal tangencies at chord contacts; it does not make every mixed-curve predicate mathematically exact. Disc-only containment and overlap use closed-form paths where implemented. Composite curved walls may use tolerance raised to the chord error. The implementation and formulas are in `domain/tessellation.py` and `geometry/facts.py`.

Typical absolute **validity** tolerances are `1e-9` in world length or area units. Descriptive contacts and inscribed-circle searches use about `1e-6`. A descriptive tolerance never turns an invalid placement valid. The exact tolerances and any curved-wall exceptions belong to the geometry layer and must be kept beside their use.

`packed_area` is the sum of shapes' own areas. `covered_area` is the area of their union within the arena, bounded by the exact sum of shape areas; `void_area` is arena area minus covered area. In a covering, overlapping and protruding copies make these quantities different. The displayed density is a descriptive fraction, not the objective for every problem. No displayed score should be interpreted as a mathematical proof of global optimality.

## Measured performance and limits

On the 2026-09-28 development setup, one `evaluate` plus `build_view` of simple valid disc grids took approximately **0.009 s for 25**, **0.027 s for 64** and **0.040 s for 100** placements. This is a narrow local measurement, not a browser frame-rate benchmark. Complex arenas, non-disc polygons, invalid candidates, repeated mouse updates, JSON transport and rendering can be much slower. The editor has not been validated for smooth interaction at 50–100 shapes, so the catalog/UI should not promise that scale yet.

The frontend receives engine view models rather than recomputing geometry. A new metric or geometry overlay must be implemented in geometry and exposed through the API before display. Performance work should profile the specific slow operation and preserve the same verdict and JSON contract.

## Manual placement

Dragging reports the pointer's world displacement without rounding it to a global grid. Zooming in therefore gives finer control. On release, the editor may request a contact guide within **3 screen pixels, capped at 0.02 world units**. The geometry layer considers only boundaries named by effective containment and non-overlap constraints, and only finishes a movement *toward* a nearby contact. It leaves invalid placements and movements away from a contact untouched. Each suggested correction is revalidated by the normal engine before it is returned. This guide is an editing aid, not a change to validity tolerances or a guarantee of finding an optimal arrangement.
