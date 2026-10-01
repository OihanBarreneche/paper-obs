"""A picture of an arrangement in the form Erich Friedman's Packing Center asks for.

A submission replaces a picture on a page, so the new one keeps the old one's pixel size,
colours, orientation and file type, with no border and no text (docs/research-mode.md,
section 6). Given the picture it replaces, the size and the three colours (background,
copies, outlines) are read from it; each can be set by hand instead. The outlines come from
the problem's own shapes and arena, as the engine builds them. Needs Pillow (the
``research`` extra).
"""

from __future__ import annotations

from pathlib import Path

from shapely import affinity
from shapely.geometry import Polygon

from paper_obs.domain.candidate import Candidate
from paper_obs.domain.problem import Problem

Color = tuple[int, int, int]


def submission_picture(problem: Problem, candidate: Candidate, path: Path, *, like: Path | None = None,
                       size: tuple[int, int] | None = None, background: Color | None = None,
                       fill: Color | None = None, outline: Color | None = None,
                       rotate: float = 0.0, margin: int = 1) -> Path:
    """Draw the arena and the copies, fitted to the picture, and save it; the suffix picks the format.

    ``rotate`` turns the drawing by that many degrees counter-clockwise, to match the page's
    orientation. Without ``like``, the defaults are 200 x 200 pixels, white, light grey copies and
    black outlines.
    """
    from PIL import Image, ImageDraw

    found = _read_style(like) if like is not None else {}
    width, height = size or found.get("size") or (200, 200)
    colours = {"background": background or found.get("background") or (255, 255, 255),
               "fill": fill or found.get("fill") or (200, 200, 200),
               "outline": outline or found.get("outline") or (0, 0, 0)}
    outlines = [_exterior(problem.arena.geometry)] if problem.arena is not None else []
    copies = [affinity.translate(problem.shape.footprint(item.resolved_scale(candidate.scale), item.rotation), item.x, item.y)
              for item in candidate.placements]
    shapes = [affinity.rotate(shape, rotate, origin=(0, 0)) for shape in outlines + copies]
    left, bottom, right, top = _bounds(shapes)
    zoom = min((width - 1 - 2 * margin) / (right - left), (height - 1 - 2 * margin) / (top - bottom))
    # Pixel y grows downwards; the drawing is centred in the picture.
    dx = (width - 1 - zoom * (right - left)) / 2 - zoom * left
    dy = (height - 1 + zoom * (top - bottom)) / 2 + zoom * bottom
    to_pixels = lambda shape: [(dx + zoom * x, dy - zoom * y) for x, y in shape.exterior.coords]  # noqa: E731
    image = Image.new("RGB", (width, height), colours["background"])
    draw = ImageDraw.Draw(image)
    for index, shape in enumerate(shapes):
        arena = index < len(outlines)
        draw.polygon(to_pixels(shape), fill=None if arena else colours["fill"], outline=colours["outline"])
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".gif":
        image = image.quantize(colors=8)
    image.save(path)
    return path


def _read_style(picture: Path) -> dict:
    """Size and colours of a published picture: the corner is the background, the most common
    other colour fills the copies, and the darkest colour draws the outlines."""
    from PIL import Image

    with Image.open(picture) as source:
        image = source.convert("RGB")
    counts = sorted(image.getcolors(maxcolors=image.width * image.height), reverse=True)
    background = image.getpixel((0, 0))
    others = [colour for _, colour in counts if colour != background]
    return {"size": image.size, "background": background,
            "fill": others[0] if others else None,
            "outline": min(others, key=sum) if len(others) > 1 else None}


def _exterior(region) -> Polygon:
    """The arena's outline; a region in several parts keeps its largest."""
    return Polygon(max(getattr(region, "geoms", [region]), key=lambda part: part.area).exterior)


def _bounds(shapes) -> tuple[float, float, float, float]:
    boxes = [shape.bounds for shape in shapes]
    return (min(box[0] for box in boxes), min(box[1] for box in boxes),
            max(box[2] for box in boxes), max(box[3] for box in boxes))


__all__ = ["submission_picture"]
