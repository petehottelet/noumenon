"""Check the explorer's glyph-face distance-field atlases against their sources."""

import json
from pathlib import Path
import re

import numpy as np
import pytest

import export_face_sdf as face


ROOT = Path(__file__).resolve().parents[1]
BAR = [[0, 0], [70, 0], [70, 210], [0, 210], [0, 0]]
RING = [[0, 0], [70, 0], [70, 210], [0, 210], [0, 4], [4, 4], [4, 206], [66, 206], [66, 4], [0, 4], [0, 0],
        [0, 0], [0, 0], [0, 0], [0, 0]]


def letters(contours=None):
    order = [chr(code) for code in [*range(65, 91), *range(97, 123)]]
    return [{"character": char, "contours": contours or [BAR, RING]} for char in order]


def receipt(face_id):
    return json.loads((face.OUTPUT / f"{face_id}-sdf.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("face_id", face.FACE_IDS)
def test_committed_atlases_match_their_receipts(face_id):
    # Font files are build inputs, so CI checks font faces against their
    # receipts; the vendored Yautja source is always rebuilt and compared.
    result = face.verify(face_id)
    assert result["face"] == face_id
    assert result["validation"]["minimum_iou"] >= face.IOU_GATE
    assert result["count"] == len(result["glyphs"])


def test_yautja_face_keeps_the_rain_letter_order_and_its_upstream_pin():
    result = receipt("yautja")
    assert [glyph["character"] for glyph in result["glyphs"]] == [
        chr(code) for code in [*range(65, 91), *range(97, 123)]]
    assert result["source"]["repository"] == "https://github.com/petehottelet/yautja"
    assert re.fullmatch(r"[0-9a-f]{40}", result["source"]["commit"])


@pytest.mark.parametrize("face_id", list(face.FONT_FACES))
def test_font_faces_pin_their_fonts_without_redistributing_them(face_id):
    source = receipt(face_id)["source"]
    pinned = face.FONT_FACES[face_id]
    assert source["repository"] == "https://github.com/google/fonts"
    assert re.fullmatch(r"[0-9a-f]{40}", source["commit"])
    assert source["path"] == pinned["font"] and source["sha256"] == pinned["sha256"]
    assert source["license"] == "SIL Open Font License 1.1" and source["redistributed"] is False
    assert [glyph["character"] for glyph in receipt(face_id)["glyphs"]] == pinned["characters"]
    assert not list(ROOT.glob("face-sources/**/*.ttf")) and not list(ROOT.glob("svg-preview/**/*.ttf"))


def test_ogham_turns_so_its_stemline_runs_down_the_column():
    assert receipt("ogham")["fit"]["quarter_turns"] == 1
    assert all(receipt(face_id)["fit"]["quarter_turns"] == 0 for face_id in face.FONT_FACES if face_id != "ogham")


def test_renderer_binds_every_face_atlas():
    config = (ROOT / "svg-preview" / "config.mjs").read_text(encoding="utf-8")
    declared = {value: (atlas, [int(columns), int(rows)], int(count), int(pixel_range)) for value, atlas, columns, rows, count, pixel_range in
                re.findall(r"\{value:'([\w-]+)',label:'[^']+',atlas:'([^']+)',grid:\[(\d+),(\d+)\],count:(\d+),pxRange:(\d+)", config)}
    sources = (ROOT / "svg-preview" / "source-files.mjs").read_text(encoding="utf-8")
    for face_id in face.FACE_IDS:
        atlas, grid, count, pixel_range = declared[face_id]
        result = receipt(face_id)
        assert (ROOT / "svg-preview" / atlas).resolve() == (face.OUTPUT / f"{face_id}-sdf.png").resolve()
        assert (grid, count, pixel_range) == (result["grid"], result["count"], result["distance_range_pixels"])
        assert f"faces/{face_id}-sdf.png" in sources and f"faces/{face_id}-sdf.json" in sources
    # Cyber is the Smythe catalog itself, so it reuses the original-glyph atlas.
    assert declared["cyber"][:3] == declared["smythe"][:3] == ("./generated-sdf.png", [16, 12], 192)


def test_only_lit_bars_are_drawn():
    glyph = {"character": "A", "contours": [BAR, RING, BAR]}
    assert face.lit_bars(glyph) == [BAR[:-1], BAR[:-1]]


def test_distance_field_is_signed_about_the_bar_edges():
    tile = face.distance_tile({"character": "A", "contours": [BAR]})
    assert tile.shape == (face.CELL, face.CELL)
    middle = face.CELL // 2
    assert tile[middle, middle] > 200          # well inside the bar
    assert tile[middle, 2] == 0                # far outside, beyond the encoded range
    row = tile[middle].astype(int)
    crossings = np.flatnonzero(np.diff((row > 127).astype(int)))
    assert len(crossings) == 2                 # one bar, two edges
    scale = face.placement({"contours": [BAR]})[0]
    assert abs((crossings[1] - crossings[0]) - 70 * scale) <= 1.5


@pytest.mark.parametrize("mutate, message", [
    (lambda glyphs: glyphs[:-1], "52 Yautja letter glyphs"),
    (lambda glyphs: [glyphs[1], glyphs[0], *glyphs[2:]], "52 Yautja letter glyphs"),
    (lambda glyphs: [{**glyphs[0], "contours": [RING]}, *glyphs[1:]], "no lit bars"),
    (lambda glyphs: [{**glyphs[0], "contours": [BAR[:-1]]}, *glyphs[1:]], "closed polygon"),
])
def test_unexpected_source_fails_closed(tmp_path, mutate, message):
    source = tmp_path / "glyphs.json"
    source.write_text(json.dumps(mutate(letters())), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        face.load_glyphs(source)


def test_digits_in_the_source_are_not_part_of_the_face(tmp_path):
    source = tmp_path / "glyphs.json"
    source.write_text(json.dumps(letters() + [{"character": "0", "contours": [RING]}]), encoding="utf-8")
    assert len(face.load_glyphs(source)) == 52


def test_a_changed_source_is_detected(tmp_path):
    source = tmp_path / "glyphs.json"
    source.write_bytes(face.SOURCE.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="source changed"):
        face.verify("yautja", source=source)


def test_font_faces_need_the_pinned_font(tmp_path):
    with pytest.raises(ValueError, match="needs --fonts"):
        face.render_atlas("runic")
    (tmp_path / "NotoSansRunic-Regular.ttf").write_bytes(b"not the pinned font")
    assert not face.font_available(tmp_path, "runic")
    with pytest.raises(ValueError, match="not the pinned font file"):
        face.render_atlas("runic", fonts=tmp_path)
