"""Part shapes that must not come back across recent glyphs.

A part with a joint, a curve or a counter is a distinctive shape, and so is a
group of parts that one module drew together. A lone bar, stem or leaning
stroke is one of the script's strokes and may recur.

A shape's key is its ink on a 24 x 24 grid, after centering the shape and
scaling its longer side to 22 cells, in all eight quarter turns and mirror
images. Position, size and orientation drop out, and a turned or mirrored copy
matches exactly. A new shape repeats a remembered one when they overlap at an
intersection over union of 0.78 or more; side by side, such pairs read as the
same shape. Two curves repeat at any size. Other shapes repeat only when their
longer sides are within 1.25 times each other, since a corner of the same
proportions at a clearly different size reads as a different element.

The memory holds the distinctive shapes of the last 256 accepted glyphs, as
many as the explorer's live atlas and the savers' feed show at once, so no two
glyphs on screen share one.
"""

from __future__ import annotations

from collections import deque

import numpy as np
import shapely
from shapely import union_all

GRID = 24
SUPERSAMPLE = 2
WINDOW = 256
MAX_SIMILARITY = 0.78
SIZE_RATIO = 1.25


def _polygons(shape) -> list:
    return [shape] if shape.geom_type == "Polygon" else list(getattr(shape, "geoms", []))


def longer_side(shape) -> float:
    x0, y0, x1, y1 = shape.bounds
    return max(x1 - x0, y1 - y0, 1e-6)


def is_distinctive(shape) -> bool:
    """Whether a shape has a joint, a curve or a counter, or is a group of parts.

    Plain rectangles and four-cornered strokes (bars, stems, leans and sloping
    bars) are the script's basic strokes and are free to recur.
    """
    polygons = _polygons(shape)
    if len(polygons) != 1 or polygons[0].interiors:
        return True
    return len(polygons[0].simplify(0.4).exterior.coords) - 1 > 4


def is_curved(shape) -> bool:
    """Whether a shape, or any part of a group, follows a curve or holds a counter."""
    return any(polygon.interiors or len(polygon.simplify(0.4).exterior.coords) - 1 > 14
               for polygon in _polygons(shape))


def key(shape) -> np.ndarray:
    """A shape as GRID x GRID bits in all eight quarter turns and mirror images; row 0 is as drawn.

    A cell is inked when at least half of its SUPERSAMPLE x SUPERSAMPLE sample
    points fall inside the shape. The sample points sit symmetrically about the
    shape's center, so turning or mirroring the shape turns or mirrors its bits.
    """
    x0, y0, x1, y1 = shape.bounds
    scale = (GRID - 2) / longer_side(shape)
    offsets = ((np.arange(GRID * SUPERSAMPLE) + 0.5) / SUPERSAMPLE - GRID / 2) / scale
    xs, ys = np.meshgrid((x0 + x1) / 2 + offsets, (y0 + y1) / 2 + offsets)
    inside = shapely.contains_xy(shape, xs, ys)
    bits = inside.reshape(GRID, SUPERSAMPLE, GRID, SUPERSAMPLE).mean(axis=(1, 3)) >= 0.5
    turns = [np.rot90(bits, k) for k in range(4)] + [np.rot90(bits.T, k) for k in range(4)]
    return np.stack([np.packbits(turn).view(np.uint64) for turn in turns])


def candidates(parts, groups=()) -> list:
    """The shapes of a glyph to judge: its distinctive parts, and each group of parts drawn together."""
    shapes = [part for part in parts if is_distinctive(part)]
    members: dict = {}
    for part, group in zip(parts, groups):
        members.setdefault(group, []).append(part)
    shapes += [union_all(together) for together in members.values() if len(together) > 1]
    return shapes


class RecentParts:
    """The distinctive shapes of the most recent glyphs, with their sizes and whether they curve."""

    def __init__(self, glyphs: int = WINDOW, *, size_ratio: float = SIZE_RATIO,
                 max_similarity: float = MAX_SIMILARITY) -> None:
        if glyphs < 1 or size_ratio < 1 or not 0 < max_similarity <= 1:
            raise ValueError("the window holds at least one glyph, the size ratio is at least 1, "
                             "and the similarity limit is in (0, 1]")
        self.window, self.size_ratio, self.max_similarity = glyphs, size_ratio, max_similarity
        self._glyphs: deque = deque(maxlen=glyphs)
        self._keys = np.zeros((0, GRID * GRID // 64), np.uint64)
        self._ink = np.zeros(0, np.int64)
        self._sizes = np.zeros(0)
        self._curved = np.zeros(0, bool)

    def __len__(self) -> int:
        return len(self._keys)

    def similarity(self, turns: np.ndarray, size: float, curved: bool) -> float:
        """The best overlap with a remembered shape it could repeat: a curve of any size, or any shape of a similar size."""
        among = np.abs(np.log(self._sizes / size)) <= np.log(self.size_ratio)
        if curved:
            among |= self._curved
        keys, ink = self._keys[among], self._ink[among]
        if not len(keys):
            return 0.0
        overlap = np.bitwise_count(keys[None] & turns[:, None]).sum(axis=2)
        union = ink[None] + np.bitwise_count(turns).sum(axis=1)[:, None] - overlap
        return float((overlap / np.maximum(union, 1)).max())

    def compare(self, shapes) -> tuple[float, list]:
        """The shapes' best overlap with remembered ones, and the entries to remember if the glyph is kept."""
        best, entries = 0.0, []
        for shape in shapes:
            turns, size, curved = key(shape), longer_side(shape), is_curved(shape)
            best = max(best, self.similarity(turns, size, curved))
            entries.append((turns[0], size, curved))
        return best, entries

    def accepts(self, shapes) -> bool:
        """Whether one module's parts, singly and together, differ from every remembered shape they could repeat."""
        chosen = [shape for shape in shapes if is_distinctive(shape)]
        if len(shapes) > 1:
            chosen.append(union_all(shapes))
        return all(self.similarity(key(shape), longer_side(shape), is_curved(shape)) < self.max_similarity
                   for shape in chosen)

    def remember(self, entries: list) -> None:
        """Hold one accepted glyph's shapes; the oldest glyph's are forgotten once the window is full."""
        keys = np.stack([entry[0] for entry in entries]) if entries else self._keys[:0]
        self._glyphs.append((keys, np.asarray([entry[1] for entry in entries], float),
                             np.asarray([entry[2] for entry in entries], bool)))
        self._keys = np.concatenate([entry[0] for entry in self._glyphs])
        self._sizes = np.concatenate([entry[1] for entry in self._glyphs])
        self._curved = np.concatenate([entry[2] for entry in self._glyphs])
        self._ink = np.bitwise_count(self._keys).sum(axis=1)


__all__ = ["GRID", "WINDOW", "MAX_SIMILARITY", "SIZE_RATIO", "RecentParts", "candidates", "is_curved",
           "is_distinctive", "key", "longer_side"]
