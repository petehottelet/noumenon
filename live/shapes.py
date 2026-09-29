"""The local lane's shape grammar: new glyphs drawn in the approved catalog's style.

The grammar copies no alphabet's outlines. Its modules are structural ideas
collected from every glyph family the explorer carries, each redrawn with the
approved catalog's rules: stems 13.5 to 16.5 units wide, bars 12.5 to 14 thick,
square ends, curves that taper to a straight cut, and gaps of 10.5 to 15 units.

| Source alphabet | Modules it contributes |
|---|---|
| Approved catalog | corners, roofs, interrupted strokes, offset pairs, leaning pairs, sloping headers, hooks, crooks, shoulders, bowls, cut crescents, sweeps, squares |
| Classic reference | combs (E, ヨ), crossings (十, 丰), frames with a bar (日), roofs that overhang their legs (ホ, モ), ticks |
| Runic | branches (ᚠ), forks (ᛉ, ᛦ), arrows (ᛏ), crossings (ᚷ), bolts (ᛋ), diamonds (ᛜ), loops (ᚱ, ᚦ), H-beams (ᚺ), bowties (ᛞ) |
| Ogham | rungs on a stem line, squared spirals from the supplementary letters |
| Tifinagh | rings, rings with an inner dot (ⵙ), open rings, hourglasses (ⵅ), chevrons |
| Yautja | clusters of short oblique dashes |
| Braille | square dots of unequal size |
| Share Tech Mono | chamfered corners, angled bar ends, flat-bottomed bowls |
| Press Start 2P | stepped corners, stairs and pixel-stepped curves |

Every module takes continuous proportions, weights, curvature and taper. The
builder then turns, mirrors, leans, interrupts or pixel-steps it, so parts
rarely share geometry, and it redraws any module whose parts repeat a recent
shape (see parts.py). A glyph is two halves side by side or stacked, as most
approved glyphs are, a main half beside two quarters, or one module across the
whole glyph; it keeps the catalog's composition, glyph box and ink coverage.
Coordinates use the catalog's 100-unit canvas, y down.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import random

import shapely
from shapely import affinity, union_all
from shapely.geometry import LineString, Point, Polygon, box

# Style rules from the catalog review and its measurements (100-unit canvas).
STEM = (13.5, 16.5)     # upright stem width
BAR = (12.5, 14.0)      # crossbar thickness
END = (0.56, 0.74)      # a curve's end width as a share of its full width
GAP = (10.5, 15.0)      # space between separate parts
SNAP = 0.5
# The catalog's ink coverage runs from 17.2% to 23.9% (5th to 95th percentile).
INK = (1760.0, 2360.0)
# Parts shrink at most this far to fit their region, so strokes stay heavy, and a
# glyph's main module stretches at most this far to span its region.
LEAST_SCALE = 0.86
STRETCH = 1.12
# One corner treatment per glyph: the catalog's square corners, Share Tech Mono's
# chamfers, rounded outer corners, and Press Start 2P's stepped notches.
CORNERS = (("square", 52), ("chamfer", 18), ("round", 16), ("step", 14))
# Share of glyphs whose curves are stepped on a pixel grid, as Press Start 2P draws them.
PIXEL_SHARE = 0.1
# Share of bar and stem ends cut at an angle, as Share Tech Mono cuts some; the rest are square.
ANGLED_ENDS = 0.1
# Shares of modules the builder leans (horizontal cuts kept) or slopes (vertical cuts kept).
LEAN_SHARE, SLOPE_SHARE = 0.12, 0.03


def snap(value: float) -> float:
    return round(value / SNAP) * SNAP


def pick(rng, table):
    total = sum(weight for _, weight in table)
    roll = rng.uniform(0, total)
    for item, weight in table:
        roll -= weight
        if roll <= 0:
            return item
    return table[-1][0]


def polygons(shape) -> list:
    if shape.is_empty:
        return []
    if shape.geom_type == "Polygon":
        return [shape]
    return [g for g in getattr(shape, "geoms", []) if g.geom_type == "Polygon" and not g.is_empty]


# ---------------------------------------------------------------------------
# Stroke primitives
# ---------------------------------------------------------------------------

def rect(x0, y0, x1, y1):
    return box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def poly(points):
    return Polygon(points).buffer(0)


def path(points, width, *, join="mitre"):
    """A stroke along straight segments with flat ends cut across the stroke."""
    return LineString(points).buffer(width / 2, cap_style="flat", join_style=join, mitre_limit=2.0)


def lean(x_top, x_bottom, y0, y1, width):
    """A leaning stroke with horizontal cuts at the top and bottom."""
    return Polygon([(x_top, y0), (x_top + width, y0), (x_bottom + width, y1), (x_bottom, y1)])


def taper_lean(x_top, x_bottom, y0, y1, w_top, w_bottom):
    """A leaning stroke with horizontal cuts whose width changes from top to bottom."""
    return Polygon([(x_top, y0), (x_top + w_top, y0), (x_bottom + w_bottom, y1), (x_bottom, y1)])


def slant_bar(x0, x1, y_left, y_right, thickness):
    """A sloping bar with vertical cuts at both ends."""
    return Polygon([(x0, y_left), (x1, y_right), (x1, y_right + thickness), (x0, y_left + thickness)])


def lean_width(weight, run, rise):
    """Horizontal width that gives a leaning stroke the same weight as an upright one."""
    return weight / max(math.cos(math.atan2(abs(run), max(rise, 1e-6))), 0.55)


def cut_corner(shape, x, y, sx, sy, style):
    """Treat the outer corner at (x, y); (sx, sy) points from the corner into the shape."""
    kind, size = style
    if kind == "square" or size <= 0:
        return shape
    ex, ey = x + sx * size, y + sy * size
    if kind == "chamfer":
        cutter = Polygon([(x, y), (ex, y), (x, ey)])
    elif kind == "round":
        cutter = rect(x, y, ex, ey).difference(Point(ex, ey).buffer(size, quad_segs=12))
    else:
        cutter = rect(x, y, ex, ey)
    return shape.difference(cutter)


def _unit(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy) or 1.0
    return dx / length, dy / length


def ortho(points, widths, style=("square", 0.0)):
    """Axis-aligned strokes through ``points``, joined square; segment k is widths[k] wide.

    Every turn's outer corner takes the glyph's corner treatment.
    """
    count = len(points) - 1
    pieces = []
    for k in range(count):
        (ax, ay), (bx, by) = points[k], points[k + 1]
        w = widths[k]
        before = widths[k - 1] / 2 if k else 0.0
        after = widths[k + 1] / 2 if k + 1 < count else 0.0
        if abs(ay - by) < 1e-9:
            d = 1.0 if bx >= ax else -1.0
            pieces.append(rect(ax - d * before, ay - w / 2, bx + d * after, ay + w / 2))
        else:
            d = 1.0 if by >= ay else -1.0
            pieces.append(rect(ax - w / 2, ay - d * before, ax + w / 2, by + d * after))
    shape = union_all(pieces)
    for k in range(1, count):
        d1, d2 = _unit(points[k - 1], points[k]), _unit(points[k], points[k + 1])
        if abs(d1[0] * d2[1] - d1[1] * d2[0]) < 0.5:
            continue
        x = points[k][0] + d1[0] * widths[k] / 2 - d2[0] * widths[k - 1] / 2
        y = points[k][1] + d1[1] * widths[k] / 2 - d2[1] * widths[k - 1] / 2
        shape = cut_corner(shape, x, y, d2[0] - d1[0], d2[1] - d1[1], style)
    return shape


# Smooth centerlines: sampled segments, arcs and cubic curves joined end to end.

def seg(a, b, samples=6):
    return [(a[0] + (b[0] - a[0]) * k / samples, a[1] + (b[1] - a[1]) * k / samples) for k in range(samples + 1)]


def arc_points(cx, cy, rx, ry, a0, a1, samples=28):
    """Points on an ellipse from angle a0 to a1 in degrees; with y down, 90 is the bottom."""
    return [(cx + rx * math.cos(math.radians(a0 + (a1 - a0) * k / samples)),
             cy + ry * math.sin(math.radians(a0 + (a1 - a0) * k / samples))) for k in range(samples + 1)]


def bezier_points(p0, p1, p2, p3, samples=32):
    out = []
    for k in range(samples + 1):
        t = k / samples
        u = 1 - t
        out.append((u**3 * p0[0] + 3*u*u*t * p1[0] + 3*u*t*t * p2[0] + t**3 * p3[0],
                    u**3 * p0[1] + 3*u*u*t * p1[1] + 3*u*t*t * p2[1] + t**3 * p3[1]))
    return out


def chain(*pieces):
    out = []
    for piece in pieces:
        out.extend(piece[1:] if out and math.dist(out[-1], piece[0]) < 1e-6 else piece)
    return out


def fit_center(points, region, inset, *, keep=0.0):
    """Map a centerline's bounds onto the region, inset by half the stroke.

    ``keep`` between 0 and 1 pulls the two scale factors toward each other, so a
    curve keeps some of its drawn proportions instead of stretching to fill.
    """
    x0, y0, x1, y1 = region
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    bw, bh = max(xs) - min(xs), max(ys) - min(ys)
    tw, th = (x1 - x0) - 2 * inset, (y1 - y0) - 2 * inset
    if tw <= 1 or th <= 1:
        return None
    sx = tw / bw if bw > 1e-6 else None
    sy = th / bh if bh > 1e-6 else None
    if sx is None and sy is None:
        return None
    sx, sy = sx or sy, sy or sx
    if keep:
        mean = math.sqrt(sx * sy)
        sx, sy = min(sx, sx ** (1 - keep) * mean ** keep), min(sy, sy ** (1 - keep) * mean ** keep)
    ox = x0 + inset + (tw - bw * sx) / 2 - min(xs) * sx
    oy = y0 + inset + (th - bh * sy) / 2 - min(ys) * sy
    return [(ox + x * sx, oy + y * sy) for x, y in points]


def ribbon(center, w0, w1=None, *, hold=1.0, both=False):
    """A stroke along a smooth centerline with straight cuts across both ends.

    It keeps weight ``w0`` for ``hold`` of its length, then tapers toward ``w1``;
    with ``both`` it tapers from the middle toward both ends.
    """
    if len(center) < 2:
        return Polygon()
    lengths = [0.0]
    for a, b in zip(center, center[1:]):
        lengths.append(lengths[-1] + math.dist(a, b))
    total = lengths[-1] or 1.0
    end = w0 if w1 is None else w1
    left, right, widths = [], [], []
    for k, (x, y) in enumerate(center):
        a, b = center[max(k - 1, 0)], center[min(k + 1, len(center) - 1)]
        tx, ty = b[0] - a[0], b[1] - a[1]
        norm = math.hypot(tx, ty) or 1.0
        nx, ny = -ty / norm, tx / norm
        u = lengths[k] / total
        if both:
            u = abs(2 * u - 1)
        taper = max(0.0, (u - hold) / (1 - hold)) ** 1.3 if hold < 1 else 0.0
        half = (w0 + (end - w0) * taper) / 2
        widths.append(2 * half)
        left.append((x + nx * half, y + ny * half))
        right.append((x - nx * half, y - ny * half))
    outline = Polygon(left + right[::-1])
    if outline.is_valid:
        return outline
    # A bend tighter than the stroke folds its inner edge; refuse it rather than draw a kink.
    repaired = outline.buffer(0)
    expected = sum((widths[k] + widths[k + 1]) / 2 * (lengths[k + 1] - lengths[k]) for k in range(len(center) - 1))
    if repaired.geom_type != "Polygon" or abs(repaired.area - expected) > 0.06 * expected:
        return Polygon()
    return repaired


def pixelate(shape, cell):
    """Step a shape's outline on a square grid, as a pixel font draws its curves.

    A cell is inked when its center is inside the shape.
    """
    if shape.is_empty:
        return shape
    x0, y0, x1, y1 = shape.bounds
    columns, rows = int((x1 - x0) / cell) + 2, int((y1 - y0) / cell) + 2
    xs = [x0 + (i + 0.5) * cell for i in range(columns)]
    runs = []
    for j in range(rows):
        y = y0 + (j + 0.5) * cell
        inside = shapely.contains_xy(shape, xs, [y] * columns)
        i = 0
        while i < columns:
            if inside[i]:
                start = i
                while i < columns and inside[i]:
                    i += 1
                runs.append(box(x0 + start * cell, y - cell / 2, x0 + i * cell, y + cell / 2))
            i += 1
    return union_all(runs) if runs else shape


def _taper(rng):
    return rng.uniform(*END)


def _angled_end(rng, weight):
    """How far a stroke's end cut slants: usually square, as the catalog cuts, sometimes angled."""
    return rng.uniform(-0.9, 0.9) * weight if rng.random() < ANGLED_ENDS else 0.0


