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

from paper_obs.geometry.submission import submission_svg

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
    elif path.suffix.lower() == ".gif" and style["outside"] is None:
        rgba = image
        opaque = Image.new("RGB", rgba.size, (255, 255, 255))
        opaque.paste(rgba, mask=rgba)
        image = opaque.quantize(colors=255)
        pixels = getattr(image, "get_flattened_data", image.getdata)()
        alpha = getattr(rgba, "get_flattened_data", rgba.getdata)()
        image.putdata([255 if colour[3] < 128 else index for index, colour in zip(pixels, alpha)])
        palette = image.getpalette()
        palette[765:768] = [255, 255, 255]
        image.putpalette(palette)
        image.info["transparency"] = 255
    elif path.suffix.lower() != ".png":
        opaque = Image.new("RGB", image.size, style["outside"] or (255, 255, 255))
        opaque.paste(image, mask=image)
        image = opaque.quantize(colors=256) if path.suffix.lower() == ".gif" else opaque
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        image.convert("RGB").save(path, quality=100, subsampling=0)
    else:
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
    outline = min(opaque, key=sum) if opaque else DEFAULT["outline"]
    fills = [colour for colour in others if colour != outline]
    return {"size": image.size, "crisp": len(counts) <= FLAT_COLOURS,
            "outside": None if any(colour[3] == 0 for _, colour in counts) else corner, "inside": empty,
            "fill": fills[0] if fills else empty,
            "outline": outline}


__all__ = ["DEFAULT", "submission_picture", "submission_svg"]
