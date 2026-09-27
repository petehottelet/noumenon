"""Derive the explorer's glyph-face distance-field atlases.

Build every face: python export_face_sdf.py --fonts DIR
Check the committed atlases: python export_face_sdf.py --check [--fonts DIR]

Faces come from two kinds of source.

- Yautja: the default HUD glyph set of the Yautja project, vendored byte for
  byte in face-sources/yautja/glyphs.json. Its code rain draws the 52 letter
  glyphs; this face uses the same 52. Each glyph is a set of angled bars: lit
  bars are filled polygons and unlit bars are hairline rings that vanish at
  rain sizes, so the atlas keeps the lit bars only.
- Google Fonts: the SIL Open Font License fonts in FONT_FACES. The font files
  are build inputs pinned by hash, not redistributed; only the derived atlases
  ship. DIR must hold the pinned files.

--check verifies every committed atlas against its receipt, and rebuilds and
compares each face whose source is available: always for Yautja, and for a
font face when --fonts holds its pinned file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import distance_transform_edt


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "face-sources" / "yautja" / "glyphs.json"
OUTPUT = ROOT / "svg-preview" / "faces"
VERSION = "face-sdf-v2"
CELL, RANGE, SUPERSAMPLE, COLUMNS = 128, 16, 8, 16
IOU_GATE = .94

# Each Yautja glyph's full bar frame, lit and unlit, is fitted into this box and
# centred, as the Yautja renderer fits its 0.85:1 cell, so lit bars keep their places.
FIT_HEIGHT, FIT_ASPECT = 110, .85
LIT_POINTS = range(4, 10)
YAUTJA = {
    "label": "Yautja", "columns": 13,
    "source": {
        "kind": "polygons",
        "repository": "https://github.com/petehottelet/yautja",
        "commit": "901f46c7438fba941775c584ffccd3d9a0f8ac08",
        "path": "src/yautja/assets/glyphs.json",
        "license": "MIT; code and original glyph artwork, Copyright (c) 2026 Pete Hottelet",
    },
}

# A font face renders every listed character with one scale, chosen so the
# union of their ink fits FONT_FIT pixels and centred, so marks keep their
# relative sizes and places. Ogham turns a quarter so its stemline runs down
# the column, reading upward as on standing stones.
FONT_FIT = 104
GOOGLE_FONTS = "https://github.com/google/fonts"
GOOGLE_FONTS_COMMIT = "23e54b51ddffbc7713c583748e3bd86f62b1fa4a"
TERMINAL = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ#$%&*+-/<=>?@|"
FONT_FACES = {
    "ogham": {"label": "Ogham", "font": "ofl/notosansogham/NotoSansOgham-Regular.ttf",
              "blob": "1067748cef2dbbd6b70d0ab64950942daae1f9c5",
              "sha256": "6a70572d381f3a54fdaa3b373b865f4d97377c65434493b294b1dfacc7c4f58c",
              "characters": [chr(code) for code in range(0x1681, 0x169B)], "quarter_turns": 1},
    "runic": {"label": "Runic", "font": "ofl/notosansrunic/NotoSansRunic-Regular.ttf",
              "blob": "57b2db815c219b0e217d592183618e2a133e0dbc",
              "sha256": "615b6c1166a8c51816dc1536784acbf486547e3bed03dbfdd70910e10066793b",
              "characters": [chr(code) for code in range(0x16A0, 0x16EB)]},
    "tifinagh": {"label": "Tifinagh", "font": "ofl/notosanstifinagh/NotoSansTifinagh-Regular.ttf",
                 "blob": "93f487c899a180e17aec835403284ee57b461b1c",
                 "sha256": "b08755bdee9835ebbca1095460e36a9e2f3ae396919fd0fa2377d9b4a3388f7e",
                 "characters": [chr(code) for code in range(0x2D30, 0x2D68)]},
    "braille": {"label": "Braille", "font": "ofl/notosanssymbols2/NotoSansSymbols2-Regular.ttf",
                "blob": "caf89dd0e60e23ac39ce18da823095959d409437",
                "sha256": "7d5fb73b7ca67a6798101741f5d280a3d016a56a197afcd4199dbb57b4b82a21",
                "characters": [chr(code) for code in range(0x2801, 0x2900)]},
    "share-tech-mono": {"label": "Share Tech Mono", "font": "ofl/sharetechmono/ShareTechMono-Regular.ttf",
                        "blob": "1611474a4cc94c3cb51664597cae92a6f3c68857",
                        "sha256": "9ceab1f87414829af259c0f537573ae03ef7dd3147c0b27a36a1a0beb6732677",
                        "characters": list(TERMINAL)},
    "press-start-2p": {"label": "Press Start 2P", "font": "ofl/pressstart2p/PressStart2P-Regular.ttf",
                       "blob": "39adf42efa597906e53be689474ac82214112124",
                       "sha256": "034c77f1f05ec89421e4a63f0e3a4ca1ecf852cc6d2bf611f126f275728e017d",
                       "characters": list(TERMINAL)},
}
FACE_IDS = ["yautja", *FONT_FACES]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------- Yautja polygons ----------

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


# ---------- Google Fonts ----------

def font_path(fonts: Path, face_id: str) -> Path:
    return fonts / Path(FONT_FACES[face_id]["font"]).name


def font_available(fonts: Path | None, face_id: str) -> bool:
    path = fonts and font_path(fonts, face_id)
    return bool(path and path.is_file() and sha256(path.read_bytes()) == FONT_FACES[face_id]["sha256"])


def font_masks(face_id: str, fonts: Path) -> list[np.ndarray]:
    """Render each character of a font face as a supersampled cell mask."""
    face, path = FONT_FACES[face_id], font_path(fonts, face_id)
    if sha256(path.read_bytes()) != face["sha256"]:
        raise ValueError(f"{path.name} is not the pinned font file")
    size = CELL * SUPERSAMPLE
    reference = ImageFont.truetype(str(path), 1000)

    def ink(font, character):
        box = font.getbbox(character, anchor="ms")
        return None if box[2] <= box[0] or box[3] <= box[1] else box

    boxes = [ink(reference, character) for character in face["characters"]]
    missing = [f"U+{ord(character):04X}" for character, box in zip(face["characters"], boxes) if box is None]
    if missing:
        raise ValueError(f"{path.name} draws nothing for {', '.join(missing)}")
    left, top = min(box[0] for box in boxes), min(box[1] for box in boxes)
    right, bottom = max(box[2] for box in boxes), max(box[3] for box in boxes)
    scale = FONT_FIT * SUPERSAMPLE / max(right - left, bottom - top)
    font = ImageFont.truetype(str(path), 1000 * scale)
    origin = (size / 2 - (left + right) / 2 * scale, size / 2 - (top + bottom) / 2 * scale)
    notdef = None
    masks = []
    for character in face["characters"]:
        image = Image.new("L", (size, size), 0)
        ImageDraw.Draw(image).text(origin, character, font=font, fill=255, anchor="ms")
        mask = np.rot90(np.asarray(image) > 127, face.get("quarter_turns", 0))
        if notdef is None:
            probe = Image.new("L", (size, size), 0)
            ImageDraw.Draw(probe).text(origin, "", font=font, fill=255, anchor="ms")
            notdef = np.rot90(np.asarray(probe) > 127, face.get("quarter_turns", 0))
        if np.array_equal(mask, notdef):
            raise ValueError(f"{path.name} has no glyph for U+{ord(character):04X}")
        masks.append(np.ascontiguousarray(mask))
    return masks


# ---------- shared distance fields ----------

def blocks(values: np.ndarray) -> np.ndarray:
    """Average each supersampled block into one cell pixel."""
    return values.reshape(CELL, SUPERSAMPLE, CELL, SUPERSAMPLE).mean(axis=(1, 3))


def signed_tile(inside: np.ndarray) -> np.ndarray:
    """Signed distance in atlas pixels, sampled at each cell pixel's centre."""
    if not inside.any():
        raise ValueError("a glyph rasterized empty")
    signed = np.where(inside, distance_transform_edt(inside) - .5,
                      .5 - distance_transform_edt(~inside)) / SUPERSAMPLE
    # A signed distance is linear across an edge, so a block mean is its centre value.
    return np.clip(np.round((.5 + blocks(signed) / RANGE) * 255), 0, 255).astype(np.uint8)


