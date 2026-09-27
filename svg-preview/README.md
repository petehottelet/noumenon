# Noumenon web explorer

The explorer adapts the MIT-licensed rain, bloom, and palette renderer from
[m8e/matrix-rain](https://github.com/m8e/matrix-rain) and
[Rezmason/matrix](https://github.com/Rezmason/matrix). Classic starts with a fixed
2D grid. The reference's base glyphs carry the effect; Smythe's original SVGs
appear in 10% of selections by default.

## README animation

[Animated GIF](preview.gif) · [Still image](preview.png) · [Capture record](preview-animation.json).

Both previews show **100% of selections from the 192-glyph Smythe catalog**,
using the actual Classic renderer and Matrix palette. The GIF is 900×506
pixels and loops at 20 playback frames per second. A short dissolve joins the
loop. Frame timing is an export setting, not a performance result. The capture
record identifies the Smythe source revision and the renderer source hashes at
capture time; later path and name changes are not reflected in those hashes.

## Run and controls

From the repository root:

```bash
python -m http.server 8000 --bind 127.0.0.1
```

Open [the explorer](http://localhost:8000/svg-preview/) or
[the 192-glyph catalog](http://localhost:8000/svg-preview/catalog.html).
The static preview requires a WebGL-capable browser, with no API key or build step.

| Input | Action |
|---|---|
| Bottom-right corner (click or tap) / S | Open or close the settings panel |
| Space | Pause or resume playback |
| R | Reset the viewpoint |
| F | Toggle fullscreen |
| Arrow up / down in 3D | Move forward / backward |
| Arrow left / right in 3D | Move sideways |
| Escape, or a click on the rain | Close the settings panel |

The corner is otherwise empty. For five seconds after the page loads, a
tooltip names it and the gear shows in its circle; both fade out together.
Afterwards a hovering mouse fades the gear in, and touch screens show it only
beside that first tooltip. Opening the panel invalidates a running
measurement. Inside a menu, S types ahead to an option instead of closing the
panel, and Escape closes an open menu before it closes the panel.

Every preset builds on one of three looks: Classic, the default 2D effect;
Operator; and 3D, which adds navigation. The presets are Classic, Operator,
3D, Downpour, Zen garden, Inferno, Synthwave, Northern lights, Amber
terminal, Ghost, Spectrum, Hunter, Warp speed, Runestones, Arcade, and
Mainframe. Each preset only sets
values the panel exposes, so any preset can be adjusted afterwards, and the
3D travel controls apply to 3D and Warp speed. Once a control leaves the
chosen preset's values, the menu reads **Custom**; choosing the preset again
restores it. The address keeps the preset either way, so a reload returns to
the same look. **Enter 3D** and **Classic view**
switch the look but keep the glyph face, mix, palette, background, and leading
glyph color, so a preset's colors carry across. The glyph face, original-glyph
mix,
columns, motion, glow, render scale, glyph transforms, travel, and supported
colors apply live: sliders and colour pickers rebuild the scene once they
settle, and other controls apply at once. Changes made during a rebuild wait
for it and then apply together. The URL keeps each applied configuration. If
a rebuild fails, the panel reports why and undoes only that rebuild's change;
edits made while it ran still apply.
Only options supported by the selected engine are exposed.

The default **Matrix green** grade uses a 137-degree body hue and mint
`#A2FFD8` leading glyphs. **Reference colors** retains the original body
palette. White, Amber, Crimson, Toxic and Ultraviolet hold one hue; Sakura
and Ice also pale toward their brightest glyphs; Fire, Synthwave, Aurora and
Spectrum blend from one hue in the dim trails to another at the heads. Every
palette keeps the look's exposure curve, and the leading glyph color is
independently adjustable. The interface follows the palette too: the panel,
menus, tooltip, gear, outline, and wordmark take the dim-trail hue for text
and glass and the head hue for highlights. Matrix green keeps the panel's
designed colors.

**Glyph face** chooses what the rain draws. **Smythe + classic** mixes the
192 originals with the 56 reference glyphs at the original-glyph share. Every
other face draws every cell from its own set, so the mix slider is disabled:

| Face | Glyphs | Source |
|---|---|---|
| Cyber | The 192 Smythe originals alone | The Yautja project's name for the same catalog; it reuses `generated-sdf.png` |
| Yautja | 52 letter glyphs of the [Yautja](https://github.com/petehottelet/yautja) default HUD, the ones its code rain draws | Vendored polygons; lit bars only, since the unlit hairline rings vanish at rain sizes |
| Ogham | 26 letters, U+1681–U+169A, turned so the stemline runs down the column | Noto Sans Ogham |
| Runic | 75 runes, U+16A0–U+16EA | Noto Sans Runic |
| Tifinagh | 56 letters, U+2D30–U+2D67 | Noto Sans Tifinagh |
| Braille | 255 dot patterns, U+2801–U+28FF | Noto Sans Symbols 2 |
| Share Tech Mono | Digits, capitals and 14 symbols | Share Tech Mono |
| Press Start 2P | The same 50 characters in 8-bit type | Press Start 2P |

Each font face uses one scale for all of its glyphs, so marks keep their
relative sizes and places; Ogham and Braille are fine-grained and read best
with fewer columns. Hunter pairs Yautja with Crimson, Runestones pairs Runic
with Amber, Arcade pairs Press Start 2P with Spectrum, and Mainframe sets
Share Tech Mono on the Operator look.

The control panel follows [hottelet.com](https://www.hottelet.com/)'s floating
HUD: a glass folder along the bottom of the window, grouped controls in
Roboto with IBM Plex Mono readouts, primary green `#37FF6E` and bright
`#9CFFBC`, a soft phosphor glow, scanlines, and a pixel resolve when it opens.
The folder's raised tab carries the SMYTHE wordmark, outlined Trajan Pro Bold
that links to the Smythe repository. The tab sits flush with the panel's left
edge and slopes steeply down to the body at 60 degrees, and one continuous outline
traces both. In browsers with
customizable selects, menus open as the same glass card with a green
highlight; other browsers keep their native menu. The footer credits the
reference renderer. These interface colors are
separate from the rain's 137° body hue and `#A2FFD8` highlights. Both fonts
load from Google Fonts, and [font and logo provenance](fonts/provenance.json)
records them; the Trajan font file is not bundled.

## Two catalogs, separate provenance

The licensed base catalog contains **56 visible classic glyphs plus the
reference's blank selection slot**. Each glyph selection draws from the
original catalog with a default probability of 10%; other selections use the
57 reference slots. The mix is weighted by catalog choice, so the larger
original catalog does not dominate the effect. The setting is adjustable
from 0% to 100%.

[Base SVGs and source](reference/README.md) ·
[Artwork provenance](reference/provenance.json) ·
[Artwork MIT notice](reference/LICENSE) ·
[Engine MIT notice](engine/LICENSE).

The imports are pinned to
[5ba9049](https://github.com/m8e/matrix-rain/tree/5ba90490453ceceb6812d6b1bc658a99a92411d0).
Credit to Rezmason and the reference project's contributors. Noumenon adapts
licensed renderer code and base artwork; the additional 192 Smythe glyphs are
independently authored.

[192-glyph sheet](../catalog/contact-sheet-128.png) ·
[16 px](../catalog/contact-sheet-16.png) ·
[32 px](../catalog/contact-sheet-32.png) ·
[64 px](../catalog/contact-sheet-64.png) ·
[SVG files, manifest, and pin](../catalog/README.md).

The gallery shows only the original glyphs. The live effect keeps its
adjustable reference mix; use **Original glyphs: 100%** to see only the
originals. `glyphs.js` is the browser copy of `../catalog/catalog.json`;
`python export_glyphs.py` rewrites it.

## Renderer and checks

The adapted REGL pipeline retains the reference's stationary grid cells,
traveling illumination, glyph changes, scalar bloom, and final palette mapping.
Classic uses 80 cells across the viewport's longer dimension and a default
render scale of 0.75. At 1920 × 1080 and DPR 1, those settings imply 24-pixel
cells and a 1440 × 810 drawing buffer. These are configuration-derived sizes,
not measured performance results.

The original glyphs reach the GPU through `generated-sdf.png`, a multi-channel
signed distance field atlas built from the source SVGs with MSDFgen 1.13.
[Its receipt](generated-sdf.json) binds the atlas to every source SVG, and
`python export_generated_sdf.py --check` verifies that binding. The other
faces use the same slot with atlases in `faces/`: single-channel signed
distance fields computed exactly from each glyph rasterized at 8×. Yautja's
comes from the vendored [polygon source](../face-sources/yautja/glyphs.json);
the font faces come from Google Fonts files pinned by commit, Git blob and
SHA-256 in each receipt, such as [Runic's](faces/runic-sdf.json). The fonts
are build inputs and are not redistributed. `python export_face_sdf.py --check`
verifies every atlas against its receipt and rebuilds each face whose source
is present; `--fonts FONT_DIR` supplies the fonts. The
[reference provenance](reference/provenance.json) identifies the pinned
artwork.

Settings schema, URL, and control panel checks run without a browser:

```bash
node svg-preview/verify-settings.mjs
node svg-preview/verify-hud.mjs
```

The other offline checks cover presets, palettes, glyph faces, frame timing,
the 3D model, source provenance, browser helpers, and measurement receipts:

```bash
node svg-preview/verify-config.mjs
node svg-preview/verify-timing.mjs
node svg-preview/verify-model.mjs
node svg-preview/verify-provenance.mjs
node svg-preview/verify-browser-command.mjs
node svg-preview/verify-measure-guard.mjs
node svg-preview/verify-lifecycle.mjs
node svg-preview/verify-measurement.mjs
node svg-preview/verify-browser-metadata.mjs
node svg-preview/verify-raf-control.mjs
```

Benchmark completion restores exactly one animation loop. The lifecycle
regression executes the renderer through repeated measurements, pause/resume,
and timeout, rejecting duplicate scheduled callbacks. It also checks that a
settings change made during the first load waits for that scene.

### Browser review and measurement

These helpers drive a local browser through the `agent-browser` tool against
a localhost server and write new receipts; each refuses to replace an existing
one.

- `review.mjs` checks the three looks, the default 10% mix and the 0% and
  100% endpoints, paused 3D movement and exact reset, the catalog page,
  settings and keyboard interruption of measurements, and WebGL context loss.
  It binds every served source and captures `preview.png`.
- `measure.mjs` collects one timing session under the
  [renderer performance protocol](protocols/renderer_performance_20260907.md):
  five seconds of warmup, then 60 seconds of samples at a 1080p viewport and
  0.75 render scale. `aggregate-measurements.mjs` recomputes every summary for
  a complete six-session campaign. Callback intervals and CPU submission
  remain separate from GPU execution and physical presentation.
- `raf-control.mjs` records blank-page callback cadence under the
  [cadence control protocol](protocols/renderer_cadence_control_20260907.md).
- `soak.mjs` runs a ten-minute travel, resize, and pause stability check.

Set `NOUMENON_MEASURE_POWER_PROFILE` and `NOUMENON_MEASURE_WORKLOADS` to the
observed host conditions before a measurement. Smythe froze both protocols for
its 2026-09-07 renderer campaign; that campaign's receipts and results remain
in the [Smythe repository](https://github.com/petehottelet/smythe).

## Native source builds and next checks

The Windows, macOS, and Linux source ports in the
[native guide](../README.md#build-the-native-ports) use these same SVG
outlines: 56 visible reference glyphs, the blank slot, and 192 originals, with
a 10% original mix. Native GDI+, Core Graphics, and Cairo render the filled
contours into cached sprites. The [catalog record](../native-catalog.json)
binds both source catalogs. Precompiled packages are not distributed; the
native guide lists build commands. The native savers retain their three-layer
motion. The REGL exposure pipeline, 3D exploration, and live settings are
next for the native ports.

Next: measure reference-behavior tolerances, visible-browser/display cadence,
and GPU timing for the same preset and catalog configuration. Keep licensing,
source hashes, screenshots, and test receipts together.
