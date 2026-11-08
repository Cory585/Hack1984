"""Tiny stdlib web server.  python -m conflict_check.server [--replay] [--port 8000]"""
from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .pipeline import check_article
from .session import Session

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web", "index.html")
CACHE = os.path.join(ROOT, "cache")


def load_env(path: str = os.path.join(ROOT, ".env")) -> None:
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class Handler(BaseHTTPRequestHandler):
    default_replay = False

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(WEB, "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        elif self.path == "/api/config":
            self._json(200, {"replay_default": self.default_replay,
                             "keys": {"tavily": bool(os.environ.get("TAVILY_API_KEY")),
                                      "exa": bool(os.environ.get("EXA_API_KEY"))}})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/api/check":
            return self._json(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n) or b"{}")
            s = Session(cache_dir=CACHE, replay=bool(req.get("replay", self.default_replay)))
            result = check_article(s, url=req.get("url") or None, text=req.get("text") or None)
            self._json(200, result)
        except ValueError as e:
            self._json(400, {"error": str(e)})
        except Exception as e:
            self._json(500, {"error": f"{type(e).__name__}: {e}"})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--replay", action="store_true", help="serve cached responses only (demo mode)")
    args = ap.parse_args()
    load_env()
    Handler.default_replay = args.replay
    print(f"Conflict Check on http://localhost:{args.port}  (replay={'on' if args.replay else 'off'})")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