def _span(rng, low, full, *, share=0.5):
    """A stroke length: the region's full length ``full`` for ``share`` of draws, else between ``low`` and it."""
    return full if rng.random() < share else rng.uniform(min(low, full), full)


# ---------------------------------------------------------------------------
# Modules. Each draws inside a local region (x0, y0, x1, y1) with stem width W,
# bar thickness H and the glyph's corner style, and returns a list of parts.
# Strokes that should join are unioned into one part; None means the region
# cannot hold the module. The builder turns, mirrors and leans the result.
# ---------------------------------------------------------------------------

def m_bar(rng, x0, y0, x1, y1, W, H, st):
    """A bar, sometimes with angled ends as Share Tech Mono cuts them."""
    w, h = x1 - x0, y1 - y0
    if w < 22 or h < H:
        return None
    length = _span(rng, max(22.0, 0.5 * w), w)
    x = rng.choice((x0, x1 - length, x0 + rng.uniform(0, w - length)))
    y = rng.choice((y0, y1 - H, y0 + rng.uniform(0, h - H)))
    a = _angled_end(rng, H)
    b = _angled_end(rng, H)
    return [poly([(x + max(a, 0), y), (x + length - max(b, 0), y),
                  (x + length - max(-b, 0), y + H), (x + max(-a, 0), y + H)])]


def m_stem(rng, x0, y0, x1, y1, W, H, st):
    """An upright stem, sometimes with a slanted end cut."""
    w, h = x1 - x0, y1 - y0
    if h < 26 or w < W:
        return None
    length = _span(rng, max(26.0, 0.55 * h), h)
    x = rng.choice((x0, x1 - W, x0 + rng.uniform(0, w - W)))
    y = rng.choice((y0, y1 - length, y0 + rng.uniform(0, h - length)))
    a = _angled_end(rng, W)
    b = _angled_end(rng, W)
    return [poly([(x, y + max(a, 0)), (x + W, y + max(-a, 0)),
                  (x + W, y + length - max(b, 0)), (x, y + length - max(-b, 0))])]


def m_corner(rng, x0, y0, x1, y1, W, H, st):
    """An L-shaped corner with arms of independent length; sometimes the stem runs on as a foot."""
    w, h = x1 - x0, y1 - y0
    if w < W + 12 or h < H + 16:
        return None
    reach = _span(rng, max(W + 12, 0.45 * w), w, share=0.35)
    rise = _span(rng, max(H + 16, 0.5 * h), h)
    if rng.random() < 0.2 and rise >= 2.2 * H + 16:
        foot = rng.uniform(0.5, 1.1) * H
        y = y1 - foot - H
        return [union_all([rect(x0, y1 - rise, x0 + W, y1), rect(x0, y, x0 + reach, y + H)])]
    x, y = x0 + W / 2, y1 - H / 2
    return [ortho([(x, y1 - rise), (x, y), (x0 + reach, y)], [W, H], st)]


def m_roof(rng, x0, y0, x1, y1, W, H, st):
    """A header on one or two legs of unequal length, sometimes overhanging them as in ホ and モ."""
    w, h = x1 - x0, y1 - y0
    if w < W + 14 or h < H + 24:
        return None
    over_l = rng.choice((0.0, 0.0, rng.uniform(5, 0.26 * w)))
    over_r = rng.choice((0.0, 0.0, rng.uniform(5, 0.26 * w)))
    if w - over_l - over_r < 2 * W + 10:
        over_l = over_r = 0.0
    legs = rng.choice(("both", "both", "both", "left", "right")) if w >= 2 * W + 9 else rng.choice(("left", "right"))
    if legs != "both" and w - over_l - over_r < W + 8:
        over_l = over_r = 0.0
    pieces = [rect(x0, y0, x1, y0 + H)]
    if legs in ("both", "left"):
        pieces.append(rect(x0 + over_l, y0, x0 + over_l + W, y0 + _span(rng, max(0.55 * h, H + 20), h)))
    if legs in ("both", "right"):
        if legs == "both" and rng.random() < 0.3:
            # The second leg ends in a curl, as the catalog's roof hooks do.
            xr = x1 - over_r - W / 2
            drop = rng.uniform(0.55, 1.0) * h - W / 2
            curl = -rng.uniform(0.2, 0.42) * w
            center = chain(seg((xr, y0 + H / 2), (xr, y0 + drop * 0.6)),
                           bezier_points((xr, y0 + drop * 0.6), (xr, y0 + drop), (xr, y0 + drop),
                                         (xr + curl, y0 + drop - rng.uniform(0, 8))))
            pieces.append(ribbon(center, W, W * _taper(rng), hold=0.6))
        else:
            pieces.append(rect(x1 - over_r - W, y0, x1 - over_r, y0 + rng.uniform(max(0.4, (H + 20) / h), 1.0) * h))
    shape = union_all(pieces)
    if legs in ("both", "left") and over_l == 0:
        shape = cut_corner(shape, x0, y0, 1, 1, st)
    if legs in ("both", "right") and over_r == 0:
        shape = cut_corner(shape, x1, y0, -1, 1, st)
    return [shape]


def m_tee(rng, x0, y0, x1, y1, W, H, st):
    """A bar with a stem dropping from an offset point, as in 丁."""
    w, h = x1 - x0, y1 - y0
    if w < W + 14 or h < H + 24:
        return None
    left = x0 + rng.choice((0.0, rng.uniform(0, 0.2 * w)))
    right = x1 - rng.choice((0.0, rng.uniform(0, 0.2 * w)))
    if right - left < W + 14:
        left, right = x0, x1
    sx = rng.uniform(left + 7.0, right - W - 7.0)
    drop = _span(rng, max(H + 24, 0.6 * h), h)
    return [union_all([rect(left, y0, right, y0 + H), rect(sx, y0, sx + W, y0 + drop)])]


def m_cross(rng, x0, y0, x1, y1, W, H, st):
    """A crossing joined off center; sometimes two bars, as in 丰."""
    w, h = x1 - x0, y1 - y0
    if w < W + 16 or h < 2 * H + 16:
        return None
    sx = rng.uniform(x0 + max(7.0, 0.2 * (w - W)), x1 - W - max(7.0, 0.2 * (w - W)))
    top = y0 + rng.choice((0.0, rng.uniform(0, 0.15 * h)))
    bottom = y1 - rng.choice((0.0, rng.uniform(0, 0.15 * h)))
    pieces = [rect(sx, top, sx + W, bottom)]
    if h >= 3 * H + 30 and rng.random() < 0.35:
        first = rng.uniform(top + 0.1 * h, top + 0.35 * h)
        second = rng.uniform(first + H + 10.5, max(first + H + 10.5, bottom - 0.1 * h - H))
        ys = [first, min(second, bottom - H)]
    else:
        ys = [rng.uniform(top + 0.18 * (bottom - top), bottom - 0.18 * (bottom - top) - H)]
    for y in ys:
        a = min(rng.choice((0.0, rng.uniform(0, 0.25 * w))), sx - x0 - 7.0)
        b = min(rng.choice((0.0, rng.uniform(0, 0.25 * w))), x1 - sx - W - 7.0)
        pieces.append(rect(x0 + max(a, 0), y, x1 - max(b, 0), y + H))
    return [union_all(pieces)]


