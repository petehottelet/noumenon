"""The local lane's shape grammar, the part memory that keeps shapes from repeating, and their gate."""

from __future__ import annotations

import asyncio
import random
import re
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("shapely")

from shapely import affinity, box  # noqa: E402
from shapely.geometry import Polygon  # noqa: E402

from live import feedcheck, parts, shapes  # noqa: E402
from live.compile import Glyph, compile_shapes, svg_for  # noqa: E402
from live.style import StyleGate  # noqa: E402
from svg_raster import render_svg  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ELL = Polygon([(20, 20), (35, 20), (35, 70), (65, 70), (65, 84), (20, 84)])
ARC = shapes.ribbon(shapes.arc_points(50, 50, 24, 24, 180, 360), 14)


def _designs(count, start=0):
    found = []
    for seed in range(start, start + count):
        drawn = shapes.design(random.Random(seed))
        if drawn is not None:
            found.append(drawn)
    return found


def _catalog_polygons(path):
    pieces = []
    for d in re.findall(r' d="([^"]+)"', path.read_text(encoding="utf-8")):
        rings = [[tuple(map(float, point.split())) for point in re.split(r"\s*L\s*", ring.strip()) if point]
                 for ring in re.split(r"\s*Z\s*", d.replace("M", " ").strip()) if ring.strip()]
        pieces.append(Polygon(rings[0], rings[1:]))
    return pieces


def test_the_catalog_box_and_ink_constants_match_the_approved_glyphs():
    glyphs = [_catalog_polygons(path) for path in sorted((ROOT / "catalog").glob("GLYPH-*.svg"))]
    assert len(glyphs) == 192
    bounds = [(min(p.bounds[0] for p in g), min(p.bounds[1] for p in g),
               max(p.bounds[2] for p in g), max(p.bounds[3] for p in g)) for g in glyphs]
    box_measured = (min(b[0] for b in bounds), min(b[1] for b in bounds),
                    max(b[2] for b in bounds), max(b[3] for b in bounds))
    assert np.allclose(box_measured, shapes.BOX, atol=0.5)
    widths = sorted(b[2] - b[0] for b in bounds)
    heights = sorted(b[3] - b[1] for b in bounds)
    pick = lambda values, share: values[round(share * (len(values) - 1))]  # noqa: E731
    assert pick(widths, 0.05) == pytest.approx(shapes.MIN_SIZE[0], abs=0.5)
    assert pick(heights, 0.05) == pytest.approx(shapes.MIN_SIZE[1], abs=0.5)
    ink = sorted(sum(p.area for p in g) / 10000 for g in glyphs)
    assert pick(ink, 0.05) == pytest.approx(shapes.CATALOG_INK[0], abs=0.002)
    assert pick(ink, 0.95) == pytest.approx(shapes.CATALOG_INK[1], abs=0.002)


def test_designs_keep_the_catalog_composition_box_and_ink_and_never_stand_alone():
    designs = _designs(40)
    assert len(designs) >= 36
    layouts = set()
    for drawn in designs:
        assert 2 <= len(drawn.parts) <= 4
        assert all(p.geom_type == "Polygon" and p.is_valid and not p.is_empty for p in drawn.parts)
        assert shapes.composition_problem(drawn.parts) is None
        assert shapes.envelope_problem(drawn.parts) is None
        assert len(drawn.modules) == len(drawn.groups) == len(drawn.parts)
        assert drawn.record == {"grammar": shapes.GRAMMAR, "layout": drawn.layout, "modules": list(drawn.modules)}
        layouts.add(drawn.layout)
    assert len(layouts) >= 4


def test_a_seed_draws_the_same_glyph_when_nothing_is_remembered():
    first, again = shapes.design(random.Random(7)), shapes.design(random.Random(7))
    assert [p.wkb for p in first.parts] == [p.wkb for p in again.parts] and first.groups == again.groups


def test_shape_designs_compile_to_the_catalog_svg_format():
    pattern = re.compile(r'<svg xmlns="http://www\.w3\.org/2000/svg" viewBox="0 0 100 100" width="128" height="128">'
                         r'(<path fill="#000000" fill-rule="nonzero" d="M[0-9. LMZ]+Z"/>)+</svg>')
    for drawn in _designs(20, start=100):
        glyph = compile_shapes(drawn.record, drawn.parts, drawn.groups)
        assert pattern.fullmatch(glyph.svg), glyph.svg[:120]
        assert render_svg(glyph.svg).size == (128, 128)
        assert feedcheck.command_count(glyph.svg.encode())
        assert all(0 <= value <= 100 for polygon in glyph.polygons for value in polygon.bounds)
        assert len(glyph.groups) == len(glyph.polygons)
        assert compile_shapes(drawn.record, drawn.parts, drawn.groups) == glyph
    with pytest.raises(ValueError):
        compile_shapes({}, [], [])


def test_part_keys_ignore_position_quarter_turns_and_mirror_images():
    recent = parts.RecentParts(4)
    recent.remember(recent.compare([ELL])[1])
    for shape in (affinity.translate(ELL, 7, -3), affinity.rotate(ELL, 90, origin="center"),
                  affinity.scale(ELL, -1, 1, origin="center"), affinity.rotate(affinity.scale(ELL, 1, -1), 270)):
        assert recent.compare([shape])[0] == pytest.approx(1.0)


