"""Rasterize the catalog's restricted filled-path SVG format.

The parser and nonzero, 4x-antialiased rasterizer are copied unchanged from
Smythe's ``benchmarks/svg_glyphs.py`` (``render_svg`` and its helpers), so an
MSDF atlas rebuild compares against the same source-raster oracle. Only
explicit absolute M/L/Z contours with black nonzero fills are accepted.
"""

from __future__ import annotations

import math
import re
from xml.etree import ElementTree as ET

import numpy as np
from PIL import Image, ImageDraw

SVG_NS = "http://www.w3.org/2000/svg"
_TOKEN = re.compile(r"[MLZ]|[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


def _parse_paths(svg: str) -> list[list[list[tuple[float, float]]]]:
    if not isinstance(svg, str) or len(svg.encode("utf-8")) > 262144:
        raise ValueError("SVG must be text of at most 256 KiB")
    if "<!" in svg or "<?" in svg:
        raise ValueError("DTD, entities, comments, and processing instructions are not allowed")
    root = ET.fromstring(svg)
    if root.tag != f"{{{SVG_NS}}}svg" or root.attrib.get("viewBox") != "0 0 100 100":
        raise ValueError("expected an SVG with viewBox 0 0 100 100")
    if set(root.attrib) - {"viewBox", "width", "height"}:
        raise ValueError("unsupported root attributes")
    if any(root.attrib.get(key) != "128" for key in ("width", "height")):
        raise ValueError("source SVG dimensions must be 128 by 128")
    paths = []
    for child in root:
        if child.tag != f"{{{SVG_NS}}}path" or len(child):
            raise ValueError("only leaf path elements are accepted")
        if set(child.attrib) != {"d", "fill", "fill-rule"}:
            raise ValueError("paths require only d, fill, and fill-rule")
        if child.attrib["fill"] != "#000000" or child.attrib["fill-rule"] != "nonzero":
            raise ValueError("glyphs require black nonzero fills")
        data = child.attrib["d"]
        tokens = _TOKEN.findall(data)
        if re.sub(r"[\s,]", "", _TOKEN.sub("", data)):
            raise ValueError("only explicit absolute M/L/Z path commands are supported")
        rings, ring = [], None
        position = 0
        while position < len(tokens):
            token = tokens[position]
            if token == "Z":
                if ring is None or len(ring) < 3:
                    raise ValueError("closed contours need at least three vertices")
                rings.append(ring)
                ring = None
                position += 1
                continue
            if token not in {"M", "L"} or position+2 >= len(tokens):
                raise ValueError("malformed path command")
            if (token == "M" and ring is not None) or (token == "L" and ring is None):
                raise ValueError("each contour must start with M and close with Z")
            point = (float(tokens[position+1]), float(tokens[position+2]))
            if any(not math.isfinite(v) or not 0 <= v <= 100 for v in point):
                raise ValueError("coordinates must be finite and inside the viewBox")
            if token == "M":
                ring = []
            ring.append(point)
            position += 3
        if ring is not None or not rings:
            raise ValueError("unclosed or empty path")
        paths.append(rings)
    if not paths or sum(len(r) for p in paths for r in p) > 16000:
        raise ValueError("empty or excessively complex SVG")
    return paths


def _signed_area(points):
    return sum(x*y2-x2*y for (x, y), (x2, y2) in zip(points, points[1:]+points[:1]))/2


def render_svg(svg: str, size: int = 128) -> Image.Image:
    """Rasterize the restricted filled-path format with nonzero winding and 4x AA."""
    if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= 2048:
        raise ValueError("size must be an integer from 1 to 2048")
    paths = _parse_paths(svg)
    side = size*4
    result = np.zeros((side, side), dtype=bool)
    factor = side/100
    for path in paths:
        winding = np.zeros((side, side), dtype=np.int16)
        for ring in path:
            mask = Image.new("L", (side, side), 0)
            ImageDraw.Draw(mask).polygon([(x*factor, y*factor) for x, y in ring], fill=1)
            winding += np.asarray(mask, dtype=np.int16) * (1 if _signed_area(ring) > 0 else -1)
        result |= winding != 0
    pixels = np.where(result, 0, 255).astype(np.uint8)
    return Image.fromarray(pixels).resize((size, size), Image.Resampling.LANCZOS).convert("RGBA")
