"""What the native screensavers must read from a live feed folder.

Standard library only, so it runs wherever the native builds are tested. It
computes the report each native port prints for a feed folder, builds a test
feed with every kind of file a saver must skip, and compares a port's report
with the expected one.

    python -m live.feedcheck build DIR           # the committed fixture plus edge cases
    python -m live.feedcheck expect DIR          # the report a native port must print
    python -m live.feedcheck check DIR REPORT    # compare a port's report; exit 1 on a difference

The rules mirror the native readers: the newest 256 names ending in ``.svg``
(names sort in arrival order) are considered, and each must be a regular file
of at most 256 KiB holding the generator's format: an SVG with a 100-unit
viewBox whose black nonzero paths are closed polygons written with absolute
M, L and Z commands, every coordinate between 0 and 100, 16,000 commands at
most. Files that fail are reported as rejected and never drawn.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "live-feed"
VERSION = "native-live-feed-v1"
WINDOW = 256
POOL = 256
APPROVED = 192
FILE_BYTES = 262144
MAX_COMMANDS = 16000
NAME_LIMIT = 96
NAME_CHARACTERS = frozenset("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_.")
SEPARATORS = frozenset(" ,\t\n\r")
NUMBER_CHARACTERS = frozenset("0123456789.+-eE")
_TOKEN = re.compile(r"[ ,\t\n\r]+|[0-9.+\-eE]+|.", re.S)


def valid_name(name: str) -> bool:
    return (5 <= len(name) < NAME_LIMIT and not name.startswith(".") and name.endswith(".svg")
            and set(name) <= NAME_CHARACTERS)


def command_count(data: bytes) -> int | None:
    """The number of path commands a native reader draws, or None when it must skip the file."""
    if not 0 < len(data) <= FILE_BYTES:
        return None
    text = data.split(b"\0", 1)[0].decode("latin-1")
    if (not text.startswith("<svg") or "<!" in text or "<?" in text
            or ' viewBox="0 0 100 100"' not in text or "evenodd" in text):
        return None
    count = contours = 0
    cursor = 0
    while (start := text.find("<path", cursor)) >= 0:
        end, data_at = text.find(">", start), text.find(' d="', start)
        if end < 0 or data_at < 0 or data_at > end:
            return None
        data_at += 4
        stop = text.find('"', data_at)
        if stop < 0 or stop > end:
            return None
        command, open_contour, points, pending = None, False, 0, []
        for match in _TOKEN.finditer(text, data_at, stop):
            token = match.group()
            if token[0] in SEPARATORS:
                continue
            if token in ("M", "L", "Z"):
                if pending:
                    return None
                if token == "Z":
                    if not open_contour or points < 3:
                        return None
                    count += 1
                    contours += 1
                    command, open_contour, points = None, False, 0
                else:
                    command = token
                continue
            if token[0] not in NUMBER_CHARACTERS:
                return None
            try:
                value = float(token)
            except ValueError:
                return None
            if not math.isfinite(value) or not 0 <= value <= 100:
                return None
            pending.append(value)
            if len(pending) < 2:
                continue
            pending = []
            if command == "M" and not open_contour:
                open_contour, points, command = True, 1, "L"
            elif command == "L" and open_contour:
                points += 1
            else:
                return None
            count += 1
        if pending or open_contour:
            return None
        cursor = end
    if not contours or count > MAX_COMMANDS:
        return None
    return count


def _read(path: Path) -> bytes | None:
    try:
        info = os.lstat(path)
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_size > FILE_BYTES:
        return None
    return path.read_bytes()


def approved_motion(root: Path = ROOT) -> tuple[float, int]:
    """Live glyphs move at the approved originals' median speed and trail."""
    source = (root / "glyphs.js").read_text(encoding="utf-8")
    match = re.search(r"const GLYPHS=(\{.*\});\s*$", source, re.S)
    if match is None:
        raise ValueError("glyphs.js has no motion table")
    motion = json.loads(match.group(1))
    return statistics.median(motion["speeds"]), math.floor(statistics.median(motion["trails"]) + .5)


def expect(folder: Path) -> dict:
    folder = Path(folder)
    names = sorted((name for name in os.listdir(folder) if valid_name(name)), reverse=True)
    considered = names[:WINDOW]
    glyphs, rejected = [], []
    for name in considered:
        data = _read(folder / name)
        count = None if data is None else command_count(data)
        if count is None:
            rejected.append(name)
        else:
            glyphs.append({"name": name, "commands": count})
    live = len(glyphs)
    approved = APPROVED if live < POOL - APPROVED else POOL - live
    speed, trail = approved_motion()
    return {"version": VERSION, "files": len(names), "considered": len(considered), "live": live,
            "approved_in_pool": approved, "pool": live + approved, "speed": speed, "trail": trail,
            "rejected": rejected, "glyphs": glyphs}


