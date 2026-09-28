"""The live generator's grid grammar, SVG compiler and style gate."""

from __future__ import annotations

import re

import pytest

pytest.importorskip("shapely")

from shapely.geometry import box  # noqa: E402

from live import feedcheck, grammar  # noqa: E402
from live.compile import Glyph, compile_spec, svg_for  # noqa: E402
from live.style import INK_RANGE, MAX_PIECES, StyleGate  # noqa: E402
from svg_raster import render_svg  # noqa: E402

STEM = ["#.", "#.", "#.", "#.", "#."]
HOOK = ["##", "#.", "#.", "#.", "##"]


@pytest.fixture(scope="module")
def gate():
    return StyleGate()


def _spec(left, right, layout="columns", **left_options):
    return {"layout": layout, "halves": [{"cells": left, **left_options}, {"cells": right}]}


def test_sampled_designs_are_deterministic_and_obey_the_grammar():
    layouts = set()
    for seed in range(300):
        spec = grammar.sample_spec(seed)
        assert grammar.sample_spec(seed) == spec
        assert grammar.check_spec(spec) == spec
        cells = sum(len(grammar.filled(half["cells"])) for half in spec["halves"])
        assert 5 <= cells <= 13
        layouts.add(spec["layout"])
    assert layouts == set(grammar.LAYOUTS)


@pytest.mark.parametrize("spec, message", [
    (_spec(["#.", ".#", "..", "..", ".."], STEM), "corner"),
    (_spec(["#.", "..", "..", "..", ".."], STEM), "at least two"),
    (_spec(["#..", "#.", "#.", "#.", "#."], STEM), "rows of"),
    (_spec(STEM, STEM, round=["2,0,tl"]), "not a turn"),
    (_spec([".#", ".#", ".#", ".#", ".#"], STEM, lean="right"), "empty column"),
    (_spec(HOOK, STEM, lean="left"), "one straight stem"),
    (_spec(STEM, STEM, lean="sideways"), "lean must be"),
    (_spec(["##"] * 5, ["##"] * 5), "between 5 and 13"),
    (_spec(STEM, STEM, layout="rings"), "layout"),
    ({"layout": "columns", "halves": [{"cells": STEM}]}, "two halves"),
])
def test_the_grammar_rejects_designs_outside_the_style(spec, message):
    with pytest.raises(ValueError, match=message):
        grammar.check_spec(spec)


def test_rounding_only_at_turns_and_leaning_only_single_stems():
    assert (0, 0, "tl") in grammar.eligible_corners(grammar.filled(HOOK))
    assert grammar.eligible_corners(grammar.filled(STEM)) == []
    assert grammar.lean_stem(grammar.filled(STEM)) == (0, 0, 4)
    assert grammar.lean_stem(grammar.filled(HOOK)) is None


def test_compiled_glyphs_use_the_catalog_svg_format():
    pattern = re.compile(r'<svg xmlns="http://www\.w3\.org/2000/svg" viewBox="0 0 100 100" width="128" height="128">'
                         r'(<path fill="#000000" fill-rule="nonzero" d="M[0-9. LMZ]+Z"/>)+</svg>')
    for seed in range(40):
        glyph = compile_spec(grammar.sample_spec(seed), seed=seed)
        assert pattern.fullmatch(glyph.svg), glyph.svg[:120]
        assert render_svg(glyph.svg).size == (128, 128)          # the catalog's strict rasterizer
        assert feedcheck.command_count(glyph.svg.encode())       # every native reader accepts it
        assert compile_spec(glyph.spec, seed=seed) == glyph        # deterministic, down to the bytes
        assert all(0 <= value <= 100 for polygon in glyph.polygons for value in polygon.bounds)


def test_rounded_turns_and_leaning_stems_change_the_outline():
    plain = compile_spec(_spec(HOOK, STEM), seed=1)
    rounded = compile_spec(_spec(HOOK, STEM, round=["0,0,tl", "4,0,bl"]), seed=1)
    assert rounded.polygons[0].area < plain.polygons[0].area
    upright = compile_spec(_spec(STEM, STEM), seed=1)
    leaning = compile_spec(_spec(STEM, STEM, lean="right"), seed=1)
    assert leaning.polygons[0].bounds[2] > upright.polygons[0].bounds[2] + 10


def test_the_gate_accepts_glyphs_in_the_approved_range(gate):
    accepted = 0
    for seed in range(40):
        report = gate.check(compile_spec(grammar.sample_spec(seed), seed=seed))
        if report.ok:
            accepted += 1
            assert INK_RANGE[0] <= report.metrics["ink"] <= INK_RANGE[1]
            assert report.metrics["pieces"] <= MAX_PIECES
    assert accepted >= 10


def _accepted(gate, start=0):
    for seed in range(start, start + 200):
        glyph = compile_spec(grammar.sample_spec(seed), seed=seed)
        report = gate.check(glyph)
        if report.ok:
            return glyph, report
    raise AssertionError("no glyph passed the gate")


def test_the_gate_rejects_repeats_letters_and_off_style_ink():
    gate = StyleGate()
    glyph, report = _accepted(gate)
    gate.remember("first", report)
    again = gate.check(glyph)
    assert not again.ok and any("near match of first" in reason for reason in again.reasons)

    lettered = StyleGate(letters=False)
    lettered.letters, lettered.letter_font = report.silhouette[None], "test"
    assert any("reads like" in reason for reason in lettered.check(glyph).reasons)

    square = box(10, 10, 90, 90)
    heavy = lettered.check(Glyph(spec={}, svg=svg_for([square]), polygons=(square,), sha256=""))
    assert any("ink coverage" in reason for reason in heavy.reasons)
    speck, bar = box(10, 10, 20, 20), box(10, 40, 90, 60)
    specked = lettered.check(Glyph(spec={}, svg=svg_for([speck, bar]), polygons=(speck, bar), sha256=""))
    assert any("smaller than" in reason for reason in specked.reasons)


def test_the_gate_forgets_the_oldest_glyphs_beyond_its_memory():
    gate = StyleGate(letters=False, memory=2)
    for index in range(3):
        _, report = _accepted(gate, start=index * 50)
        gate.remember(f"g{index}", report)
    assert gate.session_ids == ["g1", "g2"]
