"""The local explorer server: its file allowlist and the live glyph stream."""

from __future__ import annotations

import http.client
import io
import json

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("shapely")

from live import grammar  # noqa: E402
from live.compile import compile_spec  # noqa: E402
from live.server import ROOT, allowed, serve, tile_png  # noqa: E402
from live.sinks import Memory  # noqa: E402


@pytest.mark.parametrize("path", ["/index.html", "/glyphs.js", "/svg-preview/", "/svg-preview/index.html",
                                  "/svg-preview/live.mjs", "/catalog/GLYPH-000.svg"])
def test_the_explorer_files_are_served(path):
    assert allowed(path) is not None


@pytest.mark.parametrize("path", ["/", "/AGENTS.override.md", "/.git/config", "/live/runner.py",
                                  "/svg-preview/../live/runner.py", "/svg-preview/..%2f..", "/tmp/x",
                                  "/svg-preview\\..\\README.md", "/requirements-dev.txt", "/catalog/../.env",
                                  "/svg-preview/missing.html"])
def test_nothing_else_in_the_repository_is_served(path):
    assert allowed(path) is None


def test_a_tile_is_a_signed_distance_field_in_the_atlas_encoding():
    glyph = compile_spec(grammar.sample_spec(4), seed=4)
    image = Image.open(io.BytesIO(tile_png(glyph.polygons)))
    assert image.size == (128, 128) and image.mode == "RGB"
    pixels = np.asarray(image)
    assert (pixels[..., 0] == pixels[..., 1]).all() and (pixels[..., 0] == pixels[..., 2]).all()
    assert pixels.min() < 64 and pixels.max() > 192     # outside and inside the ink


def test_the_server_streams_glyphs_on_this_machine_only():
    with pytest.raises(ValueError):
        serve(Memory(), dict, host="0.0.0.0", port=0)
    memory = Memory()
    for seq in (1, 2):
        glyph = compile_spec(grammar.sample_spec(seq), seed=seq)
        memory.write({"seq": seq, "id": f"test-{seq:06d}", "lane": "local", "svg": glyph.svg,
                      "polygons": glyph.polygons})
    server = serve(memory, lambda: {"session": "test", "latest": memory.latest}, port=0)
    port = server.server_address[1]

    def get(path):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    try:
        status, headers, body = get("/live/status")
        assert status == 200 and json.loads(body) == {"session": "test", "latest": 2}
        assert headers["Cache-Control"] == "no-store"
        status, _, body = get("/live/glyphs?after=1")
        assert status == 200
        assert json.loads(body) == {"latest": 2, "glyphs": [
            {"seq": 2, "id": "test-000002", "lane": "local", "tile": "/live/tiles/2.png", "svg": "/live/svg/2.svg"}]}
        status, headers, body = get("/live/tiles/2.png")
        assert status == 200 and headers["Content-Type"] == "image/png" and body.startswith(b"\x89PNG")
        status, headers, body = get("/live/svg/1.svg")
        assert status == 200 and headers["Content-Type"] == "image/svg+xml"
        assert body.decode() == memory.get(1)["svg"]
        assert get("/live/tiles/9.png")[0] == 404
        assert get("/live/tiles/1.svg")[0] == 404
        assert get("/live/glyphs?after=soon")[0] == 400
        status, headers, _ = get("/")
        assert status == 302 and headers["Location"] == "/svg-preview/?glyphFace=live"
        status, _, body = get("/svg-preview/")
        assert status == 200 and body == (ROOT / "svg-preview" / "index.html").read_bytes()
        for path in ("/AGENTS.override.md", "/live/server.py", "/svg-preview/../live/server.py", "/.git/HEAD"):
            assert get(path)[0] == 404, path
    finally:
        server.shutdown()
        server.server_close()
