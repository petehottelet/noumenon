"""The endless generation loop through real Smythe graphs, with scripted providers only."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

import pytest

pytest.importorskip("shapely")
smythe = pytest.importorskip("smythe")

from live import feedcheck, grammar, lanes, sinks  # noqa: E402
from live.__main__ import main  # noqa: E402
from live.compile import compile_spec  # noqa: E402
from live.runner import Runner, Settings  # noqa: E402
from live.parts import RecentParts  # noqa: E402
from live.style import StyleGate  # noqa: E402


class ScriptedModel(smythe.Provider):
    """Answers every model-lane request with the same reply, at a fixed price."""

    def __init__(self, reply: str, cost: float = 0.01, fail: bool = False):
        self.reply, self.cost, self.fail, self.calls = reply, cost, fail, 0

    def budget_estimate_usd(self, model):
        return self.cost

    async def complete(self, system, prompt, model):
        self.calls += 1
        assert lanes.parse_request(prompt)["lane"] == "model"
        if self.fail:
            raise RuntimeError("provider unavailable")
        return smythe.CompletionResult(text=self.reply, cost_usd=self.cost, prompt_tokens=10, completion_tokens=10)


@pytest.fixture(scope="module")
def shared_gate():
    return StyleGate()


def _gate(shared):
    """A fresh session on the shared catalog silhouettes, so tests do not see each other's glyphs."""
    gate = StyleGate.__new__(StyleGate)
    gate.__dict__.update(shared.__dict__)
    gate.session, gate.session_coarse, gate.session_ids = [], [], []
    gate.parts = RecentParts(shared.parts.window)
    return gate


def _passing_specs(gate, count):
    """Designs that pass the gate one after another, so none repeats an earlier one's parts."""
    specs = []
    for seed in range(500):
        spec = grammar.sample_spec(seed)
        report = gate.check(compile_spec(spec))
        if report.ok and spec not in specs:
            gate.remember(f"pick-{len(specs)}", report)
            specs.append(spec)
            if len(specs) == count:
                return specs
    raise AssertionError("not enough designs pass the gate")


def _run(runner):
    return asyncio.run(runner.run())


def test_the_local_lane_archives_every_glyph_and_bounds_the_feed(tmp_path, shared_gate):
    memory = sinks.Memory()
    archive = sinks.Archive(tmp_path / "archive", "session")
    feed = sinks.Feed(tmp_path / "feed", 4)
    lines = []
    runner = Runner(Settings(interval=0, seed=11, limit=6), [memory, archive, feed],
                    gate=_gate(shared_gate), log=lines.append)
    totals = _run(runner)
    assert totals.accepted == 6 and totals.by_lane == {"local": 6, "model": 0} and totals.spend_usd == 0
    saved = sorted(archive.folder.glob("*.svg"))
    assert len(saved) == 6 and archive.count == 6
    manifest = [json.loads(line) for line in (archive.folder / "manifest.jsonl").read_text().splitlines()]
    assert [entry["id"] for entry in manifest] == [path.stem for path in saved]
    assert all("svg" not in entry and "polygons" not in entry for entry in manifest)
    assert {entry["lane"] for entry in manifest} == {"local"} and all(entry["seed"] is not None for entry in manifest)
    for path in saved:
        assert feedcheck.command_count(path.read_bytes())
    # The feed keeps only the newest glyphs, named so that name order is arrival order.
    assert sorted(path.name for path in feed.folder.glob("*.svg")) == [path.name for path in saved[-4:]]
    assert [record["seq"] for record in memory.after(0)] == [1, 2, 3, 4, 5, 6]
    assert memory.get(3)["id"] == saved[2].stem and memory.after(6) == [] and memory.latest == 6
    assert len(lines) == 6


def test_the_model_lane_parses_replies_rejects_bad_designs_and_stops_at_its_cap(shared_gate):
    gate = _gate(shared_gate)
    good = _passing_specs(_gate(shared_gate), 2)
    bad = {"layout": "columns", "halves": [{"cells": ["#.", ".#", "..", "..", ".."]}, good[0]["halves"][1]]}
    model = ScriptedModel(json.dumps({"designs": [*good, bad]}), cost=0.01)
    lines = []
    runner = Runner(Settings(lanes=("model",), interval=0, backoff=0, max_usd=0.05, call_estimate_usd=0.01),
                    [sinks.Memory()], gate=gate, providers={"model": model}, log=lines.append)
    totals = _run(runner)
    assert model.calls == 5                         # 5 x $0.01 reaches the $0.05 cap
    assert totals.spend_usd == pytest.approx(0.05)
    assert totals.by_lane["model"] == 2             # the repeats of each reply are near matches
    assert totals.rejected == 5 + 4 * 2             # the bad design every time, then the repeats
    assert "spending cap $0.05" in totals.model_stopped
    assert any("model lane stopped" in line and "no lane remains" in line for line in lines)