def distance_tile(glyph: dict) -> np.ndarray:
    return signed_tile(glyph_mask(glyph, CELL * SUPERSAMPLE))


def decode_mask(tile: np.ndarray) -> np.ndarray:
    return tile > 127


def mask_iou(left: np.ndarray, right: np.ndarray) -> float:
    union = np.count_nonzero(left | right)
    return float(np.count_nonzero(left & right) / union) if union else 1.0


def face_masks(face_id: str, *, fonts: Path | None = None, source: Path = SOURCE) -> tuple[list[str], list[np.ndarray]]:
    if face_id == "yautja":
        glyphs = load_glyphs(source)
        return [glyph["character"] for glyph in glyphs], [glyph_mask(glyph, CELL * SUPERSAMPLE) for glyph in glyphs]
    if fonts is None:
        raise ValueError(f"the {face_id} face needs --fonts with its pinned font file")
    return list(FONT_FACES[face_id]["characters"]), font_masks(face_id, fonts)


def columns_for(face_id: str, count: int) -> tuple[int, int]:
    columns = YAUTJA["columns"] if face_id == "yautja" else COLUMNS
    return columns, math.ceil(count / columns)


def render_atlas(face_id: str = "yautja", *, fonts: Path | None = None, source: Path = SOURCE) -> tuple[np.ndarray, list[dict]]:
    characters, masks = face_masks(face_id, fonts=fonts, source=source)
    columns, rows = columns_for(face_id, len(masks))
    atlas = np.zeros((rows * CELL, columns * CELL), dtype=np.uint8)
    records = []
    for index, (character, inside) in enumerate(zip(characters, masks)):
        tile = signed_tile(inside)
        column, row = index % columns, index // columns
        atlas[row * CELL:(row + 1) * CELL, column * CELL:(column + 1) * CELL] = tile
        fidelity = mask_iou(decode_mask(tile), blocks(inside.astype(float)) >= .5)
        if fidelity < IOU_GATE:
            raise ValueError(f"decoded distance field differs from {face_id} U+{ord(character):04X}: IoU={fidelity:.6f}")
        records.append({"character": character, "codepoint": f"U+{ord(character):04X}", "cell": [column, row],
                        "source_raster_iou_at128": round(fidelity, 6), "ink_pixels_at128": int(decode_mask(tile).sum())})
    return atlas, records


