"""The geometry layer: the deterministic, LLM-free core of the lab.

The engine answers three questions about a candidate — is it valid, how good is
it, where is it empty — and draws it. It knows nothing about search, agents or
workflows, and nothing else in the project is allowed to reimplement its
computations.
"""

from .analysis import MIN_VOID_AREA_RATIO, CandidateAnalysis, Void, analyze_facts, find_voids
from .bounds import ScaleBounds, scale_bounds
from .engine import Evaluation, analyze, evaluate, facts_for, inspect_shape, validate
from .facts import (
    enclosing_container,
    instance_bounds,
    AREA_TOLERANCE,
    CONTACT_TOLERANCE,
    LENGTH_TOLERANCE,
    Clearance,
    Containment,
    Facts,
    Overlap,
    ShapeInstance,
    build_facts,
    outline_to_arena_distance,
)
from .metrics import compute_metrics
from .rendering import RenderOptions, render_svg
from .validation import Validation, evaluate_constraints
from .view import (
    ArenaPartView,
    ShapePrimitive,
    View,
    VoidBox,
    arena_part_views,
    arena_path,
    build_view,
    path_data,
)

__all__ = [
    "enclosing_container",
    "instance_bounds",
    "AREA_TOLERANCE",
    "CONTACT_TOLERANCE",
    "LENGTH_TOLERANCE",
    "MIN_VOID_AREA_RATIO",
    "ArenaPartView",
    "CandidateAnalysis",
    "Clearance",
    "Containment",
    "Evaluation",
    "Facts",
    "Overlap",
    "RenderOptions",
    "ScaleBounds",
    "ShapeInstance",
    "ShapePrimitive",
    "Validation",
    "View",
    "VoidBox",
    "arena_part_views",
    "arena_path",
    "Void",
    "analyze",
    "analyze_facts",
    "build_facts",
    "build_view",
    "compute_metrics",
    "evaluate",
    "evaluate_constraints",
    "facts_for",
    "inspect_shape",
    "find_voids",
    "outline_to_arena_distance",
    "path_data",
    "render_svg",
    "scale_bounds",
    "validate",
]
