"""The vendored 192-glyph catalog, its pin, and the web exports built from it."""

import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from export_glyphs import MOTION, _payload
from export_native_glyphs import ORIGINAL, REPO_ROOT

# SHA-256 of catalog/manifest.json, copied from Smythe's benchmarks/noumenon/catalog.
CATALOG_MANIFEST_SHA256 = "a4d29072ab56d49fb05eca150ee510f823e727e59f9b861d76a28a92e7c34168"
CATALOG = REPO_ROOT / ORIGINAL


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_vendored_catalog_matches_its_pin_and_every_svg_hash():
    assert hashlib.sha256((CATALOG / "manifest.json").read_bytes()).hexdigest() == CATALOG_MANIFEST_SHA256
    manifest, catalog = _json(CATALOG / "manifest.json"), _json(CATALOG / "catalog.json")
    ids = [f"GLYPH-{index:03d}" for index in range(192)]
    assert manifest["count"] == catalog["count"] == 192
    assert [glyph["glyph_id"] for glyph in manifest["glyphs"]] == ids
    assert [glyph["glyph_id"] for glyph in catalog["glyphs"]] == ids
    for listed, current in zip(manifest["glyphs"], catalog["glyphs"], strict=True):
        digest = hashlib.sha256((CATALOG / listed["file"]).read_bytes()).hexdigest()
        assert digest == listed["svg_sha256"] == current["svg_sha256"], listed["glyph_id"]
    body = {key: value for key, value in catalog.items() if key != "catalog_sha256"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    assert catalog["catalog_sha256"] == hashlib.sha256(canonical).hexdigest()


def test_catalog_directory_keeps_only_runtime_artwork():
    # Generator inputs and review or measurement records stay in Smythe.
    expected = {f"GLYPH-{index:03d}.svg" for index in range(192)} | {
        "README.md", "catalog.json", "manifest.json",
        *(f"contact-sheet-{size}.png" for size in (16, 32, 64, 128)),
    }
    assert {path.name for path in CATALOG.iterdir()} == expected


def test_readmes_document_the_catalog_pin():
    for readme in (REPO_ROOT / "README.md", CATALOG / "README.md"):
        text = readme.read_text(encoding="utf-8")
        assert CATALOG_MANIFEST_SHA256 in text, readme
        assert "benchmarks/noumenon/catalog" in text, readme


def test_current_web_catalog_and_source_exports_use_the_revised_contours():
    assert ORIGINAL == Path("catalog")
    current = _json(REPO_ROOT / ORIGINAL / "catalog.json")
    assert _payload()["paths"] == [g["paths"] for g in current["glyphs"]]
    browser = (REPO_ROOT / "svg-preview/glyphs.js").read_text(encoding="utf-8")
    assert json.loads(browser.split(" = ", 1)[1].strip().removesuffix(";")) == current
    # The vendored SVG files, not a generator, are the source of every path.
    for glyph in current["glyphs"]:
        root = ET.fromstring((REPO_ROOT / ORIGINAL / f'{glyph["glyph_id"]}.svg').read_bytes())
        assert [path.get("d") for path in root] == glyph["paths"], glyph["glyph_id"]


def test_glyph_motion_covers_every_catalog_glyph_and_feeds_the_canvas_view():
    motion = _json(MOTION)
    assert motion["count"] == len(motion["speeds"]) == len(motion["trails"]) == 192
    assert all(isinstance(value, float) and 0.65 <= value <= 2.35 for value in motion["speeds"])
    assert all(isinstance(value, int) and 8 <= value <= 26 for value in motion["trails"])
    canvas = (REPO_ROOT / "glyphs.js").read_text(encoding="utf-8")
    data = json.loads(re.search(r"const GLYPHS=(\{.*\});\s*$", canvas, re.S).group(1))
    assert data["speeds"] == motion["speeds"]
    assert data["trails"] == motion["trails"]
    assert data["catalog_sha256"] == _json(CATALOG / "catalog.json")["catalog_sha256"]
