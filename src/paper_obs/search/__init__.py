"""The search layer: how one candidate becomes another.

Operators are small, named, deterministic transformations — initialize, mutate,
relax, repair — that a baseline, a search loop or an agent can call. They never
decide validity and never touch a workflow engine: that is what makes them
usable both by a plain local search and by a team of agents, which is the
comparison the lab exists to make.

Every operator takes a problem and a candidate and returns a *child* of that
candidate, so a lineage is readable from the candidates alone. Randomness goes
through a ``numpy.random.Generator`` seeded from the problem.

:mod:`~paper_obs.search.baselines` sits on top of them: the two plain
strategies a workflow is compared against, each producing the convergence curve
it reached for a given number of engine evaluations.
"""

from .baselines import (
    BASELINES,
    Baseline,
    BasinHoppingBaseline,
    Convergence,
    LatticeBaseline,
    Run,
    Step,
    convergence_svg,
)
from .operators import (
    compact,
    contract_scale,
    cover_initialize,
    displace,
    fill_void,
    grid_initialize,
    grow_sizes,
    increase_scale,
    jitter,
    local_relax,
    random_initialize,
    remove_shapes,
    repair_overlaps,
    reseed_region,
    staggered_initialize,
    tight_lattice_scale,
    translate_cluster,
    varied_initialize,
)

__all__ = [
    "BASELINES",
    "Baseline",
    "BasinHoppingBaseline",
    "Convergence",
    "LatticeBaseline",
    "Run",
    "Step",
    "contract_scale",
    "compact",
    "convergence_svg",
    "cover_initialize",
    "displace",
    "fill_void",
    "grid_initialize",
    "grow_sizes",
    "increase_scale",
    "jitter",
    "local_relax",
    "random_initialize",
    "remove_shapes",
    "repair_overlaps",
    "reseed_region",
    "staggered_initialize",
    "tight_lattice_scale",
    "translate_cluster",
    "varied_initialize",
]
