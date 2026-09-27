"""Derive the Yautja glyph face's distance-field atlas from its polygon source.

Build: python export_face_sdf.py
Check that the committed atlas still matches its source: add --check.

The source is the default HUD glyph set of the Yautja project, vendored byte
for byte in face-sources/yautja/glyphs.json. The code rain there draws the 52
letter glyphs; this face uses the same 52. Each glyph is a set of angled bars:
lit bars are filled polygons and unlit bars are hairline rings that vanish at
rain sizes, so the atlas keeps the lit bars only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import distance_transform_edt


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "face-sources" / "yautja" / "glyphs.json"
OUTPUT = ROOT / "svg-preview" / "faces"
VERSION = "yautja-face-sdf-v1"
COUNT, COLUMNS, ROWS, CELL, RANGE, SUPERSAMPLE = 52, 13, 4, 128, 16, 8
# Each glyph's full bar frame, lit and unlit, is fitted into this box and centred,
# as the Yautja renderer fits its 0.85:1 cell, so lit bars keep their places.
FIT_HEIGHT, FIT_ASPECT = 110, .85
LIT_POINTS = range(4, 10)
UPSTREAM = {
    "repository": "https://github.com/petehottelet/yautja",
    "commit": "901f46c7438fba941775c584ffccd3d9a0f8ac08",
    "path": "src/yautja/assets/glyphs.json",
    "license": "MIT; code and original glyph artwork, Copyright (c) 2026 Pete Hottelet",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_glyphs(source: Path = SOURCE) -> list[dict]:
    """Return the letter glyphs in the Yautja rain's order, A-Z then a-z."""
    glyphs = json.loads(source.read_text(encoding="utf-8"))
    letters = [glyph for glyph in glyphs if glyph["character"].isascii() and glyph["character"].isalpha()]
    order = [chr(code) for code in [*range(65, 91), *range(97, 123)]]
    if [glyph["character"] for glyph in letters] != order:
        raise ValueError("expected the 52 Yautja letter glyphs in A-Z, a-z order")
    for glyph in letters:
        contours = glyph["contours"]
        if not contours or any(len(contour) < 4 or contour[0] != contour[-1] for contour in contours):
            raise ValueError(f"expected closed polygon contours for {glyph['character']}")
        if not any(len(contour) in LIT_POINTS for contour in contours):
            raise ValueError(f"glyph {glyph['character']} has no lit bars")
    return letters


def lit_bars(glyph: dict) -> list[list[list[float]]]:
    """Filled bars are single closed polygons; unlit bars trace an outer and inner ring."""
    return [contour[:-1] for contour in glyph["contours"] if len(contour) in LIT_POINTS]


def placement(glyph: dict) -> tuple[float, float, float]:
    points = np.array([point for contour in glyph["contours"] for point in contour], dtype=float)
    (left, bottom), (right, top) = points.min(axis=0), points.max(axis=0)
    scale = min(FIT_HEIGHT * FIT_ASPECT / (right - left), FIT_HEIGHT / (top - bottom))
    return scale, (left + right) / 2, (bottom + top) / 2


def glyph_mask(glyph: dict, size: int) -> np.ndarray:
    """Rasterize the lit bars into a size x size cell; y points down."""
    scale, middle_x, middle_y = placement(glyph)
    factor = size / CELL
    image = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(image)
    for bar in lit_bars(glyph):
        draw.polygon([((CELL / 2 + (x - middle_x) * scale) * factor,
                       (CELL / 2 - (y - middle_y) * scale) * factor) for x, y in bar], fill=255)
    return np.asarray(image) > 127


def blocks(values: np.ndarray) -> np.ndarray:
    """Average each supersampled block into one cell pixel."""
    return values.reshape(CELL, SUPERSAMPLE, CELL, SUPERSAMPLE).mean(axis=(1, 3))


def coverage_mask(glyph: dict) -> np.ndarray:
    """Cell pixels at least half covered by lit bars, the reference for fidelity."""
    return blocks(glyph_mask(glyph, CELL * SUPERSAMPLE).astype(float)) >= .5


def distance_tile(glyph: dict) -> np.ndarray:
    """Signed distance in atlas pixels, sampled at each cell pixel's centre."""
    inside = glyph_mask(glyph, CELL * SUPERSAMPLE)
    if not inside.any():
        raise ValueError(f"glyph {glyph['character']} rasterized empty")
    signed = np.where(inside, distance_transform_edt(inside) - .5,
                      .5 - distance_transform_edt(~inside)) / SUPERSAMPLE
    # A signed distance is linear across an edge, so a block mean is its centre value.
    return np.clip(np.round((.5 + blocks(signed) / RANGE) * 255), 0, 255).astype(np.uint8)


def decode_mask(tile: np.ndarray) -> np.ndarray:
    return tile > 127


def mask_iou(left: np.ndarray, right: np.ndarray) -> float:
    union = np.count_nonzero(left | right)
    return float(np.count_nonzero(left & right) / union) if union else 1.0


