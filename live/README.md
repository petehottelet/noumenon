# Live glyph generator

`python -m live` generates new Noumenon glyphs in the style of the 192
approved originals for as long as it runs. It is optional: the explorer and
the native savers run without it, and only this folder imports Smythe.

```bash
python -m pip install -r requirements-dev.txt   # Shapely, and Smythe on Python 3.11+
python -m live                                  # local lane, save everything, serve the explorer
python -m live --no-save                        # keep glyphs in memory and the feed only
python -m live --lane both --max-usd 2          # add a live model, capped at $2 for the session
```

## Pipeline

1. **Design.** Each round is a Smythe `ExecutionGraph` of design requests that
   a `Swarm` runs with bounded concurrency. The **local lane** answers through
   a $0 provider that draws glyphs with the shape grammar
   ([shapes.py](shapes.py)). The **model lane** sends the style brief
   ([lanes.py](lanes.py)) and recent accepted grid designs to a text model and
   parses grid designs ([grammar.py](grammar.py)) from its reply; designs that
   break the grid grammar are counted as rejected. The defaults are
   `claude-fable-5-1` (`--model-provider anthropic`, `ANTHROPIC_API_KEY`) and
   `gpt-5.6-sol` (`--model-provider openai`, `OPENAI_API_KEY`); `--model`
   chooses another. Rounds alternate when both lanes run.
2. **Grammars.** The **shape grammar** (local lane) has 38 modules gathered
   from every glyph family the explorer carries: the approved catalog, the
   classic reference, Runic, Ogham, Tifinagh, Yautja, Braille, Share Tech Mono
   and Press Start 2P. Each is redrawn with the catalog's rules: stems 13.5 to
   16.5 units wide, bars 12.5 to 14 thick, square ends, curves that taper to a
   straight cut, and gaps of 10.5 to 15 units. Every module takes continuous
   proportions, weights, curvature and taper, and may be turned, mirrored,
   leaned, broken by a gap or stepped on a pixel grid. A glyph is two halves
   side by side or stacked, a main half beside two quarters, or one large
   module with a mark or a deliberate break, never a single module alone. It has
   two to four parts and keeps the catalog's glyph box (x 13 to 89, y 13 to
   91, at least 62 by 68 units) and ink (0.172 to 0.239). A module whose parts
   would repeat a recent shape (step 4) is redrawn while the glyph is built, so
   the glyph a seed yields also depends on what came before it.

   The **grid grammar** (model lane) divides a glyph into two halves, side by
   side (`columns`) or stacked (`tiers`), either side of a 12-unit gap. Each
   half is 5 cells along its strokes and 2 across, about 14 units each, and
   fills at least 2 cells; a glyph fills 5 to 13. Cells never touch only at a
   corner. A corner may be rounded only where a stroke turns, and a half
   holding one straight stem of 3 or more cells may lean it into its empty
   column.
3. **Compile.** [compile.py](compile.py) writes the catalog's SVG format: a
   100-unit viewBox with one black nonzero path per piece, holes included.
   Shape designs arrive as polygons. Grid specs have their cell edges jittered
   within the approved stroke widths (stems 14 to 16 units, bars 13 to 15),
   their rounded turns cut and their leaning stems sheared.
4. **Gate.** [style.py](style.py) keeps a glyph only if its ink coverage is
   0.165 to 0.25 (the approved set's 5th to 95th percentile is 0.173 to
   0.241); it has at most four pieces and at most one small mark; no piece is
   under 195 square units, no counter under 150 and no gap under 8; its pieces
   and holes stay the same at 16, 32, 64 and 128 px and at two ink thresholds;
   it is not a near-copy (IoU of 0.85 or more, allowing shifts and turns) of a
   catalog glyph or one accepted earlier in the session; it does not match a
   bold letter, numeral or common symbol at an IoU of 0.65 or more (the
   approved glyphs score a median of 0.46); and none of its distinctive shapes
   repeats one of the last 256 accepted glyphs ([parts.py](parts.py)). A
   distinctive shape is a part with a joint, a curve or a counter, or the parts
   one module drew together. It repeats a remembered shape when they overlap at
   an IoU of 0.78 or more in any quarter turn or mirror image: curves at any
   size, other shapes within 1.25 times the size. Lone bars, stems and leaning
   strokes may recur.