def compare(report: dict, expected: dict) -> list[str]:
    """Differences between a native report and the expected one."""
    problems = []
    for key, value in expected.items():
        actual = report.get(key)
        if key == "speed":
            if not isinstance(actual, (int, float)) or abs(actual - value) > 1e-6:
                problems.append(f"speed: {actual!r} != {value!r}")
        elif actual != value:
            problems.append(f"{key}: expected {value!r:.300}, got {actual!r:.300}")
    return problems


def _polygon(points: list[tuple[float, float]]) -> str:
    return "M " + " L ".join(f"{x:g} {y:g}" for x, y in points) + " Z"


def _svg(*paths: str, rule: str = "nonzero") -> bytes:
    body = "".join(f'<path fill="#000000" fill-rule="{rule}" d="{d}"/>' for d in paths)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="128" height="128">'
            + body + "</svg>").encode()


def _commands(total: int) -> str:
    """One closed contour with exactly ``total`` commands."""
    points = [(10, 10), (90, 10), (90, 90)]
    points += [(10 + (i % 80), 90 - (i % 7)) for i in range(total - 1 - len(points))]
    return _polygon(points)


def edge_cases() -> dict[str, bytes]:
    """Files a native reader must reject, accept at a limit, or ignore by name."""
    square = _polygon([(20, 20), (80, 20), (80, 80), (20, 80)])
    at_limit = _svg(square)
    at_limit += b" " * (FILE_BYTES - len(at_limit))
    too_large = at_limit + b" "
    prefix = "20260927T120000-0000"
    return {
        f"{prefix}09.svg": _svg(_polygon([(20, 20), (140, 20), (80, 80)])),  # outside the canvas
        f"{prefix}10.svg": _svg(square, rule="evenodd"),
        f"{prefix}11.svg": _svg("m 20 20 l 60 0 l 0 60 z"),                 # relative commands
        f"{prefix}12.svg": _svg("M 20 20 C 40 0 60 0 80 20 L 50 80 Z"),      # curves
        f"{prefix}13.svg": _svg("M 20 20 L 80 20 L 80 80"),                  # never closed
        f"{prefix}14.svg": too_large,
        f"{prefix}15.svg": at_limit,                                         # exactly 256 KiB: drawn
        f"{prefix}16.svg": _svg(_commands(MAX_COMMANDS + 1)),
        f"{prefix}17.svg": _svg(_commands(MAX_COMMANDS)),                    # at the command limit: drawn
        f"{prefix}18.svg": b"",
        f"{prefix}19.svg": b"\xef\xbb\xbf" + _svg(square),                   # byte order mark
        f"{prefix}20.svg": _svg(square).replace(b' d="', b' data-d="'),      # a path with no d
        f"{prefix}21.svg": _svg(square).replace(b"20 20 L", b"20 20 L 1e5"),  # a number out of range
        f"{prefix}22.svg": _svg("M 20 20 L 0x40 20 L 80 80 Z"),              # hexadecimal
        "notes.txt": b"not a glyph",
        ".hidden.svg": _svg(square),
        f"{prefix}23.svg.tmp": _svg(square),
        "has space.svg": _svg(square),
        "UPPER.SVG": _svg(square),
    }


def build(folder: Path, fillers: int = 250) -> Path:
    """The fixture glyphs, the edge cases, and enough older glyphs to overflow the window."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    fixtures = sorted(FIXTURE.glob("*.svg"))
    if not fixtures:
        raise FileNotFoundError("the live-feed fixture is missing")
    for path in fixtures:
        shutil.copyfile(path, folder / path.name)
    for name, data in edge_cases().items():
        (folder / name).write_bytes(data)
    for index in range(fillers):
        shutil.copyfile(fixtures[index % len(fixtures)], folder / f"20200101T000000-{index:06d}.svg")
    return folder


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) == 2 and args[0] == "build":
        print(build(Path(args[1])))
        return 0
    if len(args) == 2 and args[0] == "expect":
        print(json.dumps(expect(Path(args[1]))))
        return 0
    if len(args) == 3 and args[0] == "check":
        report = json.loads(Path(args[2]).read_text(encoding="utf-8-sig"))
        expected = expect(Path(args[1]))
        problems = compare(report, expected)
        for problem in problems:
            print(problem, file=sys.stderr)
        if not problems:
            print(f"live feed report matches: {expected['live']} live, {len(expected['rejected'])} rejected, "
                  f"{expected['files']} files")
        return 1 if problems else 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