def test_a_straight_shape_may_return_at_another_size_but_a_curve_may_not():
    recent = parts.RecentParts(4)
    recent.remember(recent.compare([ELL, ARC])[1])
    assert not parts.is_curved(ELL) and parts.is_curved(ARC)
    assert recent.compare([affinity.scale(ELL, 1.6, 1.6)])[0] < parts.MAX_SIMILARITY
    assert recent.compare([affinity.scale(ARC, 1.6, 1.6)])[0] > 0.9


def test_the_part_memory_forgets_the_oldest_glyph():
    recent = parts.RecentParts(2)
    for _ in range(3):
        recent.remember(recent.compare([ELL])[1])
    assert len(recent) == 2
    with pytest.raises(ValueError):
        parts.RecentParts(0)


def test_plain_strokes_may_recur_but_joints_curves_and_module_groups_may_not():
    bar, lean = box(20, 20, 80, 33), shapes.lean(40, 20, 15, 85, 16)
    assert not parts.is_distinctive(bar) and not parts.is_distinctive(lean)
    assert parts.is_distinctive(ELL) and parts.is_distinctive(ARC)
    pair = [box(20, 20, 70, 33), box(30, 60, 80, 73)]
    assert parts.candidates(pair, groups=(0, 1)) == []
    assert len(parts.candidates(pair, groups=(0, 0))) == 1
    recent = parts.RecentParts(4)
    assert recent.accepts(pair)
    recent.remember(recent.compare(parts.candidates(pair, groups=(0, 0)))[1])
    assert not recent.accepts([affinity.translate(p, 4, 2) for p in pair])


def test_the_gate_refuses_a_glyph_that_repeats_a_recent_part():
    gate = StyleGate(letters=False)
    first = next(d for d in _designs(30, start=200)
                 if gate.check(compile_shapes(d.record, d.parts, d.groups)).ok
                 and parts.candidates(d.parts, d.groups))
    glyph = compile_shapes(first.record, first.parts, first.groups)
    report = gate.check(glyph)
    gate.remember("first", report)
    turned = [affinity.rotate(p, 180, origin=(50, 50)) for p in glyph.polygons]
    again = gate.check(Glyph(spec={}, svg=svg_for(turned), polygons=tuple(turned), sha256="", groups=glyph.groups))
    assert any(reason.startswith("repeats a recent part") for reason in again.reasons)
    assert again.metrics["part_similarity"] >= parts.MAX_SIMILARITY


def test_a_live_session_repeats_no_distinctive_part_on_screen():
    pytest.importorskip("smythe")
    from live import sinks
    from live.runner import Runner, Settings

    memory = sinks.Memory()
    runner = Runner(Settings(interval=0, seed=5, limit=12), [memory], gate=StyleGate(letters=False),
                    log=lambda line: None)
    totals = asyncio.run(runner.run())
    assert totals.accepted == 12
    seen = []
    for record in memory.after(0):
        entries = parts.RecentParts().compare(parts.candidates(record["polygons"]))[1]
        for turns, size, curved in ((parts.key(shape), parts.longer_side(shape), parts.is_curved(shape))
                                    for shape in parts.candidates(record["polygons"])):
            for key, other_size, other_curved in seen:
                if (curved and other_curved) or abs(np.log(size / other_size)) <= np.log(parts.SIZE_RATIO):
                    overlap = np.bitwise_count(turns & key).sum(axis=1)
                    union = np.bitwise_count(turns).sum(axis=1) + np.bitwise_count(key).sum() - overlap
                    assert float((overlap / np.maximum(union, 1)).max()) < parts.MAX_SIMILARITY
        seen += entries
    assert {record["model"] for record in memory.after(0)} == {"noumenon-shape-grammar"}


MODULES = sorted({module for table in (shapes.MODULES, shapes.WHOLE, shapes.SMALL, shapes.MARKS)
                  for module, _ in table}, key=lambda module: module.__name__)


@pytest.mark.parametrize("module", MODULES, ids=lambda module: module.__name__[2:])
def test_every_module_draws_valid_parts_somewhere(module):
    rng = random.Random(module.__name__)
    drawn = 0
    for region in ((0, 0, 34, 72), (0, 0, 72, 34), (0, 0, 70, 70), (0, 0, 28, 30)):
        for _ in range(12):
            result = module(rng, *region, 15.0, 13.0, ("square", 0.0))
            if not result:
                continue
            for part in result:
                assert part.is_valid and part.area > 30
            drawn += 1
    assert drawn


def test_a_bend_tighter_than_its_stroke_is_refused_rather_than_kinked():
    assert shapes.ribbon(shapes.arc_points(50, 50, 4, 4, 0, 180), 16).is_empty
    assert shapes.ribbon(shapes.arc_points(50, 50, 25, 25, 0, 180), 16).is_valid


def test_pixel_steps_keep_every_edge_on_the_grid():
    stepped = shapes.pixelate(ARC, 6.5)
    for polygon in shapes.polygons(stepped):
        coords = list(polygon.exterior.coords)
        assert all(a[0] == b[0] or a[1] == b[1] for a, b in zip(coords, coords[1:]))
    assert abs(stepped.area - ARC.area) / ARC.area < 0.25
