"""Where accepted live glyphs go: an archive, a feed for the native savers, and memory.

The archive keeps every accepted glyph of a session: one SVG per glyph and a
manifest line describing how it was made. It is on by default; running without
saving skips it. The feed keeps only the newest glyphs, a bounded rotating set
the native screensavers read while they run. The web explorer reads from memory.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = ROOT / "generated-glyphs"
FEED_SIZE = 256
MAC_SAVER_CONTAINER = Path("~/Library/Containers/com.apple.ScreenSaver.Engine.legacyScreenSaver/Data").expanduser()


def default_feed() -> Path:
    """The per-user folder the native savers read, overridable with NOUMENON_LIVE_FEED.

    macOS runs screen savers in a sandbox whose home is the legacyScreenSaver
    container, so the feed goes inside that container when it exists."""
    override = os.environ.get("NOUMENON_LIVE_FEED")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Noumenon" / "live-feed"
    if sys.platform == "darwin":
        home = MAC_SAVER_CONTAINER if MAC_SAVER_CONTAINER.is_dir() else Path.home()
        return home / "Library" / "Application Support" / "Noumenon" / "live-feed"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "noumenon" / "live-feed"


def session_name(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")


def _atomic_write(path: Path, text: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


class Archive:
    """Every accepted glyph of a session, with a manifest of how each was made."""

    def __init__(self, root: Path, session: str):
        self.folder = Path(root) / session
        self.count = 0

    def write(self, record: dict) -> Path:
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / f"{record['id']}.svg"
        _atomic_write(path, record["svg"])
        entry = {key: value for key, value in record.items() if key not in ("svg", "polygons")}
        with open(self.folder / "manifest.jsonl", "a", encoding="utf-8", newline="\n") as manifest:
            manifest.write(json.dumps(entry, sort_keys=True) + "\n")
        self.count += 1
        return path


class Feed:
    """The newest glyphs, named so that name order is arrival order, pruned to a fixed size."""

    def __init__(self, folder: Path, size: int = FEED_SIZE):
        if size < 1:
            raise ValueError("the feed must hold at least one glyph")
        self.folder, self.size = Path(folder), size

    def write(self, record: dict) -> Path:
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / f"{record['id']}.svg"
        _atomic_write(path, record["svg"])
        existing = sorted(self.folder.glob("*.svg"))
        for old in existing[:max(0, len(existing) - self.size)]:
            try:
                old.unlink()
            except OSError:  # already gone, or briefly held open by a saver; the next write retries
                pass
        return path


class Memory:
    """Recent glyphs for the web stream, numbered by arrival."""

    def __init__(self, size: int = 512):
        self.records: deque[dict] = deque(maxlen=size)
        self.latest = 0
        self.lock = threading.Lock()

    def write(self, record: dict) -> None:
        with self.lock:
            self.latest = record["seq"]
            self.records.append(record)

    def after(self, seq: int) -> list[dict]:
        with self.lock:
            return [record for record in self.records if record["seq"] > seq]

    def get(self, seq: int) -> dict | None:
        with self.lock:
            return next((record for record in self.records if record["seq"] == seq), None)
