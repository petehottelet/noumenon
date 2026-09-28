"""Glyph design specs on the approved Noumenon grid, and the local lane's sampler.

Every composed glyph in the approved catalog splits into two halves, side by
side ("columns") or stacked ("tiers"), separated by a 12-unit gap. Each half is
a coarse grid of about 14-unit cells: 5 cells along the strokes' long axis and
2 across. A design fills cells, may round the outer corner of a cell where a
stroke turns (bowls and shoulders; stroke ends stay straight-cut), and may lean
one straight stem across its half.

A spec is plain JSON, so the model lane can write specs too:

    {"layout": "columns",
     "halves": [{"cells": ["##", "#.", "#.", "#.", "##"], "round": ["0,0,tl"], "lean": null},
                {"cells": ["..", "#.", "#.", "#.", ".."], "round": [], "lean": "right"}]}

``cells`` lists the 5 rows along the long axis (top to bottom for columns, left
to right for tiers); each row has 2 characters across the half. ``round`` names
cells "row,column,corner" with corner tl, tr, br or bl. ``lean`` shears the
half's single straight stem "left" or "right" by one cell.
"""

from __future__ import annotations

import json
import random

LAYOUTS = ("columns", "tiers")
LONG, ACROSS = 5, 2
CORNERS = ("tl", "tr", "br", "bl")
LEANS = (None, "left", "right")

# Half-cell motifs drawn from the approved vocabulary: stems, feet and heads,
# hooks, crescents, shelves, paired and interrupted marks, blocks and steps.
MOTIFS = (
    ("#.", "#.", "#.", "#.", "#."),      # stem
    ("#.", "#.", "#.", "#.", "##"),      # stem with foot
    ("##", "#.", "#.", "#.", "#."),      # stem with head
    ("##", "#.", "#.", "#.", "##"),      # crescent
    (".#", ".#", ".#", ".#", "##"),      # hook
    ("##", ".#", "..", "..", ".."),      # roof shoulder
    ("##", "..", "..", "..", ".."),      # shelf
    ("#.", "..", "#.", "..", "#."),      # three marks
    ("##", "##", "..", "#.", "#."),      # block over short stem
    ("..", "##", ".#", "..", ".."),      # short elbow mark
    ("#.", "#.", "..", "#.", "#."),      # interrupted stem
    ("..", "##", "##", "..", ".."),      # heavy block
    ("##", "#.", "..", ".#", "##"),      # double corner
    ("#.", "#.", "##", ".#", ".#"),      # stepped diagonal
    ("##", ".#", ".#", ".#", ".."),      # pillar with cap
    ("..", "..", "..", "##", "#."),      # low sweep
    ("##", "..", "##", "..", ".."),      # bar pair
    ("..", "#.", "#.", "#.", ".."),      # short post
    ("#.", "#.", "#.", "..", "##"),      # stem over detached foot
    ("..", "#.", "##", "#.", ".."),      # side tab
)


def _flip_across(rows):
    return tuple(row[::-1] for row in rows)


def _flip_along(rows):
    return tuple(reversed(rows))


def filled(rows) -> set[tuple[int, int]]:
    return {(r, c) for r, row in enumerate(rows) for c, ch in enumerate(row) if ch == "#"}


def components(cells: set[tuple[int, int]]) -> list[set[tuple[int, int]]]:
    seen, groups = set(), []
    for start in sorted(cells):
        if start in seen:
            continue
        group, stack = set(), [start]
        while stack:
            cell = stack.pop()
            if cell in seen:
                continue
            seen.add(cell)
            group.add(cell)
            r, c = cell
            stack.extend(n for n in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)) if n in cells)
        groups.append(group)
    return groups


def eligible_corners(cells: set[tuple[int, int]]) -> list[tuple[int, int, str]]:
    """Outer corners where a stroke turns: both sides of the corner are open, both
    opposite sides continue, and the cell inside the turn is empty. Rounding then
    makes a bowl or shoulder of even width, never a cap or a rounded block."""
    out = []
    for r, c in sorted(cells):
        up, down, left, right = (r - 1, c) in cells, (r + 1, c) in cells, (r, c - 1) in cells, (r, c + 1) in cells
        for corner, open_sides, held, inside in (("tl", (not up, not left), (down, right), (r + 1, c + 1)),
                                                 ("tr", (not up, not right), (down, left), (r + 1, c - 1)),
                                                 ("br", (not down, not right), (up, left), (r - 1, c - 1)),
                                                 ("bl", (not down, not left), (up, right), (r - 1, c + 1))):
            if all(open_sides) and all(held) and inside not in cells:
                out.append((r, c, corner))
    return out


