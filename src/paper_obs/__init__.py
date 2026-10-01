"""A modular laboratory for 2D geometric packing.

The lab exists to compare search strategies on the same problems, on the same
exact score: a random search, a lattice construction, a local relaxation, a
human moving shapes by hand, and later a team of agents. Layers are strictly
separated:

``paper_obs.domain``
    What a packing problem *is*: shapes, arena, objective, constraints,
    candidate. Pure data, no geometry computation, no LLM.
``paper_obs.geometry``
    The deterministic engine: is this candidate valid, what is its score, what
    does it look like, where is it empty?
``paper_obs.search``
    How to transform a candidate: initialization, mutation, relaxation, repair,
    and (later) the agentic workflows that decide which operator to apply.

Nothing in ``domain`` or ``geometry`` knows about an LLM, a workflow engine or a
UI, which is what makes the rest of the lab replaceable.
"""

__version__ = "0.1.0"
