"""Style gates for live glyphs: the checks the approved catalog passed.

A glyph passes when its pieces and counters are large enough, its pieces stay
apart, its ink coverage sits in the catalog's range, its piece and hole counts
hold from 16 to 128 px and across ink thresholds, and its silhouette is not a
near match (IoU 0.85, allowing 2 px shifts and mirror images) of an approved
glyph, of a glyph accepted earlier in the session, or of a letter, numeral or
common symbol when a bold system font is available to draw them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage
from shapely.geometry import Polygon

from svg_raster import render_svg

ROOT = Path(__file__).resolve().parents[1]
MIN_PIECE, MIN_COUNTER, MIN_SPACING = 195.0, 150.0, 8.0
# The approved catalog's 5th-95th percentile ink is 0.173-0.241, with at most four pieces.
INK_RANGE = (0.165, 0.25)
MAX_PIECES, SMALL_PIECE, MAX_SMALL = 4, 300.0, 1
NEAR_MATCH = 0.85
LETTER_MATCH = 0.80
SMALL_SIZES = (16, 32, 64)
SIDE = 64
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789=+-<>/\\|#%&[](){}!?:;"
FONT_CANDIDATES = (
    "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/verdanab.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
)
EIGHT = np.ones((3, 3), bool)


@dataclass
class Report:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    silhouette: np.ndarray | None = None


def ink_mask(svg: str, size: int, threshold: int = 128) -> np.ndarray:
    return np.asarray(render_svg(svg, size).convert("L")) < threshold


def topology(mask: np.ndarray) -> tuple[int, int]:
    """Ink pieces (8-connected) and enclosed holes (4-connected background)."""
    pieces = ndimage.label(mask, structure=EIGHT)[1]
    background, count = ndimage.label(~mask)
    border = set(np.unique(np.concatenate([background[0], background[-1], background[:, 0], background[:, -1]])))
    holes = len(set(range(1, count + 1)) - border)
    return pieces, holes


def silhouette(mask: np.ndarray) -> np.ndarray:
    """Crop to the ink, scale the longer side to 64 px and centre it."""
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return np.zeros((SIDE, SIDE), bool)
    crop = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = crop.shape
    scale = SIDE / max(h, w)
    size = (max(1, round(w * scale)), max(1, round(h * scale)))
    image = Image.fromarray((crop * 255).astype(np.uint8)).resize(size, Image.Resampling.BILINEAR)
    out = np.zeros((SIDE, SIDE), bool)
    x, y = (SIDE - size[0]) // 2, (SIDE - size[1]) // 2
    out[y:y + size[1], x:x + size[0]] = np.asarray(image) >= 128
    return out


def _variants(mask: np.ndarray) -> np.ndarray:
    """The silhouette, mirrored, flipped and both, each shifted up to 2 px."""
    out = []
    for oriented in (mask, mask[:, ::-1], mask[::-1], mask[::-1, ::-1]):
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                out.append(np.roll(np.roll(oriented, dy, 0), dx, 1))
    return np.stack(out)


def best_iou(mask: np.ndarray, references: np.ndarray) -> tuple[float, int]:
    """Highest IoU of the mask's variants against each reference; returns (iou, index)."""
    if not len(references):
        return 0.0, -1
    variants = _variants(mask).reshape(100, -1).astype(np.float32)
    refs = references.reshape(len(references), -1).astype(np.float32)
    inter = variants @ refs.T
    union = variants.sum(1)[:, None] + refs.sum(1)[None, :] - inter
    scores = (inter / np.maximum(union, 1)).max(0)
    index = int(scores.argmax())
    return float(scores[index]), index


def _coarse(mask: np.ndarray) -> np.ndarray:
    """A 16 x 16 signature for a quick first pass before the exact comparison."""
    return (mask.reshape(16, 4, 16, 4).mean(axis=(1, 3)) >= .5).ravel()


def _coarse_overlap(shape: np.ndarray, coarse_refs: np.ndarray) -> np.ndarray:
    probes = np.stack([_coarse(v) for v in (shape, shape[:, ::-1], shape[::-1], shape[::-1, ::-1])])
    inter = (probes[:, None] & coarse_refs[None]).sum(2)
    union = np.maximum((probes[:, None] | coarse_refs[None]).sum(2), 1)
    return (inter / union).max(0)


def _letter_silhouettes() -> tuple[np.ndarray, str] | tuple[None, None]:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).is_file():
            font = ImageFont.truetype(candidate, 200)
            masks = []
            for char in LETTERS:
                image = Image.new("L", (320, 320), 0)
                ImageDraw.Draw(image).text((160, 160), char, font=font, fill=255, anchor="mm")
                masks.append(silhouette(np.asarray(image) >= 128))
            return np.stack(masks), Path(candidate).name
    return None, None


