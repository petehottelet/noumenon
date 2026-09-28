"""The live feed rules every native screensaver follows, and the design lanes' text handling."""

from __future__ import annotations

import json
import statistics

import pytest

from export_native_glyphs import build_payload
from live import feedcheck, lanes
from live.grammar import sample_spec


def test_names_that_sort_in_arrival_order_are_read_and_others_ignored():
    for name in ("20260927T120000-000001.svg", "a-b_c.d.svg", "x.svg"):
        assert feedcheck.valid_name(name), name
    for name in (".hidden.svg", "has space.svg", "UPPER.SVG", "glyph.svg.tmp", "notes.txt", ".svg",
                 "é.svg", "a" * 92 + ".svg"):
        assert not feedcheck.valid_name(name), name


def test_the_committed_fixture_is_the_generator_format():
    names = sorted(path.name for path in feedcheck.FIXTURE.iterdir())
    assert names == [f"20260927T120000-{n:06d}.svg" for n in range(1, 9)]
    for name in names:
        data = (feedcheck.FIXTURE / name).read_bytes()
        assert data.startswith(b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"')
        assert feedcheck.command_count(data) > 4


def test_edge_cases_are_rejected_accepted_at_the_limits_or_ignored():
    accepted, rejected, ignored = set(), set(), set()
    for name, data in feedcheck.edge_cases().items():
        if not feedcheck.valid_name(name):
            ignored.add(name)
        elif feedcheck.command_count(data) is None:
            rejected.add(name[-6:-4])
        else:
            accepted.add(name[-6:-4])
    assert accepted == {"15", "17"}  # exactly 256 KiB, exactly 16,000 commands
    assert rejected == {f"{n:02d}" for n in (9, 10, 11, 12, 13, 14, 16, 18, 19, 20, 21, 22)}
    assert ignored == {"notes.txt", ".hidden.svg", "20260927T120000-000023.svg.tmp", "has space.svg", "UPPER.SVG"}
    data = feedcheck.edge_cases()
    assert len(data["20260927T120000-000015.svg"]) == feedcheck.FILE_BYTES
    assert feedcheck.command_count(data["20260927T120000-000017.svg"]) == feedcheck.MAX_COMMANDS


@pytest.mark.parametrize("path, accepted", [
    ("M 10 10 L 90 10 L 50 90 Z", True),
    ("M10,10L90,10L50,90Z", True),
    ("M 10 10 L 90 10 L 50 90 Z M 20 20 L 30 20 L 25 30 Z", True),
    ("M 1e1 10 L 9e1 10 L 50 90 Z", True),
    ("M 10 10 L 90 10 Z", False),                 # two points close nothing
    ("M 10 10 L 90 10 L 50 Z", False),            # half a coordinate
    ("M 10 10 L 90 10 L 50 90 Z L 1 1", False),   # a line after the contour closed
    ("L 10 10 L 90 10 L 50 90 Z", False),         # no move
    ("M 10 10 M 20 20 L 90 10 L 50 90 Z", False),  # a second move inside a contour
    ("M 10 10 L 90 10 L 50 -1 Z", False),
    ("M 10 10 L 90 10 L 50 100.5 Z", False),
    ("M 10 10 L 90 10 L 1-2 90 Z", False),        # numbers run together
    ("M 10 10 L 90 10 L 50 90 H 4 Z", False),
])
def test_path_rules(path, accepted):
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="128" height="128">'
           f'<path fill="#000000" fill-rule="nonzero" d="{path}"/></svg>').encode()
    assert (feedcheck.command_count(svg) is not None) is accepted