def lean_stem(cells: set[tuple[int, int]]):
    """The single straight stem a half may lean: one column holding one run of at
    least three cells, with the other column empty along that run."""
    if len(components(cells)) != 1:
        return None
    columns = {c for _, c in cells}
    if len(columns) != 1:
        return None
    column = next(iter(columns))
    rows = sorted(r for r, _ in cells)
    if len(rows) < 3 or rows != list(range(rows[0], rows[-1] + 1)):
        return None
    return column, rows[0], rows[-1]


def check_half(half: dict) -> set[tuple[int, int]]:
    rows = half.get("cells")
    if not isinstance(rows, list) or len(rows) != LONG or any(not isinstance(row, str) or len(row) != ACROSS or set(row) - {"#", "."} for row in rows):
        raise ValueError(f"each half needs {LONG} rows of {ACROSS} characters, '#' or '.'")
    cells = filled(rows)
    if len(cells) < 2:
        raise ValueError("each half needs at least two filled cells")
    for r, c in cells:
        for dr, dc in ((1, 1), (1, -1)):
            if (r + dr, c + dc) in cells and (r + dr, c) not in cells and (r, c + dc) not in cells:
                raise ValueError("cells may not touch only at a corner")
    allowed = set(eligible_corners(cells))
    for item in half.get("round") or []:
        try:
            r, c, corner = item.split(",")
            key = (int(r), int(c), corner.strip())
        except (AttributeError, ValueError):
            raise ValueError("round entries look like 'row,column,corner'") from None
        if key not in allowed:
            raise ValueError(f"corner {item} is not a turn; only bowls and shoulders may be rounded")
    lean = half.get("lean")
    if lean not in LEANS:
        raise ValueError("lean must be null, 'left' or 'right'")
    if lean is not None:
        stem = lean_stem(cells)
        if stem is None:
            raise ValueError("only a half holding one straight stem of three or more cells may lean")
        column = stem[0]
        if (lean == "right" and column == ACROSS - 1) or (lean == "left" and column == 0):
            raise ValueError("a stem leans into the empty column, not out of its half")
    return cells


def check_spec(spec: dict) -> dict:
    """Validate a spec's structure and grammar; return it normalized."""
    if not isinstance(spec, dict) or spec.get("layout") not in LAYOUTS:
        raise ValueError(f"layout must be one of {LAYOUTS}")
    halves = spec.get("halves")
    if not isinstance(halves, list) or len(halves) != 2:
        raise ValueError("a glyph has exactly two halves")
    total = sum(len(check_half(half)) for half in halves)
    if not 5 <= total <= 13:
        raise ValueError("a glyph fills between 5 and 13 cells")
    return {"layout": spec["layout"],
            "halves": [{"cells": list(h["cells"]), "round": sorted(h.get("round") or []), "lean": h.get("lean")} for h in halves]}


def spec_key(spec: dict) -> str:
    return json.dumps(check_spec(spec), sort_keys=True, separators=(",", ":"))


def sample_half(rng: random.Random) -> dict:
    # Fuller motifs are likelier, as the approved glyphs favor long strokes over lone marks.
    rows = rng.choices(MOTIFS, weights=[len(filled(m)) ** 2 for m in MOTIFS])[0]
    if rng.random() < .5:
        rows = _flip_across(rows)
    if rng.random() < .5:
        rows = _flip_along(rows)
    rows = list(rows)
    # Grow or trim one cell at the motif's edge for variety, when the grammar allows it.
    if rng.random() < .35:
        r, c = rng.randrange(LONG), rng.randrange(ACROSS)
        trial = [list(row) for row in rows]
        trial[r][c] = "." if trial[r][c] == "#" else "#"
        trial = ["".join(row) for row in trial]
        try:
            check_half({"cells": trial})
            rows = trial
        except ValueError:
            pass
    cells = filled(rows)
    corners = eligible_corners(cells)
    rng.shuffle(corners)
    rounded = [f"{r},{c},{corner}" for r, c, corner in corners[:rng.choice((0, 0, 1, 1, 2))]]
    lean = None
    stem = lean_stem(cells)
    if stem is not None and rng.random() < .45:
        lean = "right" if stem[0] == 0 else "left"
    return {"cells": rows, "round": rounded, "lean": lean}


def sample_spec(seed: int) -> dict:
    """A deterministic design for one seed; callers retry with later seeds on rejection."""
    rng = random.Random(seed)
    for _ in range(64):
        spec = {"layout": rng.choice(LAYOUTS), "halves": [sample_half(rng), sample_half(rng)]}
        try:
            return check_spec(spec)
        except ValueError:
            continue
    raise ValueError(f"seed {seed} produced no valid design")