class StyleGate:
    """Judge compiled glyphs and remember the accepted ones for this session."""

    def __init__(self, catalog: Path = ROOT / "catalog", *, letters: bool = True, memory: int = 1024):
        svgs = sorted(catalog.glob("GLYPH-*.svg"))
        self.catalog_ids = [path.stem for path in svgs]
        self.catalog = np.stack([silhouette(ink_mask(path.read_text(encoding="utf-8"), 128)) for path in svgs]) if svgs \
            else np.zeros((0, SIDE, SIDE), bool)
        self.letters, self.letter_font = _letter_silhouettes() if letters else (None, None)
        self.catalog_coarse = np.stack([_coarse(m) for m in self.catalog]) if len(self.catalog) else np.zeros((0, 256), bool)
        self.memory = memory
        self.session: list[np.ndarray] = []
        self.session_coarse: list[np.ndarray] = []
        self.session_ids: list[str] = []

    def _references(self):
        refs, coarse, ids = [self.catalog], [self.catalog_coarse], list(self.catalog_ids)
        if self.session:
            refs.append(np.stack(self.session))
            coarse.append(np.stack(self.session_coarse))
            ids += self.session_ids
        return np.concatenate(refs), np.concatenate(coarse), ids

    def check(self, glyph) -> Report:
        reasons, metrics = [], {}
        polygons = glyph.polygons
        if not polygons or any(not p.is_valid for p in polygons):
            return Report(False, ["invalid geometry"])
        areas = [p.area for p in polygons]
        holes = [Polygon(i).area for p in polygons for i in p.interiors]
        metrics.update(pieces=len(polygons), counters=len(holes), ink=round(sum(areas) / 10000, 4))
        if min(areas) < MIN_PIECE:
            reasons.append(f"a piece is smaller than {MIN_PIECE:g} square units")
        if len(polygons) > MAX_PIECES:
            reasons.append(f"more than {MAX_PIECES} pieces")
        if sum(a < SMALL_PIECE for a in areas) > MAX_SMALL:
            reasons.append("more than one small mark")
        if holes and min(holes) < MIN_COUNTER:
            reasons.append(f"a counter is smaller than {MIN_COUNTER:g} square units")
        if not INK_RANGE[0] <= metrics["ink"] <= INK_RANGE[1]:
            reasons.append("ink coverage is outside the catalog's range")
        spacing = min((a.distance(b) for i, a in enumerate(polygons) for b in polygons[i + 1:]), default=None)
        if spacing is not None:
            metrics["spacing"] = round(spacing, 2)
            if spacing < MIN_SPACING:
                reasons.append(f"pieces sit closer than {MIN_SPACING:g} units")
        try:
            full = ink_mask(glyph.svg, 128)
        except ValueError as error:
            return Report(False, reasons + [f"format: {error}"], metrics)
        counts = topology(full)
        metrics["topology"] = list(counts)
        if topology(ink_mask(glyph.svg, 128, 96)) != counts or topology(ink_mask(glyph.svg, 128, 160)) != counts:
            reasons.append("pieces or holes change with the ink threshold")
        for size in SMALL_SIZES:
            if topology(ink_mask(glyph.svg, size)) != counts:
                reasons.append(f"pieces or holes change at {size} px")
                break
        shape = silhouette(full)
        refs, coarse, ids = self._references()
        if len(refs):
            close = np.nonzero(_coarse_overlap(shape, coarse) >= .5)[0]
            iou, index = best_iou(shape, refs[close]) if len(close) else (0.0, -1)
            metrics["nearest"] = {"iou": round(iou, 4), "glyph": ids[close[index]] if index >= 0 else None}
            if iou >= NEAR_MATCH:
                reasons.append(f"near match of {ids[close[index]]} (IoU {iou:.2f})")
        if self.letters is not None:
            iou, index = best_iou(shape, self.letters)
            metrics["letter"] = {"iou": round(iou, 4), "char": LETTERS[index], "font": self.letter_font}
            if iou >= LETTER_MATCH:
                reasons.append(f"reads like '{LETTERS[index]}' (IoU {iou:.2f})")
        return Report(not reasons, reasons, metrics, shape)

    def remember(self, glyph_id: str, report: Report) -> None:
        """Hold an accepted glyph's silhouette so later glyphs must differ from it."""
        self.session.append(report.silhouette)
        self.session_coarse.append(_coarse(report.silhouette))
        self.session_ids.append(glyph_id)
        if len(self.session) > self.memory:
            del self.session[0], self.session_coarse[0], self.session_ids[0]