5. **Release.** Accepted glyphs wait in a short queue and are released every
   `--interval` seconds (default 2) to the archive, the feed and the explorer.

A failed batch never stops the flow. The model lane stops for the session
once another call could pass `--max-usd`; the local lane continues.

## Where glyphs go

- **Archive** (default): `generated-glyphs/<session>/` holds every accepted
  glyph as `<session>-<number>.svg` and a `manifest.jsonl` line with its lane,
  seed, provider, model, design (a grid spec, or the shape grammar's layout and
  modules), SHA-256 and measurements. `--out` chooses the folder; `--no-save`
  skips the archive.
- **Feed** (default): the newest 256 glyphs in the per-user folder the native
  savers read, pruned as new glyphs arrive, so it stays small either way.
  `--feed` or `NOUMENON_LIVE_FEED` chooses the folder; `--no-feed` skips it.

  | System | Feed folder |
  |---|---|
  | Windows | `%LOCALAPPDATA%\Noumenon\live-feed` |
  | macOS | `~/Library/Containers/com.apple.ScreenSaver.Engine.legacyScreenSaver/Data/Library/Application Support/Noumenon/live-feed` when that container exists (the screen saver sandbox's home), else `~/Library/Application Support/Noumenon/live-feed` |
  | Linux | `$XDG_DATA_HOME/noumenon/live-feed`, normally `~/.local/share/noumenon/live-feed` |

- **Explorer**: [server.py](server.py) serves the explorer's own files on
  127.0.0.1 (`--port`, default 8000; `0` turns it off; `--open` opens a
  browser) and streams each glyph as its SVG and as a 128 px signed distance
  tile in the explorer's atlas encoding. Nothing else in the repository is
  served.

## What the native savers read

Every port follows the same rules, which [feedcheck.py](feedcheck.py) states
in Python and CI checks against each compiled saver:

- Every two seconds, the newest 256 names ending in `.svg` (names sort in
  arrival order; only letters, digits, `-`, `_` and `.`, not starting with a
  dot) are considered. A glyph is read once, while its file stays among them.
- A file must be a regular file of at most 256 KiB, not a link or a pipe,
  holding an SVG with `viewBox="0 0 100 100"` whose black nonzero paths are
  closed polygons in absolute M, L and Z commands, every coordinate from 0 to
  100, 16,000 commands at most. Anything else is skipped.
- The readable glyphs, newest first, join the original family. With L live
  glyphs, the pool holds all L plus the last `min(192, 256 - L)` approved
  originals: new glyphs first join the 192, then replace them one by one from
  the first, as in the explorer's live atlas.
- Live glyphs fall at the approved originals' median speed and trail length.

```bash
python -m live.feedcheck build /tmp/live-feed            # the fixture plus edge cases
python -m live.feedcheck expect /tmp/live-feed           # the report a saver must give
dist/noumenon-linux-x86_64 --live-report /tmp/live-feed > report.json
python -m live.feedcheck check /tmp/live-feed report.json
```

The Windows and macOS smoke checks get the same report from the compiled
`.scr` (its `/live-report <folder> <report.json>` mode, started directly
rather than through the shell, which opens a `.scr` as a screensaver) and from
the loaded `.saver` bundle.

## Tests

`tests/test_live_*.py` cover both grammars, the SVG format, the style gate and
its memory of recent parts, the runner through real Smythe graphs with
scripted providers (archive and feed writes, `--no-save`, parsing, rejection,
the spending cap, and a session that repeats no part), the server's allowlist
and stream, and the feed rules. They make no network or paid model
calls. `svg-preview/verify-live.mjs` checks the explorer's live atlas.
