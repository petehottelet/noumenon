# Third-party notices

The browser renderer adapts [m8e/matrix-rain](https://github.com/m8e/matrix-rain),
a fork of [Rezmason/matrix](https://github.com/Rezmason/matrix), pinned at
`5ba90490453ceceb6812d6b1bc658a99a92411d0`.

| Included material | Copyright and license | Record |
|---|---|---|
| Rain simulation, glyph shaders, bloom, palette, utilities, and preset configuration | Copyright 2018 Rezmason; [MIT](engine/LICENSE) | [Adaptation manifest](engine/manifest.json) |
| Classic glyph artwork and its MSDF texture | Distributed in the pinned reference repository with its [MIT notice](reference/LICENSE); historical artwork origins are recorded separately | [Artwork provenance](reference/provenance.json), [texture hash](lib/provenance.json) |
| REGL runtime | Copyright 2016 Mikola Lysenko; [MIT](lib/regl.LICENSE) | [Pinned dependency hashes](lib/provenance.json) |
| gl-matrix 3.4.0 | Copyright 2015–2021 Brandon Jones and Colin MacKenzie IV; [MIT](lib/gl-matrix.LICENSE) | [Pinned dependency hashes](lib/provenance.json) |
| Settings gear icon | Google [Material Symbols](https://github.com/google/material-design-icons); [Apache License 2.0](https://github.com/google/material-design-icons/blob/master/LICENSE) | Path data inlined in [index.html](index.html) |
| Roboto and IBM Plex Mono interface fonts | Loaded from Google Fonts at runtime, not redistributed; licenses for [Roboto](https://fonts.google.com/specimen/Roboto/license) and [IBM Plex Mono](https://fonts.google.com/specimen/IBM+Plex+Mono/license) | [Font record](fonts/provenance.json) |

The original 192-glyph Smythe catalog and Noumenon's mix controls and
navigation additions are covered by the repository [MIT license](../LICENSE).
Imported reference characters are labeled separately and are not counted as
newly generated benchmark outputs.

The original-glyph GPU atlas was built with Viktor Chlumsky's
[MSDFgen 1.13](https://github.com/Chlumsky/msdfgen/releases/tag/v1.13).
The [atlas receipt](generated-sdf.json) records the tool, source SVGs,
transformation, and output hashes. The build tool is not bundled with the preview.

The reference project's account of the classic artwork traces it to earlier
promotional artwork and type designs. The retained repository license does not
independently establish the rights in every historical source. See the artwork
record for the specific attribution supplied by the reference project.
