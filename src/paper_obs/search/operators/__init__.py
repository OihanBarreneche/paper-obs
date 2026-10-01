"""The operator library, grouped by intent.

``initialization`` proposes a first candidate, ``mutation`` disturbs one,
``relaxation`` exploits one, ``repair`` steers one back towards validity and
``polish`` runs a short local search that keeps its topology. All
of them are pure functions of a problem and a candidate, and none of them decides
whether the result is valid: that is the engine's job.
"""

from .initialization import (
    cover_initialize,
    grid_initialize,
    random_initialize,
    staggered_initialize,
    tight_lattice_scale,
    varied_initialize,
)
from .mutation import (
    displace,
    jitter,
    remove_shapes,
    reseed_region,
    translate_cluster,
)
from .polish import polish
from .relaxation import (
    compact,
    contract_scale,
    fit_cover_scale,
    grow_sizes,
    increase_scale,
    local_relax,
)
from .repair import repair_overlaps
from .void_fill import fill_void

__all__ = [
    "contract_scale",
    "compact",
    "cover_initialize",
    "displace",
    "fit_cover_scale",
    "grid_initialize",
    "grow_sizes",
    "increase_scale",
    "jitter",
    "fill_void",
    "local_relax",
    "polish",
    "random_initialize",
    "remove_shapes",
    "repair_overlaps",
    "reseed_region",
    "staggered_initialize",
    "tight_lattice_scale",
    "translate_cluster",
    "varied_initialize",
]
