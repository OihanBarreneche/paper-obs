"""The one chord count every curved shape is tessellated with, and its error.

A disc or an ellipse has no polygonal outline, and shapely works on polygons.
The engine therefore compiles a curved primitive to a **circumscribed** n-gon:
every chord is tangent to the true curve, so the polygon contains the ideal
shape. That direction is deliberate -- an inscribed polygon would cut into the
curve and refuse the exact tangent arrangements a lattice produces -- but it is
an approximation, and this module is where the approximation lives: one chord
count, and the closed-form error it implies, so no other module invents a
number.

The polygon is exact at the tangency points and worst at its vertices. For a
chord count `n` and a curve of radius `R`:

* the vertex sits at `R / cos(pi/n)`, a relative excess of
  `1/cos(pi/n) - 1`;
* the sagitta, the gap between chord and arc, is `R (1 - cos(pi/n))`;
* the area is `n R**2 tan(pi/n)` for a disc, a relative excess of
  `n tan(pi/n) / pi - 1`.

At `CHORD_COUNT = 256` those are 7.53e-5, 7.53e-5 and 5.02e-5. Every decision
read off the compiled polygon carries that error. A decision that only involves
discs does not have to: `paper_obs.geometry.exact_discs` answers it in closed
form, which is why a disc packing is judged exactly and the polygon stays where
a closed form genuinely does not exist -- the editor, the general case, and a
boolean composition that mixes arcs with straight walls.
"""

from __future__ import annotations

import math

#: Chords a full circle is tessellated with, everywhere in the lab. The one
#: place this number is written; every other module imports it under its own
#: historical name (CIRCLE_SEGMENTS, ARC_SEGMENTS) or refers to it here.
CHORD_COUNT = 256


def chord_radius_relative_error(segments: int = CHORD_COUNT) -> float:
    """Relative excess of the polygon's vertices over the true radius.

    This is the largest relative error the tessellation puts on a *length* read
    against the curve: a distance to a curved boundary can be off by this
    fraction of the radius, so a disc placed against a curved wall may be
    accepted while sitting that far outside the ideal curve.
    """
    return 1.0 / math.cos(math.pi / segments) - 1.0


def chord_area_relative_error(segments: int = CHORD_COUNT) -> float:
    """Relative excess of the polygon's area over the true disc area."""
    return segments * math.tan(math.pi / segments) / math.pi - 1.0


__all__ = [
    "CHORD_COUNT",
    "chord_area_relative_error",
    "chord_radius_relative_error",
]
