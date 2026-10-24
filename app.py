"""Run the local movie recommendation API and its static interface."""

from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from recommender import Recommender


ROOT = Path(__file__).parent
DATA = ROOT / "data"
catalog = DATA / "movies.csv" if (DATA / "movies.csv").exists() else DATA / "demo_movies.csv"
engine = Recommender(catalog, DATA / "model.json")


class Handler(BaseHTTPRequestHandler):
    def send_security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")

    def send_json(self, value: dict | list, status: int = 200):
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_security_headers()
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urlparse(self.path)
        args = parse_qs(parsed.query)
        if parsed.path == "/api/health":
            return self.send_json({
                "status": "ok",
                "movies": len(engine.movies),
                "mode": "full" if catalog.name == "movies.csv" else "demo",
                "collaborative": bool(engine.neighbors),
                "modelSchema": engine.model.get("schemaVersion"),
            })
        if parsed.path == "/api/movies":
            return self.send_json(engine.search(args.get("q", [""])[0][:100]))
        if parsed.path == "/api/genres":
            return self.send_json(engine.genres())
        if parsed.path == "/api/recommendations":
            raw = args.get("liked", [""])[0].split(",")[:30]
            try:
                liked = [int(item) for item in raw if item]
                limit = max(1, min(30, int(args.get("limit", ["12"])[0])))
            except ValueError:
                return self.send_json({"error": "liked and limit must be integers"}, 400)
            return self.send_json(engine.recommend(liked, limit, args.get("genre", [""])[0][:40]))
        static = {
            "/": ("index.html", "text/html"),
            "/styles.css": ("styles.css", "text/css"),
            "/enhancements.css": ("enhancements.css", "text/css"),
            "/app.js": ("app.js", "text/javascript"),
        }
        if parsed.path not in static:
            return self.send_json({"error": "Not found"}, 404)
        name, content_type = static[parsed.path]
        payload = (ROOT / "public" / name).read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_security_headers()
        self.end_headers()
        self.wfile.write(payload)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"PickMyMovie at http://{host}:{port} ({len(engine.movies)} movies, {catalog.name})")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
