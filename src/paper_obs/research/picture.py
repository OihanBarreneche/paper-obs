"""A picture of an arrangement in the form Erich Friedman's Packing Center asks for.

A submission replaces a picture on a page, so the new one keeps the old one's pixel size,
colours, orientation and file type, with no border and no text (docs/research-mode.md,
section 6). The drawing is an SVG first, written beside the picture: the outlines come from
the problem's own shapes and arena, with one-pixel lines. It is then rendered by resvg and
saved in the format the file name asks for.

The pages do not share one style. Some pictures have a handful of flat colours and a
transparent outside (26 tans in an L), others are anti-aliased on white (38 squares in a
triangle). Given the picture it replaces, the size, the style and the colours are read from it:
few colours give crisp edges in that exact palette, many give anti-aliased edges. Needs
resvg-py and Pillow (the ``research`` extra).
"""

from __future__ import annotations

import io
from pathlib import Path

from shapely import affinity
from shapely.geometry import Polygon

from paper_obs.domain.candidate import Candidate
from paper_obs.domain.problem import Problem

#: A picture with at most this many colours is drawn with crisp edges in its exact palette.
FLAT_COLOURS = 16
#: The style without a picture to copy: anti-aliased on white, light grey copies, black lines.
#: ``outside`` is the colour around the arena (``None``: transparent), ``inside`` its empty space.
DEFAULT = {"size": (200, 200), "crisp": False, "outside": (255, 255, 255), "inside": (255, 255, 255),
           "fill": (210, 210, 210), "outline": (0, 0, 0)}


def submission_picture(problem: Problem, candidate: Candidate, path: Path, *, like: Path | None = None,
                       size: tuple[int, int] | None = None, rotate: float = 0.0, style: dict | None = None) -> Path:
    """Draw the arena and the copies, write the SVG beside ``path``, render it and save it.

    ``rotate`` turns the drawing by that many degrees counter-clockwise, to match the page's
    orientation. ``style`` sets any of the :data:`DEFAULT` keys over what ``like`` gives. A
    ``.svg`` path writes the SVG only.
    """
    style = {**DEFAULT, **(_read_style(like) if like is not None else {}), **(style or {})}
    if size is not None:
        style["size"] = size
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    svg = submission_svg(problem, candidate, style, rotate)
    path.with_suffix(".svg").write_text(svg, encoding="utf-8")
    if path.suffix.lower() != ".svg":
        _render(svg, style, path)
    return path


def submission_svg(problem: Problem, candidate: Candidate, style: dict, rotate: float = 0.0) -> str:
    """The SVG of a submission picture: the arena's bounding box fills it, its edge on the outer pixels."""
    width, height = style["size"]
    region = problem.arena.geometry if problem.arena is not None else None
    arena = [] if region is None else [affinity.rotate(part, rotate, origin=(0, 0))
                                      for part in getattr(region, "geoms", [region])]
    copies = [affinity.rotate(affinity.translate(problem.shape.footprint(item.resolved_scale(candidate.scale),
                                                                          item.rotation), item.x, item.y),
                              rotate, origin=(0, 0)) for item in candidate.placements]
    boxes = [shape.bounds for shape in (arena or copies)]
    left, bottom = min(box[0] for box in boxes), min(box[1] for box in boxes)
    right, top = max(box[2] for box in boxes), max(box[3] for box in boxes)
    # A one-pixel line centred half a pixel in from the border fills the picture's outer pixels.
    zoom = min((width - 1) / (right - left), (height - 1) / (top - bottom))
    dx = (width - zoom * (right - left)) / 2 - zoom * left
    dy = (height + zoom * (top - bottom)) / 2 + zoom * bottom

    def outline(shape: Polygon) -> str:
        return " ".join("M" + " L".join(f"{dx + zoom * x:.3f},{dy - zoom * y:.3f}" for x, y in ring.coords[:-1]) + " Z"
                        for ring in (shape.exterior, *shape.interiors))

    def colour(rgb) -> str:
        return "none" if rgb is None else "#%02x%02x%02x" % tuple(rgb)

    stroke = f'stroke="{colour(style["outline"])}" stroke-width="1"'
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
             f'shape-rendering="{"crispEdges" if style["crisp"] else "geometricPrecision"}">',
             f'<rect width="{width}" height="{height}" fill="{colour(style["outside"])}"/>']
    lines += [f'<path d="{outline(part)}" fill="{colour(style["inside"])}" fill-rule="evenodd" {stroke}/>' for part in arena]
    lines += [f'<path d="{outline(shape)}" fill="{colour(style["fill"])}" {stroke}/>' for shape in copies]
    return "\n".join(lines + ["</svg>", ""])


def _render(svg: str, style: dict, path: Path) -> None:
    """Render the SVG with resvg and save it: a flat picture in its exact palette, else the full render."""
    import resvg_py
    from PIL import Image

    image = Image.open(io.BytesIO(bytes(resvg_py.svg_to_bytes(svg_string=svg, skip_system_fonts=True)))).convert("RGBA")
    if style["crisp"]:
        palette = [style["outline"], style["fill"], style["inside"], style["outside"] or (255, 255, 255)]
        flat = Image.new("P", image.size)
        flat.putpalette([value for rgb in palette for value in rgb])
        flat.putdata([3 if a < 128 and style["outside"] is None else
                      min(range(4), key=lambda k: sum((c - p) ** 2 for c, p in zip((r, g, b), palette[k])))
                      for r, g, b, a in getattr(image, "get_flattened_data", image.getdata)()])
        if style["outside"] is None:
            flat.info["transparency"] = 3
        image = flat
    elif path.suffix.lower() != ".png":
        opaque = Image.new("RGB", image.size, style["outside"] or (255, 255, 255))
        opaque.paste(image, mask=image)
        image = opaque.quantize(colors=256) if path.suffix.lower() == ".gif" else opaque
    image.save(path)


def _read_style(picture: Path) -> dict:
    """Size, style and colours of a published picture.

    Transparent pixels make the outside transparent, else the corner's colour is the outside.
    Of the opaque colours, white (or else the corner) is empty space, the most common other one
    fills the copies, and the darkest draws the lines.
    """
    from PIL import Image

    with Image.open(picture) as source:
        image = source.convert("RGBA")
    counts = sorted(image.getcolors(maxcolors=image.width * image.height), reverse=True)
    opaque = [colour[:3] for _, colour in counts if colour[3] > 0]
    corner = image.getpixel((0, 0))[:3]
    empty = (255, 255, 255) if (255, 255, 255) in opaque else corner
    others = [colour for colour in opaque if colour != empty]
    return {"size": image.size, "crisp": len(counts) <= FLAT_COLOURS,
            "outside": None if any(colour[3] == 0 for _, colour in counts) else corner, "inside": empty,
            "fill": others[0] if others else DEFAULT["fill"],
            "outline": min(opaque, key=sum) if opaque else DEFAULT["outline"]}


__all__ = ["DEFAULT", "submission_picture", "submission_svg"]