def source_record(face_id: str, source: Path = SOURCE) -> dict:
    if face_id == "yautja":
        return {**YAUTJA["source"], "vendored_path": source.relative_to(ROOT).as_posix(), "sha256": sha256(source.read_bytes())}
    face = FONT_FACES[face_id]
    folder = Path(face["font"]).parent.as_posix()
    return {"kind": "font", "repository": GOOGLE_FONTS, "commit": GOOGLE_FONTS_COMMIT, "path": face["font"],
            "git_blob_sha1": face["blob"], "sha256": face["sha256"], "redistributed": False,
            "license": "SIL Open Font License 1.1",
            "license_url": f"{GOOGLE_FONTS}/blob/{GOOGLE_FONTS_COMMIT}/{folder}/OFL.txt"}


def contract(face_id: str, count: int) -> dict:
    columns, rows = columns_for(face_id, count)
    return {"version": VERSION, "face": face_id, "count": count, "grid": [columns, rows], "cell_pixels": [CELL, CELL],
            "texture_pixels": [columns * CELL, rows * CELL], "distance_range_pixels": RANGE}


def build(face_id: str, *, fonts: Path | None = None, source: Path = SOURCE, output: Path = OUTPUT) -> dict:
    atlas, records = render_atlas(face_id, fonts=fonts, source=source)
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"{face_id}-sdf.png"
    Image.fromarray(atlas, "L").convert("RGB").save(target, optimize=True)
    label = YAUTJA["label"] if face_id == "yautja" else FONT_FACES[face_id]["label"]
    fit = ({"height_pixels": FIT_HEIGHT, "width_to_height": FIT_ASPECT, "per_glyph": True} if face_id == "yautja" else
           {"union_ink_pixels": FONT_FIT, "per_glyph": False, "quarter_turns": FONT_FACES[face_id].get("quarter_turns", 0)})
    receipt = {
        **contract(face_id, len(records)), "label": label,
        "method": "Exact Euclidean distance transform of the glyph rasterized at 8x, averaged to each cell pixel",
        "source": source_record(face_id, source),
        "order": "row-major in the listed character order",
        "distance_range_semantics": "full range 16 atlas pixels; -8 outside to +8 inside; boundary 0.5",
        "channels": "RGB with equal channels; median(r,g,b) is the signed distance",
        "fit": fit,
        "atlas_sha256": sha256(target.read_bytes()),
        "exporter_sha256": sha256(Path(__file__).read_bytes()),
        "validation": {"minimum_iou_gate": IOU_GATE,
                       "minimum_iou": min(record["source_raster_iou_at128"] for record in records),
                       "comparison": "decoded field threshold versus cell pixels at least half covered at 8x"},
        "glyphs": records,
    }
    (output / f"{face_id}-sdf.json").write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n",
                                                encoding="utf-8", newline="\n")
    return receipt