def test_the_local_lane_continues_when_the_model_lane_has_no_budget(shared_gate):
    model = ScriptedModel("{}")
    runner = Runner(Settings(lanes=("local", "model"), interval=0, max_usd=0, limit=3), [sinks.Memory()],
                    gate=_gate(shared_gate), providers={"model": model}, log=lambda line: None)
    totals = _run(runner)
    assert model.calls == 0 and totals.accepted == 3 and totals.by_lane["local"] == 3
    assert totals.model_stopped == "spending cap $0.00 reached"


def test_a_failing_model_never_stops_the_flow(shared_gate):
    model = ScriptedModel("", fail=True)
    runner = Runner(Settings(lanes=("local", "model"), interval=0, backoff=0, max_usd=1, limit=4),
                    [sinks.Memory()], gate=_gate(shared_gate), providers={"model": model}, log=lambda line: None)
    totals = _run(runner)
    assert model.calls >= 1 and totals.accepted == 4 and totals.by_lane == {"local": 4, "model": 0}


def test_a_model_provider_needs_its_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        lanes.model_provider("anthropic")
    with pytest.raises(ValueError):
        lanes.model_provider("elsewhere")


def test_the_command_saves_by_default_and_not_with_no_save(tmp_path, capsys):
    common = ["--count", "3", "--interval", "0", "--port", "0", "--seed", "21", "--feed", str(tmp_path / "feed")]
    assert main([*common, "--out", str(tmp_path / "saved")]) == 0
    sessions = list((tmp_path / "saved").iterdir())
    assert len(sessions) == 1 and len(list(sessions[0].glob("*.svg"))) == 3
    assert "saving to" in capsys.readouterr().out
    assert main([*common, "--no-save", "--out", str(tmp_path / "unsaved")]) == 0
    assert not (tmp_path / "unsaved").exists()
    output = capsys.readouterr().out
    assert "not saving glyphs" in output and "3 glyphs accepted" in output
    assert len(list((tmp_path / "feed").glob("*.svg"))) == 6
    assert main([*common, "--no-save", "--no-feed", "--out", str(tmp_path / "none")]) == 0
    assert "no feed" in capsys.readouterr().out


@pytest.mark.parametrize("arguments", [["--count", "0"], ["--concurrency", "0"], ["--interval", "-1"],
                                       ["--max-usd", "-2"], ["--lane", "psychic"]])
def test_the_command_rejects_bad_options(arguments):
    with pytest.raises(SystemExit):
        main(arguments)


def test_the_feed_folder_matches_what_each_saver_reads(monkeypatch, tmp_path):
    monkeypatch.setenv("NOUMENON_LIVE_FEED", str(tmp_path / "chosen"))
    assert sinks.default_feed() == tmp_path / "chosen"
    monkeypatch.delenv("NOUMENON_LIVE_FEED")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert sinks.default_feed() == tmp_path / "data" / "noumenon" / "live-feed"
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert sinks.default_feed() == tmp_path / "local" / "Noumenon" / "live-feed"
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sinks, "MAC_SAVER_CONTAINER", tmp_path / "container")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
    assert sinks.default_feed() == tmp_path / "home" / "Library" / "Application Support" / "Noumenon" / "live-feed"
    (tmp_path / "container").mkdir()
    assert sinks.default_feed() == tmp_path / "container" / "Library" / "Application Support" / "Noumenon" / "live-feed"


def test_the_feed_keeps_writing_when_a_saver_holds_an_old_file(tmp_path, monkeypatch):
    feed = sinks.Feed(tmp_path, 2)
    record = {"svg": "<svg/>"}
    for index in range(2):
        feed.write({**record, "id": f"a{index}"})
    real_unlink = Path.unlink

    def held(path, *args, **kwargs):
        raise PermissionError("in use")

    monkeypatch.setattr(Path, "unlink", held)
    feed.write({**record, "id": "a2"})              # pruning fails quietly
    monkeypatch.setattr(Path, "unlink", real_unlink)
    feed.write({**record, "id": "a3"})              # and catches up on the next write
    assert sorted(path.name for path in tmp_path.glob("*.svg")) == ["a2.svg", "a3.svg"]
    assert not list(tmp_path.glob("*.tmp"))
    with pytest.raises(ValueError):
        sinks.Feed(tmp_path, 0)