def test_a_built_feed_expects_the_newest_256_and_the_reported_pool(tmp_path):
    folder = feedcheck.build(tmp_path / "feed")
    report = feedcheck.expect(folder)
    assert (report["files"], report["considered"], report["live"]) == (272, 256, 244)
    assert report["rejected"] == [f"20260927T120000-0000{n:02d}.svg"
                                  for n in (22, 21, 20, 19, 18, 16, 14, 13, 12, 11, 10, 9)]
    assert [glyph["name"] for glyph in report["glyphs"][:4]] == [
        "20260927T120000-000017.svg", "20260927T120000-000015.svg",
        "20260927T120000-000008.svg", "20260927T120000-000007.svg"]
    assert report["glyphs"][-1]["name"] == "20200101T000000-000016.svg"  # the 16 oldest fall outside
    assert (report["approved_in_pool"], report["pool"]) == (12, 256)
    assert feedcheck.compare(report, report) == []
    assert feedcheck.compare({**report, "speed": report["speed"] + 1e-3}, report)
    assert feedcheck.compare({**report, "glyphs": report["glyphs"][1:]}, report)


@pytest.mark.parametrize("live, approved", [(0, 192), (8, 192), (63, 192), (64, 192), (65, 191), (200, 56), (256, 0)])
def test_new_glyphs_fill_the_pool_then_replace_approved_originals(tmp_path, live, approved):
    fixture = sorted(feedcheck.FIXTURE.glob("*.svg"))
    tmp_path.joinpath("feed").mkdir()
    for index in range(live):
        tmp_path.joinpath("feed", f"g{index:04d}.svg").write_bytes(fixture[index % len(fixture)].read_bytes())
    report = feedcheck.expect(tmp_path / "feed")
    assert (report["live"], report["approved_in_pool"], report["pool"]) == (live, approved, live + approved)


def test_live_glyphs_move_at_the_approved_originals_median():
    payload = build_payload()
    originals = slice(payload["original_offset"], payload["original_offset"] + payload["original_count"])
    speed, trail = feedcheck.approved_motion()
    assert speed == statistics.median(payload["speeds"][originals])
    assert trail == int(statistics.median(payload["trails"][originals]) + .5)


def test_check_command_line(tmp_path, capsys):
    folder = tmp_path / "feed"
    assert feedcheck.main(["build", str(folder)]) == 0
    assert feedcheck.main(["expect", str(folder)]) == 0
    expected = json.loads(capsys.readouterr().out.splitlines()[-1])
    report = tmp_path / "report.json"
    report.write_text(json.dumps(expected), encoding="utf-8")
    assert feedcheck.main(["check", str(folder), str(report)]) == 0
    report.write_text(json.dumps({**expected, "live": 1}), encoding="utf-8")
    assert feedcheck.main(["check", str(folder), str(report)]) == 1
    assert feedcheck.main(["unknown"]) == 2


def test_model_replies_are_parsed_tolerantly_and_bad_designs_reported():
    good = sample_spec(3)
    bad = {"layout": "columns", "halves": [{"cells": ["#.", ".#", "..", "..", ".."]}, good["halves"][1]]}
    reply = "Here you go:\n```json\n" + json.dumps({"designs": [good, bad]}) + "\n```"
    specs, problems = lanes.parse_designs(reply)
    assert specs == [good] and len(problems) == 1 and "corner" in problems[0]
    assert lanes.parse_designs("no json here") == ([], ["the reply held no JSON object"])
    assert lanes.parse_designs('{"designs": 3}')[1] == ['the reply had no "designs" list']
    assert "not valid JSON" in lanes.parse_designs("{nope}")[1][0]


def test_design_requests_carry_their_lane_and_examples():
    prompt = lanes.model_prompt(4, [sample_spec(1), sample_spec(2)])
    assert lanes.parse_request(prompt) == {"lane": "model", "count": 4}
    assert json.dumps(sample_spec(1), separators=(",", ":")) in prompt
    assert lanes.parse_request(lanes.request("local", seed=7, count=2)) == {"lane": "local", "seed": 7, "count": 2}
    with pytest.raises(ValueError):
        lanes.parse_request("design me a glyph")
