"""Generate a constant flow of new Noumenon glyphs with Smythe.

    python -m live                      # local lane, save every glyph, serve the explorer
    python -m live --no-save            # keep glyphs in memory and the small feed only
    python -m live --lane both --max-usd 2 --model-provider anthropic

By default every accepted glyph is saved under generated-glyphs/<session>/ with a
manifest. --no-save skips that archive to conserve disk space. The newest glyphs
also go to a small rotating feed folder that the native screensavers read.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from live import lanes  # noqa: E402
from live.runner import Runner, Settings  # noqa: E402
from live.sinks import DEFAULT_ARCHIVE, FEED_SIZE, Archive, Feed, Memory, default_feed, session_name  # noqa: E402


def parse(argv=None):
    parser = argparse.ArgumentParser(prog="python -m live", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lane", choices=("local", "model", "both"), default="local",
                        help="local sampling (free), a live model, or both (default: local)")
    parser.add_argument("--model-provider", choices=sorted(lanes.MODEL_PROVIDERS), default="anthropic")
    parser.add_argument("--model", help="model for the model lane (default: the provider's)")
    parser.add_argument("--max-usd", type=float, default=1.0, help="model-lane spending cap for the session (default: 1.00)")
    parser.add_argument("--no-save", action="store_true", help="do not archive generated glyphs")
    parser.add_argument("--out", type=Path, default=DEFAULT_ARCHIVE, help="archive folder (default: generated-glyphs/)")
    parser.add_argument("--feed", type=Path, help="feed folder for the native screensavers")
    parser.add_argument("--no-feed", action="store_true", help="do not write the native screensaver feed")
    parser.add_argument("--port", type=int, default=8000, help="explorer port on this machine; 0 disables the server")
    parser.add_argument("--open", action="store_true", help="open the explorer in a browser")
    parser.add_argument("--interval", type=float, default=2.0, help="seconds between released glyphs (default: 2)")
    parser.add_argument("--concurrency", type=int, default=4, help="Smythe nodes run at once (default: 4)")
    parser.add_argument("--seed", type=int, help="first local seed (default: from the clock)")
    parser.add_argument("--count", type=int, help="stop after this many glyphs (default: never)")
    args = parser.parse_args(argv)
    if args.max_usd < 0 or args.interval < 0 or args.concurrency < 1 or (args.count is not None and args.count < 1):
        parser.error("spending cap and interval must be non-negative; concurrency and count at least 1")
    return args


def main(argv=None) -> int:
    import time

    args = parse(argv)
    session = session_name()
    memory = Memory()
    sinks = [memory]
    archive = None if args.no_save else Archive(args.out, session)
    if archive:
        sinks.append(archive)
    feed = None if args.no_feed else Feed(args.feed or default_feed(), FEED_SIZE)
    if feed:
        sinks.append(feed)
    chosen = ("local", "model") if args.lane == "both" else (args.lane,)
    settings = Settings(lanes=chosen, model_provider=args.model_provider, model=args.model, max_usd=args.max_usd,
                        interval=args.interval, concurrency=args.concurrency,
                        seed=args.seed if args.seed is not None else int(time.time()) % 1_000_000_000, limit=args.count)
    if "model" in chosen:
        lanes.model_provider(args.model_provider)  # fail fast on a missing key
    runner = Runner(settings, sinks)

    def status():
        return {"session": session, "lanes": list(chosen), "saving": archive is not None, "feed": feed is not None,
                "accepted": runner.totals.accepted, "rejected": runner.totals.rejected,
                "spend_usd": round(runner.totals.spend_usd, 6), "model_stopped": runner.totals.model_stopped,
                "latest": memory.latest}

    server = None
    if args.port:
        from live.server import serve
        server = serve(memory, status, port=args.port)
        url = f"http://127.0.0.1:{args.port}/svg-preview/?glyphFace=live"
        print(f"Explorer with live glyphs: {url}")
        if args.open:
            webbrowser.open(url)
    print(f"Session {session}: lanes {', '.join(chosen)}; "
          + (f"saving to {archive.folder}" if archive else "not saving glyphs")
          + (f"; feed {feed.folder}" if feed else "; no feed")
          + (f"; model cap ${args.max_usd:.2f}" if "model" in chosen else "") + ". Ctrl+C stops.")
    try:
        totals = asyncio.run(runner.run())
    except KeyboardInterrupt:
        runner.stopped = True
        totals = runner.totals
    finally:
        if server:
            server.shutdown()
    print(f"Stopped: {totals.accepted} glyphs accepted ({totals.by_lane['local']} local, {totals.by_lane['model']} model), "
          f"{totals.rejected} rejected, ${totals.spend_usd:.4f} spent"
          + (f"; saved in {archive.folder}" if archive and archive.count else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