def verify(face_id: str = "yautja", *, fonts: Path | None = None, source: Path = SOURCE, output: Path = OUTPUT) -> dict:
    receipt = json.loads((output / f"{face_id}-sdf.json").read_text(encoding="utf-8"))
    if any(receipt.get(key) != value for key, value in contract(face_id, len(receipt["glyphs"])).items()):
        raise ValueError(f"{face_id} atlas geometry or encoding contract changed")
    if face_id == "yautja" and receipt["source"]["sha256"] != sha256(source.read_bytes()):
        raise ValueError("Yautja glyph source changed; rebuild the face atlas")
    if face_id != "yautja" and receipt["source"] != source_record(face_id):
        raise ValueError(f"{face_id} font pin changed; rebuild the face atlas")
    if receipt["exporter_sha256"] != sha256(Path(__file__).read_bytes()):
        raise ValueError("face exporter changed; rebuild the face atlases")
    texture = output / f"{face_id}-sdf.png"
    if receipt["atlas_sha256"] != sha256(texture.read_bytes()):
        raise ValueError(f"{face_id} atlas image changed")
    with Image.open(texture) as image:
        if image.mode != "RGB" or list(image.size) != receipt["texture_pixels"]:
            raise ValueError(f"{face_id} atlas image format mismatch")
        committed = np.asarray(image)
    if not (np.array_equal(committed[..., 0], committed[..., 1]) and np.array_equal(committed[..., 0], committed[..., 2])):
        raise ValueError(f"{face_id} atlas channels differ")
    field = committed[..., 0]
    for record in receipt["glyphs"]:
        column, row = record["cell"]
        tile = field[row * CELL:(row + 1) * CELL, column * CELL:(column + 1) * CELL]
        if int(decode_mask(tile).sum()) != record["ink_pixels_at128"]:
            raise ValueError(f"{face_id} decoded glyph changed: {record['codepoint']}")
    if face_id == "yautja" or font_available(fonts, face_id):
        rebuilt, records = render_atlas(face_id, fonts=fonts, source=source)
        # Rounding may differ by one level across numeric libraries; the edges may not.
        if np.abs(rebuilt.astype(int) - field).max() > 1 or not np.array_equal(decode_mask(rebuilt), decode_mask(field)):
            raise ValueError(f"{face_id} atlas no longer matches its source glyphs")
        if [record["character"] for record in receipt["glyphs"]] != [record["character"] for record in records]:
            raise ValueError(f"{face_id} atlas glyph order changed")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="verify the committed atlases instead of building them")
    parser.add_argument("--fonts", type=Path, help="directory holding the pinned Google Fonts files")
    parser.add_argument("--face", choices=FACE_IDS, action="append", help="limit to these faces")
    args = parser.parse_args()
    summary = {}
    for face_id in args.face or FACE_IDS:
        receipt = (verify if args.check else build)(face_id, fonts=args.fonts)
        summary[face_id] = {"count": receipt["count"], "grid": receipt["grid"],
                            "minimum_iou": receipt["validation"]["minimum_iou"],
                            **({"rebuilt": face_id == "yautja" or font_available(args.fonts, face_id)} if args.check else {})}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