def render_atlas(source: Path = SOURCE) -> tuple[np.ndarray, list[dict]]:
    glyphs = load_glyphs(source)
    atlas = np.zeros((ROWS * CELL, COLUMNS * CELL), dtype=np.uint8)
    records = []
    for index, glyph in enumerate(glyphs):
        tile = distance_tile(glyph)
        column, row = index % COLUMNS, index // COLUMNS
        atlas[row * CELL:(row + 1) * CELL, column * CELL:(column + 1) * CELL] = tile
        fidelity = mask_iou(decode_mask(tile), coverage_mask(glyph))
        if fidelity < .94:
            raise ValueError(f"decoded distance field differs from {glyph['character']}: IoU={fidelity:.6f}")
        records.append({
            "character": glyph["character"],
            "cell": [column, row],
            "lit_bars": len(lit_bars(glyph)),
            "unlit_bars": len(glyph["contours"]) - len(lit_bars(glyph)),
            "source_raster_iou_at128": round(fidelity, 6),
            "ink_pixels_at128": int(decode_mask(tile).sum()),
        })
    return atlas, records


def build(source: Path = SOURCE, output: Path = OUTPUT) -> dict:
    atlas, records = render_atlas(source)
    output.mkdir(parents=True, exist_ok=True)
    target = output / "yautja-sdf.png"
    Image.fromarray(atlas, "L").convert("RGB").save(target, optimize=True)
    receipt = {
        "version": VERSION,
        "face": "yautja",
        "method": "Exact Euclidean distance transform of lit bars rasterized at 8x, averaged to each cell pixel",
        "source": {**UPSTREAM, "vendored_path": source.relative_to(ROOT).as_posix(),
                   "sha256": sha256(source.read_bytes())},
        "count": COUNT,
        "order": "row-major A-Z then a-z, the Yautja HUD rain's letter order",
        "grid": [COLUMNS, ROWS],
        "cell_pixels": [CELL, CELL],
        "texture_pixels": [COLUMNS * CELL, ROWS * CELL],
        "distance_range_pixels": RANGE,
        "distance_range_semantics": "full range 16 atlas pixels; -8 outside to +8 inside; boundary 0.5",
        "channels": "RGB with equal channels; median(r,g,b) is the signed distance",
        "fit": {"height_pixels": FIT_HEIGHT, "width_to_height": FIT_ASPECT, "centre": [CELL / 2, CELL / 2]},
        "atlas_sha256": sha256(target.read_bytes()),
        "exporter_sha256": sha256(Path(__file__).read_bytes()),
        "validation": {
            "minimum_iou_gate": .94,
            "minimum_iou": min(record["source_raster_iou_at128"] for record in records),
            "comparison": "decoded field threshold versus cell pixels at least half covered by lit bars at 8x",
        },
        "glyphs": records,
    }
    (output / "yautja-sdf.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
    return receipt


def verify(output: Path = OUTPUT, source: Path = SOURCE) -> dict:
    receipt = json.loads((output / "yautja-sdf.json").read_text(encoding="utf-8"))
    expected = {"version": VERSION, "count": COUNT, "grid": [COLUMNS, ROWS], "cell_pixels": [CELL, CELL],
                "texture_pixels": [COLUMNS * CELL, ROWS * CELL], "distance_range_pixels": RANGE}
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise ValueError("face atlas geometry or encoding contract changed")
    if receipt["source"]["sha256"] != sha256(source.read_bytes()):
        raise ValueError("Yautja glyph source changed; rebuild the face atlas")
    if receipt["exporter_sha256"] != sha256(Path(__file__).read_bytes()):
        raise ValueError("face exporter changed; rebuild the face atlas")
    texture = output / "yautja-sdf.png"
    if receipt["atlas_sha256"] != sha256(texture.read_bytes()):
        raise ValueError("face atlas image changed")
    with Image.open(texture) as image:
        if image.mode != "RGB" or image.size != (COLUMNS * CELL, ROWS * CELL):
            raise ValueError("face atlas image format mismatch")
        committed = np.asarray(image)
    if not (np.array_equal(committed[..., 0], committed[..., 1]) and np.array_equal(committed[..., 0], committed[..., 2])):
        raise ValueError("face atlas channels differ")
    rebuilt, records = render_atlas(source)
    # Rounding may differ by one level across numeric libraries; the edges may not.
    if np.abs(rebuilt.astype(int) - committed[..., 0]).max() > 1 or not np.array_equal(decode_mask(rebuilt), decode_mask(committed[..., 0])):
        raise ValueError("face atlas no longer matches its source glyphs")
    if [record["character"] for record in receipt["glyphs"]] != [record["character"] for record in records]:
        raise ValueError("face atlas glyph order changed")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="verify the committed atlas instead of building it")
    args = parser.parse_args()
    receipt = verify() if args.check else build()
    print(json.dumps({key: receipt[key] for key in ("version", "count", "texture_pixels", "validation")}, indent=2))


if __name__ == "__main__":
    main()
