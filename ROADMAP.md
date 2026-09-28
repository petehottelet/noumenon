# Noumenon roadmap

Noumenon is distributed as source. These items come before any precompiled
release.

## Web explorer

- **Renderer parity and presentation.** Measure visible-display cadence, GPU
  timing, and quantified tolerances against the reference renderer. A
  six-session headless timing study from September 2026 missed its frozen
  pacing target in every primary session, and a blank-page control showed
  similar callback cadence; that study is retained in Smythe's
  [evidence archive](https://github.com/petehottelet/smythe/blob/main/benchmarks/archive/README.md).

## Native ports

- **Live glyph share.** Let the Windows and macOS savers set the original
  family's share of cells, and with it how often live glyphs appear; the Linux
  port has `--mix`.
- **Native exploration modes.** Bring the web explorer's exposure pipeline, 3D
  navigation, and settings into the native savers, keep normal screensaver
  input dismissal, and verify each compiled control.
- **Windows.** Resolve the Microsoft Defender detection of the withdrawn
  v0.7.0-era Windows package before restoring precompiled downloads: keep
  quarantined copies quarantined, obtain Microsoft's analysis, investigate
  build provenance, and publish the outcome with exact artifact identities.
- **macOS.** Developer ID signing and notarization; the current bundle uses an
  ad-hoc signature.
- **Linux.** Native Wayland integration; the current port targets X11.