def m_comb(rng, x0, y0, x1, y1, W, H, st):
    """A spine with three or four arms of different reach, as in E and ヨ; a middle arm may stand apart."""
    w, h = x1 - x0, y1 - y0
    if w < W + 16 or h < 3 * H + 22:
        return None
    arms = 4 if h >= 4 * H + 34 and rng.random() < 0.25 else 3
    space = (h - arms * H) / (arms - 1)
    ys = [y0 + k * (H + space) + (rng.uniform(-0.25, 0.25) * (space - 10) if 0 < k < arms - 1 else 0)
          for k in range(arms)]
    detached = rng.random() < 0.25 and w >= W + 34
    gap = rng.uniform(*GAP)
    pieces, loose = [rect(x0, y0, x0 + W, y1)], []
    for k, y in enumerate(ys):
        end = k in (0, arms - 1)
        reach = w * (rng.uniform(0.55, 1.0) if end else rng.uniform(0.42, 0.9))
        if detached and not end and not loose:
            loose.append(rect(x0 + W + gap, y, max(x0 + reach, x0 + W + gap + 14), y + H))
        else:
            pieces.append(rect(x0, y, x0 + reach, y + H))
    shape = union_all(pieces)
    shape = cut_corner(cut_corner(shape, x0, y0, 1, 1, st), x0, y1, 1, -1, st)
    return [shape] + loose


def m_bracket(rng, x0, y0, x1, y1, W, H, st):
    """A three-sided bracket with unequal arms; sometimes it holds a mark (frame with mark)."""
    w, h = x1 - x0, y1 - y0
    if w < W + 16 or h < 2 * H + 18:
        return None
    top = rng.uniform(max(W + 14, 0.5 * w), w)
    bottom = rng.uniform(max(W + 14, 0.5 * w), w)
    x = x0 + W / 2
    shape = ortho([(x0 + top, y0 + H / 2), (x, y0 + H / 2), (x, y1 - H / 2), (x0 + bottom, y1 - H / 2)],
                  [H, W, H], st)
    gap = rng.uniform(*GAP)
    inner = (x0 + W + gap, y0 + H + gap, x0 + min(top, bottom) + rng.uniform(0, 8), y1 - H - gap)
    if rng.random() < 0.3 and inner[2] - inner[0] >= 12 and inner[3] - inner[1] >= 10:
        mh = min(inner[3] - inner[1], rng.uniform(0.85, 1.2) * H)
        my = inner[1] + rng.uniform(0, inner[3] - inner[1] - mh)
        return [shape, rect(inner[0], my, inner[2], my + mh)]
    return [shape]


def m_frame(rng, x0, y0, x1, y1, W, H, st):
    """A closed frame with an inner bar (日), the catalog's rare deliberate counter."""
    w, h = x1 - x0, y1 - y0
    if w < 2 * W + 18 or h < 3 * H + 24:
        return None
    xa, xb, ya, yb = x0 + W / 2, x1 - W / 2, y0 + H / 2, y1 - H / 2
    xm = (xa + xb) / 2
    ring = ortho([(xm, ya), (xb, ya), (xb, yb), (xa, yb), (xa, ya), (xm, ya)], [H, W, H, W, H], st)
    mid = (y0 + y1 - H) / 2 + rng.uniform(-0.12, 0.12) * (h - 3 * H)
    inner = rect(x0 + W / 2, mid, x1 - rng.choice((W / 2, W / 2, rng.uniform(W + 10, W + 18))), mid + H)
    return [union_all([ring, inner])]


def m_interrupted(rng, x0, y0, x1, y1, W, H, st):
    """A long stroke broken by a deliberate gap into unequal pieces, sometimes offset or kicked into a corner."""
    w, h = x1 - x0, y1 - y0
    gap = rng.uniform(*GAP)
    if h < 40 + gap or w < W:
        return None
    x = rng.choice((x0, x1 - W, x0 + rng.uniform(0, w - W)))
    cut = rng.uniform(y0 + 20, y1 - gap - 20)
    shift = rng.choice((0.0, 0.0, rng.uniform(-0.8, 0.8) * W))
    x2 = min(max(x + shift, x0), x1 - W)
    top = rect(x, y0 + rng.choice((0.0, 0.0, rng.uniform(0, 0.1 * h))), x + W, cut)
    if rng.random() < 0.4 and w >= W + 16:
        toward = 1 if x2 - x0 < x1 - x2 - W else -1
        room = (x1 - x2 - W / 2) if toward > 0 else (x2 + W / 2 - x0)
        reach = rng.uniform(max(W + 10, 0.45 * room), room)
        ya = y1 - H / 2
        if ya - (cut + gap) < H + 8:
            return None
        bottom = ortho([(x2 + W / 2, cut + gap), (x2 + W / 2, ya), (x2 + W / 2 + toward * reach, ya)], [W, H], st)
    else:
        bottom = rect(x2, cut + gap, x2 + W, y1 - rng.choice((0.0, 0.0, rng.uniform(0, 0.1 * h))))
    return [top, bottom]


def m_pair(rng, x0, y0, x1, y1, W, H, st):
    """Two parallel bars of unequal length, offset like the catalog's shelves."""
    w, h = x1 - x0, y1 - y0
    gap = rng.uniform(*GAP)
    if w < 22 or h < 2 * H + gap:
        return None
    ya = y0 + rng.choice((0.0, rng.uniform(0, 0.4 * (h - 2 * H - gap))))
    yb = rng.uniform(ya + H + gap, y1 - H)
    parts = []
    for y in (ya, yb):
        length = _span(rng, max(22.0, 0.4 * w), w, share=0.35)
        x = rng.choice((x0, x1 - length, x0 + rng.uniform(0, w - length)))
        if rng.random() < 0.18 and length > 30:
            rise = rng.uniform(4, 9) * rng.choice((-1, 1))
            parts.append(slant_bar(x, x + length, y + max(rise, 0), y + max(-rise, 0), H))
        else:
            parts.append(rect(x, y, x + length, y + H))
    return parts


def m_step(rng, x0, y0, x1, y1, W, H, st):
    """A stepped diagonal as a pixel font draws one, or its steps set apart as marks."""
    w, h = x1 - x0, y1 - y0
    if w < 30 or h < 30:
        return None
    t = min(W, H) * rng.uniform(0.92, 1.0)
    if rng.random() < 0.3:
        gap = rng.uniform(*GAP)
        steps = 2
        bw = (w - gap) / 2
        if bw < t:
            return None
        bh = rng.uniform(1.0, 1.3) * H
        rise = rng.uniform(0.5, 1.0) * (h - bh)
        return [rect(x0 + k * (bw + gap), y1 - bh - k * rise, x0 + k * (bw + gap) + bw * rng.uniform(0.7, 1.0),
                     y1 - k * rise) for k in range(steps)]
    steps = rng.choice((2, 3)) if min(w, h) >= 46 else 2
    xs = [x0 + t / 2 + (w - t) * k / steps * rng.uniform(0.92, 1.0) if 0 < k < steps else x0 + t / 2 + (w - t) * k / steps
          for k in range(steps + 1)]
    ys = [y1 - t / 2 - (h - t) * k / steps for k in range(steps + 1)]
    points = [(xs[0], y1)]
    for k in range(steps):
        points += [(xs[k], ys[k + 1]), (xs[k + 1], ys[k + 1])]
    return [ortho(points, [t] * (len(points) - 1), st)]


def m_rungs(rng, x0, y0, x1, y1, W, H, st):
    """A stem line carrying two to four rungs, as Ogham writes its letters; rungs may slope."""
    w, h = x1 - x0, y1 - y0
    if w < W + 18 or h < 44:
        return None
    t = min(W, H) * rng.uniform(0.82, 0.95)
    side = rng.choice(("left", "right", "cross", "cross"))
    sx = {"left": x1 - W, "right": x0, "cross": x0 + rng.uniform(0.3, 0.7) * (w - W)}[side]
    count = rng.choice((2, 3, 3, 4))
    span = rng.uniform(0.5, 0.88) * h
    while count > 2 and (span - t) / (count - 1) < t + 9.5:
        count -= 1
    step = (span - t) / (count - 1)
    if step < t + 9.5:
        return None
    start = y0 + rng.uniform(0, h - span)
    graded, sloped = rng.random() < 0.3, rng.random() < 0.2
    pieces = [rect(sx, y0, sx + W, y1)]
    for k in range(count):
        y = start + k * step
        reach = w * (0.45 + 0.5 * k / (count - 1) if graded else rng.uniform(0.55, 1.0))
        if side == "cross":
            a, b = max(x0, sx + W / 2 - reach / 2), min(x1, sx + W / 2 + reach / 2)
            if b - a < W + 12:
                a, b = max(x0, sx - 6), min(x1, sx + W + 6)
        elif side == "left":
            a, b = max(x0, sx + W - reach), sx + W
        else:
            a, b = sx, min(x1, sx + reach)
        pieces.append(slant_bar(a, b, y + 4, y - 4, t) if sloped else rect(a, y, b, y + t))
    return [union_all(pieces)]


def m_zigzag(rng, x0, y0, x1, y1, W, H, st):
    """Z and N strokes: bars or stems joined by a lean with horizontal cuts."""
    w, h = x1 - x0, y1 - y0
    if w < 30 or h < 36:
        return None
    if rng.random() < 0.5:
        # Z: two bars and a lean from the top bar's right end to the bottom bar's left end.
        wd = min(lean_width(W, w - W, h - 2 * H), 0.45 * w)
        top = rect(x0 + rng.choice((0.0, rng.uniform(0, 0.2 * w))), y0, x1, y0 + H)
        bottom = rect(x0, y1 - H, x1 - rng.choice((0.0, rng.uniform(0, 0.2 * w))), y1)
        return [union_all([top, bottom, lean(x1 - wd, x0, y0 + H / 2, y1 - H / 2, wd)])]
    # N: two stems and a lean from the left stem's top to the right stem's foot.
    wd = min(lean_width(W, w - 2 * W, h), 0.4 * w)
    la, lb = _span(rng, 0.7 * h, h), _span(rng, 0.7 * h, h)
    left, right = rect(x0, y1 - la, x0 + W, y1), rect(x1 - W, y0, x1, y0 + lb)
    return [union_all([left, right, lean(x0, x1 - wd, y1 - la, y0 + lb, wd)])]


def m_meander(rng, x0, y0, x1, y1, W, H, st):
    """A squared spiral turning inward, after Ogham's supplementary letters."""
    w, h = x1 - x0, y1 - y0
    t = min(W, H) * rng.uniform(0.86, 0.95)
    gap = rng.uniform(10.0, 12.5)
    if w < 3 * t + gap + 8 or h < 3 * t + 2 * gap:
        return None
    xa, xb, ya, yb = x0 + t / 2, x1 - t / 2, y0 + t / 2, y1 - t / 2
    xi = xa + t + gap
    if rng.random() < 0.5:
        points = [(xa, y1 - rng.uniform(0, 0.25 * h)), (xa, ya), (xb, ya), (xb, yb), (xi, yb), (xi, ya + t + gap)]
    else:
        points = [(xb - rng.uniform(0, 0.3 * w), ya), (xa, ya), (xa, yb), (xb, yb), (xb, ya + t + gap)]
    if points[-1][1] > points[-2][1] - t:
        return None
    return [ortho(points, [t] * (len(points) - 1), st)]


