"""Check the Yautja glyph face's distance-field atlas against its polygon source."""

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


def test_committed_atlas_matches_the_vendored_source():
    receipt = face.verify()
    assert receipt["count"] == 52
    assert receipt["validation"]["minimum_iou"] >= .94
    assert [glyph["character"] for glyph in receipt["glyphs"]] == [
        chr(code) for code in [*range(65, 91), *range(97, 123)]]
    assert receipt["source"]["repository"] == "https://github.com/petehottelet/yautja"
    assert re.fullmatch(r"[0-9a-f]{40}", receipt["source"]["commit"])


def test_renderer_binds_the_atlas_geometry():
    receipt = json.loads((face.OUTPUT / "yautja-sdf.json").read_text(encoding="utf-8"))
    config = (ROOT / "svg-preview" / "config.mjs").read_text(encoding="utf-8")
    match = re.search(r"value:'yautja'.*?atlas:'([^']+)',grid:\[(\d+),(\d+)\],count:(\d+),pxRange:(\d+)", config)
    assert match, "config.mjs must declare the Yautja face"
    atlas, columns, rows, count, pixel_range = match.groups()
    assert (ROOT / "svg-preview" / atlas).resolve() == (face.OUTPUT / "yautja-sdf.png").resolve()
    assert [int(columns), int(rows)] == receipt["grid"]
    assert int(count) == receipt["count"]
    assert int(pixel_range) == receipt["distance_range_pixels"]
    assert "faces/yautja-sdf.png" in (ROOT / "svg-preview" / "source-files.mjs").read_text(encoding="utf-8")


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
        face.verify(face.OUTPUT, source)
