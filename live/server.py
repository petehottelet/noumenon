"""Serve the explorer and stream live glyphs to it, on this machine only.

Only the explorer's own files are served, never the rest of the repository.
Each accepted glyph is offered as its SVG and as a 128 px signed distance tile
in the same encoding as the explorer's glyph atlases, so the page can drop it
straight into its live atlas.
"""

from __future__ import annotations

from functools import lru_cache
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import re
import threading
from urllib.parse import parse_qs, urlparse

import numpy as np
from PIL import Image, ImageDraw

from export_face_sdf import CELL, SUPERSAMPLE, signed_tile

ROOT = Path(__file__).resolve().parents[1]
STATIC_FILES = {"index.html", "glyphs.js", "noumenon-preview.png"}
STATIC_DIRECTORIES = ("svg-preview/", "catalog/")


def tile_png(polygons) -> bytes:
    """A glyph's signed distance tile: 128 px, range 16 px, equal RGB channels."""
    size = CELL * SUPERSAMPLE
    scale = size / 100
    image = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(image)
    for polygon in polygons:
        draw.polygon([(x * scale, y * scale) for x, y in polygon.exterior.coords], fill=255)
        for interior in polygon.interiors:
            draw.polygon([(x * scale, y * scale) for x, y in interior.coords], fill=0)
    tile = signed_tile(np.asarray(image) > 127)
    buffer = io.BytesIO()
    Image.fromarray(tile, "L").convert("RGB").save(buffer, "PNG")
    return buffer.getvalue()


def allowed(path: str) -> Path | None:
    """The file for a request path, when it is one of the explorer's files."""
    relative = path.lstrip("/")
    if not relative or ".." in relative.split("/") or "\\" in relative:
        return None
    if relative not in STATIC_FILES and not relative.startswith(STATIC_DIRECTORIES):
        return None
    if relative.endswith("/"):
        relative += "index.html"
    target = (ROOT / relative).resolve()
    return target if target.is_file() and target.is_relative_to(ROOT) else None


def make_handler(memory, status):
    tiles = lru_cache(maxsize=1024)(lambda seq: tile_png(memory.get(seq)["polygons"]))

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, format, *args):  # keep the console for glyph lines
            pass

        def _send(self, body: bytes, content_type: str, code=HTTPStatus.OK, cache=False):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=3600" if cache else "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, code=HTTPStatus.OK):
            self._send(json.dumps(data).encode(), "application/json", code)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/":
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", "/svg-preview/?glyphFace=live")
                self.end_headers()
                return
            if url.path == "/live/status":
                return self._json(status())
            if url.path == "/live/glyphs":
                try:
                    after = int(parse_qs(url.query).get("after", ["0"])[0])
                except ValueError:
                    return self._json({"error": "after must be an integer"}, HTTPStatus.BAD_REQUEST)
                records = memory.after(after)
                return self._json({"latest": memory.latest, "glyphs": [
                    {"seq": r["seq"], "id": r["id"], "lane": r["lane"], "tile": f"/live/tiles/{r['seq']}.png",
                     "svg": f"/live/svg/{r['seq']}.svg"} for r in records]})
            match = re.fullmatch(r"/live/(tiles|svg)/(\d+)\.(png|svg)", url.path)
            if match:
                kind, seq = match.group(1), int(match.group(2))
                record = memory.get(seq)
                if record is None or (kind == "tiles") != (match.group(3) == "png"):
                    return self._json({"error": "no such glyph"}, HTTPStatus.NOT_FOUND)
                if kind == "tiles":
                    return self._send(tiles(seq), "image/png", cache=True)
                return self._send(record["svg"].encode(), "image/svg+xml", cache=True)
            target = allowed(url.path if not url.path.endswith("/") else url.path + "index.html")
            if target is None:
                return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            self.path = "/" + target.relative_to(ROOT).as_posix()
            return super().do_GET()

        def translate_path(self, path):
            return str(ROOT / urlparse(path).path.lstrip("/"))

    return Handler


def serve(memory, status, host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    """Start the server on a background thread and return it."""
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("the live server listens on this machine only")
    server = ThreadingHTTPServer((host, port), make_handler(memory, status))
    threading.Thread(target=server.serve_forever, name="noumenon-live-server", daemon=True).start()
    return server