def m_squares(rng, x0, y0, x1, y1, W, H, st):
    """One or two square dots of unequal size, as Braille sets them."""
    w, h = x1 - x0, y1 - y0
    gap = rng.uniform(*GAP)
    sizes = [(rng.uniform(1.0, 1.5) * W, rng.uniform(1.0, 1.45) * H) for _ in range(2)]
    if w < sizes[0][0] or h < sizes[0][1]:
        return None
    horizontal = w >= sizes[0][0] + sizes[1][0] + gap
    vertical = h >= sizes[0][1] + sizes[1][1] + gap
    if (horizontal or vertical) and rng.random() < 0.55:
        (aw, ah), (bw, bh) = sizes
        if horizontal and (not vertical or rng.random() < 0.5):
            ya = y0 + rng.uniform(0, h - ah)
            yb = y0 + rng.uniform(0, h - bh)
            xb = x0 + aw + gap + rng.uniform(0, w - aw - bw - gap)
            return [rect(x0, ya, x0 + aw, ya + ah), rect(xb, yb, xb + bw, yb + bh)]
        xa = x0 + rng.uniform(0, w - aw)
        xb = x0 + rng.uniform(0, w - bw)
        yb = y0 + ah + gap + rng.uniform(0, h - ah - bh - gap)
        return [rect(xa, y0, xa + aw, y0 + ah), rect(xb, yb, xb + bw, yb + bh)]
    aw, ah = sizes[0]
    x = rng.choice((x0, x1 - aw, x0 + rng.uniform(0, w - aw)))
    y = rng.choice((y0, y1 - ah, y0 + rng.uniform(0, h - ah)))
    return [rect(x, y, x + aw, y + ah)]


def m_hbeam(rng, x0, y0, x1, y1, W, H, st):
    """Two uprights of unequal length joined by a crossbar at any height; the bar may slope, as in ᚺ."""
    w, h = x1 - x0, y1 - y0
    if w < 2 * W + 9 or h < 2 * H + 22:
        return None
    la, lb = _span(rng, 0.6 * h, h), _span(rng, 0.6 * h, h)
    ya, yb = rng.choice((y0, y1 - la)), rng.choice((y0, y1 - lb))
    lo, hi = max(ya, yb) + 2, min(ya + la, yb + lb) - H - 2
    if hi < lo:
        return None
    y = rng.uniform(lo, hi)
    if rng.random() < 0.3:
        rise = rng.uniform(-1, 1) * min(14, max(0.0, hi - lo))
        a, b = min(max(y, lo), hi), min(max(y + rise, lo), hi)
        bar = slant_bar(x0 + W / 2, x1 - W / 2, a, b, H)
    else:
        bar = rect(x0 + W / 2, y, x1 - W / 2, y + H)
    return [union_all([rect(x0, ya, x0 + W, ya + la), rect(x1 - W, yb, x1, yb + lb), bar])]


def m_lean(rng, x0, y0, x1, y1, W, H, st):
    """A leaning stroke with horizontal cuts."""
    w, h = x1 - x0, y1 - y0
    if w < W + 10 or h < 26:
        return None
    length = _span(rng, max(26.0, 0.6 * h), h)
    run = rng.uniform(0.3, 1.0) * (w - W)
    wd = min(lean_width(W, run, length) * rng.uniform(0.95, 1.05), w - run)
    y = rng.choice((y0, y1 - length))
    if rng.random() < 0.5:
        return [lean(x0 + run, x0, y, y + length, wd)]
    return [lean(x1 - wd - run, x1 - wd, y, y + length, wd)]


def m_leaning_pair(rng, x0, y0, x1, y1, W, H, st):
    """Two leaning strokes: parallel, meeting across a gap (∧), or parting (∨)."""
    w, h = x1 - x0, y1 - y0
    gap = rng.uniform(*GAP)
    if w < 2 * W + gap + 8 or h < 30:
        return None
    kind = rng.choice(("parallel", "parallel", "roof", "vee"))
    if kind == "parallel":
        run = rng.uniform(0.2, 1.0) * max(0.0, w - 2 * W - gap - 4) * 0.8
        wd = lean_width(W, run, h)
        spacing = wd + gap / math.cos(math.atan2(run, h))
        if run + spacing + wd > w:
            return None
        la, lb = _span(rng, 0.7 * h, h), _span(rng, 0.7 * h, h)
        ya, yb = rng.choice((y0, y1 - la)), rng.choice((y0, y1 - lb))
        slope = run / h
        a = lean(x0 + run - (ya - y0) * slope, x0 + run - (ya + la - y0) * slope, ya, ya + la, wd)
        b = lean(x0 + spacing + run - (yb - y0) * slope, x0 + spacing + run - (yb + lb - y0) * slope, yb, yb + lb, wd)
        return [a, b]
    top_gap = gap * rng.uniform(1.1, 1.5)
    half = (w - top_gap) / 2
    run = rng.uniform(0.45, 0.9) * (half - W)
    wd = lean_width(W, run, h)
    if run + wd > half:
        return None
    cx = x0 + w / 2
    a = lean(cx - top_gap / 2 - wd, cx - top_gap / 2 - wd - run, y0, y1, wd)
    b = lean(cx + top_gap / 2, cx + top_gap / 2 + run, y0, y1 - rng.choice((0.0, rng.uniform(0, 0.2 * h))), wd)
    parts = [a, b]
    if kind == "vee":
        parts = [affinity.scale(p, 1, -1, origin=(cx, (y0 + y1) / 2)) for p in parts]
    return parts


def m_slant(rng, x0, y0, x1, y1, W, H, st):
    """A sloping bar with vertical cuts, as the catalog's sloping headers."""
    w, h = x1 - x0, y1 - y0
    if w < 26 or h < H + 8:
        return None
    rise = rng.uniform(5, min(20, h - H))
    length = _span(rng, max(26.0, 0.6 * w), w)
    x = rng.choice((x0, x1 - length))
    y = rng.uniform(y0, y1 - H - rise)
    if rng.random() < 0.5:
        return [slant_bar(x, x + length, y + rise, y, H)]
    return [slant_bar(x, x + length, y, y + rise, H)]


def m_chevron(rng, x0, y0, x1, y1, W, H, st):
    """A ∧ of two leans that meet under a flat top; its legs differ, and a bar may cross it like A."""
    w, h = x1 - x0, y1 - y0
    if w < 2 * W + 10 or h < 30:
        return None
    apex = x0 + rng.uniform(0.38, 0.62) * w
    wd = lean_width(min(W, H), 0.45 * w, h) * rng.uniform(0.95, 1.05)
    top = rng.uniform(1.0, 1.7) * wd
    foot_l = x0 + rng.choice((0.0, rng.uniform(0, 0.1 * w)))
    foot_r = x1 - rng.choice((0.0, rng.uniform(0, 0.1 * w)))
    end_r = y1 - rng.choice((0.0, 0.0, rng.uniform(0, 0.25 * h)))
    right_run = (foot_r - (apex + top / 2)) * (end_r - y0) / h
    left = lean(apex - top / 2, foot_l, y0, y1, wd)
    right = lean(apex + top / 2 - wd, apex + top / 2 - wd + right_run, y0, end_r, wd)
    shape = union_all([left, right])
    if rng.random() < 0.3:
        y = y0 + rng.uniform(0.55, 0.78) * h
        t = (y + H / 2 - y0) / h
        xl = apex - top / 2 + (foot_l - (apex - top / 2)) * t + wd / 2
        xr = apex + top / 2 - wd + right_run * (y + H / 2 - y0) / max(end_r - y0, 1e-6) + wd / 2
        if xr - xl > wd + 6:
            shape = union_all([shape, rect(xl, y, xr, y + H)])
    return [shape]


def m_x(rng, x0, y0, x1, y1, W, H, st):
    """X crossings of two leans; with bars they become hourglasses (ⵅ), with uprights bowties (ᛞ)."""
    w, h = x1 - x0, y1 - y0
    if w < 2 * W + 10 or h < 30:
        return None
    wd = lean_width(min(W, H), w - W, h) * rng.uniform(0.95, 1.05)
    if 2 * wd > w - 4:
        return None
    s = rng.uniform(-0.22, 0.22) * w
    a = lean(x1 - wd + min(s, 0), x0 + max(s, 0), y0, y1, wd)
    b = lean(x0 + max(-s, 0), x1 - wd + min(-s, 0), y0 + rng.choice((0.0, rng.uniform(0, 0.25 * h))), y1, wd)
    kind = rng.choice(("x", "hourglass", "open", "open", "bowtie"))
    if kind == "hourglass" and h >= 2 * H + 26:
        return [union_all([a, b, rect(x0, y0, x1, y0 + H), rect(x0, y1 - H, x1, y1)])]
    if kind == "bowtie" and h >= 40:
        return [union_all([a, b, rect(x0, y0, x0 + W, y1), rect(x1 - W, y0, x1, y1)])]
    if kind == "open":
        gap = rng.uniform(*GAP)
        pieces = polygons(b.difference(a.buffer(gap, join_style="mitre")))
        if len(pieces) == 2 and min(p.area for p in pieces) > 150:
            return [a] + pieces
    return [union_all([a, b])]


