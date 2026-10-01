"""SVG rendering: serialising the view model into a picture.

Rendering draws what :func:`paper_obs.geometry.view.build_view` describes and
nothing else. It holds no geometry of its own: the arena path, the disc radii and
the polygon corners all come from the engine, which is also what the user
interface receives over HTTP. A picture and a screen therefore cannot disagree
about where a shape is.

SVG was chosen for the reasons the specification gives: it is a text format, it
survives a diff, it zooms without loss, and a browser needs no graphics engine to
display it — which is what makes a self-hosted interface cheap.

The scene is drawn in mathematical orientation (``+y`` up) and flipped once, by a
single group transform, so every coordinate here is a coordinate of the domain.
Stroke widths and dashes are given in pixels and divided by the scale, rather than
left to ``vector-effect="non-scaling-stroke"``, which rasterisers such as resvg
ignore. Text overlays are laid out in screen space, because flipped text is
unreadable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from html import escape

from paper_obs.domain.candidate import Candidate
from paper_obs.domain.problem import Problem

from .view import ShapePrimitive, View, build_view

#: Maps a coordinate of the domain onto a pixel of the SVG canvas.
ScreenProjection = Callable[[float, float], tuple[float, float]]


@dataclass(frozen=True)
class RenderOptions:
    """Everything that changes the picture but never the verdict; widths are in pixels."""

    width: int = 900
    padding: float = 24.0
    background: str = "#ffffff"
    arena_fill: str = "#f3f4f6"
    arena_stroke: str = "#111827"
    arena_stroke_width: float = 1.5
    shape_fill: str = "#93c5fd"
    shape_stroke: str = "#1d4ed8"
    shape_stroke_width: float = 0.8
    violation_fill: str = "#fecaca"
    violation_stroke: str = "#b91c1c"
    void_fill: str = "#fef3c7"
    show_violations: bool = True
    show_voids: bool = False
    show_ids: bool = False
    show_centers: bool = False
    honor_shape_colors: bool = True
    font_size: float = 10.0
    void_limit: int = 5


def render_svg(problem: Problem, candidate: Candidate, options: RenderOptions | None = None) -> str:
    """Return the SVG document showing ``candidate`` inside ``problem``."""
    options = options or RenderOptions()
    view = build_view(
        problem,
        candidate,
        with_violations=options.show_violations,
        with_voids=options.show_voids,
        void_limit=options.void_limit,
    )
    min_x, min_y, max_x, max_y = view.frame
    world_width = max(max_x - min_x, 1e-9)
    world_height = max(max_y - min_y, 1e-9)
    scale = (options.width - 2.0 * options.padding) / world_width
    height = round(world_height * scale + 2.0 * options.padding)
    scene_transform = (
        f"translate({_number(options.padding - scale * min_x)} "
        f"{_number(options.padding + scale * max_y)}) "
        f"scale({_number(scale)} {_number(-scale)})"
    )

    def to_screen(x: float, y: float) -> tuple[float, float]:
        return (
            options.padding + (x - min_x) * scale,
            options.padding + (max_y - y) * scale,
        )

    elements = [
        f'<title>{escape(problem.title)} — {escape(candidate.candidate_id)}</title>',
        f'<rect x="0" y="0" width="{options.width}" height="{height}" fill="{options.background}"/>',
        f'<g transform="{scene_transform}">',
        (
            f'<path d="{view.arena_path}" fill="{options.arena_fill}" fill-rule="evenodd" '
            f'stroke="{options.arena_stroke}" stroke-width="{_number(options.arena_stroke_width / scale)}"/>'
        ),
    ]
    elements.extend(_void_elements(view, options, 1.0 / scale))
    elements.extend(_shape_elements(view.shapes, options, 1.0 / scale))
    elements.append("</g>")
    elements.extend(_overlay_elements(candidate, options, to_screen))

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{options.width}" height="{height}" '
        f'viewBox="0 0 {options.width} {height}">\n  '
        + "\n  ".join(elements)
        + "\n</svg>\n"
    )


def _void_elements(view: View, options: RenderOptions, pixel: float) -> list[str]:
    """Return the elements outlining the empty regions; ``pixel`` is one pixel in world units."""
    return [
        f'<path d="M {_number(void.bounds[0])} {_number(void.bounds[1])} '
        f'L {_number(void.bounds[2])} {_number(void.bounds[1])} '
        f'L {_number(void.bounds[2])} {_number(void.bounds[3])} '
        f'L {_number(void.bounds[0])} {_number(void.bounds[3])} Z" '
        f'fill="none" stroke="{options.void_fill}" stroke-width="{_number(pixel)}" '
        f'stroke-dasharray="{_number(4 * pixel)} {_number(3 * pixel)}"/>'
        for void in view.voids
    ]


def _shape_elements(shapes: tuple[ShapePrimitive, ...], options: RenderOptions, pixel: float) -> list[str]:
    """Return the elements drawing every placed shape; ``pixel`` is one pixel in world units.

    Three sources of colour, in this order: a violation outranks the shape's own
    colour, which outranks the theme. The first is a verdict and never yields to
    decoration; the second paints both the fill and the stroke, so a coloured
    shape stays one readable mark.
    """
    elements = []
    for shape in shapes:
        if shape.invalid:
            fill, stroke = options.violation_fill, options.violation_stroke
        elif options.honor_shape_colors and shape.color is not None:
            fill = stroke = shape.color
        else:
            fill, stroke = options.shape_fill, options.shape_stroke
        style = (
            f'fill="{fill}" stroke="{stroke}" '
            f'stroke-width="{_number(options.shape_stroke_width * pixel)}"'
        )
        if shape.kind == "circle":
            elements.append(
                f'<circle cx="{_number(shape.center[0])}" cy="{_number(shape.center[1])}" '
                f'r="{_number(shape.radius)}" {style}/>'
            )
            continue
        points = " ".join(f"{_number(x)},{_number(y)}" for x, y in shape.points)
        elements.append(f'<polygon points="{points}" {style}/>')
    return elements


def _overlay_elements(
    candidate: Candidate, options: RenderOptions, to_screen: ScreenProjection
) -> list[str]:
    """Return the screen-space elements: shape identifiers and centre marks."""
    if not (options.show_ids or options.show_centers):
        return []
    elements = [f'<g font-family="ui-monospace, monospace" font-size="{_number(options.font_size)}">']
    for placement in candidate.placements:
        x, y = to_screen(placement.x, placement.y)
        if options.show_centers:
            elements.append(f'<circle cx="{_number(x)}" cy="{_number(y)}" r="2" fill="#111827"/>')
        if options.show_ids:
            elements.append(
                f'<text x="{_number(x)}" y="{_number(y - options.font_size)}" '
                f'text-anchor="middle" fill="#111827">{escape(placement.shape_id)}</text>'
            )
    elements.append("</g>")
    return elements


def _number(value: float) -> str:
    """Format a coordinate compactly, with four significant digits."""
    return f"{float(value):.4g}"


__all__ = ["RenderOptions", "render_svg"]
