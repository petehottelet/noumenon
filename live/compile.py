"""Compile a glyph spec into catalog-format SVG on the 100-unit canvas.

The output matches the approved catalog: viewBox 0 0 100 100 at 128 px, one
black nonzero <path> per piece, absolute M/L/Z commands only, and holes wound
opposite to their outlines. Cell edges vary per glyph within the catalog's
measured ranges: stems 14-16 units, bars 13-15, a 12-unit gap between halves.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import random

from shapely import affinity
from shapely.geometry import Point, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from live.grammar import ACROSS, LONG, check_spec, filled, lean_stem, spec_key

GAP_LOW, GAP_HIGH = 44, 56          # the halves meet this 12-unit gap
ARC_SEGMENTS = 16                   # samples per quarter circle


@dataclass(frozen=True)
class Glyph:
    spec: dict
    svg: str
    polygons: tuple[Polygon, ...]
    sha256: str


def _long_edges(rng: random.Random) -> list[int]:
    start, end = rng.choice((14, 16)), rng.choice((84, 86))
    sizes = [(end - start) // LONG] * LONG
    for i in range((end - start) - sum(sizes)):
        sizes[i % LONG] += 1
    for _ in range(3):  # move one unit between cells, keeping bars 13-15 thick
        a, b = rng.randrange(LONG), rng.randrange(LONG)
        if a != b and sizes[a] > 13 and sizes[b] < 15:
            sizes[a] -= 1
            sizes[b] += 1
    edges = [start]
    for size in sizes:
        edges.append(edges[-1] + size)
    return edges


def _across_edges(rng: random.Random, low_half: bool) -> list[int]:
    if low_half:
        outer = rng.choice((14, 16))
        middle = outer + rng.choice([w for w in (14, 15, 16) if 14 <= GAP_LOW - (outer + w) <= 16])
        return [outer, middle, GAP_LOW]
    outer = rng.choice((84, 86))
    middle = outer - rng.choice([w for w in (14, 15, 16) if 14 <= (outer - w) - GAP_HIGH <= 16])
    return [GAP_HIGH, middle, outer]


def _jitter_rng(spec: dict, seed: int | None) -> random.Random:
    key = spec_key(spec) if seed is None else f"{seed}"
    return random.Random(int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big"))


def _cell_box(layout, long_edges, across_edges, r, c):
    a0, a1 = long_edges[r], long_edges[r + 1]
    b0, b1 = across_edges[c], across_edges[c + 1]
    return box(b0, a0, b1, a1) if layout == "columns" else box(a0, b0, a1, b1)


def _corner_point(layout, long_edges, across_edges, r, c, corner):
    along = long_edges[r] if corner[0] == "t" else long_edges[r + 1]
    across = across_edges[c] if corner[1] == "l" else across_edges[c + 1]
    inward_along = 1 if corner[0] == "t" else -1
    inward_across = 1 if corner[1] == "l" else -1
    if layout == "columns":
        return (across, along), (inward_across, inward_along)
    return (along, across), (inward_along, inward_across)


def _half_shape(layout, half, long_edges, across_edges):
    cells = filled(half["cells"])
    shape = unary_union([_cell_box(layout, long_edges, across_edges, r, c) for r, c in cells])
    for item in half["round"]:
        r, c, corner = item.split(",")
        r, c = int(r), int(c)
        cell = _cell_box(layout, long_edges, across_edges, r, c)
        x0, y0, x1, y1 = cell.bounds
        radius = min(x1 - x0, y1 - y0)
        (px, py), (dx, dy) = _corner_point(layout, long_edges, across_edges, r, c, corner)
        square = box(min(px, px + dx * radius), min(py, py + dy * radius), max(px, px + dx * radius), max(py, py + dy * radius))
        disc = Point(px + dx * radius, py + dy * radius).buffer(radius, quad_segs=ARC_SEGMENTS)
        shape = shape.difference(square.difference(disc))
    if half["lean"]:
        column, first, last = lean_stem(cells)
        shift = (across_edges[1 - column + 1] - across_edges[1 - column]) * (1 if half["lean"] == "right" else -1)
        start, end = long_edges[first], long_edges[last + 1]
        # Shear so the stem's start stays put and its end moves one cell across.
        factor = shift / (end - start)
        if layout == "columns":
            shape = affinity.affine_transform(shape, [1, factor, 0, 1, -factor * start, 0])
        else:
            shape = affinity.affine_transform(shape, [1, 0, factor, 1, 0, -factor * start])
    return shape


def _number(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _ring(coords) -> str:
    points = list(coords)[:-1]
    return "M" + " L".join(f"{_number(x)} {_number(y)}" for x, y in points) + " Z"


def svg_for(polygons) -> str:
    paths = []
    for polygon in polygons:
        rings = [_ring(polygon.exterior.coords)] + [_ring(interior.coords) for interior in polygon.interiors]
        paths.append(f'<path fill="#000000" fill-rule="nonzero" d="{" ".join(rings)}"/>')
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="128" height="128">'
            + "".join(paths) + "</svg>")


def compile_spec(spec: dict, seed: int | None = None) -> Glyph:
    spec = check_spec(spec)
    rng = _jitter_rng(spec, seed)
    long_edges = _long_edges(rng)
    halves = [_across_edges(rng, True), _across_edges(rng, False)]
    shape = unary_union([_half_shape(spec["layout"], half, long_edges, edges)
                         for half, edges in zip(spec["halves"], halves)])
    parts = [shape] if shape.geom_type == "Polygon" else list(shape.geoms)
    # Round to the serialized precision, then order pieces top-left first.
    parts = [orient(Polygon([(round(x, 2), round(y, 2)) for x, y in p.exterior.coords],
                            [[(round(x, 2), round(y, 2)) for x, y in i.coords] for i in p.interiors]), sign=1.0)
             for p in parts if not p.is_empty]
    parts.sort(key=lambda p: (round(p.bounds[1]), round(p.bounds[0])))
    svg = svg_for(parts)
    return Glyph(spec=spec, svg=svg, polygons=tuple(parts), sha256=hashlib.sha256(svg.encode()).hexdigest())


__all__ = ["Glyph", "compile_spec", "svg_for", "ACROSS", "LONG"]