def m_branch(rng, x0, y0, x1, y1, W, H, st):
    """A stem with one or two branches rising from it, as ᚠ and ᚨ; branches sometimes stand apart."""
    w, h = x1 - x0, y1 - y0
    if w < W + 15 or h < 40:
        return None
    detached = rng.random() < 0.3
    gap = rng.uniform(*GAP)
    base_x = x0 + W + gap if detached else x0 + W * 0.5
    run = x1 - base_x
    if run < 14:
        return None
    rise = rng.uniform(0.5, 1.15) * run
    wd = min(lean_width(min(W, H), run, rise), 0.6 * run)
    count = rng.choice((1, 2, 2))
    phi = math.atan2(rise, run)
    spacing = (gap + wd * math.sin(phi)) / max(math.cos(phi), 0.3) + 3
    first = y0 + rise + rng.uniform(0, 0.15 * h)
    bases = [first] + ([first + spacing + rng.uniform(0, 8)] if count == 2 else [])
    if bases[-1] > y1 - 4:
        bases = bases[:1]
        if bases[0] > y1 - 4:
            return None
    stem = rect(x0, y0 + rng.choice((0.0, 0.0, rng.uniform(0, 0.12 * h))), x0 + W, y1)
    if detached:
        return [stem] + [lean(x1 - wd, base_x, b - rise, b, wd) for b in bases]
    # A joined branch narrows to the stem's width where it meets it, so no ledge shows.
    foot = min(wd, W)
    return [union_all([stem] + [taper_lean(x1 - wd, x0 + (W - foot) / 2, b - rise, b, wd, foot) for b in bases])]


def m_fork(rng, x0, y0, x1, y1, W, H, st):
    """A stem that splits into two arms, as ᛉ and Y; sometimes the stem runs on between them (Ψ)."""
    w, h = x1 - x0, y1 - y0
    if w < 2 * W + 6 or h < 44:
        return None
    cx = x0 + rng.uniform(0.42, 0.58) * w
    split = y0 + rng.uniform(0.38, 0.62) * h
    top_l = y0 + rng.choice((0.0, rng.uniform(0, 0.2 * h)))
    top_r = y0 + rng.choice((0.0, rng.uniform(0, 0.2 * h)))
    wl = lean_width(min(W, H), cx - x0, split - top_l)
    wr = lean_width(min(W, H), x1 - cx, split - top_r)
    if wl > 0.45 * (cx - x0 + W) or wr > 0.45 * (x1 - cx + W):
        return None
    # Each arm narrows to the stem's width where they meet, so no ledge shows.
    fl, fr = min(wl, W), min(wr, W)
    pieces = [rect(cx - W / 2, split - 2, cx + W / 2, y1),
              taper_lean(x0, cx - fl / 2, top_l, split + 2, wl, fl),
              taper_lean(x1 - wr, cx - fr / 2, top_r, split + 2, wr, fr)]
    if rng.random() < 0.3 and w >= 3 * W + 22:
        pieces.append(rect(cx - W / 2, y0 + rng.uniform(0, 0.15 * h), cx + W / 2, split))
    return [union_all(pieces)]


def m_arrow(rng, x0, y0, x1, y1, W, H, st):
    """A stem under an arrowhead, as ᛏ; the barbs sometimes stand apart from the stem."""
    w, h = x1 - x0, y1 - y0
    if w < 2 * W + 6 or h < 44:
        return None
    cx = x0 + rng.uniform(0.4, 0.6) * w
    drop_l = rng.uniform(0.25, 0.55) * h
    drop_r = min(drop_l * rng.choice((rng.uniform(0.5, 0.75), rng.uniform(1.3, 1.8))), 0.7 * h)
    wl = lean_width(min(W, H), cx - x0, drop_l)
    wr = lean_width(min(W, H), x1 - cx, drop_r)
    stem = rect(cx - W / 2, y0, cx + W / 2, y1 - rng.choice((0.0, rng.uniform(0, 0.12 * h))))
    if rng.random() < 0.5:
        gap = rng.uniform(*GAP)
        left = lean(cx - W / 2 - gap - wl, x0, y0 + 4, y0 + drop_l, wl)
        right = lean(cx + W / 2 + gap, x1 - wr, y0 + 4, y0 + drop_r, wr)
        if left.bounds[0] < x0 - 1 or right.bounds[2] > x1 + 1:
            return None
        return [stem, left, right]
    left = lean(cx - wl / 2, x0, y0, y0 + drop_l, wl)
    right = lean(cx - wr / 2, x1 - wr, y0, y0 + drop_r, wr)
    return [union_all([stem, left, right])]


def m_bolt(rng, x0, y0, x1, y1, W, H, st):
    """A bolt of two leans joined by a short bar, as ᛋ and ᛊ."""
    w, h = x1 - x0, y1 - y0
    if w < 2 * W + 2 or h < 44:
        return None
    ym = y0 + rng.uniform(0.4, 0.6) * h
    xa, xb = x0 + rng.uniform(0.35, 0.55) * w, x0 + rng.uniform(0.45, 0.65) * w
    wd = lean_width(min(W, H), xa - x0, ym - y0)
    top = lean(x0, xa - wd, y0, ym + H / 2, wd)
    bar = rect(min(xa, xb) - wd, ym - H / 2, max(xa, xb) + wd, ym + H / 2)
    bottom = lean(xb, x1 - wd, ym - H / 2, y1, wd)
    return [union_all([top, bar, bottom])]


def m_diamond(rng, x0, y0, x1, y1, W, H, st):
    """A diamond: a ring with a counter (ᛜ), or two open halves facing across gaps."""
    w, h = x1 - x0, y1 - y0
    if w < 34 or h < 34:
        return None
    t = min(W, H) * rng.uniform(0.9, 1.0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = w / 2 - t * 0.75, h / 2 - t * 0.75
    if min(rx, ry) < t + 6:
        return None
    top, right, bottom, left = (cx, cy - ry), (cx + rx, cy), (cx, cy + ry), (cx - rx, cy)
    if rng.random() < 0.3:
        start = ((top[0] + right[0]) / 2, (top[1] + right[1]) / 2)
        return [path([start, right, bottom, left, top, start], t)]
    gap = rng.uniform(*GAP)
    if rng.random() < 0.5:
        a = path([(cx - gap / 2, cy - ry + gap * 0.9), left, (cx - gap / 2, cy + ry - gap * 0.9)], t)
        b = path([(cx + gap / 2, cy - ry + gap * 0.9), right, (cx + gap / 2, cy + ry - gap * 0.9)], t)
    else:
        a = path([(cx - rx + gap * 0.9, cy - gap / 2), top, (cx + rx - gap * 0.9, cy - gap / 2)], t)
        b = path([(cx - rx + gap * 0.9, cy + gap / 2), bottom, (cx + rx - gap * 0.9, cy + gap / 2)], t)
    return [a, b]


def m_dashes(rng, x0, y0, x1, y1, W, H, st):
    """Two or three short oblique dashes, as Yautja strings them."""
    w, h = x1 - x0, y1 - y0
    if w < 24 or h < 34:
        return None
    t = min(W, H) * rng.uniform(0.9, 1.0)
    gap = rng.uniform(*GAP)
    count = rng.choice((2, 2, 3))
    parts = []
    for _ in range(24):
        if len(parts) == count:
            break
        length = rng.uniform(18, 26)
        angle = math.radians(rng.choice((-1, 1)) * rng.uniform(28, 62))
        dx, dy = math.cos(angle) * length / 2, math.sin(angle) * length / 2
        cx, cy = rng.uniform(x0 + abs(dx) + t / 2, x1 - abs(dx) - t / 2), rng.uniform(y0 + abs(dy) + t / 2, y1 - abs(dy) - t / 2)
        dash = path([(cx - dx, cy - dy), (cx + dx, cy + dy)], t)
        if all(dash.distance(p) >= gap for p in parts):
            parts.append(dash)
    return parts if len(parts) >= 2 else None


def m_hook(rng, x0, y0, x1, y1, W, H, st):
    """A stem whose foot sweeps into a tapered tail, as J and し; the tail may reach out flat or curl back up."""
    w, h = x1 - x0, y1 - y0
    if w < W + 12 or h < 32:
        return None
    turn = rng.uniform(0.3, 0.8)
    reach = rng.uniform(0.45, 1.0)
    lift = rng.uniform(0.3, 0.85) if rng.random() < 0.4 else rng.uniform(-0.05, 0.3)
    curl = rng.uniform(0.1, 0.9)
    drop = turn + (1.0 - turn) * rng.uniform(0.55, 1.0)
    dip = 1.0 + rng.uniform(0.0, 0.15)
    top = rng.choice((0.0, 0.0, 0.0, rng.uniform(-0.2, 0.2)))
    center = chain(seg((top, 0.0), (0.0, turn)),
                   bezier_points((0.0, turn), (0.0, drop), (reach * curl, dip), (reach, 1.0 - lift)))
    center = fit_center(center, (x0, y0 + rng.choice((0.0, 0.0, rng.uniform(0, 0.15 * h))), x1, y1), W / 2,
                        keep=0.0)
    if not center:
        return None
    lengths = [math.dist(a, b) for a, b in zip(center, center[1:])]
    hold = sum(lengths[:6]) / sum(lengths) + rng.uniform(0.0, 0.2)
    return [ribbon(center, W, W * _taper(rng), hold=min(hold, 0.85))]


def m_crook(rng, x0, y0, x1, y1, W, H, st):
    """A stem whose top turns over in a round shoulder and ends in a straight cut, as ſ and ᒉ."""
    w, h = x1 - x0, y1 - y0
    if w < W + 18 or h < 40:
        return None
    over = rng.uniform(0, 120)
    ry = rng.uniform(0.2, 0.7)
    center = chain(seg((0.0, 1.0), (0.0, ry)), arc_points(0.5, ry, 0.5, ry, 180, 270 + over))
    region = (x0, y0, x1, y1 - rng.choice((0.0, 0.0, rng.uniform(0, 0.18 * h))))
    center = fit_center(center, region, W / 2)
    if not center:
        return None
    return [ribbon(center, W, W * rng.uniform(0.62, 0.9), hold=rng.uniform(0.55, 0.85))]


def m_shoulder(rng, x0, y0, x1, y1, W, H, st):
    """A stem arching over into a second, shorter leg, as n, h and ᚢ."""
    w, h = x1 - x0, y1 - y0
    if w < 2 * W + 8 or h < 36:
        return None
    ry = rng.uniform(0.18, 0.5)
    leg_l, leg_r = 1.0, rng.uniform(ry + 0.1, 1.0)
    head = rng.choice((0.0, 0.0, rng.uniform(0.2, 0.45)))
    center = chain(seg((0.0, leg_l), (0.0, ry + head)), arc_points(0.5, ry + head, 0.5, ry, 180, 360),
                   seg((1.0, ry + head), (1.0, leg_r)))
    if head:
        # The first stem rises past the arch, as in h.
        stem_top = (x0, y0, x0 + W, y0 + head * h)
        center = fit_center(center, (x0, y0 + head * h * 0.9, x1, y1), W / 2, keep=0.0)
        if not center:
            return None
        return [union_all([ribbon(center, W, W * rng.uniform(0.82, 0.95), hold=0.8), rect(*stem_top)])]
    center = fit_center(center, (x0, y0, x1, y1), W / 2)
    if not center:
        return None
    return [ribbon(center, W, W * rng.uniform(0.82, 0.95), hold=0.8)]


def m_bowl(rng, x0, y0, x1, y1, W, H, st):
    """U bowls with arms of different height, a round or flat bottom and tapered tips."""
    w, h = x1 - x0, y1 - y0
    if w < 2 * W + 10 or h < 30:
        return None
    arm_l, arm_r = rng.uniform(0.0, 0.3), rng.uniform(0.0, 0.65)
    depth = rng.uniform(0.3, 0.75)
    base = 1.0 - depth
    kind = rng.random()
    if kind < 0.35:
        # A lopsided cubic bowl, deepest off center.
        dip = rng.uniform(0.95, 1.35)
        center = bezier_points((0.0, arm_l), (rng.uniform(-0.25, 0.35), dip), (rng.uniform(0.65, 1.25), dip),
                               (1.0, arm_r), samples=40)
    elif kind < 0.55:
        r = rng.uniform(0.18, 0.4)
        bottom = chain(arc_points(r, 1.0 - r, r, r, 180, 90), seg((r, 1.0), (1.0 - r, 1.0)),
                       arc_points(1.0 - r, 1.0 - r, r, r, 90, 0))
        center = chain(seg((0.0, arm_l), (0.0, 1.0 - r)), bottom, seg((1.0, 1.0 - r), (1.0, arm_r)))
    else:
        center = chain(seg((0.0, arm_l), (0.0, base)), arc_points(0.5, base, 0.5, depth, 180, 0),
                       seg((1.0, base), (1.0, arm_r)))
    center = fit_center(center, (x0, y0, x1, y1), W / 2, keep=rng.uniform(0.0, 0.15))
    if not center:
        return None
    both = rng.random() < 0.4
    return [ribbon(center, W, W * _taper(rng), hold=rng.uniform(0.35, 0.7), both=both)]


def m_crescent(rng, x0, y0, x1, y1, W, H, st):
    """A cut crescent: an arc of 60 to 260 degrees, thickest in the middle, cut straight at both tips."""
    w, h = x1 - x0, y1 - y0
    if w < W + 16 or h < 30:
        return None
    span = rng.uniform(60, 260)
    start = rng.uniform(0, 360)
    squash = rng.uniform(0.45, 1.0)
    center = arc_points(0.0, 0.0, 1.0, squash, start, start + span, samples=36)
    center = fit_center(center, (x0, y0, x1, y1), W * 0.55, keep=rng.uniform(0.0, 0.4))
    if not center:
        return None
    return [ribbon(center, W * rng.uniform(1.0, 1.12), W * rng.uniform(0.5, 0.72), hold=rng.uniform(0.1, 0.45),
                   both=rng.random() < 0.6)]


def m_sweep(rng, x0, y0, x1, y1, W, H, st):
    """A long tapered sweep from one corner toward the other, as ノ and ㇏; sometimes cut in two."""
    w, h = x1 - x0, y1 - y0
    if w < W + 18 or h < 36:
        return None
    p1 = (rng.uniform(-0.1, 0.4), rng.uniform(0.2, 0.7))
    p2 = (rng.uniform(0.3, 0.9), rng.uniform(0.6, 1.1))
    center = bezier_points((0.0, 0.0), p1, p2, (1.0, rng.uniform(0.75, 1.0)))
    center = fit_center(center, (x0, y0, x1, y1), W / 2)
    if not center:
        return None
    return [ribbon(center, W * rng.uniform(1.0, 1.1), W * _taper(rng), hold=rng.uniform(0.25, 0.6))]


def m_scurve(rng, x0, y0, x1, y1, W, H, st):
    """A reverse curve with one inflection, as S and ∫."""
    w, h = x1 - x0, y1 - y0
    if w < W + 18 or h < 40:
        return None
    bend = rng.uniform(0.5, 1.2)
    center = bezier_points((1.0, rng.uniform(0.0, 0.15)), (-bend, rng.uniform(0.15, 0.4)),
                           (1.0 + bend, rng.uniform(0.6, 0.85)), (0.0, rng.uniform(0.85, 1.0)), samples=40)
    center = fit_center(center, (x0, y0, x1, y1), W / 2)
    if not center:
        return None
    return [ribbon(center, W, W * _taper(rng), hold=rng.uniform(0.5, 0.8), both=rng.random() < 0.3)]


def m_ring(rng, x0, y0, x1, y1, W, H, st):
    """Rings: open with straight cuts, closed around a counter, or holding a dot (ⵙ)."""
    w, h = x1 - x0, y1 - y0
    if w < 34 or h < 34:
        return None
    t = min(W, H) * rng.uniform(0.92, 1.02)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = w / 2 - t / 2, h / 2 - t / 2
    kind = rng.choice(("open", "open", "open", "closed", "dot"))
    if kind == "open":
        opening = rng.uniform(40, 120)
        start = rng.uniform(0, 360)
        center = arc_points(cx, cy, rx, ry, start + opening / 2, start + 360 - opening / 2, samples=48)
        return [ribbon(center, t, t * _taper(rng), hold=rng.uniform(0.6, 0.9))]
    outer = affinity.scale(Point(cx, cy).buffer(1.0, quad_segs=24), rx + t / 2, ry + t / 2)
    inner = affinity.scale(Point(cx, cy).buffer(1.0, quad_segs=24), rx - t / 2, ry - t / 2)
    ring = outer.difference(inner)
    if kind == "dot":
        # The dot's corners keep a full gap from the ring's inner edge.
        gap = rng.uniform(*GAP)
        half = min((min(rx, ry) - t / 2 - gap) / math.sqrt(2), rng.uniform(0.35, 0.5) * W)
        if half < 5:
            return None
        return [ring, rect(cx - half, cy - half, cx + half, cy + half)]
    return [ring]


def m_loop(rng, x0, y0, x1, y1, W, H, st):
    """A stem carrying a bowl at its head, closed (ᚱ, P) or left open with a straight cut (ᚦ-like)."""
    w, h = x1 - x0, y1 - y0
    if w < W + 22 or h < 44:
        return None
    t = min(W, H)
    bowl_h = rng.uniform(0.45, 0.65) * h
    stem = rect(x0, y0, x0 + W, y1 - rng.choice((0.0, rng.uniform(0, 0.12 * h))))
    closed = rng.random() < 0.35
    xa = x0 + W - 1
    if rng.random() < 0.5:
        center = chain(seg((xa, y0 + t / 2), (x1 - bowl_h / 2, y0 + t / 2)),
                       arc_points(x1 - bowl_h / 2, y0 + bowl_h / 2, bowl_h / 2 - t / 2, bowl_h / 2 - t / 2, 270, 450),
                       seg((x1 - bowl_h / 2, y0 + bowl_h - t / 2), (xa if closed else xa + rng.uniform(*GAP) + 2,
                                                                   y0 + bowl_h - t / 2)))
        if x1 - bowl_h / 2 <= xa + 4:
            return None
        bowl = ribbon(center, t)
    else:
        tip = (x1 - t / 2, y0 + bowl_h / 2)
        end = (xa if closed else xa + rng.uniform(*GAP) + 4, y0 + bowl_h - t / 2)
        bowl = path([(xa, y0 + t / 2), tip, end], t)
    if closed:
        return [union_all([stem, bowl])]
    return [union_all([stem, bowl])] if bowl.intersects(stem) else [stem, bowl]


def m_pixel(rng, x0, y0, x1, y1, W, H, st):
    """A curve stepped on a pixel grid, as Press Start 2P draws its bowls and arcs."""
    curve = pick(rng, ((m_bowl, 3), (m_crescent, 2), (m_hook, 2), (m_shoulder, 2), (m_crook, 1), (m_scurve, 1)))
    parts = curve(rng, x0, y0, x1, y1, W, H, st)
    if not parts:
        return None
    cell = min(W, H) * rng.uniform(0.42, 0.55)
    return [pixelate(p, cell) for p in parts if p is not None and not p.is_empty] or None


def m_tick(rng, x0, y0, x1, y1, W, H, st):
    """A short oblique tick, as in ソ and ツ and the Yautja dashes."""
    w, h = x1 - x0, y1 - y0
    if w < 16 or h < 18:
        return None
    t = min(W, H) * rng.uniform(0.92, 1.0)
    length = rng.uniform(18, min(28, max(18.5, math.hypot(w, h) - t)))
    angle = math.radians(rng.choice((-1, 1)) * rng.uniform(30, 65))
    dx, dy = math.cos(angle) * length / 2, math.sin(angle) * length / 2
    if 2 * abs(dx) + t > w or 2 * abs(dy) + t > h:
        return None
    cx = rng.uniform(x0 + abs(dx) + t / 2, x1 - abs(dx) - t / 2)
    cy = rng.uniform(y0 + abs(dy) + t / 2, y1 - abs(dy) - t / 2)
    if rng.random() < 0.5:
        return [path([(cx - dx, cy - dy), (cx + dx, cy + dy)], t)]
    wd = lean_width(t, 2 * abs(dx), 2 * abs(dy))
    return [lean(cx - dx - wd / 2, cx + dx - wd / 2, cy - abs(dy), cy + abs(dy), wd) if dx * dy < 0
            else lean(cx + abs(dx) - wd / 2, cx - abs(dx) - wd / 2, cy - abs(dy), cy + abs(dy), wd)]


# Modules for a half of the glyph, weighted toward the catalog's own mix of
# straight corners and bars, with curves and diagonals drawn from the other alphabets.
MODULES = (
    (m_corner, 8), (m_roof, 5), (m_tee, 3), (m_cross, 2), (m_comb, 2), (m_bracket, 3), (m_frame, 1),
    (m_interrupted, 5), (m_pair, 5), (m_step, 3), (m_rungs, 2), (m_zigzag, 2), (m_meander, 1), (m_hbeam, 2),
    (m_stem, 3), (m_bar, 2), (m_lean, 2), (m_leaning_pair, 3), (m_slant, 2), (m_chevron, 2), (m_x, 1),
    (m_branch, 2), (m_fork, 2), (m_arrow, 0.5), (m_bolt, 1), (m_diamond, 1), (m_dashes, 1),
    (m_hook, 8), (m_crook, 5), (m_shoulder, 4), (m_bowl, 6), (m_crescent, 7), (m_sweep, 5), (m_scurve, 4),
    (m_ring, 2), (m_loop, 1), (m_pixel, 3), (m_squares, 2),
)
# Modules that can carry a whole glyph with at most a mark beside them.
# Modules that can carry a whole glyph beside a mark or across a break. Those whose
# lone form reads as a letter or symbol (X, Y, T, Z, <, + and arrows) are rare here.
WHOLE = (
    (m_comb, 3), (m_bracket, 3), (m_frame, 1), (m_roof, 3), (m_shoulder, 3), (m_bowl, 3), (m_ring, 2),
    (m_x, 0.3), (m_diamond, 2), (m_loop, 2), (m_meander, 2), (m_hbeam, 2), (m_cross, 0.3), (m_tee, 0.5),
    (m_chevron, 0.5), (m_fork, 0.3), (m_branch, 2), (m_zigzag, 0.5), (m_crook, 3), (m_hook, 3),
    (m_sweep, 3), (m_scurve, 3), (m_crescent, 3), (m_rungs, 2), (m_bolt, 1), (m_pixel, 2), (m_interrupted, 1),
)
# Small modules for a quarter of the glyph or a mark in free space.
SMALL = (
    (m_bar, 5), (m_stem, 3), (m_corner, 5), (m_squares, 4), (m_tick, 3), (m_lean, 2), (m_slant, 2),
    (m_crescent, 5), (m_hook, 3), (m_step, 1), (m_chevron, 1), (m_pair, 1), (m_tee, 1), (m_pixel, 1),
)
MARKS = ((m_squares, 4), (m_bar, 4), (m_tick, 3), (m_stem, 2), (m_corner, 2), (m_crescent, 1))


def fit_group(parts, x0, y0, x1, y1, *, least=LEAST_SCALE):
    """Scale and center a module's parts together inside the region, or None if that squeezes them too far."""
    bounds = [p.bounds for p in parts]
    bx0, by0 = min(b[0] for b in bounds), min(b[1] for b in bounds)
    bx1, by1 = max(b[2] for b in bounds), max(b[3] for b in bounds)
    scale = min(1.0, (x1 - x0) / max(bx1 - bx0, 1e-6), (y1 - y0) / max(by1 - by0, 1e-6))
    if scale < least:
        return None
    if scale < 1.0:
        center = ((bx0 + bx1) / 2, (by0 + by1) / 2)
        parts = [affinity.scale(part, scale, scale, origin=center) for part in parts]
        bounds = [p.bounds for p in parts]
        bx0, by0 = min(b[0] for b in bounds), min(b[1] for b in bounds)
        bx1, by1 = max(b[2] for b in bounds), max(b[3] for b in bounds)
    dx = x0 - bx0 if bx0 < x0 else (x1 - bx1 if bx1 > x1 else 0.0)
    dy = y0 - by0 if by0 < y0 else (y1 - by1 if by1 > y1 else 0.0)
    return [affinity.translate(part, dx, dy) for part in parts]


def interrupt(rng, parts, gap):
    """Cut a module's largest part across with a straight gap, as the catalog's interrupted strokes do."""
    k = max(range(len(parts)), key=lambda i: parts[i].area)
    part = parts[k]
    x0, y0, x1, y1 = part.bounds
    across = (x1 - x0) > (y1 - y0)
    if rng.random() < 0.25:
        across = not across
    if across:
        c = rng.uniform(x0 + 0.3 * (x1 - x0), x1 - 0.3 * (x1 - x0))
        band = rect(c - gap / 2, y0 - 1, c + gap / 2, y1 + 1)
    else:
        c = rng.uniform(y0 + 0.3 * (y1 - y0), y1 - 0.3 * (y1 - y0))
        band = rect(x0 - 1, c - gap / 2, x1 + 1, c + gap / 2)
    pieces = polygons(part.difference(band))
    if len(pieces) != 2 or min(p.area for p in pieces) < 180:
        return None
    for piece in pieces:
        bx0, by0, bx1, by1 = piece.bounds
        if min(bx1 - bx0, by1 - by0) < 8:
            return None
    return parts[:k] + pieces + parts[k + 1:]


class Builder:
    """Parts under construction: joined strokes form one part, separate parts keep gaps.

    ``is_new``, when given, is asked about each module's parts, as they will
    finally be drawn, before they are kept; a module that repeats a recent shape
    is redrawn. ``flip`` mirrors the finished glyph left to right.
    """

    def __init__(self, rng, frame, style, pixel, gap, is_new=None, flip=False):
        self.rng, self.f, self.style, self.pixel, self.gap = rng, frame, style, pixel, gap
        self.is_new, self.flip = is_new, flip
        self.parts, self.modules, self.groups, self.motifs = [], [], [], []

    def finished(self, parts):
        """Parts as the finished glyph draws them."""
        return [affinity.scale(p, xfact=-1, yfact=1, origin=(50, 50)) for p in parts] if self.flip else list(parts)

    @property
    def ink(self) -> float:
        return sum(part.area for part in self.parts)

    def fits(self, shape):
        f = self.f
        x0, y0, x1, y1 = shape.bounds
        return (x0 >= f["L"] - 0.5 and y0 >= f["T"] - 0.5 and x1 <= f["R"] + 0.5 and y1 <= f["B"] + 0.5
                and all(shape.distance(part) >= self.gap - 0.01 for part in self.parts))

    def _draw_once(self, motif, region):
        """Draw ``motif`` in ``region`` with a random turn, mirror and lean."""
        rng, f = self.rng, self.f
        x0, y0, x1, y1 = region
        lean_angle = rng.choice((-1, 1)) * rng.uniform(7, 18) if rng.random() < LEAN_SHARE else 0.0
        slope_angle = rng.choice((-1, 1)) * rng.uniform(5, 12) if not lean_angle and rng.random() < SLOPE_SHARE else 0.0
        # Leave room for the lean, so the leaned module still fills its region.
        shrink_x = abs(math.tan(math.radians(lean_angle))) * (y1 - y0)
        shrink_y = abs(math.tan(math.radians(slope_angle))) * (x1 - x0)
        ax0, ax1 = x0 + shrink_x / 2, x1 - shrink_x / 2
        ay0, ay1 = y0 + shrink_y / 2, y1 - shrink_y / 2
        w, h = ax1 - ax0, ay1 - ay0
        if w < 12 or h < 12:
            return None
        turn = rng.choice((0, 90, 180, 270))
        for _ in range(2):
            if turn in (90, 270):
                lw, lh, a, b = h, w, f["H"], f["W"]
            else:
                lw, lh, a, b = w, h, f["W"], f["H"]
            parts = motif(rng, 0.0, 0.0, lw, lh, a, b, self.style)
            if parts:
                break
            turn = (turn + 90) % 360
        if not parts:
            return None
        parts = [p for p in parts if p is not None]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        out = []
        for part in parts:
            part = affinity.rotate(part, turn, origin=(lw / 2, lh / 2))
            out.append(affinity.translate(part, cx - lw / 2, cy - lh / 2))
        if rng.random() < 0.5:
            out = [affinity.scale(p, -1, 1, origin=(cx, cy)) for p in out]
        if lean_angle:
            out = [affinity.skew(p, xs=lean_angle, origin=(cx, cy)) for p in out]
        if slope_angle:
            out = [affinity.skew(p, ys=slope_angle, origin=(cx, cy)) for p in out]
        if self.pixel and motif in (m_bowl, m_crescent, m_hook, m_shoulder, m_crook, m_scurve, m_sweep, m_ring):
            cell = min(f["W"], f["H"]) * rng.uniform(0.42, 0.55)
            out = [pixelate(p, cell) for p in out]
        return out

    def draw(self, table, region, *, fill=(0.0, 0.0), long=0.0, ink=0.0, anchor=(), budget=4, tries=10):
        """Draw a module from ``table`` into ``region``; keep it only if its parts keep their gaps.

        ``fill`` is the share of the region's width and height the module must
        span; a module that spans that much is stretched by up to STRETCH to span
        all of it. ``long`` is the length one of its parts must reach, and ``ink``
        the area its parts must cover. ``anchor`` names the region sides the
        module is pushed against.
        """
        x0, y0, x1, y1 = region
        if x1 - x0 < 12 or y1 - y0 < 12:
            return False
        room = min(budget, 4 - len(self.parts))
        for _ in range(tries):
            motif = pick(self.rng, table)
            parts = self._draw_once(motif, region)
            if not parts:
                continue
            parts = [q.buffer(0) for p in parts for q in polygons(p.buffer(0))]
            parts = [p for p in parts if p.area > 30]
            if not parts or len(parts) > room:
                continue
            if len(parts) < room and self.rng.random() < 0.16:
                parts = interrupt(self.rng, parts, self.gap) or parts
            parts = fit_group(parts, *region)
            if not parts:
                continue
            bounds = [p.bounds for p in parts]
            bx0, by0 = min(b[0] for b in bounds), min(b[1] for b in bounds)
            bx1, by1 = max(b[2] for b in bounds), max(b[3] for b in bounds)
            if bx1 - bx0 < fill[0] * (x1 - x0) or by1 - by0 < fill[1] * (y1 - y0):
                continue
            if long and max(max(b[2] - b[0], b[3] - b[1]) for b in bounds) < long / STRETCH:
                continue
            sx = min((x1 - x0) / (bx1 - bx0), STRETCH) if fill[0] else 1.0
            sy = min((y1 - y0) / (by1 - by0), STRETCH) if fill[1] else 1.0
            if sx > 1.0 or sy > 1.0:
                parts = [affinity.scale(p, sx, sy, origin=(bx0, by0)) for p in parts]
                bx1, by1 = bx0 + (bx1 - bx0) * sx, by0 + (by1 - by0) * sy
            dx = (x0 - bx0 if "left" in anchor else 0.0) + (x1 - bx1 if "right" in anchor else 0.0)
            dy = (y0 - by0 if "top" in anchor else 0.0) + (y1 - by1 if "bottom" in anchor else 0.0)
            if dx or dy:
                parts = [affinity.translate(p, dx, dy) for p in parts]
            area = sum(p.area for p in parts)
            if self.ink + area > INK[1] or area < ink:
                continue
            if not all(self.fits(p) for p in parts):
                continue
            if self.is_new is not None and not self.is_new(self.finished(parts)):
                continue
            name = motif.__name__[2:]
            self.parts += parts
            self.modules += [name] * len(parts)
            self.groups += [len(self.motifs)] * len(parts)
            self.motifs.append(name)
            return True
        return False

    def split(self) -> bool:
        """Break the largest part with a straight gap, as the catalog's split glyphs are broken."""
        if not self.parts or len(self.parts) >= 4:
            return False
        k = max(range(len(self.parts)), key=lambda i: self.parts[i].area)
        pieces = interrupt(self.rng, [self.parts[k]], self.gap)
        if pieces is None:
            return False
        self.parts[k:k + 1] = pieces
        self.modules[k:k + 1] = [self.modules[k]] * len(pieces)
        self.groups[k:k + 1] = [self.groups[k]] * len(pieces)
        return True

    def add_mark(self, tries=6):
        """Add a small mark where the parts leave room, as the catalog's floating bars and squares do."""
        f = self.f
        # Points where a mark at least 16 units across can sit, clear of every part by the gap.
        xs = [self.rng.uniform(f["L"] + 8, f["R"] - 8) for _ in range(tries * 4)]
        ys = [self.rng.uniform(f["T"] + 8, f["B"] - 8) for _ in range(tries * 4)]
        if self.parts:
            clear = shapely.distance(union_all(self.parts), shapely.points(xs, ys)) >= self.gap + 8
            points = [(x, y) for x, y, ok in zip(xs, ys, clear) if ok]
        else:
            points = list(zip(xs, ys))
        for x, y in points:
            w, h = self.rng.uniform(18, 34), self.rng.uniform(18, 34)
            region = (max(f["L"], x - w / 2), max(f["T"], y - h / 2), min(f["R"], x + w / 2), min(f["B"], y + h / 2))
            if self.draw(MARKS, region, budget=1, tries=2):
                return True
            tries -= 1
            if tries <= 0:
                break
        return False


def _frame(rng):
    return {"W": snap(rng.uniform(*STEM)), "H": snap(rng.uniform(*BAR)),
            "L": snap(rng.uniform(13, 18)), "R": snap(rng.uniform(82, 87)),
            "T": snap(rng.uniform(13, 16)), "B": snap(rng.uniform(84, 89))}


def _style(rng, W):
    kind = pick(rng, CORNERS)
    size = {"square": 0.0, "chamfer": rng.uniform(0.35, 0.62), "round": rng.uniform(0.5, 0.88),
            "step": rng.uniform(0.38, 0.52)}[kind] * W
    return kind, size


def _split(a, b, gap, share):
    cut = a + (b - a) * share
    return (a, cut - gap / 2), (cut + gap / 2, b)


# A glyph's main module carries a stroke at least this long (half the catalog's glyphs have one of 68).
LONG = 36.0
# Attempts for a glyph's main module, whose shapes are the most often refused as repeats.
MAIN_TRIES = 24
# Ink a mark typically adds, which a glyph's second half may leave for one.
MARK_INK = 250.0
# Two halves side by side or stacked, as most catalog glyphs are; one module across the whole
# glyph, where the widest modules fit; or a main half beside two quarters.
LAYOUTS = (("columns", 28), ("tiers", 26), ("whole", 22), ("columns+split", 13), ("tiers+split", 11))


@dataclass(frozen=True)
class Design:
    """One drawn glyph: its finished parts, the module and module draw each came from, and its layout."""

    parts: tuple
    modules: tuple[str, ...]
    groups: tuple[int, ...]
    layout: str

    @property
    def record(self) -> dict:
        """How the glyph was made, as the archive's manifest records it."""
        return {"grammar": GRAMMAR, "layout": self.layout, "modules": list(self.modules)}


GRAMMAR = "shapes-1"


def construct(rng: random.Random, *, is_new=None) -> Design:
    """Draw one new glyph; ``is_new`` is passed to the builder (see Builder)."""
    f = _frame(rng)
    gap = rng.uniform(*GAP)
    g = Builder(rng, f, _style(rng, f["W"]), rng.random() < PIXEL_SHARE, gap, is_new, flip=rng.random() < 0.5)
    L, T, R, B = f["L"], f["T"], f["R"], f["B"]
    layout = pick(rng, LAYOUTS)
    if layout in ("columns", "tiers"):
        first = rng.random() < 0.5
        share = rng.uniform(0.52, 0.66) if first else rng.uniform(0.34, 0.48)
        if layout == "columns":
            (a, b), (c, d) = _split(L, R, gap, share)
            halves = [((a, T, b, B), ("left",)), ((c, T, d, B), ("right",))]
        else:
            (a, b), (c, d) = _split(T, B, gap, share)
            halves = [((L, a, R, b), ("top",)), ((L, c, R, d), ("bottom",))]
        if not first:
            halves.reverse()
        g.draw(MODULES, halves[0][0], fill=(0.0, 0.9) if layout == "columns" else (0.9, 0.0), long=LONG,
               anchor=halves[0][1], budget=2, tries=MAIN_TRIES)
        # The second half carries enough ink, with room for a mark, to reach the catalog's floor.
        need = max(0.0, INK[0] - g.ink - MARK_INK)
        if not g.draw(MODULES, halves[1][0], ink=need, anchor=halves[1][1], budget=2):
            g.draw(SMALL, halves[1][0], anchor=halves[1][1], budget=2, tries=6)
    elif layout == "whole":
        g.draw(WHOLE, (L, T, R, B), fill=(0.9, 0.9), long=LONG, budget=3, tries=MAIN_TRIES)
        if len(g.parts) < 2 or (len(g.parts) < 4 and rng.random() < 0.35):
            g.add_mark()
        if len(g.parts) == 1:
            g.split()
    else:
        if layout == "columns+split":
            if rng.random() < 0.5:
                (a, b), (c, d) = _split(L, R, gap, rng.uniform(0.5, 0.64))
                big, rest = ((a, T, b, B), ("left",)), (c, d)
            else:
                (a, b), (c, d) = _split(L, R, gap, rng.uniform(0.36, 0.5))
                big, rest = ((c, T, d, B), ("right",)), (a, b)
            (p, q), (r, s) = _split(T, B, gap, rng.uniform(0.38, 0.62))
            small = [((rest[0], p, rest[1], q), ("top",)), ((rest[0], r, rest[1], s), ("bottom",))]
        else:
            if rng.random() < 0.5:
                (a, b), (c, d) = _split(T, B, gap, rng.uniform(0.5, 0.64))
                big, rest = ((L, a, R, b), ("top",)), (c, d)
            else:
                (a, b), (c, d) = _split(T, B, gap, rng.uniform(0.36, 0.5))
                big, rest = ((L, c, R, d), ("bottom",)), (a, b)
            (p, q), (r, s) = _split(L, R, gap, rng.uniform(0.38, 0.62))
            small = [((p, rest[0], q, rest[1]), ("left",)), ((r, rest[0], s, rest[1]), ("right",))]
        g.draw(MODULES, big[0], fill=(0.0, 0.9) if layout == "columns+split" else (0.9, 0.0), long=LONG,
               anchor=big[1], budget=2, tries=MAIN_TRIES)
        for k, (region, anchor) in enumerate(small):
            need = max(0.0, INK[0] - g.ink - MARK_INK) / (2 - k)
            g.draw(SMALL, region, ink=need, anchor=anchor, budget=1)
    for _ in range(2):
        if g.ink >= INK[0] or len(g.parts) >= 4 or not g.add_mark():
            break
    kept = [(part, name, group) for part, name, group in zip(g.parts, g.modules, g.groups) if not part.is_empty]
    return Design(parts=tuple(g.finished(part for part, _, _ in kept)), modules=tuple(name for _, name, _ in kept),
                  groups=tuple(group for _, _, group in kept), layout=layout)


def composition_problem(parts) -> str | None:
    """Catalog composition rules: one to four parts, a stroke of some length, few tiny marks.

    Every catalog glyph has one to four parts, 95% have a part at least 31 units
    long, and 98% have at most one part under 260 square units.
    """
    if not 1 <= len(parts) <= 4:
        return "part count"
    spans = [max(x1 - x0, y1 - y0) for x0, y0, x1, y1 in (part.bounds for part in parts)]
    if max(spans) < 31:
        return "no long stroke"
    if sum(part.area < 260 for part in parts) > 1:
        return "fragmented"
    return None


# The approved catalog's glyph box and ink, measured from catalog/: every glyph lies
# within x 13-89 and y 13-91, 95% are at least 62 units wide and 68 tall, and the
# 5th to 95th percentile of ink coverage is 0.172 to 0.239.
BOX = (13.0, 13.0, 89.0, 91.0)
MIN_SIZE = (62.0, 68.0)
CATALOG_INK = (0.172, 0.239)


def envelope_problem(parts) -> str | None:
    """Why a glyph falls outside the catalog's box, size or ink, or None."""
    bounds = [part.bounds for part in parts]
    x0, y0 = min(b[0] for b in bounds), min(b[1] for b in bounds)
    x1, y1 = max(b[2] for b in bounds), max(b[3] for b in bounds)
    if x0 < BOX[0] or y0 < BOX[1] or x1 > BOX[2] or y1 > BOX[3]:
        return "bounds"
    if x1 - x0 < MIN_SIZE[0] or y1 - y0 < MIN_SIZE[1]:
        return "size"
    if not CATALOG_INK[0] <= sum(part.area for part in parts) / 10000 <= CATALOG_INK[1]:
        return "coverage"
    return None


def design(rng: random.Random, *, is_new=None, attempts: int = 48) -> Design | None:
    """Draw glyphs until one keeps the catalog's composition, box and ink; None if none does.

    A glyph of one part is redrawn too: a single module alone tends to read as a
    letter, and the approved glyphs are nearly all composed of two or more.
    """
    for _ in range(attempts):
        drawn = construct(rng, is_new=is_new)
        if (len(drawn.parts) >= 2 and not composition_problem(drawn.parts)
                and not envelope_problem(drawn.parts)):
            return drawn
    return None
